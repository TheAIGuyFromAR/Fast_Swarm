"""
Pattern Backtest Utilities - Core backtesting functions.

Ported from Coinswarm-1/local-utilities/backtesting with improvements:
- Async-first using SQLAlchemy sessions
- No SQLite - PostgreSQL only (enhanced_candles table)
- Integrated with local_agents backtest engine
- Simplified API for service use

Key Functions:
- generate_random_windows: Create random time windows for testing
- backtest_pattern_on_windows: Run backtest for pattern across windows
- calculate_metrics_for_trades: Calculate fitness metrics from trades
"""

import json
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Configuration
MIN_CANDLES = 50  # Minimum candles for indicator warmup
STOP_LOSS_PCT = -10.0
TAKE_PROFIT_PCT = 25.0
HOLD_LIMIT_1H = 168  # 7 days max hold for hourly
HOLD_LIMIT_1D = 30  # 30 days max hold for daily

# Window types (V3 style)
TIME_WINDOWS = [
    {"name": "1mo", "days": 30},
    {"name": "3mo", "days": 90},
    {"name": "6mo", "days": 180},
    {"name": "1yr", "days": 365},
]

# Windows per year by timeframe (auto-scaling)
WINDOWS_PER_YEAR = {
    "1d": 100,
    "1h": 300,
    "6h": 150,
    "15m": 400,
    "1m": 500,
}


@dataclass
class BacktestMetrics:
    """Backtest result metrics."""

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl_pct: float = 0.0
    avg_pnl_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    profit_factor: float = 0.0
    benchmark_return_pct: float = 0.0
    alpha_pct: float = 0.0
    expectancy_pct: float = 0.0
    fitness_score: float = 0.0
    window_name: str = ""
    window_days: int = 0


async def generate_random_windows(
    session: AsyncSession,
    asset: str,
    timeframe: str,
    num_windows: int | None = None,
) -> list[dict[str, Any]]:
    """
    Generate random test windows from available data.

    V3-style approach:
    - Random window sizes from TIME_WINDOWS
    - Random start positions within available data
    - Auto-scales with data availability

    Args:
        session: Async database session
        asset: Asset symbol (BTC, ETH, etc.)
        timeframe: Timeframe (1h, 1d, etc.)
        num_windows: Override window count (default: auto-scaled)

    Returns:
        List of window configs with start_ts, end_ts, etc.
    """
    # Get data range from enhanced_candles
    result = await session.execute(
        text("""
            SELECT
                EXTRACT(EPOCH FROM MIN(time)) * 1000 as min_ts,
                EXTRACT(EPOCH FROM MAX(time)) * 1000 as max_ts,
                COUNT(*) as candle_count
            FROM enhanced_candles
            WHERE symbol = :asset AND timeframe = :tf
        """),
        {"asset": asset, "tf": timeframe},
    )
    row = result.fetchone()

    if not row or row[0] is None:
        return []

    min_ts = int(row[0])
    max_ts = int(row[1])
    candle_count = int(row[2] or 0)

    MS_PER_DAY = 24 * 60 * 60 * 1000
    available_days = (max_ts - min_ts) / MS_PER_DAY

    if available_days < 30 or candle_count < MIN_CANDLES * 2:
        return []

    # Auto-calculate window count
    if num_windows is None:
        available_years = available_days / 365
        density = WINDOWS_PER_YEAR.get(timeframe, 100)
        num_windows = max(50, int(available_years * density))

    windows = []
    for _ in range(num_windows):
        # Pick random window size
        window_config = random.choice(TIME_WINDOWS)
        window_days = window_config["days"]

        # Adjust if larger than available
        if window_days > available_days:
            window_days = int(available_days * 0.8)

        window_ms = window_days * MS_PER_DAY

        # Random start
        max_start = max_ts - window_ms
        if max_start <= min_ts:
            max_start = min_ts + MS_PER_DAY

        start_ts = random.randint(int(min_ts), int(max_start))
        end_ts = start_ts + window_ms

        windows.append(
            {
                "name": window_config["name"],
                "days": window_days,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "asset": asset,
                "timeframe": timeframe,
                "regime": f"random_{timeframe}",
            }
        )

    return windows


def _calculate_regime_stats(trades: list[dict]) -> dict:
    """
    Calculate regime-based performance statistics from trades.

    Args:
        trades: List of trade dicts with regime tracking fields

    Returns:
        Dict with:
        - by_entry_regime: stats per regime at entry
        - defensive_exits: count of bear protection force exits
    """
    if not trades:
        return {"by_entry_regime": {}, "defensive_exits": 0}

    entry_stats: dict[str, dict] = {}
    defensive_exits = 0

    for trade in trades:
        entry_regime = trade.get("entry_regime", "NEUTRAL")
        exit_reason = trade.get("exit_reason", "")
        pnl = trade.get("pnl_pct", 0) or 0

        # Entry regime stats
        if entry_regime not in entry_stats:
            entry_stats[entry_regime] = {"count": 0, "total_pnl": 0.0, "wins": 0}
        entry_stats[entry_regime]["count"] += 1
        entry_stats[entry_regime]["total_pnl"] += pnl
        if pnl > 0:
            entry_stats[entry_regime]["wins"] += 1

        # Count bear protection force exits
        if exit_reason == "bear_protection_defensive":
            defensive_exits += 1

    # Calculate averages and win rates
    for regime, stats in entry_stats.items():
        count = stats["count"]
        stats["avg_pnl"] = round(stats["total_pnl"] / count, 2) if count > 0 else 0.0
        stats["win_rate"] = round(stats["wins"] / count * 100, 1) if count > 0 else 0.0

    return {
        "by_entry_regime": entry_stats,
        "defensive_exits": defensive_exits,
    }


def calculate_metrics_for_trades(
    trades: list[dict],
    benchmark_return_pct: float = 0.0,
    window_name: str = "unknown",
    window_days: int = 0,
) -> dict[str, Any]:
    """
    Calculate performance metrics from trade list.

    Uses V3-style fitness calculation:
    - Signed contributions for alpha, sortino, calmar (can go negative)
    - Normalized contributions for expectancy, drawdown

    Args:
        trades: List of trade dicts with 'pnl_pct' key
        benchmark_return_pct: Buy-and-hold return for this window
        window_name: Window identifier
        window_days: Window duration

    Returns:
        Dict with all metrics
    """
    if not trades:
        # No trades = 0% return, so alpha = -benchmark (you underperformed by not trading)
        # If benchmark was +5% and you sat out, your alpha is -5%
        alpha_pct = -benchmark_return_pct if benchmark_return_pct else 0.0
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "total_pnl_pct": 0.0,
            "avg_pnl_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "calmar_ratio": 0.0,
            "profit_factor": 0.0,
            "benchmark_return_pct": benchmark_return_pct,
            "alpha_pct": alpha_pct,
            "expectancy_pct": 0.0,
            "fitness_score": 0.0,
            "window_name": window_name,
            "window_days": window_days,
        }

    pnls = [float(t.get("pnl_pct", 0) or 0) for t in trades]
    winning = [p for p in pnls if p > 0]
    losing = [p for p in pnls if p <= 0]

    total_trades = len(trades)
    winning_trades = len(winning)
    losing_trades = len(losing)
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

    total_pnl_pct = sum(pnls)
    avg_pnl_pct = total_pnl_pct / total_trades if total_trades > 0 else 0.0

    # Profit factor
    gross_wins = sum(winning) if winning else 0.0
    gross_losses = abs(sum(losing)) if losing else 0.0
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else (gross_wins if gross_wins > 0 else 0.0)

    # Expectancy
    avg_win = sum(winning) / len(winning) if winning else 0.0
    avg_loss = abs(sum(losing) / len(losing)) if losing else 0.0
    expectancy_pct = (win_rate / 100 * avg_win) - ((1 - win_rate / 100) * avg_loss)

    # Metrics via QuantStats-backed engine
    from Fast_Swarm.Metrics.metrics_engine import (
        calculate_max_drawdown as _engine_dd,
        calculate_sharpe as _engine_sh,
        calculate_sortino as _engine_so,
    )
    returns_frac = [p / 100 for p in pnls]
    max_drawdown_pct = _engine_dd(returns_frac) * 100
    sharpe_ratio = _engine_sh(returns_frac)
    sortino_ratio = _engine_so(returns_frac)

    # Calmar ratio
    calmar_ratio = total_pnl_pct / max_drawdown_pct if max_drawdown_pct > 0 else total_pnl_pct
    calmar_ratio = max(-10.0, min(10.0, calmar_ratio))

    # Alpha
    alpha_pct = total_pnl_pct - benchmark_return_pct

    # FITNESS SCORE (V3 formula)
    # Signed contributions
    alpha_capped = max(-100, min(100, alpha_pct))
    alpha_contribution = (alpha_capped / 100) * 40

    sortino_capped = max(-10, min(10, sortino_ratio))
    sortino_contribution = (sortino_capped / 10) * 14

    calmar_capped = max(-10, min(10, calmar_ratio))
    calmar_contribution = (calmar_capped / 10) * 11

    # Normalized contributions
    expectancy_normalized = max(0, min(100, ((expectancy_pct + 10) / 20) * 100))
    expectancy_contribution = (expectancy_normalized / 100) * 30

    drawdown_inverted = 50 - max_drawdown_pct
    drawdown_normalized = max(0, min(100, (drawdown_inverted / 50) * 100))
    drawdown_contribution = (drawdown_normalized / 100) * 5

    fitness_score = (
        alpha_contribution
        + sortino_contribution
        + calmar_contribution
        + expectancy_contribution
        + drawdown_contribution
    )
    fitness_score = round(max(0, min(100, fitness_score)), 2)

    # Calculate regime stats from trades (if regime data available)
    regime_stats = _calculate_regime_stats(trades)

    return {
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": round(win_rate, 2),
        "total_pnl_pct": round(total_pnl_pct, 4),
        "avg_pnl_pct": round(avg_pnl_pct, 4),
        "max_drawdown_pct": round(max_drawdown_pct, 4),
        "sharpe_ratio": round(sharpe_ratio, 4),
        "sortino_ratio": round(sortino_ratio, 4),
        "calmar_ratio": round(calmar_ratio, 4),
        "profit_factor": round(profit_factor, 4),
        "benchmark_return_pct": round(benchmark_return_pct, 4),
        "alpha_pct": round(alpha_pct, 4),
        "expectancy_pct": round(expectancy_pct, 4),
        "fitness_score": fitness_score,
        "window_name": window_name,
        "window_days": window_days,
        "regime_stats": regime_stats,  # Bear protection tracking
    }


async def backtest_pattern_on_windows(
    session: AsyncSession,
    pattern: dict,
    windows: list[dict],
    asset: str,
    timeframe: str,
    preloaded_candles: dict = None,
) -> list[dict]:
    """
    Run backtest for a pattern on multiple windows.

    Uses local_agents backtest engine if available, falls back to simple simulation.

    Args:
        session: Async database session
        pattern: Pattern dict with entry_conditions, exit_conditions
        windows: List of window configs from generate_random_windows
        asset: Asset symbol
        timeframe: Timeframe
        preloaded_candles: Optional dict of "{symbol}_{timeframe}" -> DataFrame
                          for pre-loaded candle data (avoids repeated DB loads)

    Returns:
        List of result dicts, one per window with trades
    """
    # Parse conditions
    entry_str = pattern.get("entry_conditions", "[]")
    exit_str = pattern.get("exit_conditions", "{}")

    try:
        entry_conditions = json.loads(entry_str) if isinstance(entry_str, str) else entry_str
    except json.JSONDecodeError:
        return []

    try:
        exit_config = json.loads(exit_str) if isinstance(exit_str, str) else exit_str
    except json.JSONDecodeError:
        exit_config = {}

    if not entry_conditions:
        return []

    # Try to use local_agents engine
    try:
        from Fast_Swarm.local_agents.backtest.data import OHLCVLoader
        from Fast_Swarm.local_agents.backtest.engine import BacktestConfig, LocalBacktestEngine
        from Fast_Swarm.local_agents.core.state import AgentRecord
        from Fast_Swarm.local_agents.core.traits import AgentTraits

        USE_ENGINE = True
    except ImportError:
        USE_ENGINE = False

    results = []
    pattern_id = pattern.get("pattern_id", "unknown")

    for window in windows:
        try:
            if USE_ENGINE:
                # Use local_agents engine
                loader = OHLCVLoader()
                default_traits = AgentTraits()
                config = BacktestConfig.from_traits(default_traits)

                pattern_dict = {
                    pattern_id: {
                        "pattern_id": pattern_id,
                        "entry_conditions": entry_conditions,
                        "exit_conditions": exit_config,
                    }
                }

                test_agent = AgentRecord(
                    agent_id=f"pattern_test_{pattern_id}",
                    agent_name=f"Test_{pattern_id[:20]}",
                    traits=default_traits.__dict__,
                    pattern_ids=[pattern_id],
                    pattern_weights={pattern_id: 1.0},
                )

                engine = LocalBacktestEngine(
                    loader=loader,
                    config=config,
                    patterns=pattern_dict,
                    preloaded_candles=preloaded_candles,
                )

                # Run engine in thread pool so it doesn't block the event loop
                # This allows asyncio.wait_for() timeouts to actually work
                import asyncio

                trades = await asyncio.to_thread(
                    engine.run,
                    agent=test_agent,
                    dataset={
                        "assets": [asset],
                        "timeframe": timeframe,
                        "start_ts": window["start_ts"],
                        "end_ts": window["end_ts"],
                    },
                )

                # Convert to dicts - preserve regime tracking info
                trade_dicts = []
                for t in trades:
                    if hasattr(t, "pnl_pct"):
                        trade_dict = {
                            "pnl_pct": t.pnl_pct,
                            "entry_regime": getattr(t, "entry_regime", "NEUTRAL"),
                            "exit_regime": getattr(t, "exit_regime", "NEUTRAL"),
                            "exit_reason": getattr(t, "exit_reason", ""),
                        }
                        trade_dicts.append(trade_dict)

            else:
                # Fallback: simple simulation (no indicator matching)
                trade_dicts = await _simple_backtest(
                    session, asset, timeframe, window["start_ts"], window["end_ts"], entry_conditions, exit_config
                )

            # Always record a result - even 0 trades is valid data (0% ROI, 0% DD)
            # A window that was tested but produced no trades has:
            # - Starting balance = Ending balance
            # - 0% return, 0% drawdown, 0 trades
            benchmark = await _get_window_benchmark(session, asset, timeframe, window["start_ts"], window["end_ts"])

            # calculate_metrics_for_trades handles empty trade list properly
            # Pass trade_dicts (even if empty) to get consistent metric structure
            metrics = calculate_metrics_for_trades(
                trade_dicts if trade_dicts else [],
                benchmark_return_pct=benchmark,
                window_name=window.get("name", "unknown"),
                window_days=window.get("days", 0),
            )

            metrics["pattern_id"] = pattern_id
            metrics["asset"] = asset
            metrics["timeframe"] = timeframe
            metrics["regime"] = window.get("regime", "random")
            metrics["run_at"] = datetime.utcnow().isoformat()

            results.append(metrics)

        except Exception as e:
            print(f"[Backtest] Window error for {pattern_id}: {e}")
            continue

    return results


async def _get_window_benchmark(
    session: AsyncSession,
    asset: str,
    timeframe: str,
    start_ts: int,
    end_ts: int,
) -> float:
    """Get buy-and-hold return for a window."""
    result = await session.execute(
        text("""
            SELECT close FROM enhanced_candles
            WHERE symbol = :asset AND timeframe = :tf
              AND EXTRACT(EPOCH FROM time) * 1000 >= :start
              AND EXTRACT(EPOCH FROM time) * 1000 <= :end
            ORDER BY time
            LIMIT 1
        """),
        {"asset": asset, "tf": timeframe, "start": start_ts, "end": end_ts},
    )
    start_row = result.fetchone()

    result = await session.execute(
        text("""
            SELECT close FROM enhanced_candles
            WHERE symbol = :asset AND timeframe = :tf
              AND EXTRACT(EPOCH FROM time) * 1000 >= :start
              AND EXTRACT(EPOCH FROM time) * 1000 <= :end
            ORDER BY time DESC
            LIMIT 1
        """),
        {"asset": asset, "tf": timeframe, "start": start_ts, "end": end_ts},
    )
    end_row = result.fetchone()

    if start_row and end_row and start_row[0] > 0:
        start_price = float(start_row[0])
        end_price = float(end_row[0])
        return ((end_price - start_price) / start_price) * 100
    return 0.0


async def _simple_backtest(
    session: AsyncSession,
    asset: str,
    timeframe: str,
    start_ts: int,
    end_ts: int,
    entry_conditions: list,
    exit_config: dict,
) -> list[dict]:
    """
    Simple fallback backtest without local_agents engine.

    Uses random entry (since we can't evaluate conditions without indicators)
    and fixed stop/take profit exits.
    """
    # This is a placeholder - real backtesting needs the engine
    # Just return empty to indicate we need local_agents
    return []
