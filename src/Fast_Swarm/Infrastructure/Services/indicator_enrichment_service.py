"""
Indicator Enrichment Service - Precomputes derived indicators for enhanced_candles.

This service computes derived/computed indicators (like maCross, volatilityRegime, etc.)
and stores them directly in the enhanced_candles table. This eliminates the need to
compute these indicators on-the-fly during backtesting, providing massive performance gains.

The indicators computed here match what patterns expect from COMPUTED_INDICATORS in pattern_matcher.py.
"""

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from Fast_Swarm.Database import async_session_maker

logger = logging.getLogger("indicator_enrichment")


# Batch size for updates (avoid memory issues on 5M+ rows)
BATCH_SIZE = 10000


async def compute_derived_indicators_batch(
    session: AsyncSession,
    symbol: str | None = None,
    timeframe: str | None = None,
    limit: int | None = None,
) -> int:
    """
    Compute derived indicators for candles that don't have them yet.

    This updates the enhanced_candles table in batches, computing:
    - MA cross signals (ma_cross_20_50, golden_cross, death_cross)
    - MACD cross signal
    - Price vs MA percentages
    - RSI/Stoch conditions
    - Trend/volatility regimes
    - Session indicators
    - Volume conditions

    Args:
        session: Database session
        symbol: Optional symbol filter (e.g., 'BTC')
        timeframe: Optional timeframe filter (e.g., '1h')
        limit: Optional limit on rows to process

    Returns:
        Number of rows updated
    """
    # Build WHERE clause for filtering
    where_clauses = ["derived_computed_at IS NULL"]
    if symbol:
        where_clauses.append(f"symbol = '{symbol}'")
    if timeframe:
        where_clauses.append(f"timeframe = '{timeframe}'")

    where_sql = " AND ".join(where_clauses)
    limit_sql = f"LIMIT {limit}" if limit else ""

    # SQL to compute all derived indicators in one pass
    # This is MUCH faster than Python loops - let PostgreSQL do the work
    update_sql = text(f"""
        UPDATE enhanced_candles ec
        SET
            -- MA Cross signals (1 = bullish, -1 = bearish, 0 = neutral)
            ma_cross_20_50 = CASE
                WHEN ema_21 IS NOT NULL AND sma_50 IS NOT NULL THEN
                    CASE WHEN ema_21 > sma_50 THEN 1 WHEN ema_21 < sma_50 THEN -1 ELSE 0 END
                ELSE NULL
            END,

            golden_cross = CASE
                WHEN sma_50 IS NOT NULL AND sma_200 IS NOT NULL THEN
                    CASE WHEN sma_50 > sma_200 THEN 1 ELSE 0 END
                ELSE NULL
            END,

            death_cross = CASE
                WHEN sma_50 IS NOT NULL AND sma_200 IS NOT NULL THEN
                    CASE WHEN sma_50 < sma_200 THEN 1 ELSE 0 END
                ELSE NULL
            END,

            -- MACD Cross
            macd_cross = CASE
                WHEN macd_line IS NOT NULL AND macd_signal IS NOT NULL THEN
                    CASE WHEN macd_line > macd_signal THEN 1 WHEN macd_line < macd_signal THEN -1 ELSE 0 END
                ELSE NULL
            END,

            -- Price vs MA percentages
            price_vs_ema_9_pct = CASE
                WHEN ema_9 IS NOT NULL AND ema_9 > 0 THEN ((close - ema_9) / ema_9) * 100
                ELSE NULL
            END,

            price_vs_ema_20_pct = CASE
                WHEN ema_21 IS NOT NULL AND ema_21 > 0 THEN ((close - ema_21) / ema_21) * 100
                ELSE NULL
            END,

            price_vs_ema_21_pct = CASE
                WHEN ema_21 IS NOT NULL AND ema_21 > 0 THEN ((close - ema_21) / ema_21) * 100
                ELSE NULL
            END,

            price_vs_sma_50_pct = CASE
                WHEN sma_50 IS NOT NULL AND sma_50 > 0 THEN ((close - sma_50) / sma_50) * 100
                ELSE NULL
            END,

            price_vs_sma_200_pct = CASE
                WHEN sma_200 IS NOT NULL AND sma_200 > 0 THEN ((close - sma_200) / sma_200) * 100
                ELSE NULL
            END,

            -- Price above MA booleans
            price_above_ema_9 = CASE WHEN ema_9 IS NOT NULL THEN CASE WHEN close > ema_9 THEN 1 ELSE 0 END ELSE NULL END,
            price_above_ema_20 = CASE WHEN ema_21 IS NOT NULL THEN CASE WHEN close > ema_21 THEN 1 ELSE 0 END ELSE NULL END,
            price_above_ema_21 = CASE WHEN ema_21 IS NOT NULL THEN CASE WHEN close > ema_21 THEN 1 ELSE 0 END ELSE NULL END,
            price_above_sma_50 = CASE WHEN sma_50 IS NOT NULL THEN CASE WHEN close > sma_50 THEN 1 ELSE 0 END ELSE NULL END,
            price_above_sma_200 = CASE WHEN sma_200 IS NOT NULL THEN CASE WHEN close > sma_200 THEN 1 ELSE 0 END ELSE NULL END,

            -- RSI conditions
            rsi_oversold = CASE WHEN rsi_14 IS NOT NULL THEN CASE WHEN rsi_14 < 30 THEN 1 ELSE 0 END ELSE NULL END,
            rsi_overbought = CASE WHEN rsi_14 IS NOT NULL THEN CASE WHEN rsi_14 > 70 THEN 1 ELSE 0 END ELSE NULL END,
            rsi_neutral = CASE WHEN rsi_14 IS NOT NULL THEN CASE WHEN rsi_14 >= 30 AND rsi_14 <= 70 THEN 1 ELSE 0 END ELSE NULL END,

            -- Stochastic conditions
            stoch_oversold = CASE WHEN stoch_k IS NOT NULL THEN CASE WHEN stoch_k < 20 THEN 1 ELSE 0 END ELSE NULL END,
            stoch_overbought = CASE WHEN stoch_k IS NOT NULL THEN CASE WHEN stoch_k > 80 THEN 1 ELSE 0 END ELSE NULL END,

            -- Trend strength
            strong_trend = CASE WHEN adx_14 IS NOT NULL THEN CASE WHEN adx_14 > 25 THEN 1 ELSE 0 END ELSE NULL END,
            weak_trend = CASE WHEN adx_14 IS NOT NULL THEN CASE WHEN adx_14 < 20 THEN 1 ELSE 0 END ELSE NULL END,

            -- Volatility regime (based on NATR)
            volatility_regime = CASE
                WHEN natr_14 IS NOT NULL THEN
                    CASE
                        WHEN natr_14 < 2 THEN 'low'
                        WHEN natr_14 < 5 THEN 'medium'
                        ELSE 'high'
                    END
                ELSE NULL
            END,

            -- Trend regime (based on ADX and DI)
            trend_regime = CASE
                WHEN adx_14 IS NOT NULL THEN
                    CASE
                        WHEN adx_14 < 20 THEN 'sideways'
                        WHEN plus_di IS NOT NULL AND minus_di IS NOT NULL THEN
                            CASE WHEN plus_di > minus_di THEN 'uptrend' ELSE 'downtrend' END
                        ELSE 'sideways'
                    END
                ELSE NULL
            END,

            -- Session indicators (based on hour of candle timestamp)
            -- Note: Must use ec.time to avoid ambiguity with batch.time
            is_asian_session = CASE WHEN EXTRACT(HOUR FROM ec.time) >= 0 AND EXTRACT(HOUR FROM ec.time) < 8 THEN 1 ELSE 0 END,
            is_london_session = CASE WHEN EXTRACT(HOUR FROM ec.time) >= 8 AND EXTRACT(HOUR FROM ec.time) < 16 THEN 1 ELSE 0 END,
            is_us_session = CASE WHEN EXTRACT(HOUR FROM ec.time) >= 13 AND EXTRACT(HOUR FROM ec.time) < 21 THEN 1 ELSE 0 END,
            is_us_market_hours = CASE WHEN EXTRACT(HOUR FROM ec.time) >= 14 AND EXTRACT(HOUR FROM ec.time) < 21 THEN 1 ELSE 0 END,

            -- Bollinger conditions
            price_at_bb_upper = CASE WHEN bb_upper IS NOT NULL THEN CASE WHEN close >= bb_upper THEN 1 ELSE 0 END ELSE NULL END,
            price_at_bb_lower = CASE WHEN bb_lower IS NOT NULL THEN CASE WHEN close <= bb_lower THEN 1 ELSE 0 END ELSE NULL END,
            bb_squeeze = CASE WHEN bb_width IS NOT NULL THEN CASE WHEN bb_width < 0.05 THEN 1 ELSE 0 END ELSE NULL END,

            -- Volume conditions
            high_volume = CASE
                WHEN volume_sma_20 IS NOT NULL AND volume_sma_20 > 0 THEN
                    CASE WHEN volume > volume_sma_20 * 1.5 THEN 1 ELSE 0 END
                ELSE NULL
            END,
            low_volume = CASE
                WHEN volume_sma_20 IS NOT NULL AND volume_sma_20 > 0 THEN
                    CASE WHEN volume < volume_sma_20 * 0.5 THEN 1 ELSE 0 END
                ELSE NULL
            END,

            -- Mark as computed
            derived_computed_at = NOW()

        FROM (
            SELECT time, exchange, symbol, timeframe
            FROM enhanced_candles
            WHERE {where_sql}
            ORDER BY time
            {limit_sql}
        ) AS batch
        WHERE ec.time = batch.time
          AND ec.exchange = batch.exchange
          AND ec.symbol = batch.symbol
          AND ec.timeframe = batch.timeframe
    """)

    result = await session.execute(update_sql)
    await session.commit()

    return result.rowcount


async def run_enrichment(
    symbols: list[str] | None = None,
    timeframes: list[str] | None = None,
    batch_size: int = BATCH_SIZE,
) -> dict[str, int]:
    """
    Run full enrichment for specified symbols/timeframes.

    Args:
        symbols: List of symbols to enrich (default: all)
        timeframes: List of timeframes to enrich (default: all)
        batch_size: Rows per batch

    Returns:
        Dict of symbol_timeframe -> rows updated
    """
    results = {}
    import time

    global_start = time.time()

    async with async_session_maker() as session:
        # Get distinct symbol/timeframe combinations if not specified
        if not symbols or not timeframes:
            query = text("""
                SELECT DISTINCT symbol, timeframe
                FROM enhanced_candles
                WHERE derived_computed_at IS NULL
                LIMIT 500
            """)
            result = await session.execute(query)
            pairs = result.fetchall()
        else:
            pairs = [(s, t) for s in symbols for t in timeframes]

        total_updated = 0
        total_pairs = len(pairs)
        print(f"[Enrichment] Found {total_pairs} symbol/timeframe pairs to process", flush=True)

        for idx, (symbol, timeframe) in enumerate(pairs):
            pair_start = time.time()
            print(f"[Enrichment] [{idx + 1}/{total_pairs}] Processing {symbol}/{timeframe}...", flush=True)

            updated = 0
            batch_num = 0
            while True:
                batch_num += 1
                batch_updated = await compute_derived_indicators_batch(
                    session,
                    symbol=symbol,
                    timeframe=timeframe,
                    limit=batch_size,
                )

                if batch_updated == 0:
                    break

                updated += batch_updated
                total_updated += batch_updated
                elapsed = time.time() - global_start
                rate = total_updated / elapsed if elapsed > 0 else 0
                print(
                    f"  [Batch {batch_num}] +{batch_updated:,} rows | {symbol}/{timeframe}: {updated:,} | Total: {total_updated:,} | Rate: {rate:,.0f}/sec",
                    flush=True,
                )

            pair_elapsed = time.time() - pair_start
            if updated > 0:
                results[f"{symbol}_{timeframe}"] = updated
                print(f"[Enrichment] ✓ {symbol}/{timeframe}: {updated:,} rows in {pair_elapsed:.1f}s", flush=True)

        total_elapsed = time.time() - global_start
        print(f"[Enrichment] COMPLETE: {total_updated:,} total rows enriched in {total_elapsed:.1f}s", flush=True)

    return results


async def get_enrichment_status() -> dict:
    """
    Get current enrichment status.

    Returns:
        Dict with counts of enriched vs unenriched candles
    """
    async with async_session_maker() as session:
        query = text("""
            SELECT
                COUNT(*) as total,
                COUNT(derived_computed_at) as enriched,
                COUNT(*) - COUNT(derived_computed_at) as pending
            FROM enhanced_candles
        """)
        result = await session.execute(query)
        row = result.fetchone()

        return {
            "total_candles": row[0],
            "enriched": row[1],
            "pending": row[2],
            "percent_complete": round(row[1] / row[0] * 100, 2) if row[0] > 0 else 0,
        }


async def add_derived_columns_if_missing():
    """
    Add the derived indicator columns to enhanced_candles if they don't exist.

    This is a one-time migration that adds the new columns.
    Safe to run multiple times (uses IF NOT EXISTS).
    """
    columns = [
        ("ma_cross_20_50", "INTEGER"),
        ("golden_cross", "INTEGER"),
        ("death_cross", "INTEGER"),
        ("macd_cross", "INTEGER"),
        ("price_vs_ema_9_pct", "DOUBLE PRECISION"),
        ("price_vs_ema_20_pct", "DOUBLE PRECISION"),
        ("price_vs_ema_21_pct", "DOUBLE PRECISION"),
        ("price_vs_sma_50_pct", "DOUBLE PRECISION"),
        ("price_vs_sma_200_pct", "DOUBLE PRECISION"),
        ("price_above_ema_9", "INTEGER"),
        ("price_above_ema_20", "INTEGER"),
        ("price_above_ema_21", "INTEGER"),
        ("price_above_sma_50", "INTEGER"),
        ("price_above_sma_200", "INTEGER"),
        ("rsi_oversold", "INTEGER"),
        ("rsi_overbought", "INTEGER"),
        ("rsi_neutral", "INTEGER"),
        ("stoch_oversold", "INTEGER"),
        ("stoch_overbought", "INTEGER"),
        ("strong_trend", "INTEGER"),
        ("weak_trend", "INTEGER"),
        ("volatility_regime", "VARCHAR(20)"),
        ("trend_regime", "VARCHAR(20)"),
        ("is_asian_session", "INTEGER"),
        ("is_london_session", "INTEGER"),
        ("is_us_session", "INTEGER"),
        ("is_us_market_hours", "INTEGER"),
        ("price_at_bb_upper", "INTEGER"),
        ("price_at_bb_lower", "INTEGER"),
        ("bb_squeeze", "INTEGER"),
        ("high_volume", "INTEGER"),
        ("low_volume", "INTEGER"),
        ("derived_computed_at", "TIMESTAMPTZ"),
    ]

    async with async_session_maker() as session:
        for col_name, col_type in columns:
            try:
                await session.execute(
                    text(f"""
                    ALTER TABLE enhanced_candles
                    ADD COLUMN IF NOT EXISTS {col_name} {col_type}
                """)
                )
            except Exception as e:
                logger.warning(f"Column {col_name} may already exist: {e}")

        await session.commit()
        logger.info(f"[Migration] Added {len(columns)} derived indicator columns")


# Convenience function for running from command line or startup
async def startup_enrichment(background: bool = True):
    """
    Run indicator enrichment on startup.

    Args:
        background: Run in background task (default: True)
    """

    async def _run():
        # First ensure columns exist
        await add_derived_columns_if_missing()

        # Check status
        status = await get_enrichment_status()
        logger.info(
            f"[Enrichment] Status: {status['enriched']:,}/{status['total_candles']:,} enriched ({status['percent_complete']}%)"
        )

        if status["pending"] > 0:
            logger.info(f"[Enrichment] Starting enrichment of {status['pending']:,} pending candles...")
            await run_enrichment()
        else:
            logger.info("[Enrichment] All candles already enriched!")

    if background:
        asyncio.create_task(_run())
    else:
        await _run()
