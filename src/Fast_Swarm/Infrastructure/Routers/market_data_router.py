from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import desc, select

from ...Database import get_session
from ..Models.market_data_models import ExchangeTick, OrderBookSnapshot
from ..Models.exchange_models import LiveTradeUnified
from ..Services.market_data_service import MarketDataService
from ..Services.bear_protection_service import get_bear_protection

router = APIRouter(prefix="/market_data", tags=["Market Data"])
market_service = MarketDataService()


@router.get("/candles", response_model=list[dict])
async def get_candles(
    symbol: str = Query(..., description="e.g. BTC, ETH, SOL"),
    timeframe: str = Query("1h", description="e.g. 1m, 5m, 15m, 1h, 1d"),
    limit: int = Query(100, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    """
    Get latest candles with pre-computed indicators for a symbol.

    Returns newest first. Includes 200+ technical indicators like RSI, MACD,
    Bollinger Bands, ATR, ADX, Stochastic, and more.
    """
    candles = await market_service.get_recent_candles(session, symbol, timeframe, limit)
    return [
        {
            "time": c.time.isoformat() if c.time else None,
            "symbol": c.symbol,
            "timeframe": c.timeframe,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
            "rsi_14": c.rsi_14,
            "macd_line": c.macd_line,
            "macd_signal": c.macd_signal,
            "bb_upper": c.bb_upper,
            "bb_lower": c.bb_lower,
            "atr_14": c.atr_14,
            "adx_14": c.adx_14,
            "stoch_k": c.stoch_k,
            "stoch_d": c.stoch_d,
            "fear_greed_value": c.fear_greed_value,
            "regime": c.regime,
        }
        for c in candles
    ]


@router.get("/range")
async def get_candle_range(
    symbol: str,
    timeframe: str,
    start: datetime = Query(..., description="ISO format start time"),
    end: datetime = Query(..., description="ISO format end time"),
    session: AsyncSession = Depends(get_session),
):
    """Get candles within a specific time range."""
    candles = await market_service.get_candle_range(session, symbol, timeframe, start, end)
    return [
        {
            "time": c.time.isoformat() if c.time else None,
            "symbol": c.symbol,
            "timeframe": c.timeframe,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
            "rsi_14": c.rsi_14,
            "macd_line": c.macd_line,
            "atr_14": c.atr_14,
            "regime": c.regime,
        }
        for c in candles
    ]


@router.get("/price/{symbol}")
async def get_latest_price(symbol: str, session: AsyncSession = Depends(get_session)):
    """Get the latest close price for a symbol."""
    price = await market_service.get_latest_price(session, symbol)
    return {"symbol": symbol, "price": price}


@router.get("/symbols")
async def get_available_symbols(session: AsyncSession = Depends(get_session)):
    """Get list of all available symbols in the database."""
    symbols = await market_service.get_available_symbols(session)
    return {"symbols": symbols, "count": len(symbols)}


@router.get("/timeframes/{symbol}")
async def get_available_timeframes(symbol: str, session: AsyncSession = Depends(get_session)):
    """Get available timeframes for a specific symbol."""
    timeframes = await market_service.get_available_timeframes(session, symbol)
    return {"symbol": symbol, "timeframes": timeframes}


@router.get("/ticks")
async def get_ticks(
    symbol: str = Query(..., description="Symbol (e.g., BTC, ETH)"),
    limit: int = Query(100, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    """Get raw tick data (12.5M+ rows)."""
    stmt = select(ExchangeTick).where(ExchangeTick.symbol == symbol).order_by(desc(ExchangeTick.time)).limit(limit)
    result = await session.exec(stmt)
    return [
        {
            "time": t.time.isoformat(),
            "exchange": t.exchange,
            "symbol": t.symbol,
            "price": t.price,
            "size": t.size,
            "side": t.side,
        }
        for t in result.all()
    ]


@router.get("/orderbook")
async def get_orderbook_snapshots(
    symbol: str | None = Query(None, description="Filter by symbol"),
    limit: int = Query(100, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    """Get order book snapshots (781K+ rows)."""
    stmt = select(OrderBookSnapshot).order_by(desc(OrderBookSnapshot.timestamp))
    if symbol:
        stmt = stmt.where(OrderBookSnapshot.symbol == symbol)
    stmt = stmt.limit(limit)
    result = await session.exec(stmt)
    return [
        {
            "timestamp": s.timestamp,
            "exchange": s.exchange,
            "symbol": s.symbol,
            "mid_price": s.mid_price,
            "spread_bps": s.spread_bps,
            "imbalance": s.imbalance,
            "bid_vol_10": s.bid_vol_10,
            "ask_vol_10": s.ask_vol_10,
        }
        for s in result.all()
    ]


@router.get("/regime")
async def get_regime(
    total_capital: float = Query(100000.0, description="Total portfolio capital for utilization calc"),
    session: AsyncSession = Depends(get_session),
):
    """
    Get Bear Protection regime status with per-asset + portfolio-weighted view.

    Returns:
    - portfolio: Weighted regime across all assets (50% by position, 50% by market cap)
    - by_asset: Per-asset regime states with triggers
    - utilization: Progress bar data for invested vs limit
    - config: Current thresholds and hysteresis settings

    The portfolio weighted_regime_score (-1 to 1) controls max portfolio position:
    - Score <= -0.33: DEFENSIVE (0% max)
    - Score -0.33 to 0.33: NEUTRAL (65% max)
    - Score >= 0.33: AGGRESSIVE (90% max)
    """
    bp = get_bear_protection()

    # Query per-symbol positions from open trades
    stmt = (
        select(
            LiveTradeUnified.symbol,
            func.coalesce(func.sum(LiveTradeUnified.size_usd), 0).label("position_usd")
        )
        .where(LiveTradeUnified.status == "open")
        .group_by(LiveTradeUnified.symbol)
    )
    result = await session.execute(stmt)
    positions = {row.symbol: float(row.position_usd) for row in result.all()}

    # Market caps - placeholder values (would come from external API in production)
    # Using relative weights: BTC=1T, ETH=400B, SOL=100B, others=10B
    MARKET_CAP_ESTIMATES = {
        "BTC": 1_000_000_000_000,
        "BTC-USDT": 1_000_000_000_000,
        "ETH": 400_000_000_000,
        "ETH-USDT": 400_000_000_000,
        "SOL": 100_000_000_000,
        "SOL-USDT": 100_000_000_000,
    }
    DEFAULT_MARKET_CAP = 10_000_000_000
    all_symbols = set(positions.keys()) | set(bp.get_all_asset_regimes().keys())
    market_caps = {s: MARKET_CAP_ESTIMATES.get(s, DEFAULT_MARKET_CAP) for s in all_symbols}

    # Calculate portfolio-weighted regime
    portfolio = bp.calculate_portfolio_regime(positions, market_caps)

    # Get total invested for utilization calc
    total_invested = sum(positions.values())
    limit_pct = portfolio["max_position_pct"]
    PERCENTAGE_MULTIPLIER = 100
    invested_pct = round((total_invested / total_capital) * PERCENTAGE_MULTIPLIER, 1) if total_capital > 0 else 0
    headroom_pct = max(0, limit_pct - invested_pct)
    over_limit = invested_pct > limit_pct

    # Get all per-asset regime states
    asset_regimes = bp.get_all_asset_regimes()
    by_asset = {}
    for symbol, state in asset_regimes.items():
        by_asset[symbol] = {
            "regime": state.regime.value,
            "trigger": state.trigger,
            "since": state.since.isoformat() if state.since else None,
            "consecutive_safe_candles": state.consecutive_safe_candles,
            "consecutive_bullish_candles": state.consecutive_bullish_candles,
            "position_usd": positions.get(symbol, 0),
        }

    return {
        # Portfolio-weighted regime (controls max portfolio position)
        "portfolio": {
            "weighted_regime_score": portfolio["weighted_regime_score"],
            "effective_regime": portfolio["effective_regime"],
            "max_position_pct": portfolio["max_position_pct"],
        },
        # Per-asset regimes
        "by_asset": by_asset,
        # Progress bar data
        "utilization": {
            "invested_pct": invested_pct,
            "invested_usd": round(total_invested, 2),
            "limit_pct": limit_pct,
            "limit_usd": round(total_capital * limit_pct / PERCENTAGE_MULTIPLIER, 2),
            "headroom_pct": headroom_pct,
            "over_limit": over_limit,
            "total_capital": total_capital,
        },
        # Configuration
        "config": {
            "limits": {
                "DEFENSIVE": f"{int(bp.config.defensive_max * PERCENTAGE_MULTIPLIER)}%",
                "NEUTRAL": f"{int(bp.config.neutral_max * PERCENTAGE_MULTIPLIER)}%",
                "AGGRESSIVE": f"{int(bp.config.aggressive_max * PERCENTAGE_MULTIPLIER)}%",
            },
            "thresholds": {
                "exit_acc": bp.config.exit_acc_threshold,
                "exit_adx_jerk": bp.config.exit_adx_jerk_threshold,
                "entry_vel": bp.config.entry_vel_threshold,
                "entry_acc": bp.config.entry_acc_threshold,
            },
            "hysteresis": {
                "exit_defensive_acc_buffer": bp.config.exit_defensive_acc_buffer,
                "exit_defensive_jerk_buffer": bp.config.exit_defensive_jerk_buffer,
                "defensive_min_hold_hours": bp.config.defensive_min_hold_hours,
                "exit_defensive_confirm_candles": bp.config.exit_defensive_confirm_candles,
                "enter_aggressive_confirm_candles": bp.config.enter_aggressive_confirm_candles,
            },
            "tf_confirm": {
                "defensive": bp.config.defensive_tf_confirm,
                "aggressive": bp.config.aggressive_tf_confirm,
            },
        },
    }
