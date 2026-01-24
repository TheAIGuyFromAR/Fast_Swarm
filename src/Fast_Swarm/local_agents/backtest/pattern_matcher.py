"""
Pattern Matching for Backtesting.

Evaluates pattern conditions against candle data using the confidence system.

MERGED FROM: local-utilities/metrics/pattern_matcher.py
This is the CANONICAL pattern matcher for Coinswarm.

Features:
- ~250+ indicator aliases (camelCase, snake_case, pandas_ta, PostgreSQL)
- COMPUTED_INDICATORS set for derived indicators
- INDICATOR_CANONICAL reverse mapping
- Confidence scoring via MatchResult
- Fuzzy period matching (finds ema_21 when ema_20 requested)
"""

import math
import re
from dataclasses import dataclass
from typing import Any

from Fast_Swarm.local_agents.shared.confidence import (
    evaluate_condition_confidence,
)

# Rate-limit indicator resolution warnings (log each indicator failure only once)
_warned_indicators: set[str] = set()


# =============================================================================
# Indicator Name Mapping (V3 Canonical -> pandas_ta -> PostgreSQL enhanced_candles)
#
# MERGED FROM: local-utilities/metrics/pattern_matcher.py (~340 aliases)
# This is the CANONICAL indicator alias mapping for Coinswarm.
# =============================================================================

INDICATOR_ALIASES = {
    # =========================================================================
    # Motion Derivatives (from analyze_motion_derivatives.py)
    # These are 1st-6th order derivatives of price and indicators
    # Stored in data/derivatives/ partitioned parquet files
    # =========================================================================
    # Price derivatives (close)
    "velocity": "close_velocity_zscore",
    "acceleration": "close_acceleration_zscore",
    "jerk": "close_jerk_zscore",
    "snap": "close_snap_zscore",
    "crackle": "close_crackle_zscore",
    "pop": "close_pop_zscore",
    # Explicit close prefix versions
    "closeVelocity": "close_velocity_zscore",
    "closeAcceleration": "close_acceleration_zscore",
    "closeJerk": "close_jerk_zscore",
    "closeSnap": "close_snap_zscore",
    "closeCrackle": "close_crackle_zscore",
    "closePop": "close_pop_zscore",
    # Snake_case versions
    "close_velocity": "close_velocity_zscore",
    "close_acceleration": "close_acceleration_zscore",
    "close_jerk": "close_jerk_zscore",
    "close_snap": "close_snap_zscore",
    "close_crackle": "close_crackle_zscore",
    "close_pop": "close_pop_zscore",
    # Raw (non-normalized) versions
    "velocityRaw": "close_velocity",
    "accelerationRaw": "close_acceleration",
    "jerkRaw": "close_jerk",
    "snapRaw": "close_snap",
    "crackleRaw": "close_crackle",
    "popRaw": "close_pop",
    # RSI derivatives
    "rsiVelocity": "rsi_14_velocity_zscore",
    "rsiAcceleration": "rsi_14_acceleration_zscore",
    "rsiJerk": "rsi_14_jerk_zscore",
    "rsi_velocity": "rsi_14_velocity_zscore",
    "rsi_acceleration": "rsi_14_acceleration_zscore",
    "rsi_jerk": "rsi_14_jerk_zscore",
    # MACD derivatives
    "macdVelocity": "macd_histogram_velocity_zscore",
    "macdAcceleration": "macd_histogram_acceleration_zscore",
    "macdJerk": "macd_histogram_jerk_zscore",
    "macd_velocity": "macd_histogram_velocity_zscore",
    "macd_acceleration": "macd_histogram_acceleration_zscore",
    "macd_jerk": "macd_histogram_jerk_zscore",
    # OBV derivatives (volume momentum)
    "obvVelocity": "obv_velocity_zscore",
    "obvAcceleration": "obv_acceleration_zscore",
    "obv_velocity": "obv_velocity_zscore",
    "obv_acceleration": "obv_acceleration_zscore",
    # ATR derivatives (volatility change)
    "atrVelocity": "atr_14_velocity_zscore",
    "atrAcceleration": "atr_14_acceleration_zscore",
    "atr_velocity": "atr_14_velocity_zscore",
    "atr_acceleration": "atr_14_acceleration_zscore",
    # Divergence flags (boolean)
    "accelJerkDiv": "close_accel_jerk_div",
    "priceRsiDiv": "price_vs_rsi_vel_div",
    "accel_jerk_divergence": "close_accel_jerk_div",
    "price_rsi_divergence": "price_vs_rsi_vel_div",
    # =========================================================================
    # Momentum Indicators
    # =========================================================================
    "rsi14": "rsi_14",
    "rsi": "rsi_14",
    "rsi7": "rsi_7",
    "rsi21": "rsi_21",
    "RSI_14": "rsi_14",
    "RSI_7": "rsi_7",
    "RSI_21": "rsi_21",
    "macd": "macd_line",
    "macdLine": "macd_line",
    "macdSignal": "macd_signal",
    "macdHistogram": "macd_histogram",
    "MACD_12_26_9": "macd_line",
    "MACDs_12_26_9": "macd_signal",
    "MACDh_12_26_9": "macd_histogram",
    "stochasticK": "stoch_k",
    "stochasticD": "stoch_d",
    "stochK": "stoch_k",
    "stochD": "stoch_d",
    "STOCHk_14_3_3": "stoch_k",
    "STOCHd_14_3_3": "stoch_d",
    "STOCH_K": "stoch_k",
    "STOCH_D": "stoch_d",
    "williamsR": "willr_14",
    "willr": "willr_14",
    "WILLR_14": "willr_14",
    "mfi14": "mfi_14",
    "mfi": "mfi_14",
    "MFI_14": "mfi_14",
    "mfiVolume": "mfi_14",
    "ultimateOsc": "uo",
    "ultimateOscillator": "uo",
    "uo": "uo",
    "UO_7_14_28": "uo",
    "roc10": "roc_10",
    "roc": "roc_10",
    "ROC_10": "roc_10",
    "momentum": "mom_10",
    "momentum1": "mom_10",
    "momentum5": "mom_10",
    "momentum10": "mom_10",
    "mom": "mom_10",
    "MOM_10": "mom_10",
    "cmo14": "cmo_14",
    "cmo": "cmo_14",
    "CMO_14": "cmo_14",
    "cci20": "cci_14",
    "cci": "cci_14",
    "CCI_14": "cci_14",
    "CCI_20": "cci_20",
    "CCI_14_0.015": "cci_14",
    "bop": "bop",
    "BOP": "bop",
    "ao": "ao",
    "AO_5_34": "ao",
    "apo": "apo",
    "APO_12_26": "apo",
    # =========================================================================
    # Trend Indicators
    # =========================================================================
    "adx14": "adx_14",
    "adx": "adx_14",
    "ADX_14": "adx_14",
    "plusDI": "plus_di",
    "minusDI": "minus_di",
    "DMP_14": "plus_di",
    "DMN_14": "minus_di",
    "aroonUp": "aroon_up",
    "aroonDown": "aroon_down",
    "aroonOsc": "aroon_osc",
    "AROONU_14": "aroon_up",
    "AROOND_14": "aroon_down",
    "AROONOSC_14": "aroon_osc",
    "choppiness": "chop",
    "chop": "chop",
    "CHOP_14_1_100.0": "chop",
    "dpo": "dpo",
    "DPO_14": "dpo",
    "DPO_20": "dpo",
    # =========================================================================
    # Volatility Indicators
    # =========================================================================
    "atr14": "atr_14",
    "atr": "atr_14",
    "atr_14": "atr_14",
    "atr7": "atr_7",
    "atr_7": "atr_7",
    "ATRr_14": "atr_14",
    "ATRr_7": "atr_7",
    "natr14": "natr_14",
    "natr": "natr_14",
    "NATR_14": "natr_14",
    "bollingerBandwidth": "bb_bandwidth",
    "bollingerPercentB": "bb_percent",
    "bbBandwidth": "bb_bandwidth",
    "bbPercentB": "bb_percent",
    "bbUpper": "bb_upper",
    "bbLower": "bb_lower",
    "bbMiddle": "bb_middle",
    "BBB_5_2.0_2.0": "bb_bandwidth",
    "BBP_5_2.0_2.0": "bb_percent",
    "BBU_5_2.0_2.0": "bb_upper",
    "BBL_5_2.0_2.0": "bb_lower",
    "BBM_5_2.0_2.0": "bb_middle",
    "BBW_20": "bb_bandwidth",
    "BBW_5": "bb_bandwidth",
    "bb_width": "bb_bandwidth",
    "PERCENT_B": "bb_percent",
    "bb_percent_b": "bb_percent",
    "bollingerUpper": "bb_upper",
    "bollingerLower": "bb_lower",
    # =========================================================================
    # Volume Indicators
    # =========================================================================
    "ad": "ad",
    "AD": "ad",
    "adosc": "adosc",
    "ADOSC_3_10": "adosc",
    "cmf20": "cmf",
    "cmf": "cmf",
    "CMF_20": "cmf",
    "obv": "obv",
    "OBV": "obv",
    "volumeRatio": "volume_sma_20",
    "volumeSma": "volume_sma_20",
    "efi": "efi",
    "EFI_13": "efi",
    "PVT": "pvt",
    # =========================================================================
    # Moving Averages (map to PostgreSQL enhanced_candles columns)
    # =========================================================================
    "ema9": "ema_9",
    "ema10": "ema_9",  # Closest available
    "ema12": "ema_12",
    "ema20": "ema_21",  # Closest available
    "ema21": "ema_21",
    "ema26": "ema_26",
    "ema50": "sma_50",  # Use SMA as proxy
    "ema200": "sma_200",  # Use SMA as proxy
    "EMA_9": "ema_9",
    "EMA_10": "ema_9",
    "EMA_12": "ema_12",
    "EMA_20": "ema_21",
    "EMA_21": "ema_21",
    "EMA_26": "ema_26",
    "EMA_50": "sma_50",
    "EMA_200": "sma_200",
    "sma20": "sma_20",
    "sma50": "sma_50",
    "sma200": "sma_200",
    "SMA_20": "sma_20",
    "SMA_50": "sma_50",
    "SMA_200": "sma_200",
    "dema10": "dema",
    "DEMA_10": "dema",
    "DEMA_21": "dema",
    "hma16": "hma",
    "HMA_16": "hma",
    "tema10": "tema",
    "TEMA_10": "tema",
    "wma10": "wma",
    "WMA_10": "wma",
    # =========================================================================
    # PRECOMPUTED DERIVED INDICATORS (stored in DB - fastest path)
    # These map to columns added by indicator_enrichment_service.py
    # =========================================================================
    # MA Cross signals (precomputed as integers: 1=bullish, -1=bearish, 0=neutral)
    "maCross": "ma_cross_20_50",
    "goldenCross": "golden_cross",
    "deathCross": "death_cross",
    "macdCross": "macd_cross",
    "macdBullishCross": "macd_cross",  # Same column, check for > 0
    # Price vs MA percentages (precomputed)
    "priceVsEma9Pct": "price_vs_ema_9_pct",
    "priceVsEma10Pct": "price_vs_ema_9_pct",  # Closest
    "priceVsEma20Pct": "price_vs_ema_20_pct",
    "priceVsEma21Pct": "price_vs_ema_21_pct",
    "priceVsSma50Pct": "price_vs_sma_50_pct",
    "priceVsSma200Pct": "price_vs_sma_200_pct",
    "priceVsEma": "price_vs_ema_21_pct",
    "priceVsSma": "price_vs_sma_50_pct",
    # Price above MA booleans (precomputed as integers: 1=true, 0=false)
    "priceAboveEma": "price_above_ema_21",
    "priceAboveEma9": "price_above_ema_9",
    "priceAboveEma20": "price_above_ema_20",
    "priceAboveEma21": "price_above_ema_21",
    "priceAboveSma50": "price_above_sma_50",
    "priceAboveSma200": "price_above_sma_200",
    "aboveEma": "price_above_ema_21",
    "aboveSma": "price_above_sma_50",
    # RSI conditions (precomputed as integers)
    "rsiOversold": "rsi_oversold",
    "rsiOverbought": "rsi_overbought",
    "rsiNeutral": "rsi_neutral",
    # Stochastic conditions (precomputed)
    "stochOversold": "stoch_oversold",
    "stochOverbought": "stoch_overbought",
    # Trend conditions (precomputed)
    "strongTrend": "strong_trend",
    "weakTrend": "weak_trend",
    # Regime indicators (precomputed as strings)
    "volatilityRegime": "volatility_regime",
    "trendRegime": "trend_regime",
    # Session indicators (precomputed as integers)
    "isAsianSession": "is_asian_session",
    "isLondonSession": "is_london_session",
    "isUSSession": "is_us_session",
    "isUSMarketHours": "is_us_market_hours",
    "isEuropeanSession": "is_london_session",  # Alias
    # Bollinger conditions (precomputed)
    "bbAtUpper": "price_at_bb_upper",
    "bbAtLower": "price_at_bb_lower",
    "bbSqueeze": "bb_squeeze",
    # Volume conditions (precomputed)
    "highVolume": "high_volume",
    "volumeSpike": "high_volume",
    "lowVolume": "low_volume",
    "volumeDry": "low_volume",
    # =========================================================================
    # StochRSI
    # =========================================================================
    "stochRsi": "stochrsi_k",
    "stochRsiK": "stochrsi_k",
    "stochRsiD": "stochrsi_d",
    "STOCHRSIk_14_14_3_3": "stochrsi_k",
    "STOCHRSId_14_14_3_3": "stochrsi_d",
    # =========================================================================
    # TRIX
    # =========================================================================
    "trix": "trix",
    "trixSignal": "trix_signal",
    "TRIX_18_9": "trix",
    "TRIX_30_9": "trix",
    "TRIXs_30_9": "trix_signal",
    # =========================================================================
    # Fisher Transform
    # =========================================================================
    "fisherTransform": "fisher",
    "fisherSignal": "fisher_signal",
    "fisher": "fisher",
    "FISHERT_9": "fisher",
    "FISHERT_9_1": "fisher",
    "FISHERTs_9": "fisher_signal",
    "FISHERTs_9_1": "fisher_signal",
    # =========================================================================
    # Linear Regression
    # =========================================================================
    "linregSlope": "linreg_14",
    "linreg": "linreg_14",
    "LINREG_14": "linreg_14",
    # =========================================================================
    # Mass Index
    # =========================================================================
    "massIndex": "massi",
    "massi": "massi",
    "MASSI_9_25": "massi",
    # =========================================================================
    # Statistical Indicators
    # =========================================================================
    "vhf": "vhf_28",
    "VHF_28": "vhf_28",
    "entropy": "entropy",
    "ENTROPY_10": "entropy",
    "kurtosis": "kurtosis",
    "KURTOSIS_10": "kurtosis",
    "skew": "skew",
    "SKEW_10": "skew",
    # Map pandas_ta zscore names to our motion derivative zscores
    # ZS_* patterns use these for mean reversion signals
    "zscore": "close_velocity_zscore",
    "zscore50": "close_acceleration_zscore",
    "ZSCORE_10": "close_velocity_zscore",
    "ZSCORE_20": "close_velocity_zscore",
    "ZS_20": "close_velocity_zscore",
    "ZS_30": "close_acceleration_zscore",
    "ZS_50": "close_acceleration_zscore",
    # =========================================================================
    # Cross-Asset Metrics
    # =========================================================================
    "btc_eth_correlation": "btc_eth_correlation_14d",
    "btcEthCorrelation": "btc_eth_correlation_14d",
    "correlation": "btc_eth_correlation_14d",
    "eth_btc_ratio": "eth_btc_ratio",
    "ethBtcRatio": "eth_btc_ratio",
    "alt_dominance": "alt_dominance_pct",
    "altDominance": "alt_dominance_pct",
    "l1_momentum": "l1_momentum_pct",
    "l1Momentum": "l1_momentum_pct",
    "defi_momentum": "defi_momentum_pct",
    "defiMomentum": "defi_momentum_pct",
    "meme_momentum": "meme_momentum_pct",
    "memeMomentum": "meme_momentum_pct",
    "market_breadth_20": "market_breadth_sma20_pct",
    "marketBreadth20": "market_breadth_sma20_pct",
    "market_breadth_50": "market_breadth_sma50_pct",
    "marketBreadth50": "market_breadth_sma50_pct",
    "assets_above_ema200": "assets_above_ema200_pct",
    "assetsAboveEma200": "assets_above_ema200_pct",
    # =========================================================================
    # Time-based Indicators
    # =========================================================================
    "dayOfWeek": "day_of_week",
    "hourOfDay": "hour_of_day",
    "hour": "hour_of_day",
    "day": "day_of_week",
    "isMonday": "is_monday",
    "isThursday": "is_thursday",
    "isUSMarketHours": "is_us_market_hours",
    "isUsMarketHours": "is_us_market_hours",
    # =========================================================================
    # Regime Indicators
    # =========================================================================
    "volatilityRegime": "regime",
    "trendRegime": "regime",
    "regime": "regime",
    # =========================================================================
    # BIAS indicator
    # =========================================================================
    "BIAS_26": "bias_26",
    "BIAS_SMA_26": "bias_26",
    "bias": "bias_26",
    "bias_26": "bias_26",
    # =========================================================================
    # PPO (Percentage Price Oscillator)
    # =========================================================================
    "ppo": "ppo",
    "PPO_12_26_9": "ppo",
    # =========================================================================
    # PVI (Positive Volume Index) - pandas_ta applies EMA(13) by default
    # =========================================================================
    "pvi": "pvi",
    "pvi_ema": "pvi",
    "PVI_13": "pvi",
    # =========================================================================
    # Ulcer Index
    # =========================================================================
    "ui_14": "ui_14",
    "ulcerIndex": "ui_14",
    "UI_14": "ui_14",
    # =========================================================================
    # Supertrend direction (1=bullish, -1=bearish)
    # =========================================================================
    "supertrend_direction": "supertrend_direction",
    "supertrendDirection": "supertrend_direction",
    "SUPERTd_7_3.0": "supertrend_direction",
    # =========================================================================
    # Z-Score (30-period price z-score: (close - sma_30) / stdev_30)
    # =========================================================================
    "zscore_30": "zscore_30",
    "zscore30": "zscore_30",
    "ZS_30": "zscore_30",
    # =========================================================================
    # Cross signals (computed - use histogram as proxy)
    # =========================================================================
    "deathCross": "macd_histogram",
    "goldenCross": "macd_histogram",
    "macdBullishCross": "macd_histogram",
    "macdBearishCross": "macd_histogram",
    # =========================================================================
    # Volatility proxies
    # =========================================================================
    "cvi": "atr_14",
}

# Reverse mapping: PostgreSQL columns -> canonical short names
INDICATOR_CANONICAL = {v: k for k, v in INDICATOR_ALIASES.items()}

# Reverse alias lookup: canonical_target -> list of raw names that map to it
# Used when canonical name not found in available columns (tries raw pandas_ta names)
REVERSE_ALIASES: dict[str, list[str]] = {}
for _raw_name, _canonical in INDICATOR_ALIASES.items():
    _canonical_lower = _canonical.lower()
    if _canonical_lower not in REVERSE_ALIASES:
        REVERSE_ALIASES[_canonical_lower] = []
    REVERSE_ALIASES[_canonical_lower].append(_raw_name.lower())


# =============================================================================
# Computed/Derived Indicators (need special handling via compute_derived_indicator)
# =============================================================================

COMPUTED_INDICATORS = {
    # Cross conditions
    "goldenCross",
    "deathCross",
    "maCross",
    "macdCross",
    "macdBullishCross",
    "macdBearishCross",
    "stochasticCross",
    # Price vs MA conditions
    "aboveEma20",
    "aboveEma21",
    "aboveEma30",
    "aboveEma9",
    "aboveSma10",
    "aboveSma50",
    "aboveSma200",
    "priceBelowSma",
    "priceBelowEma",
    "priceAboveEma",
    "priceAboveSma",
    "priceVsEma",
    "priceVsSma",
    # Stochastic conditions
    "stochBullishCross",
    "stochBearishCross",
    "stochOversold",
    "stochOverbought",
    # RSI conditions
    "rsiOversold",
    "rsiOverbought",
    # Williams %R conditions
    "williamsOversold",
    "williamsOverbought",
    # Trend conditions
    "emaStackBullish",
    "emaStackBearish",
    "trendingUp",
    "trendingDown",
    "strongTrend",
    "weakTrend",
    # MACD conditions
    "macdPositive",
    "macd",
    # Bollinger conditions
    "bbAtUpper",
    "bbAtLower",
    "bbSqueeze",
    # Momentum conditions
    "momentumStrong",
    "momentumPositive",
    # Volume conditions
    "volumeSpike",
    "volumeDry",
    # Aroon conditions
    "aroonTrendUp",
    "aroonTrendDown",
    # Fisher conditions
    "fisherBullish",
    "fisherBearish",
    # PSAR conditions
    "psarBullish",
    # Other computed
    "atrPercent",
    "stddev20",
    # Time/Session indicators
    "isAsianSession",
    "isEuropeanSession",
    "isUSMarketHours",
    "isWeekend",
    "isMonday",
    "isTuesday",
    "isWednesday",
    "isThursday",
    "isFriday",
    # Regime indicators
    "volatilityRegime",
    "trendRegime",
}


def validate_pattern_conditions(
    entry_conditions: list[dict],
) -> dict[str, Any]:
    """
    Validate that all indicators in a pattern's entry conditions can be resolved.

    Checks each indicator against INDICATOR_ALIASES and COMPUTED_INDICATORS.
    Patterns with unresolvable indicators can NEVER generate trades.

    Args:
        entry_conditions: List of condition dicts with 'indicator' key.

    Returns:
        Dict with validation result:
        - {"status": "valid"} if all indicators resolvable
        - {"status": "invalid", "unresolvable": [...], "validated_at": "..."}
    """
    from datetime import datetime

    if not entry_conditions:
        return {"status": "valid", "validated_at": datetime.utcnow().isoformat()}

    unresolvable = []
    for cond in entry_conditions:
        if not isinstance(cond, dict):
            continue
        indicator_name = cond.get("indicator", "")
        if not indicator_name:
            continue

        # Check 1: Is it in INDICATOR_ALIASES (any case variation)?
        name_lower = indicator_name.lower().replace(" ", "").replace("-", "_")
        found_alias = (
            indicator_name in INDICATOR_ALIASES
            or name_lower in INDICATOR_ALIASES
            or indicator_name.lower() in INDICATOR_ALIASES
        )

        # Check 2: Is it in COMPUTED_INDICATORS?
        found_computed = indicator_name in COMPUTED_INDICATORS

        if not found_alias and not found_computed:
            unresolvable.append(indicator_name)

    if unresolvable:
        return {
            "status": "invalid",
            "unresolvable": unresolvable,
            "validated_at": datetime.utcnow().isoformat(),
        }

    return {"status": "valid", "validated_at": datetime.utcnow().isoformat()}


def resolve_indicator_name(name: str) -> str | None:
    """
    Resolve any indicator name variant to its canonical DB column name.

    Tries exact match, lowercase, underscore-normalized, and camelCase variants.

    Args:
        name: Raw indicator name from LLM or pattern (e.g., "RSI_14", "rsi14", "rsiValue")

    Returns:
        Canonical DB column name (e.g., "rsi_14"), or None if truly unresolvable.
    """
    if not name:
        return None

    # Direct match
    if name in INDICATOR_ALIASES:
        return INDICATOR_ALIASES[name]

    # Lowercase match
    lower = name.lower()
    if lower in INDICATOR_ALIASES:
        return INDICATOR_ALIASES[lower]

    # Normalized: strip spaces/hyphens, lowercase
    normalized = lower.replace(" ", "").replace("-", "_")
    if normalized in INDICATOR_ALIASES:
        return INDICATOR_ALIASES[normalized]

    # Check if it's already a canonical target (a DB column name)
    canonical_targets = set(INDICATOR_ALIASES.values())
    if name in canonical_targets or lower in canonical_targets:
        return lower if lower in canonical_targets else name

    # Check computed indicators (these don't map to columns, they compute on-the-fly)
    if name in COMPUTED_INDICATORS:
        return name  # Keep as-is, handled by compute_derived_indicator()

    return None


def normalize_pattern_conditions(conditions: list[dict]) -> tuple[list[dict], list[str]]:
    """
    Normalize all indicator names in a condition list to canonical DB column names.

    For each condition:
    - If the indicator name resolves via INDICATOR_ALIASES -> replace with canonical name
    - If unresolvable -> remove the condition and track it

    This is the preemptive fix: called BEFORE patterns are inserted into the DB,
    so LLM hallucinations get auto-corrected rather than creating broken patterns.

    Args:
        conditions: List of condition dicts, each with an 'indicator' key.

    Returns:
        Tuple of (normalized_conditions, removed_indicators):
        - normalized_conditions: Cleaned list with canonical indicator names
        - removed_indicators: List of indicator names that could not be resolved
    """
    if not conditions:
        return [], []

    normalized = []
    removed = []

    for cond in conditions:
        if not isinstance(cond, dict):
            continue

        indicator_name = cond.get("indicator", "")
        if not indicator_name:
            # Condition without indicator - keep as-is (might be a meta-condition)
            normalized.append(cond)
            continue

        canonical = resolve_indicator_name(indicator_name)

        if canonical is not None:
            # Resolved - replace with canonical name
            fixed_cond = dict(cond)
            fixed_cond["indicator"] = canonical
            normalized.append(fixed_cond)
        else:
            # Truly unresolvable - remove this condition
            removed.append(indicator_name)

    return normalized, removed


def get_valid_indicator_names() -> list[str]:
    """
    Get the complete list of valid indicator names for LLM prompts.

    Returns canonical DB column names (the TARGET values of INDICATOR_ALIASES),
    deduplicated and sorted. This is the authoritative "menu" of indicators
    the LLM should use when generating patterns.

    Returns:
        Sorted list of canonical indicator names (e.g., ["adx_14", "atr_14", ...])
    """
    # Canonical targets from aliases
    canonical = set(INDICATOR_ALIASES.values())

    # Add computed indicators (they're also valid, just computed on-the-fly)
    canonical.update(COMPUTED_INDICATORS)

    return sorted(canonical)


def compute_derived_indicator(
    name: str,
    indicators: dict[str, float],
    condition: dict | None = None,
) -> float | None:
    """
    Compute derived/computed indicators that don't exist as DB columns.

    These indicators are calculated on-the-fly from other indicator values.

    Args:
        name: Indicator name (e.g., "maCross", "priceAboveEma")
        indicators: Dict of available indicator values
        condition: Optional condition dict with params (e.g., fastPeriod, slowPeriod)

    Returns:
        Computed value, or None if cannot be computed
    """
    close = indicators.get("close", 0)

    # Extract params from condition if available
    params = condition.get("params", {}) if condition else {}

    # ==========================================================================
    # MA Cross indicators - return 1 (bullish cross), -1 (bearish cross), or 0
    # ==========================================================================
    if name == "maCross":
        # Get MA periods from params (default 21/50 matches calculate_indicators_fast output)
        fast_period = params.get("fastPeriod", 21)
        slow_period = params.get("slowPeriod", 50)
        fast_type = params.get("fastType", "ema").lower()
        slow_type = params.get("slowType", "sma").lower()

        # Build column names
        fast_col = f"{fast_type}_{fast_period}"
        slow_col = f"{slow_type}_{slow_period}"

        # Try to resolve columns
        fast_val = indicators.get(fast_col) or indicators.get(f"ema_{fast_period}") or indicators.get(f"sma_{fast_period}")
        slow_val = indicators.get(slow_col) or indicators.get(f"ema_{slow_period}") or indicators.get(f"sma_{slow_period}")

        if fast_val is not None and slow_val is not None:
            # Return relative position: positive = fast above slow, negative = fast below
            if fast_val > slow_val:
                return 1  # Bullish
            elif fast_val < slow_val:
                return -1  # Bearish
            return 0
        return None

    if name == "goldenCross":
        # SMA 50 crosses above SMA 200
        sma50 = indicators.get("sma_50")
        sma200 = indicators.get("sma_200")
        if sma50 is not None and sma200 is not None:
            return 1 if sma50 > sma200 else 0
        return None

    if name == "deathCross":
        # SMA 50 crosses below SMA 200
        sma50 = indicators.get("sma_50")
        sma200 = indicators.get("sma_200")
        if sma50 is not None and sma200 is not None:
            return 1 if sma50 < sma200 else 0
        return None

    # ==========================================================================
    # MACD Cross indicators
    # ==========================================================================
    if name in ("macdBullishCross", "macdCross"):
        macd = indicators.get("macd_line") or indicators.get("MACD_12_26_9")
        signal = indicators.get("macd_signal") or indicators.get("MACDs_12_26_9")
        if macd is not None and signal is not None:
            return 1 if macd > signal else 0
        return None

    if name == "macdBearishCross":
        macd = indicators.get("macd_line") or indicators.get("MACD_12_26_9")
        signal = indicators.get("macd_signal") or indicators.get("MACDs_12_26_9")
        if macd is not None and signal is not None:
            return 1 if macd < signal else 0
        return None

    if name == "macdPositive":
        macd = indicators.get("macd_line") or indicators.get("MACD_12_26_9")
        if macd is not None:
            return 1 if macd > 0 else 0
        return None

    # ==========================================================================
    # Price vs MA indicators
    # ==========================================================================
    if name == "priceAboveEma" or name.startswith("aboveEma"):
        period = params.get("period", 21)
        ema = indicators.get(f"ema_{period}") or indicators.get(f"EMA_{period}")
        if ema is not None and close > 0:
            return 1 if close > ema else 0
        return None

    if name == "priceAboveSma" or name.startswith("aboveSma"):
        period = params.get("period", 50)
        sma = indicators.get(f"sma_{period}") or indicators.get(f"SMA_{period}")
        if sma is not None and close > 0:
            return 1 if close > sma else 0
        return None

    if name == "priceBelowEma":
        period = params.get("period", 21)
        ema = indicators.get(f"ema_{period}") or indicators.get(f"EMA_{period}")
        if ema is not None and close > 0:
            return 1 if close < ema else 0
        return None

    if name == "priceBelowSma":
        period = params.get("period", 50)
        sma = indicators.get(f"sma_{period}") or indicators.get(f"SMA_{period}")
        if sma is not None and close > 0:
            return 1 if close < sma else 0
        return None

    if name == "priceVsEma":
        # Returns percentage difference from EMA
        period = params.get("period", 21)
        ema = indicators.get(f"ema_{period}") or indicators.get("ema_21")
        if ema is not None and ema > 0:
            return ((close - ema) / ema) * 100
        return None

    if name == "priceVsSma":
        # Returns percentage difference from SMA
        period = params.get("period", 20)
        sma = indicators.get(f"sma_{period}") or indicators.get("sma_20")
        if sma is not None and sma > 0:
            return ((close - sma) / sma) * 100
        return None

    # ==========================================================================
    # RSI conditions
    # ==========================================================================
    if name == "rsiOversold":
        rsi = indicators.get("rsi_14") or indicators.get("RSI_14")
        if rsi is not None:
            return 1 if rsi < 30 else 0
        return None

    if name == "rsiOverbought":
        rsi = indicators.get("rsi_14") or indicators.get("RSI_14")
        if rsi is not None:
            return 1 if rsi > 70 else 0
        return None

    # ==========================================================================
    # Stochastic conditions
    # ==========================================================================
    if name == "stochOversold":
        stoch_k = indicators.get("stoch_k") or indicators.get("STOCH_K")
        if stoch_k is not None:
            return 1 if stoch_k < 20 else 0
        return None

    if name == "stochOverbought":
        stoch_k = indicators.get("stoch_k") or indicators.get("STOCH_K")
        if stoch_k is not None:
            return 1 if stoch_k > 80 else 0
        return None

    if name == "stochBullishCross":
        stoch_k = indicators.get("stoch_k") or indicators.get("STOCH_K")
        stoch_d = indicators.get("stoch_d") or indicators.get("STOCH_D")
        if stoch_k is not None and stoch_d is not None:
            return 1 if stoch_k > stoch_d else 0
        return None

    if name == "stochBearishCross":
        stoch_k = indicators.get("stoch_k") or indicators.get("STOCH_K")
        stoch_d = indicators.get("stoch_d") or indicators.get("STOCH_D")
        if stoch_k is not None and stoch_d is not None:
            return 1 if stoch_k < stoch_d else 0
        return None

    # ==========================================================================
    # Williams %R conditions
    # ==========================================================================
    if name == "williamsOversold":
        willr = indicators.get("willr_14") or indicators.get("WILLR_14")
        if willr is not None:
            return 1 if willr < -80 else 0
        return None

    if name == "williamsOverbought":
        willr = indicators.get("willr_14") or indicators.get("WILLR_14")
        if willr is not None:
            return 1 if willr > -20 else 0
        return None

    # ==========================================================================
    # Trend indicators
    # ==========================================================================
    if name == "strongTrend":
        adx = indicators.get("adx_14") or indicators.get("ADX_14")
        if adx is not None:
            return 1 if adx > 25 else 0
        return None

    if name == "weakTrend":
        adx = indicators.get("adx_14") or indicators.get("ADX_14")
        if adx is not None:
            return 1 if adx < 20 else 0
        return None

    if name == "trendingUp":
        adx = indicators.get("adx_14") or indicators.get("ADX_14")
        plus_di = indicators.get("plus_di") or indicators.get("DMP_14")
        minus_di = indicators.get("minus_di") or indicators.get("DMN_14")
        if adx is not None and plus_di is not None and minus_di is not None:
            return 1 if adx > 20 and plus_di > minus_di else 0
        return None

    if name == "trendingDown":
        adx = indicators.get("adx_14") or indicators.get("ADX_14")
        plus_di = indicators.get("plus_di") or indicators.get("DMP_14")
        minus_di = indicators.get("minus_di") or indicators.get("DMN_14")
        if adx is not None and plus_di is not None and minus_di is not None:
            return 1 if adx > 20 and minus_di > plus_di else 0
        return None

    # ==========================================================================
    # Bollinger conditions
    # ==========================================================================
    if name == "bbAtUpper":
        bb_percent = indicators.get("bb_percent") or indicators.get("PERCENT_B")
        if bb_percent is not None:
            return 1 if bb_percent > 0.95 else 0
        return None

    if name == "bbAtLower":
        bb_percent = indicators.get("bb_percent") or indicators.get("PERCENT_B")
        if bb_percent is not None:
            return 1 if bb_percent < 0.05 else 0
        return None

    if name == "bbSqueeze":
        bb_width = indicators.get("bb_width") or indicators.get("BBW_20")
        if bb_width is not None:
            return 1 if bb_width < 0.05 else 0
        return None

    # ==========================================================================
    # Volume conditions
    # ==========================================================================
    if name == "volumeSpike":
        volume = indicators.get("volume")
        volume_sma = indicators.get("volume_sma_20")
        if volume is not None and volume_sma is not None and volume_sma > 0:
            return 1 if volume > volume_sma * 2 else 0
        return None

    if name == "volumeDry":
        volume = indicators.get("volume")
        volume_sma = indicators.get("volume_sma_20")
        if volume is not None and volume_sma is not None and volume_sma > 0:
            return 1 if volume < volume_sma * 0.5 else 0
        return None

    # ==========================================================================
    # Aroon conditions
    # ==========================================================================
    if name == "aroonTrendUp":
        aroon_up = indicators.get("aroon_up") or indicators.get("AROONU_14")
        aroon_down = indicators.get("aroon_down") or indicators.get("AROOND_14")
        if aroon_up is not None and aroon_down is not None:
            return 1 if aroon_up > aroon_down and aroon_up > 70 else 0
        return None

    if name == "aroonTrendDown":
        aroon_up = indicators.get("aroon_up") or indicators.get("AROONU_14")
        aroon_down = indicators.get("aroon_down") or indicators.get("AROOND_14")
        if aroon_up is not None and aroon_down is not None:
            return 1 if aroon_down > aroon_up and aroon_down > 70 else 0
        return None

    # ==========================================================================
    # Fisher Transform conditions
    # ==========================================================================
    if name == "fisherBullish":
        fisher = indicators.get("fisher") or indicators.get("FISHERT_9")
        fisher_signal = indicators.get("fisher_signal") or indicators.get("FISHERTs_9")
        if fisher is not None and fisher_signal is not None:
            return 1 if fisher > fisher_signal else 0
        return None

    if name == "fisherBearish":
        fisher = indicators.get("fisher") or indicators.get("FISHERT_9")
        fisher_signal = indicators.get("fisher_signal") or indicators.get("FISHERTs_9")
        if fisher is not None and fisher_signal is not None:
            return 1 if fisher < fisher_signal else 0
        return None

    # ==========================================================================
    # Time/Session indicators (require timestamp)
    # ==========================================================================
    timestamp = indicators.get("timestamp")
    if timestamp is not None:
        from datetime import datetime, timezone

        try:
            # Convert timestamp (ms) to datetime
            dt = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
            hour = dt.hour
            weekday = dt.weekday()  # 0=Monday, 6=Sunday

            if name == "isAsianSession":
                # Asian session: 00:00-09:00 UTC (Tokyo/HK/Singapore)
                return 1 if 0 <= hour < 9 else 0

            if name == "isEuropeanSession":
                # European session: 07:00-16:00 UTC (London)
                return 1 if 7 <= hour < 16 else 0

            if name == "isUSMarketHours":
                # US market: 13:30-20:00 UTC (NYSE open)
                return 1 if 13 <= hour < 20 else 0

            if name == "isWeekend":
                return 1 if weekday >= 5 else 0

            if name == "isMonday":
                return 1 if weekday == 0 else 0

            if name == "isTuesday":
                return 1 if weekday == 1 else 0

            if name == "isWednesday":
                return 1 if weekday == 2 else 0

            if name == "isThursday":
                return 1 if weekday == 3 else 0

            if name == "isFriday":
                return 1 if weekday == 4 else 0

        except (ValueError, OSError):
            return None

    # ==========================================================================
    # Regime indicators (simplified heuristic)
    # ==========================================================================
    if name == "volatilityRegime":
        # Return string: "low", "medium", "high"
        natr = indicators.get("natr_14") or indicators.get("NATR_14")
        if natr is not None:
            if natr < 2:
                return "low"
            elif natr < 5:
                return "medium"
            else:
                return "high"
        return None

    if name == "trendRegime":
        # Return string: "uptrend", "downtrend", "sideways"
        adx = indicators.get("adx_14") or indicators.get("ADX_14")
        plus_di = indicators.get("plus_di") or indicators.get("DMP_14")
        minus_di = indicators.get("minus_di") or indicators.get("DMN_14")
        if adx is not None:
            if adx < 20:
                return "sideways"
            elif plus_di is not None and minus_di is not None:
                if plus_di > minus_di:
                    return "uptrend"
                else:
                    return "downtrend"
        return None

    # Not a computed indicator we handle
    return None


# Indicator bounds for confidence calculation
# Uses PostgreSQL enhanced_candles column names (lowercase with underscores)
INDICATOR_BOUNDS = {
    # =========================================================================
    # Motion Derivatives (z-score normalized, typically -5 to 5)
    # =========================================================================
    # Close price derivatives
    "close_velocity_zscore": (-5, 5),
    "close_acceleration_zscore": (-5, 5),
    "close_jerk_zscore": (-5, 5),
    "close_snap_zscore": (-5, 5),
    "close_crackle_zscore": (-5, 5),
    "close_pop_zscore": (-5, 5),
    # Raw derivatives (unbounded, use large range)
    "close_velocity": (-1000, 1000),
    "close_acceleration": (-500, 500),
    "close_jerk": (-200, 200),
    "close_snap": (-100, 100),
    "close_crackle": (-50, 50),
    "close_pop": (-25, 25),
    # RSI derivatives (z-score)
    "rsi_14_velocity_zscore": (-5, 5),
    "rsi_14_acceleration_zscore": (-5, 5),
    "rsi_14_jerk_zscore": (-5, 5),
    # MACD derivatives (z-score)
    "macd_histogram_velocity_zscore": (-5, 5),
    "macd_histogram_acceleration_zscore": (-5, 5),
    "macd_histogram_jerk_zscore": (-5, 5),
    # OBV derivatives (z-score)
    "obv_velocity_zscore": (-5, 5),
    "obv_acceleration_zscore": (-5, 5),
    # ATR derivatives (z-score)
    "atr_14_velocity_zscore": (-5, 5),
    "atr_14_acceleration_zscore": (-5, 5),
    # Divergence flags (boolean: 0 or 1)
    "close_accel_jerk_div": (0, 1),
    "price_vs_rsi_vel_div": (0, 1),
    # =========================================================================
    # RSI variants (0-100)
    "rsi_14": (0, 100),
    "rsi_7": (0, 100),
    "rsi_21": (0, 100),
    # Stochastic (0-100)
    "stoch_k": (0, 100),
    "stoch_d": (0, 100),
    # Stochastic RSI (0-100)
    "stochrsi_k": (0, 100),
    "stochrsi_d": (0, 100),
    # MFI (0-100)
    "mfi_14": (0, 100),
    # ADX (0-100)
    "adx_14": (0, 100),
    # Aroon (0-100)
    "aroon_up": (0, 100),
    "aroon_down": (0, 100),
    "aroon_osc": (-100, 100),
    # CMO (-100 to 100)
    "cmo_14": (-100, 100),
    # Williams %R (-100 to 0)
    "willr_14": (-100, 0),
    # CCI (typically -200 to 200)
    "cci_14": (-200, 200),
    "cci_20": (-200, 200),
    # MACD (typically -10 to 10 for most assets)
    "macd_line": (-10, 10),
    "macd_signal": (-10, 10),
    "macd_histogram": (-5, 5),
    # ROC/Momentum (typically -20 to 20)
    "roc_10": (-20, 20),
    "mom_10": (-50, 50),
    # Bollinger %B (0 to 1, can exceed)
    "bb_percent": (-0.5, 1.5),
    "bb_width": (0, 1),
    # TRIX (typically -0.5 to 0.5)
    "trix": (-0.5, 0.5),
    # DPO (typically -50 to 50)
    "dpo": (-50, 50),
    # Fisher Transform (typically -5 to 5)
    "fisher": (-5, 5),
    "fisher_signal": (-5, 5),
    # BIAS (typically -10 to 10 percent)
    "bias_26": (-10, 10),
    # ATR (typically 0 to 20 for normalized)
    "atr_14": (0, 20),
    "natr_14": (0, 20),
    # Z-Score (-3 to 3 typically)
    "zscore_14": (-3, 3),
    "zscore_30": (-3, 3),
    "zscore_50": (-3, 3),
    # Statistical (entropy, kurtosis, skew)
    "entropy": (0, 10),
    "kurtosis": (-10, 10),
    "skew": (-3, 3),
    # Ultimate Oscillator (0-100)
    "uo": (0, 100),
    # PPO (Percentage Price Oscillator, -5 to 5 typically)
    "ppo": (-5, 5),
    # PVI (Positive Volume Index, cumulative)
    "pvi": (-1e6, 1e6),
    # Ulcer Index (0-100)
    "ui_14": (0, 100),
    # Supertrend direction (-1=bearish, 1=bullish)
    "supertrend_direction": (-1, 1),
    # Awesome Oscillator (typically -50 to 50)
    "ao": (-50, 50),
    # Choppiness (0-100)
    "chop": (0, 100),
    # VHF (0-1)
    "vhf": (0, 1),
    # Mass Index
    "massi": (0, 40),
    # Volume (0 to very large, use relative)
    "volume": (0, 1e12),
    "volume_sma_20": (0, 1e12),
    # Default for unknown indicators
    "_default": (-100, 100),
}


def resolve_indicator(name: str, available: set[str]) -> str | None:
    """
    Resolve indicator name to actual column name.

    Tries (in order):
    1. Direct match (exact column name)
    2. Alias lookup (old name → PostgreSQL name)
    3. Case-insensitive match
    4. Snake_case conversion (camelCase → snake_case)
    5. Fuzzy period matching (ema_20 finds ema_21)

    Args:
        name: Canonical indicator name.
        available: Set of available column names.

    Returns:
        Resolved column name or None.
    """
    # Build lowercase lookup set once for efficiency
    available_lower = {col.lower(): col for col in available}
    name_lower = name.lower()

    # Direct match (case-insensitive)
    if name_lower in available_lower:
        return available_lower[name_lower]

    # Alias lookup (also case-insensitive on both sides)
    alias = INDICATOR_ALIASES.get(name) or INDICATOR_ALIASES.get(name_lower)
    if alias:
        alias_lower = alias.lower()
        if alias_lower in available_lower:
            return available_lower[alias_lower]
        # Reverse lookup: find any available column whose alias maps to same canonical
        # Handles case where DataFrame still uses raw pandas_ta names (e.g. fisherts_9)
        if alias_lower in REVERSE_ALIASES:
            for alt_name in REVERSE_ALIASES[alias_lower]:
                if alt_name in available_lower:
                    return available_lower[alt_name]

    # Convert camelCase to snake_case and try again
    # aroonOsc -> aroon_osc, stochRsi -> stoch_rsi, macdLine -> macd_line
    snake_name = re.sub(r"([a-z])([A-Z])", r"\1_\2", name).lower()
    if snake_name in available_lower:
        return available_lower[snake_name]

    # Also try snake_case prefix/suffix matching
    for col_lower, col_original in available_lower.items():
        # Match if column starts with snake_name (handles period suffixes)
        if col_lower.startswith(snake_name):
            return col_original
        # Match if snake_name starts with column (handles missing periods)
        col_base = col_lower.rstrip("_0123456789")
        if snake_name.startswith(col_base) and col_base:
            return col_original

    # Fuzzy period matching: ema_20 might be stored as ema_21
    period_match = re.match(r"([a-z_]+)(\d+)", snake_name)
    if period_match:
        base, period = period_match.groups()
        period = int(period)
        # Try nearby periods
        for try_period in [period, period + 1, period - 1]:
            try_name = f"{base}_{try_period}"
            if try_name in available_lower:
                return available_lower[try_name]

    return None


def get_indicator_bounds(indicator: str) -> tuple[float, float]:
    """Get min/max bounds for an indicator."""
    if indicator in INDICATOR_BOUNDS:
        return INDICATOR_BOUNDS[indicator]

    # Try to find by prefix
    for key, bounds in INDICATOR_BOUNDS.items():
        if indicator.startswith(key.split("_")[0]):
            return bounds

    return INDICATOR_BOUNDS["_default"]


@dataclass
class MatchResult:
    """Result of pattern matching against a candle."""

    matched: bool
    confidence: float
    conditions_met: int
    conditions_total: int
    condition_details: list[dict]

    # Aliases for test compatibility
    @property
    def passed(self) -> bool:
        return self.matched

    @property
    def overall_confidence(self) -> float:
        return self.confidence


def evaluate_conditions(
    conditions: dict[str, dict] | list[dict],
    indicators: dict[str, float],
) -> MatchResult:
    """
    Evaluate pattern entry/exit conditions against indicator values.

    Args:
        conditions: Dict of indicator -> {operator, value} conditions,
                   OR list of {indicator, operator, value} dicts.
        indicators: Dict of indicator -> current value.

    Returns:
        MatchResult with confidence and condition details.

    Example (dict format):
        conditions = {
            'rsi14': {'operator': '<', 'value': 30},
            'macdHistogram': {'operator': '>', 'value': 0},
        }

    Example (list format from database):
        conditions = [
            {'indicator': 'rsi14', 'operator': '<', 'value': 30},
            {'indicator': 'macdHistogram', 'operator': '>', 'value': 0},
        ]
    """
    if not conditions:
        return MatchResult(
            matched=False,
            confidence=0.0,
            conditions_met=0,
            conditions_total=0,
            condition_details=[],
        )

    # Convert list format to dict format if needed, but keep original conditions for params
    original_conditions_list = conditions if isinstance(conditions, list) else None
    if isinstance(conditions, list):
        conditions_dict = {}
        for cond in conditions:
            if isinstance(cond, dict) and "indicator" in cond:
                indicator_name = cond["indicator"]
                conditions_dict[indicator_name] = {
                    "operator": cond.get("operator", ">"),
                    "value": cond.get("value", cond.get("threshold", 0)),
                    "params": cond.get("params", {}),  # Preserve params for computed indicators
                }
        conditions = conditions_dict

    available = set(indicators.keys())
    details = []
    confidences = []
    met_count = 0
    _shown_available = False  # Only show available columns once per call
    for indicator_name, condition in conditions.items():
        operator = condition.get("operator", ">")
        threshold = condition.get("value", condition.get("threshold", 0))

        # Resolve indicator name
        resolved = resolve_indicator(indicator_name, available)

        # If not found, try computing it (for derived/computed indicators)
        if resolved is None and indicator_name in COMPUTED_INDICATORS:
            computed_value = compute_derived_indicator(indicator_name, indicators, condition)
            if computed_value is not None:
                # Use computed value directly
                resolved = indicator_name  # Use original name for reporting
                indicators[indicator_name] = computed_value  # Add to indicators dict

        if resolved is None:
            # Rate-limited diagnostic: only log each indicator failure ONCE per process
            if indicator_name not in _warned_indicators:
                _warned_indicators.add(indicator_name)
                if not _shown_available:
                    sample_cols = sorted(list(available))[:20]
                    print(f"  [PatternMatch] Available columns ({len(available)} total): {sample_cols}")
                    _shown_available = True
                alias = INDICATOR_ALIASES.get(indicator_name)
                # Sanitize for Windows cp1252 console (pattern data may contain Greek letters)
                safe_name = indicator_name.encode("ascii", errors="replace").decode("ascii")
                safe_alias = str(alias).encode("ascii", errors="replace").decode("ascii") if alias else "None"
                print(f"  [PatternMatch] FAILED to resolve: '{safe_name}' -> alias='{safe_alias}' (not in available)")
            details.append(
                {
                    "indicator": indicator_name,
                    "status": "missing",
                    "confidence": None,
                }
            )
            continue

        current_value = indicators.get(resolved)

        if current_value is None or (isinstance(current_value, float) and math.isnan(current_value)):
            details.append(
                {
                    "indicator": indicator_name,
                    "resolved": resolved,
                    "status": "nan",
                    "confidence": None,
                }
            )
            continue

        # Get bounds for confidence calculation
        min_val, max_val = get_indicator_bounds(resolved)

        # Handle string/categorical thresholds (e.g., 'high', 'uptrend')
        # These need string equality comparison
        if isinstance(threshold, str):
            # Check if current value is also a string (regime indicators)
            if isinstance(current_value, str):
                is_met = current_value == threshold
                details.append(
                    {
                        "indicator": indicator_name,
                        "resolved": resolved,
                        "operator": operator,
                        "threshold": threshold,
                        "value": current_value,
                        "confidence": 1.0 if is_met else 0.0,
                        "met": is_met,
                    }
                )
                if is_met:
                    met_count += 1
                    confidences.append(1.0)
            else:
                # Threshold is string but value is numeric - can't compare
                details.append(
                    {
                        "indicator": indicator_name,
                        "resolved": resolved,
                        "status": "type_mismatch",
                        "threshold": threshold,
                        "value": current_value,
                        "confidence": None,
                    }
                )
            continue

        # Handle list thresholds (e.g., ["sideways", "uptrend"]) for 'in' operator
        if isinstance(threshold, list) and operator == "in":
            if isinstance(current_value, str):
                is_met = current_value in threshold
            else:
                is_met = current_value in threshold
            details.append(
                {
                    "indicator": indicator_name,
                    "resolved": resolved,
                    "operator": operator,
                    "threshold": threshold,
                    "value": current_value,
                    "confidence": 1.0 if is_met else 0.0,
                    "met": is_met,
                }
            )
            if is_met:
                met_count += 1
                confidences.append(1.0)
            continue

        # Handle 'between' operator
        if operator == "between" and isinstance(threshold, (list, tuple)) and len(threshold) == 2:
            threshold_tuple = (float(threshold[0]), float(threshold[1]))
        else:
            threshold_tuple = threshold

        # Calculate confidence
        conf = evaluate_condition_confidence(
            operator=operator,
            value=current_value,
            threshold=threshold_tuple,
            indicator_min=min_val,
            indicator_max=max_val,
        )

        # Condition is "met" only if confidence >= 0.1 (inside threshold)
        # Values below 0.1 are in the decay zone (outside threshold)
        # The confidence system uses 0.1 as the base for inside-threshold values
        is_met = conf is not None and conf >= 0.1

        if is_met:
            met_count += 1
            confidences.append(conf)

        details.append(
            {
                "indicator": indicator_name,
                "resolved": resolved,
                "operator": operator,
                "threshold": threshold,
                "value": current_value,
                "confidence": conf,
                "met": is_met,
            }
        )

    # Calculate overall confidence
    if confidences:
        overall_confidence = sum(confidences) / len(confidences)
    else:
        overall_confidence = 0.0

    # Pattern matches if all conditions are met
    total_conditions = len([d for d in details if d.get("status") not in ("missing", "nan")])
    matched = met_count == total_conditions and total_conditions > 0

    return MatchResult(
        matched=matched,
        confidence=overall_confidence,
        conditions_met=met_count,
        conditions_total=total_conditions,
        condition_details=details,
    )


class PatternMatcher:
    """
    Matches patterns against candle data.

    Handles both entry and exit conditions.
    """

    def __init__(
        self,
        pattern: dict | None = None,
        entry_conditions: dict[str, dict] | None = None,
        exit_conditions: dict[str, dict] | None = None,
        direction: str = "long",
        min_confidence: float = 0.3,
    ):
        """
        Initialize pattern matcher.

        Args:
            pattern: Pattern dict with entry_conditions, exit_conditions, etc.
            entry_conditions: Conditions for entering a trade (overrides pattern).
            exit_conditions: Conditions for exiting (overrides pattern).
            direction: "long" or "short".
            min_confidence: Minimum confidence to trigger entry.
        """
        # Support both pattern dict and direct conditions
        if pattern:
            self.pattern_id = pattern.get("pattern_id", "unknown")
            self.entry_conditions = entry_conditions or pattern.get("entry_conditions", pattern.get("conditions", {}))
            self.exit_conditions = exit_conditions or pattern.get("exit_conditions", {})
            self.direction = pattern.get("direction", direction)
        else:
            self.pattern_id = "unknown"
            self.entry_conditions = entry_conditions or {}
            self.exit_conditions = exit_conditions or {}
            self.direction = direction

        self.min_confidence = min_confidence

    def check_entry(self, indicators: dict[str, float]) -> MatchResult:
        """Check if entry conditions are met."""
        return evaluate_conditions(self.entry_conditions, indicators)

    def check_exit(self, indicators: dict[str, float]) -> MatchResult:
        """Check if exit conditions are met."""
        if not self.exit_conditions:
            return MatchResult(
                matched=False,
                confidence=0.0,
                conditions_met=0,
                conditions_total=0,
                condition_details=[],
            )
        return evaluate_conditions(self.exit_conditions, indicators)

    def should_enter(self, indicators: dict[str, float]) -> tuple[bool, float]:
        """
        Check if we should enter a trade.

        Returns:
            Tuple of (should_enter, confidence).
        """
        result = self.check_entry(indicators)
        should_enter = result.matched and result.confidence >= self.min_confidence
        return should_enter, result.confidence

    def should_exit(
        self,
        indicators: dict[str, float],
        entry_price: float,
        current_price: float,
        stop_loss_pct: float = -10.0,
        take_profit_pct: float = 25.0,
    ) -> tuple[bool, str, float]:
        """
        Check if we should exit a trade.

        Returns:
            Tuple of (should_exit, reason, confidence).
            Reasons: 'condition', 'stop_loss', 'take_profit'
        """
        # Calculate unrealized PnL
        if self.direction == "long":
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
        else:
            pnl_pct = ((entry_price - current_price) / entry_price) * 100

        # Check stop loss
        if pnl_pct <= stop_loss_pct:
            return True, "stop_loss", 1.0

        # Check take profit
        if pnl_pct >= take_profit_pct:
            return True, "take_profit", 1.0

        # Check exit conditions
        if self.exit_conditions:
            result = self.check_exit(indicators)
            if result.matched:
                return True, "condition", result.confidence

        return False, "", 0.0
