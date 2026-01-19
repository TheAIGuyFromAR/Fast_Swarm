"""
Pattern Discovery Service - Priority queue-based pattern testing.

This service implements the complete pattern testing flow:
1. Priority Queue: HIGH (fast-track) → NORMAL (active) → LOW (deprioritized)
2. Batch Backtest: Uses pre-generated window pool (15K+ windows at startup)
3. Fitness Calculation: V2 Signed Risk formula (no EV gate)
4. Tier Promotion: TIER 3 (untested) → TIER 2 (proven) → TIER 1 (elite)

Utilities are now local to Fast_Swarm (no external path dependencies).
"""

# Import local utilities (ported from Coinswarm-1/local-utilities)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from Fast_Swarm.local_agents.backtest.windows import get_windows_for_symbol, is_initialized
from Fast_Swarm.utilities import (
    PatternDiscoveryScheduler,
    backtest_pattern_on_windows,
    get_prioritized_patterns,
    update_priority_after_backtest,
)

from ..Models.pattern_models import Pattern


class PatternDiscoveryService:
    """Service for pattern discovery and priority-based testing."""

    async def run_batch_backtest(
        self,
        session: AsyncSession,
        batch_size: int = 50,
        priority_filter: str | None = None,
    ) -> dict:
        """
        Run batch backtest using priority queue.

        This is the main entry point that:
        1. Gets patterns from priority queue
        2. Runs batch backtest (random windows)
        3. Updates fitness and priority
        4. Promotes patterns to higher tiers

        Args:
            session: Database session
            batch_size: Number of patterns to test
            priority_filter: "high", "normal", "low", or None (all)

        Returns:
            Dict with backtest results
        """
        # Get patterns from priority queue
        include_low = priority_filter == "low" or priority_filter is None
        patterns = await get_prioritized_patterns(
            session,
            limit=batch_size,
            include_low=include_low,
        )

        if not patterns:
            return {
                "patterns_tested": 0,
                "message": "No patterns in priority queue",
            }

        import time

        batch_start = time.time()
        print(f"[PatternBacktest] Testing {len(patterns)} patterns across 3 assets...")

        # Use pre-generated window pool (loaded at server startup)
        assets = ["BTC", "ETH", "SOL"]
        windows_per_asset = 10

        if not is_initialized():
            print("[PatternBacktest] ERROR: Window pool not initialized!")
            return {
                "patterns_tested": 0,
                "error": "Window pool not initialized - restart server",
            }

        # Grab windows from the pre-generated pool (instant, no DB queries)
        print(f"[PatternBacktest] Sampling {windows_per_asset} windows per asset from pool...")
        windows_by_asset = {}
        for asset in assets:
            # Convert Window objects to dicts for backtest_pattern_on_windows
            pool_windows = get_windows_for_symbol(asset, count=windows_per_asset)
            if pool_windows:
                windows_by_asset[asset] = [
                    {"start_ts": w.start_ts, "end_ts": w.end_ts, "symbol": w.symbol, "timeframe": w.timeframe}
                    for w in pool_windows
                ]
                print(f"[PatternBacktest]   {asset}: {len(pool_windows)} windows")
            else:
                print(f"[PatternBacktest]   {asset}: NO WINDOWS IN POOL")

        if not windows_by_asset:
            print("[PatternBacktest] ERROR: No windows in pool for any asset")
            return {
                "patterns_tested": 0,
                "error": "No windows in pool for target assets",
            }

        total_windows = sum(len(w) for w in windows_by_asset.values())
        print(f"[PatternBacktest] Ready: {total_windows} windows from pool")

        # Run batch backtest (V3-style random windows)
        results = {}
        tested = 0

        for idx, pattern in enumerate(patterns):
            pid = pattern.get("pattern_id")
            pattern_start = time.time()
            print(f"[PatternBacktest] [{idx + 1}/{len(patterns)}] Testing {pid[:16]}...", end=" ", flush=True)
            try:
                # Test on multiple assets using PRE-GENERATED windows
                # Each window already has its own timeframe from the pool
                all_results = []
                for asset, asset_windows in windows_by_asset.items():
                    for window in asset_windows:
                        window_results = await backtest_pattern_on_windows(
                            session, pattern, [window], asset, window["timeframe"]
                        )
                        all_results.extend(window_results)

                pattern_elapsed = time.time() - pattern_start
                if all_results:
                    # Aggregate results
                    avg_fitness = sum(r.get("fitness_score", 0) for r in all_results) / len(all_results)
                    total_trades = sum(r.get("total_trades", 0) for r in all_results)

                    results[pid] = {
                        "fitness": avg_fitness,
                        "total_trades": total_trades,
                        "windows_tested": len(all_results),
                    }

                    # Update priority
                    await update_priority_after_backtest(
                        session,
                        pid,
                        new_runs=(pattern.get("total_runs") or 0) + len(all_results),
                        new_periods_tested=(pattern.get("periods_tested") or 0) + len(all_results),
                        new_fitness=avg_fitness,
                    )
                    tested += 1
                    print(
                        f"fitness={avg_fitness:.1f}, trades={total_trades}, windows={len(all_results)} ({pattern_elapsed:.1f}s)"
                    )
                else:
                    print(f"0 trades, 0 windows ({pattern_elapsed:.1f}s)")
                    results[pid] = {"total_trades": 0, "windows_tested": 0}

            except Exception as e:
                print(f"ERROR: {e}")
                results[pid] = {"error": str(e)}

        # Check for tier promotions
        batch_elapsed = time.time() - batch_start
        print("[PatternBacktest] Checking tier promotions...")
        promotions = await self._check_tier_promotions(session)

        print(f"[PatternBacktest] DONE: {tested}/{len(patterns)} patterns tested in {batch_elapsed:.1f}s")
        if promotions:
            print(f"[PatternBacktest] Tier promotions: {promotions}")

        return {
            "patterns_tested": tested,
            "total_patterns": len(patterns),
            "tier_promotions": promotions,
            "results": results,
        }

    async def run_discovery_cycle(
        self,
        session: AsyncSession,
    ) -> dict:
        """
        Run pattern discovery cycle (creates new patterns).

        Uses PatternDiscoveryScheduler to:
        1. Load chaos trades from PostgreSQL
        2. RandomForest extracts top 20 features
        3. LLM generates patterns
        4. Inserts with status='untested', origin='automated_discovery'

        Returns:
            Dict with discovery results
        """
        scheduler = PatternDiscoveryScheduler(interval_hours=6)
        result = await scheduler.run_discovery_cycle(session)

        return result.to_dict()

    async def _check_tier_promotions(self, session: AsyncSession) -> dict:
        """
        Check for patterns that should be promoted to higher tiers.

        Tier System:
        - TIER 3 (Untested): fitness = 0
        - TIER 2 (Proven): fitness 40-79
        - TIER 1 (Elite): fitness 80+

        Returns:
            Dict with promotion counts
        """
        # Get patterns that need tier updates
        result = await session.exec(select(Pattern).where(Pattern.is_active.is_(True)))
        patterns = result.all()

        promotions = {"to_tier_1": 0, "to_tier_2": 0}

        for pattern in patterns:
            fitness = pattern.fitness_score or 0
            current_tier = pattern.tier or 3

            # Promote to TIER 1 (Elite)
            if fitness >= 80 and current_tier != 1:
                pattern.tier = 1
                session.add(pattern)
                promotions["to_tier_1"] += 1

            # Promote to TIER 2 (Proven)
            elif fitness >= 40 and current_tier == 3:
                pattern.tier = 2
                session.add(pattern)
                promotions["to_tier_2"] += 1

        await session.commit()
        return promotions

    async def test_pattern_on_windows(
        self,
        session: AsyncSession,
        pattern,
        windows: list[dict],
        preloaded_candles: dict = None,
    ) -> dict:
        """
        Test a single pattern on pre-loaded windows (used by orchestrator).

        This is called by the orchestrator to test patterns one at a time
        on windows that have already been loaded. This avoids loading
        candle data multiple times.

        Args:
            session: Database session
            pattern: Pattern model object
            windows: List of window dicts with asset/timeframe/start_ts/end_ts
            preloaded_candles: Dict of (symbol, timeframe, start_ts) -> DataFrame

        Returns:
            Dict with test results
        """
        import time

        pattern_start = time.time()
        pid = pattern.pattern_id

        # Log window details at start
        if windows:
            w = windows[0]
            window_summary = f"{w.get('asset', '?')}/{w.get('timeframe', '?')}"
            if len(windows) > 1:
                window_summary += f" (+{len(windows) - 1} more)"
            print(f"[PatternTest] {pid[:8]}: testing on {window_summary}...")

        # Convert pattern model to dict format for backtest_pattern_on_windows
        pattern_dict = {
            "pattern_id": pattern.pattern_id,
            "entry_conditions": pattern.entry_conditions,
            "exit_conditions": pattern.exit_conditions,
        }

        all_results = []

        for window in windows:
            try:
                # backtest_pattern_on_windows expects windows as list
                window_results = await backtest_pattern_on_windows(
                    session,
                    pattern_dict,
                    [window],
                    window.get("asset", "BTC"),
                    window.get("timeframe", "1h"),
                    preloaded_candles=preloaded_candles,
                )
                all_results.extend(window_results)
            except Exception as e:
                print(f"[PatternTest] Window error for {pid[:8]}: {e}")

        pattern_elapsed = time.time() - pattern_start

        if all_results:
            # Aggregate results
            avg_fitness = sum(r.get("fitness_score", 0) for r in all_results) / len(all_results)
            total_trades = sum(r.get("total_trades", 0) for r in all_results)

            # Extract key metrics for logging
            avg_alpha = sum(r.get("alpha_pct", 0) for r in all_results) / len(all_results)
            avg_sortino = sum(r.get("sortino_ratio", 0) for r in all_results) / len(all_results)
            avg_drawdown = sum(r.get("max_drawdown_pct", 0) for r in all_results) / len(all_results)
            avg_win_rate = sum(r.get("win_rate", 0) for r in all_results) / len(all_results)
            total_pnl = sum(r.get("total_pnl_pct", 0) for r in all_results)

            # Get window info for logging
            window_info = ""
            if windows:
                w = windows[0]
                asset = w.get("asset", "?")
                tf = w.get("timeframe", "?")
                regime = w.get("regime", "?")
                window_info = f"{asset}/{tf} ({regime})"

            # Update pattern stats
            pattern.fitness_score = avg_fitness
            pattern.total_runs = (pattern.total_runs or 0) + len(all_results)
            pattern.periods_tested = (pattern.periods_tested or 0) + len(all_results)

            from datetime import datetime

            pattern.last_backtest_at = datetime.utcnow()

            session.add(pattern)

            # Enhanced logging with key fitness components
            print(
                f"[PatternTest] {pid[:8]}: "
                f"fitness={avg_fitness:.1f}, trades={total_trades}, "
                f"α={avg_alpha:+.1f}%, sortino={avg_sortino:.2f}, "
                f"DD={avg_drawdown:.1f}%, WR={avg_win_rate:.0f}%, "
                f"PnL={total_pnl:+.1f}% | {window_info} ({pattern_elapsed:.1f}s)"
            )

            return {
                "pattern_id": pid,
                "fitness": avg_fitness,
                "total_trades": total_trades,
                "windows_tested": len(all_results),
            }
        else:
            # No windows produced results - could be: no entry signals, asset mismatch, or too few candles
            window_info = ""
            candle_info = ""
            if windows:
                w = windows[0]
                asset = w.get("asset", "?")
                tf = w.get("timeframe", "?")
                window_info = f" | {asset}/{tf}"

                # Check candle count if preloaded_candles available
                if preloaded_candles:
                    cache_key = f"{asset}_{tf}"
                    if cache_key in preloaded_candles:
                        try:
                            candles = preloaded_candles[cache_key]
                            candle_info = f" ({len(candles)} candles)"
                        except Exception:
                            candle_info = " (candles err)"
                    else:
                        candle_info = f" (no {cache_key} in cache)"

            print(f"[PatternTest] {pid[:8]}: 0 trades, 0 windows{window_info}{candle_info} ({pattern_elapsed:.1f}s)")
            return {
                "pattern_id": pid,
                "total_trades": 0,
                "windows_tested": 0,
            }

    async def _run_in_thread(self, func, *args, **kwargs):
        """Run blocking function in thread pool."""
        import asyncio

        return await asyncio.to_thread(func, *args, **kwargs)
