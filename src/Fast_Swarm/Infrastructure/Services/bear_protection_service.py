"""
Bear Protection Service.

Supreme risk layer with VETO EXIT POWER over all pattern trades.
Monitors motion derivatives and enforces position limits.

UPDATED v3: Simplified to AJ (Acceleration + Jerk) - tested on 65 stocks + crypto
- Removed velocity requirement (barely improved performance)
- Looser acceleration threshold for better signal quality

DEFENSIVE (0% max) - Requires 2+ TFs showing:
    acc < -1.5 AND adx_jerk < -0.5
    (velocity removed - testing showed +9.1% vs +2.4% avg ROI improvement)

AGGRESSIVE (90% max) - Only 1 TF needed:
    vel < -0.5 AND acc > 1.5

NEUTRAL (65% max) - Default when no signals

Note: ADX jerk fails on hypergrowth assets (SOL, NVDA, AVGO) - consider
sector-specific overrides for momentum stocks in future versions.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class Regime(Enum):
    """Market regime states."""
    DEFENSIVE = "DEFENSIVE"   # Crash protection - 25% max
    NEUTRAL = "NEUTRAL"       # Normal operation - 50% max
    AGGRESSIVE = "AGGRESSIVE" # Opportunity mode - 75% max


@dataclass
class RegimeConfig:
    """Position limits by regime."""
    defensive_max: float = 0.0    # 0% - FULL EXIT in DEFENSIVE
    neutral_max: float = 0.65     # 65% max position in NEUTRAL (was 50%)
    aggressive_max: float = 0.90  # 90% max position in AGGRESSIVE (was 85%)

    # DEFENSIVE signal thresholds - AJ config (Acceleration + Jerk only)
    # Velocity removed after testing: acc+jerk outperformed vel+acc+jerk
    exit_vel_threshold: float = 1.0       # DEPRECATED - not used in v3 DEFENSIVE
    exit_acc_threshold: float = -1.5      # Was -2.0 - looser for better signal quality
    exit_adx_jerk_threshold: float = -0.5 # Unchanged - requires negative jerk

    # AGGRESSIVE signal thresholds - made EASIER to trigger
    entry_vel_threshold: float = -0.5     # Was -1.5 - easier to recognize recovery
    entry_acc_threshold: float = 1.5      # Was 3.0 - lower bar for acceleration

    # Multi-timeframe confirmation: require N timeframes to agree
    defensive_tf_confirm: int = 2  # Need 2+ timeframes showing danger (was 1)
    aggressive_tf_confirm: int = 1 # Only 1 timeframe needed for opportunity

    # ==========================================================================
    # HYSTERESIS CONFIG - slow to drop guard, slow to go aggressive
    # Hair trigger INTO defensive, but requires sustained evidence to EXIT
    # ==========================================================================

    # Threshold buffers for EXITING DEFENSIVE (must be ABOVE these, not just above entry)
    exit_defensive_acc_buffer: float = -1.0    # Need acc > -1.0 to exit (vs -1.5 to enter)
    exit_defensive_jerk_buffer: float = -0.25  # Need jerk > -0.25 to exit (vs -0.5 to enter)

    # Minimum hold time - stay in regime for at least N hours
    defensive_min_hold_hours: float = 2.0      # Stay DEFENSIVE for at least 2 hours
    aggressive_min_hold_hours: float = 1.0     # Stay AGGRESSIVE for at least 1 hour

    # Confirmation candles - require N consecutive candles meeting criteria
    exit_defensive_confirm_candles: int = 3    # 3 consecutive "safe" candles to exit DEFENSIVE
    enter_aggressive_confirm_candles: int = 3  # 3 consecutive "bullish" candles to enter AGGRESSIVE


@dataclass
class MarketState:
    """Current market state from derivatives."""
    time: datetime
    symbol: str

    # 1h timeframe
    tf_1h_vel: Optional[float] = None
    tf_1h_acc: Optional[float] = None
    tf_1h_adx_jerk: Optional[float] = None

    # 4h timeframe
    tf_4h_vel: Optional[float] = None
    tf_4h_acc: Optional[float] = None
    tf_4h_adx_jerk: Optional[float] = None

    # 1d timeframe
    tf_1d_vel: Optional[float] = None
    tf_1d_acc: Optional[float] = None
    tf_1d_adx_jerk: Optional[float] = None


@dataclass
class RegimeState:
    """Current regime and limits."""
    regime: Regime
    max_position: float
    triggered_by: str  # Which timeframe/signal triggered
    since: datetime
    exit_signal_active: bool
    entry_signal_active: bool


@dataclass
class AssetRegimeState:
    """Per-asset regime tracking with hysteresis counters."""
    symbol: str
    regime: Regime = Regime.NEUTRAL
    since: Optional[datetime] = None
    trigger: str = "startup"
    # Hysteresis counters
    consecutive_safe_candles: int = 0    # For exiting DEFENSIVE
    consecutive_bullish_candles: int = 0  # For entering AGGRESSIVE

    def __post_init__(self):
        if self.since is None:
            self.since = datetime.now(timezone.utc)


class BearProtectionService:
    """
    Supreme risk layer with VETO EXIT POWER.

    Monitors motion derivatives across timeframes and:
    1. Sets position limits based on regime
    2. Can FORCE EXIT positions during crashes (veto power)
    3. Patterns must respect these limits

    Usage:
        service = BearProtectionService()
        state = service.evaluate(market_state)

        # Check if pattern can trade
        if state.regime == Regime.DEFENSIVE:
            # Reduce all positions to 25% max
            pass

        # Get max allowed position
        max_size = state.max_position * capital
    """

    def __init__(self, config: Optional[RegimeConfig] = None):
        self.config = config or RegimeConfig()
        # Per-asset regime tracking
        self._asset_regimes: dict[str, AssetRegimeState] = {}
        # Legacy global regime (for backwards compatibility with existing code)
        self._current_regime = Regime.NEUTRAL
        self._regime_since = datetime.now(timezone.utc)
        self._last_trigger = "startup"

    def _get_asset_state(self, symbol: str) -> AssetRegimeState:
        """Get or create per-asset regime state."""
        if symbol not in self._asset_regimes:
            self._asset_regimes[symbol] = AssetRegimeState(symbol=symbol)
        return self._asset_regimes[symbol]

    def _check_exit_signal(
        self, vel: Optional[float], acc: Optional[float], adx_jerk: Optional[float]
    ) -> bool:
        """
        Check if exit (danger) signal fires for one timeframe.

        v3: Uses AJ config (Acceleration + Jerk only).
        Velocity removed after testing showed acc+jerk outperformed vel+acc+jerk
        by 3.8x on 65-stock backtest (+9.1% vs +2.4% avg ROI diff).
        """
        # Only require acc and adx_jerk (velocity ignored in v3)
        if acc is None or adx_jerk is None:
            return False
        return (
            acc < self.config.exit_acc_threshold
            and adx_jerk < self.config.exit_adx_jerk_threshold
        )

    def _check_entry_signal(self, vel: Optional[float], acc: Optional[float]) -> bool:
        """Check if entry (opportunity) signal fires for one timeframe."""
        if vel is None or acc is None:
            return False
        return (
            vel < self.config.entry_vel_threshold
            and acc > self.config.entry_acc_threshold
        )

    def _check_safe_to_exit_defensive(
        self, acc: Optional[float], adx_jerk: Optional[float]
    ) -> bool:
        """Check if conditions are safe enough to exit DEFENSIVE (with buffer).

        Returns True when data is unavailable (consistent with _check_exit_signal
        which returns False/no-danger on None). Missing data should not trap the
        system in DEFENSIVE mode indefinitely.
        """
        if acc is None or adx_jerk is None:
            return True
        return (
            acc > self.config.exit_defensive_acc_buffer
            and adx_jerk > self.config.exit_defensive_jerk_buffer
        )

    def evaluate(self, state: MarketState) -> RegimeState:
        """
        Evaluate market state and return current regime for the asset.

        Implements hysteresis:
        - Hair trigger INTO DEFENSIVE (immediate on danger signal)
        - Slow exit FROM DEFENSIVE (buffer + hold time + confirmation candles)
        - Slow entry INTO AGGRESSIVE (hold time + confirmation candles)

        Returns RegimeState with:
        - regime: DEFENSIVE/NEUTRAL/AGGRESSIVE
        - max_position: Maximum allowed position (0.0-0.90)
        - exit_signal_active: True if any TF shows exit signal
        - entry_signal_active: True if any TF shows entry signal
        """
        # Get per-asset state
        asset_state = self._get_asset_state(state.symbol)

        exit_signals = []
        entry_signals = []
        safe_to_exit_defensive = True  # Track if ALL TFs meet exit buffer

        # Check all timeframes
        for tf, vel, acc, jerk in [
            ("1h", state.tf_1h_vel, state.tf_1h_acc, state.tf_1h_adx_jerk),
            ("4h", state.tf_4h_vel, state.tf_4h_acc, state.tf_4h_adx_jerk),
            ("1d", state.tf_1d_vel, state.tf_1d_acc, state.tf_1d_adx_jerk),
        ]:
            if self._check_exit_signal(vel, acc, jerk):
                exit_signals.append(tf)
            if self._check_entry_signal(vel, acc):
                entry_signals.append(tf)
            # Check if this TF meets the BUFFERED threshold for exiting defensive
            if not self._check_safe_to_exit_defensive(acc, jerk):
                safe_to_exit_defensive = False

        exit_count = len(exit_signals)
        entry_count = len(entry_signals)

        # Multi-timeframe confirmation required for DEFENSIVE
        exit_confirmed = exit_count >= self.config.defensive_tf_confirm
        entry_confirmed = entry_count >= self.config.aggressive_tf_confirm

        # Calculate time in current regime (safe datetime handling)
        since_time = asset_state.since or state.time
        SECONDS_PER_HOUR = 3600
        hours_in_regime = (state.time - since_time).total_seconds() / SECONDS_PER_HOUR

        # Determine regime with HYSTERESIS
        new_regime = asset_state.regime
        trigger = asset_state.trigger

        # =====================================================================
        # HAIR TRIGGER INTO DEFENSIVE - immediate, no hysteresis
        # =====================================================================
        if exit_confirmed:
            new_regime = Regime.DEFENSIVE
            trigger = f"exit:{','.join(exit_signals)}[{exit_count}TF]"
            # Reset hysteresis counters
            asset_state.consecutive_safe_candles = 0
            asset_state.consecutive_bullish_candles = 0

        # =====================================================================
        # SLOW EXIT FROM DEFENSIVE - requires buffer + hold time + confirmation
        # =====================================================================
        elif asset_state.regime == Regime.DEFENSIVE:
            # Check all three hysteresis conditions
            min_hold_met = hours_in_regime >= self.config.defensive_min_hold_hours

            if safe_to_exit_defensive:
                asset_state.consecutive_safe_candles += 1
            else:
                asset_state.consecutive_safe_candles = 0

            confirm_met = asset_state.consecutive_safe_candles >= self.config.exit_defensive_confirm_candles

            if min_hold_met and confirm_met:
                new_regime = Regime.NEUTRAL
                trigger = f"defensive_exit:safe[{asset_state.consecutive_safe_candles}candles,{hours_in_regime:.1f}h]"
                asset_state.consecutive_safe_candles = 0

        # =====================================================================
        # SLOW ENTRY INTO AGGRESSIVE - requires hold time + confirmation
        # =====================================================================
        elif entry_confirmed and asset_state.regime != Regime.AGGRESSIVE:
            asset_state.consecutive_bullish_candles += 1

            # Check if we've met confirmation threshold
            if asset_state.consecutive_bullish_candles >= self.config.enter_aggressive_confirm_candles:
                new_regime = Regime.AGGRESSIVE
                trigger = f"entry:{','.join(entry_signals)}[{entry_count}TF,{asset_state.consecutive_bullish_candles}candles]"
                asset_state.consecutive_bullish_candles = 0
        else:
            # Reset bullish counter if no entry signal
            asset_state.consecutive_bullish_candles = 0

            # Return to NEUTRAL from AGGRESSIVE when no signals
            if asset_state.regime == Regime.AGGRESSIVE and exit_count == 0 and entry_count == 0:
                min_hold_met = hours_in_regime >= self.config.aggressive_min_hold_hours
                if min_hold_met:
                    new_regime = Regime.NEUTRAL
                    trigger = "no_signals"

        # Update per-asset state if changed
        if new_regime != asset_state.regime:
            logger.info(
                f"REGIME CHANGE [{state.symbol}]: {asset_state.regime.value} -> {new_regime.value} "
                f"triggered by {trigger}"
            )
            asset_state.regime = new_regime
            asset_state.since = state.time
            asset_state.trigger = trigger

        # Also update legacy global state (for backwards compatibility)
        self._current_regime = new_regime
        self._regime_since = asset_state.since
        self._last_trigger = trigger

        # Get position limit
        if new_regime == Regime.DEFENSIVE:
            max_pos = self.config.defensive_max
        elif new_regime == Regime.AGGRESSIVE:
            max_pos = self.config.aggressive_max
        else:
            max_pos = self.config.neutral_max

        return RegimeState(
            regime=new_regime,
            max_position=max_pos,
            triggered_by=trigger,
            since=asset_state.since or state.time,
            exit_signal_active=exit_confirmed,
            entry_signal_active=entry_confirmed,
        )

    def get_position_limit(self, capital: float) -> float:
        """Get maximum position size in dollars."""
        if self._current_regime == Regime.DEFENSIVE:
            return capital * self.config.defensive_max
        elif self._current_regime == Regime.AGGRESSIVE:
            return capital * self.config.aggressive_max
        return capital * self.config.neutral_max

    def should_force_exit(self, state: MarketState) -> bool:
        """
        Check if positions should be force-reduced.

        This is the VETO POWER - when True, ALL positions must be
        reduced to DEFENSIVE limit regardless of pattern signals.
        """
        result = self.evaluate(state)
        return result.exit_signal_active and result.regime == Regime.DEFENSIVE

    def get_regime(self) -> Regime:
        """Get current regime."""
        return self._current_regime

    def get_regime_duration_hours(self) -> float:
        """Get hours in current regime."""
        SECONDS_PER_HOUR = 3600
        if self._regime_since is None:
            return 0.0
        delta = datetime.now(timezone.utc) - self._regime_since
        return delta.total_seconds() / SECONDS_PER_HOUR

    def get_all_asset_regimes(self) -> dict[str, AssetRegimeState]:
        """Get all per-asset regime states."""
        return self._asset_regimes.copy()

    def get_asset_regime(self, symbol: str) -> AssetRegimeState:
        """Get regime state for a specific asset."""
        return self._get_asset_state(symbol)

    def calculate_portfolio_regime(
        self,
        positions: dict[str, float],  # symbol -> position_size_usd
        market_caps: dict[str, float],  # symbol -> market_cap
    ) -> dict:
        """
        Calculate portfolio-weighted regime.

        Weighting: 50% by position size, 50% by market cap.
        This weighted regime controls max portfolio position.

        Args:
            positions: Dict of symbol -> current position size in USD
            market_caps: Dict of symbol -> market cap in USD

        Returns:
            {
                "weighted_regime_score": float (-1 to 1, -1=DEFENSIVE, 0=NEUTRAL, 1=AGGRESSIVE),
                "effective_regime": str (DEFENSIVE/NEUTRAL/AGGRESSIVE),
                "max_position_pct": int,
                "by_asset": {...per-asset details...}
            }
        """
        REGIME_SCORES = {
            Regime.DEFENSIVE: -1.0,
            Regime.NEUTRAL: 0.0,
            Regime.AGGRESSIVE: 1.0,
        }

        # Collect all symbols from positions and tracked assets
        all_symbols = set(positions.keys()) | set(self._asset_regimes.keys())

        if not all_symbols:
            # No assets tracked yet
            return {
                "weighted_regime_score": 0.0,
                "effective_regime": "NEUTRAL",
                "max_position_pct": int(self.config.neutral_max * 100),
                "by_asset": {},
            }

        # Calculate totals for weighting
        total_position = sum(positions.values()) or 1.0  # Avoid div by zero
        total_market_cap = sum(market_caps.get(s, 0) for s in all_symbols) or 1.0

        weighted_score = 0.0
        by_asset = {}

        for symbol in all_symbols:
            asset_state = self._get_asset_state(symbol)
            score = REGIME_SCORES[asset_state.regime]

            # Calculate weights
            position_weight = positions.get(symbol, 0) / total_position
            mcap_weight = market_caps.get(symbol, 0) / total_market_cap

            # 50/50 blend of position and market cap weights
            POSITION_WEIGHT_RATIO = 0.5
            MCAP_WEIGHT_RATIO = 0.5
            combined_weight = (position_weight * POSITION_WEIGHT_RATIO) + (mcap_weight * MCAP_WEIGHT_RATIO)

            weighted_score += score * combined_weight

            by_asset[symbol] = {
                "regime": asset_state.regime.value,
                "score": score,
                "position_usd": positions.get(symbol, 0),
                "position_weight": round(position_weight, 4),
                "mcap_weight": round(mcap_weight, 4),
                "combined_weight": round(combined_weight, 4),
                "trigger": asset_state.trigger,
            }

        # Determine effective regime from weighted score
        DEFENSIVE_THRESHOLD = -0.33
        AGGRESSIVE_THRESHOLD = 0.33
        if weighted_score <= DEFENSIVE_THRESHOLD:
            effective_regime = Regime.DEFENSIVE
        elif weighted_score >= AGGRESSIVE_THRESHOLD:
            effective_regime = Regime.AGGRESSIVE
        else:
            effective_regime = Regime.NEUTRAL

        # Get position limit for effective regime
        limits = {
            Regime.DEFENSIVE: self.config.defensive_max,
            Regime.NEUTRAL: self.config.neutral_max,
            Regime.AGGRESSIVE: self.config.aggressive_max,
        }

        return {
            "weighted_regime_score": round(weighted_score, 3),
            "effective_regime": effective_regime.value,
            "max_position_pct": int(limits[effective_regime] * 100),
            "by_asset": by_asset,
        }


# Singleton instance
_bear_protection: Optional[BearProtectionService] = None


def get_bear_protection() -> BearProtectionService:
    """Get singleton bear protection service."""
    global _bear_protection
    if _bear_protection is None:
        _bear_protection = BearProtectionService()
    return _bear_protection
