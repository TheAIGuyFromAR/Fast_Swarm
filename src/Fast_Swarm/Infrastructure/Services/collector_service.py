import asyncio
import logging
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ..Models.exchange_models import Trade
from ..Models.market_data_models import Candle, ExchangeTick, OrderBookSnapshot
from .market_data_service import MarketDataService

# Import normalized data structures from WebSocket layer
try:
    from Fast_Swarm.exchanges.base_ws import KlineData, NormalizedOrderBook, NormalizedTrade
except ImportError:
    # Fallback for when imports fail (testing, etc.)
    NormalizedTrade = Any
    NormalizedOrderBook = Any
    KlineData = Any

logger = logging.getLogger(__name__)


class DataCollectorService:
    """
    Data Collector Service.
    Aggregates live streams into OHLCV candles across multiple timeframes.
    Handles startup backfilling and database batching.
    """

    TIMEFRAMES = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
    MAX_QUEUE_SIZE = 10000  # Backpressure: stop accepting if queue exceeds this
    RESUME_THRESHOLD = 5000  # Resume collection when queue drains to this level

    # Keep 1500 1m candles per symbol (~25 hours). All higher timeframes
    # are rolled up on-demand from these. With 128GB RAM this is trivial.
    BUFFER_SIZE_1M = 1500

    # How many 1m candles make each higher timeframe
    TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}

    def __init__(self, session_factory):
        self.session_factory = session_factory
        self.market_service = MarketDataService()
        self._pending_candles: dict[str, Candle] = {}  # "(exchange, symbol, tf)" -> Candle
        self._write_queue_candles: list[Candle] = []
        self._write_queue_trades: list[Trade] = []
        self._write_queue_ticks: list[ExchangeTick] = []
        self._write_queue_orderbooks: list[OrderBookSnapshot] = []
        self._batch_size = 50
        self._tick_batch_size = 100  # Higher batch for high-frequency tick data
        self._collection_paused = False  # Backpressure flag

        # Track current minute candles being built from ticks
        # Key: "exchange:symbol" -> {"open": float, ...}
        self._minute_candles: dict[str, dict] = {}

        # In-memory candle buffers per symbol per timeframe
        # 1m is source of truth (1500 candles = 25 hours)
        # Higher TFs are rolled up from 1m and cached (250 each for indicators)
        # Key: "exchange:symbol" -> {"1m": deque, "5m": deque, "15m": deque, ...}
        self._candle_buffers: dict[str, dict[str, deque]] = {}

        # Callbacks fired when a candle closes on any timeframe
        # Signature: callback(exchange, symbol, timeframe, candle_dict, history_list)
        self._candle_close_callbacks: list[Callable] = []

    @property
    def _total_queue_size(self) -> int:
        """Total items across all write queues."""
        return (
            len(self._write_queue_candles)
            + len(self._write_queue_trades)
            + len(self._write_queue_ticks)
            + len(self._write_queue_orderbooks)
        )

    def _check_backpressure(self) -> bool:
        """Check if queue is too full, apply backpressure if needed. Returns True if paused."""
        if self._total_queue_size >= self.MAX_QUEUE_SIZE:
            if not self._collection_paused:
                self._collection_paused = True
                logger.warning(
                    f"Queue full ({self._total_queue_size}/{self.MAX_QUEUE_SIZE}), "
                    "pausing collection until DB recovers"
                )
            return True
        return False

    def _check_resume(self):
        """Resume collection if queue has drained enough."""
        if self._collection_paused and self._total_queue_size < self.RESUME_THRESHOLD:
            self._collection_paused = False
            logger.info(
                f"Queue drained ({self._total_queue_size}/{self.RESUME_THRESHOLD}), "
                "resuming collection"
            )

    def on_candle_close(self, callback: Callable):
        """
        Register a callback for candle close events.

        Callback signature:
            callback(exchange: str, symbol: str, timeframe: str,
                     candle: dict, history: list[dict])

        The history is a list of the last N candle dicts for that symbol/timeframe,
        ordered chronologically (oldest first). Use it to compute indicators.
        """
        self._candle_close_callbacks.append(callback)

    def remove_candle_close_callback(self, callback: Callable):
        """Remove a candle close callback."""
        if callback in self._candle_close_callbacks:
            self._candle_close_callbacks.remove(callback)

    def get_candle_history(self, symbol: str, timeframe: str = "1m", exchange: str | None = None) -> list[dict]:
        """
        Get the in-memory candle history for a symbol/timeframe.

        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            timeframe: Candle timeframe (default "1m")
            exchange: Exchange name (if None, searches all exchanges)

        Returns:
            List of candle dicts ordered chronologically (oldest first)
        """
        if exchange:
            key = f"{exchange}:{symbol}"
            buffers = self._candle_buffers.get(key, {})
            buf = buffers.get(timeframe)
            return list(buf) if buf else []

        # Search all exchanges for this symbol
        for buf_key, buffers in self._candle_buffers.items():
            if buf_key.endswith(f":{symbol}"):
                buf = buffers.get(timeframe)
                if buf:
                    return list(buf)
        return []

    def _get_or_create_buffer(self, key: str) -> dict[str, deque]:
        """Get or create the buffer dict for a symbol key."""
        if key not in self._candle_buffers:
            self._candle_buffers[key] = {
                "1m": deque(maxlen=self.BUFFER_SIZE_1M),
                "5m": deque(maxlen=250),
                "15m": deque(maxlen=250),
                "1h": deque(maxlen=250),
                "4h": deque(maxlen=250),
                "1d": deque(maxlen=250),
            }
        return self._candle_buffers[key]

    def _fire_candle_close(self, exchange: str, symbol: str, timeframe: str, candle: dict, history: deque):
        """Fire all candle close callbacks."""
        if not self._candle_close_callbacks:
            return
        history_list = list(history)
        for cb in self._candle_close_callbacks:
            try:
                cb(exchange, symbol, timeframe, candle, history_list)
            except Exception as e:
                logger.error(f"Candle close callback error: {e}")

    def _rollup_higher_timeframes(self, key: str, exchange: str, symbol: str, minute_ts: int):
        """
        Roll up 1m candles into higher timeframes from the in-memory buffer.

        When a 1m candle closes, check if any higher timeframe boundary has been crossed.
        If so, aggregate the appropriate 1m candles into the higher timeframe candle.
        """
        buffers = self._candle_buffers.get(key)
        if not buffers:
            return

        buf_1m = buffers["1m"]
        if not buf_1m:
            return

        for tf, tf_seconds in self.TIMEFRAMES.items():
            if tf == "1m":
                continue

            # Check if this minute timestamp is on a timeframe boundary
            # e.g., for 5m: minute_ts 300, 600, 900... (every 5 minutes)
            # The candle that just closed has timestamp = minute_ts
            # A 5m boundary means (minute_ts + 60) % 300 == 0
            # (the NEXT minute starts a new 5m period)
            next_minute = minute_ts + 60
            if next_minute % tf_seconds != 0:
                continue

            # We're at a timeframe boundary - roll up from 1m buffer
            n_minutes = tf_seconds // 60  # How many 1m candles in this timeframe
            if len(buf_1m) < n_minutes:
                continue  # Not enough data yet

            # Take the last N 1m candles for this period
            recent = list(buf_1m)[-n_minutes:]

            rolled = {
                "time": recent[0]["time"],  # Open time of first candle
                "open": recent[0]["open"],
                "high": max(c["high"] for c in recent),
                "low": min(c["low"] for c in recent),
                "close": recent[-1]["close"],
                "volume": sum(c["volume"] for c in recent),
            }

            # Append to the timeframe's buffer
            buffers[tf].append(rolled)

            # Fire callbacks for this timeframe too
            self._fire_candle_close(exchange, symbol, tf, rolled, buffers[tf])

            logger.debug(
                f"Rolled up {tf} candle: {symbol} "
                f"O={rolled['open']:.2f} C={rolled['close']:.2f} "
                f"({n_minutes} 1m candles)"
            )

    @staticmethod
    def _normalize_symbol_for_db(symbol: str) -> str:
        """
        Strip quote currency suffixes to get the base symbol as stored in the DB.

        Exchange formats: "BTCUSDT", "BTC-USD", "BTC-USDT", "BTCUSD", "BTC-PERP"
        DB format: "BTC"
        """
        # Remove separators first
        s = symbol.replace("-", "").replace("_", "")
        # Strip known quote suffixes (longest first to avoid partial matches)
        for suffix in ("USDT", "PERP", "USD"):
            if s.endswith(suffix) and len(s) > len(suffix):
                s = s[: -len(suffix)]
                break
        return s

    async def prefill_buffers_from_db(self, symbols: dict[str, list[str]]):
        """
        Pre-fill the 1m candle buffers from enhanced_candles table on startup.

        This ensures paper trading can evaluate immediately instead of waiting
        250+ minutes for the buffer to fill from live ticks.

        Args:
            symbols: {"binance": ["BTCUSDT", ...], "coinbase": ["BTC-USD", ...]}
        """
        from sqlalchemy import text

        async with self.session_factory() as session:
            for exchange, symbol_list in symbols.items():
                for symbol in symbol_list:
                    # DB stores base symbols ("BTC") not exchange format ("BTCUSDT")
                    db_symbol = self._normalize_symbol_for_db(symbol)
                    try:
                        result = await session.execute(
                            text("""
                                SELECT time, open, high, low, close, volume
                                FROM enhanced_candles
                                WHERE symbol = :symbol AND timeframe = '1m'
                                ORDER BY time DESC
                                LIMIT :limit
                            """),
                            {"symbol": db_symbol, "limit": self.BUFFER_SIZE_1M},
                        )
                        rows = result.fetchall()

                        if not rows:
                            logger.warning(
                                f"[Buffer] No 1m candles found for DB symbol '{db_symbol}' "
                                f"(from {exchange}:{symbol})"
                            )
                            continue

                        # Reverse to chronological order (oldest first)
                        # Key uses the EXCHANGE format (e.g. "binance:BTCUSDT") to match
                        # what live ticks will use as their buffer key
                        key = f"{exchange}:{symbol}"
                        buffers = self._get_or_create_buffer(key)
                        for row in reversed(rows):
                            ts = row[0]
                            # Convert datetime to unix timestamp if needed
                            if hasattr(ts, "timestamp"):
                                ts = int(ts.timestamp())
                            buffers["1m"].append({
                                "time": ts,
                                "open": float(row[1]) if row[1] else 0,
                                "high": float(row[2]) if row[2] else 0,
                                "low": float(row[3]) if row[3] else 0,
                                "close": float(row[4]) if row[4] else 0,
                                "volume": float(row[5]) if row[5] else 0,
                            })

                        logger.info(
                            f"[Buffer] Pre-filled {len(buffers['1m'])} 1m candles "
                            f"for {key} (queried DB as '{db_symbol}')"
                        )
                    except Exception as e:
                        logger.warning(f"[Buffer] Failed to pre-fill {exchange}:{symbol}: {e}")

    def _validate_candle(self, candle: Candle) -> tuple[bool, str]:
        """
        Validate OHLC relationships to catch data corruption.
        Returns (is_valid, reason) tuple.
        """
        o, h, l, c = candle.open, candle.high, candle.low, candle.close

        if h < l:
            return False, f"high ({h}) < low ({l})"
        if h < o or h < c:
            return False, f"high ({h}) < open ({o}) or close ({c})"
        if l > o or l > c:
            return False, f"low ({l}) > open ({o}) or close ({c})"
        if c is None or c <= 0:
            return False, f"close <= 0 ({c})"
        if candle.volume is not None and candle.volume < 0:
            return False, f"negative volume ({candle.volume})"

        return True, "ok"

    async def verify_and_backfill(self, symbols: dict[str, list[str]]):
        """
        Check for gaps in historical data and run backfillers.
        """
        logger.info("Initializing Data Health Check...")
        for exchange, asset_list in symbols.items():
            for asset in asset_list:
                await self._check_asset_gaps(exchange, asset)
        logger.info("Data Health Check Complete.")

    async def _check_asset_gaps(self, exchange: str, asset: str):
        """Check for gaps in the last 24h for a specific asset."""
        # Simple implementation: check if we have any data in the last 1h
        now = int(datetime.utcnow().timestamp())
        async with self.session_factory() as session:
            latest = await self.market_service.get_recent_candles(session, asset, "1m", limit=1)
            if not latest or latest[0].timestamp < now - 3600:
                logger.warning(f"Gap detected for {exchange}:{asset}. Triggering backfill...")
                await self._trigger_backfill(exchange, asset, "1m")

    async def _trigger_backfill(self, exchange: str, asset: str, timeframe: str):
        """Simulate/Trigger external backfill script."""
        # In a real integrated system, this would call a method on backfiller_service
        logger.info(f"Backfilling {asset} on {exchange} for {timeframe}...")

    def handle_live_trade(self, trade_data: "NormalizedTrade"):
        """
        Process a live trade from StreamManager.

        Does two things:
        1. Queues the raw tick for batch write to exchange_ticks table
        2. Updates/creates the current 1-minute candle from ticks

        Args:
            trade_data: NormalizedTrade from WebSocket layer
        """
        # 1. Queue raw tick for batch write
        tick = ExchangeTick(
            exchange=trade_data.exchange,
            symbol=trade_data.symbol,
            trade_id=trade_data.trade_id,
            time=datetime.fromtimestamp(trade_data.timestamp / 1000, tz=UTC),
            price=trade_data.price,
            size=trade_data.size,
            side=trade_data.side,
        )
        self._write_queue_ticks.append(tick)

        # Check if we need to flush tick batch
        if len(self._write_queue_ticks) >= self._tick_batch_size:
            asyncio.create_task(self._flush_tick_batch())

        # 2. Build 1-minute candle from ticks
        key = f"{trade_data.exchange}:{trade_data.symbol}"
        trade_minute = (trade_data.timestamp // 60000) * 60  # Floor to minute (seconds)

        if key not in self._minute_candles:
            # Start new candle
            self._minute_candles[key] = {
                "exchange": trade_data.exchange,
                "symbol": trade_data.symbol,
                "open": trade_data.price,
                "high": trade_data.price,
                "low": trade_data.price,
                "close": trade_data.price,
                "volume": trade_data.size,
                "minute_ts": trade_minute,
                "trade_count": 1,
                "buy_volume": trade_data.size if trade_data.side == "buy" else 0,
                "sell_volume": trade_data.size if trade_data.side == "sell" else 0,
            }
        else:
            candle = self._minute_candles[key]

            # Check if we've moved to a new minute
            if trade_minute > candle["minute_ts"]:
                # Close the old candle and queue for write
                self._finalize_minute_candle(key, candle)

                # Start new candle
                self._minute_candles[key] = {
                    "exchange": trade_data.exchange,
                    "symbol": trade_data.symbol,
                    "open": trade_data.price,
                    "high": trade_data.price,
                    "low": trade_data.price,
                    "close": trade_data.price,
                    "volume": trade_data.size,
                    "minute_ts": trade_minute,
                    "trade_count": 1,
                    "buy_volume": trade_data.size if trade_data.side == "buy" else 0,
                    "sell_volume": trade_data.size if trade_data.side == "sell" else 0,
                }
            else:
                # Update current candle
                candle["high"] = max(candle["high"], trade_data.price)
                candle["low"] = min(candle["low"], trade_data.price)
                candle["close"] = trade_data.price
                candle["volume"] += trade_data.size
                candle["trade_count"] += 1
                if trade_data.side == "buy":
                    candle["buy_volume"] += trade_data.size
                else:
                    candle["sell_volume"] += trade_data.size

    def _finalize_minute_candle(self, key: str, candle: dict):
        """Convert accumulated tick data into a Candle, buffer it, and fire callbacks."""
        finished_candle = Candle(
            exchange=candle["exchange"],
            asset=candle["symbol"],
            timeframe="1m",
            timestamp=candle["minute_ts"],
            open=candle["open"],
            high=candle["high"],
            low=candle["low"],
            close=candle["close"],
            volume=candle["volume"],
            is_closed=True,
        )

        # Validate OHLC relationships before queuing
        is_valid, reason = self._validate_candle(finished_candle)
        if not is_valid:
            logger.warning(
                f"Rejecting invalid candle {candle['symbol']} @ {candle['minute_ts']}: {reason}"
            )
            return  # Don't queue invalid candles

        logger.debug(
            f"[Candle] Finalized 1m: {candle['symbol']} "
            f"C={candle['close']:.2f} callbacks={len(self._candle_close_callbacks)}"
        )

        # === ALWAYS buffer the 1m candle + fire callbacks (in-memory, zero cost) ===
        candle_dict = {
            "time": candle["minute_ts"],
            "open": candle["open"],
            "high": candle["high"],
            "low": candle["low"],
            "close": candle["close"],
            "volume": candle["volume"],
        }
        buffers = self._get_or_create_buffer(key)
        buffers["1m"].append(candle_dict)

        # Fire 1m candle close callbacks
        self._fire_candle_close(
            candle["exchange"], candle["symbol"], "1m", candle_dict, buffers["1m"]
        )

        # Roll up to higher timeframes if on a boundary
        self._rollup_higher_timeframes(
            key, candle["exchange"], candle["symbol"], candle["minute_ts"]
        )

        logger.debug(
            f"Finalized 1m candle: {candle['symbol']} "
            f"O={candle['open']:.2f} H={candle['high']:.2f} "
            f"L={candle['low']:.2f} C={candle['close']:.2f} V={candle['volume']:.4f} "
            f"(buffer: {len(buffers['1m'])})"
        )

        # Backpressure: only skip DB persistence, never skip in-memory ops
        if self._check_backpressure():
            return

        self._write_queue_candles.append(finished_candle)

    async def _flush_tick_batch(self):
        """Flush queued ticks to database using ON CONFLICT DO NOTHING for idempotency."""
        if not self._write_queue_ticks:
            return

        ticks_to_write = self._write_queue_ticks[:]
        self._write_queue_ticks = []  # Clear immediately to prevent re-queuing duplicates

        try:
            async with self.session_factory() as session:
                from sqlalchemy.dialects.postgresql import insert

                # Convert ticks to dicts for bulk insert
                tick_dicts = [
                    {
                        "exchange": tick.exchange,
                        "symbol": tick.symbol,
                        "trade_id": tick.trade_id,
                        "time": tick.time,
                        "price": tick.price,
                        "size": tick.size,
                        "side": tick.side,
                    }
                    for tick in ticks_to_write
                ]

                if tick_dicts:
                    # Use PostgreSQL INSERT ... ON CONFLICT DO NOTHING
                    # This silently skips duplicates instead of failing the entire batch
                    stmt = insert(ExchangeTick).values(tick_dicts)
                    stmt = stmt.on_conflict_do_nothing(
                        index_elements=["exchange", "symbol", "trade_id"]
                    )
                    await session.execute(stmt)
                    await session.commit()

                logger.debug(f"Flushed {len(ticks_to_write)} ticks to exchange_ticks (duplicates skipped)")
        except Exception as e:
            logger.error(f"Failed to flush ticks: {e}")
            # DON'T re-queue - this prevents infinite loops on persistent errors
            # Lost ticks are acceptable; infinite error loops are not

    def handle_live_kline(self, kline_data: "KlineData"):
        """
        Process a live kline from StreamManager.

        Handles kline data directly from exchange websocket (more efficient than
        building from ticks when exchange provides kline streams).

        Args:
            kline_data: KlineData from WebSocket layer
        """
        key = f"{kline_data.exchange}:{kline_data.symbol}:{kline_data.timeframe}"

        # Create or update pending candle
        candle = Candle(
            exchange=kline_data.exchange,
            asset=kline_data.symbol,
            timeframe=kline_data.timeframe,
            timestamp=kline_data.timestamp,
            open=kline_data.open,
            high=kline_data.high,
            low=kline_data.low,
            close=kline_data.close,
            volume=kline_data.volume,
            quote_volume=kline_data.quote_volume,
            is_closed=kline_data.is_closed,
        )

        if kline_data.is_closed:
            # Validate OHLC relationships before queuing
            is_valid, reason = self._validate_candle(candle)
            if not is_valid:
                logger.warning(
                    f"Rejecting invalid kline {kline_data.symbol} @ {kline_data.timestamp}: {reason}"
                )
                # Remove from pending if exists
                if key in self._pending_candles:
                    del self._pending_candles[key]
                return  # Don't queue invalid candles

            # Backpressure: don't accept if queue is full
            if self._check_backpressure():
                if key in self._pending_candles:
                    del self._pending_candles[key]
                return

            # Candle is complete - queue for write
            self._write_queue_candles.append(candle)

            # Remove from pending if exists
            if key in self._pending_candles:
                del self._pending_candles[key]

            # Buffer and roll up for 1m candles
            if kline_data.timeframe == "1m":
                kline_key = f"{kline_data.exchange}:{kline_data.symbol}"
                kline_dict = {
                    "time": kline_data.timestamp,
                    "open": kline_data.open,
                    "high": kline_data.high,
                    "low": kline_data.low,
                    "close": kline_data.close,
                    "volume": kline_data.volume,
                }
                kline_buffers = self._get_or_create_buffer(kline_key)
                kline_buffers["1m"].append(kline_dict)
                self._fire_candle_close(
                    kline_data.exchange, kline_data.symbol, "1m", kline_dict, kline_buffers["1m"]
                )
                self._rollup_higher_timeframes(
                    kline_key, kline_data.exchange, kline_data.symbol, kline_data.timestamp
                )

            # Check if we need to flush
            if len(self._write_queue_candles) >= self._batch_size:
                asyncio.create_task(self._flush_batches())

            logger.debug(
                f"Closed kline: {kline_data.symbol} {kline_data.timeframe} "
                f"O={kline_data.open:.2f} H={kline_data.high:.2f} "
                f"L={kline_data.low:.2f} C={kline_data.close:.2f}"
            )
        else:
            # Candle still forming - update pending
            self._pending_candles[key] = candle

    def handle_order_book(self, order_book_data: "NormalizedOrderBook"):
        """
        Process a live order book snapshot from StreamManager.

        Stores L2 order book snapshots with computed metrics (imbalance, spread).

        Args:
            order_book_data: NormalizedOrderBook from WebSocket layer
        """
        # Calculate top 10 level volumes
        bid_vol_10 = sum(size for _, size in order_book_data.bids[:10])
        ask_vol_10 = sum(size for _, size in order_book_data.asks[:10])

        snapshot = OrderBookSnapshot(
            exchange=order_book_data.exchange,
            symbol=order_book_data.symbol,
            timestamp=order_book_data.timestamp,
            bid_vol_10=bid_vol_10,
            ask_vol_10=ask_vol_10,
            imbalance=order_book_data.imbalance,
            spread_bps=order_book_data.spread_bps,
            mid_price=order_book_data.mid_price,
            created_at=datetime.now(UTC),
        )

        self._write_queue_orderbooks.append(snapshot)

        # Flush if batch full
        if len(self._write_queue_orderbooks) >= self._batch_size:
            asyncio.create_task(self._flush_orderbook_batch())

    async def _flush_orderbook_batch(self):
        """Flush queued order book snapshots to database."""
        if not self._write_queue_orderbooks:
            return

        snapshots_to_write = self._write_queue_orderbooks[:]
        self._write_queue_orderbooks = []

        try:
            async with self.session_factory() as session:
                for snapshot in snapshots_to_write:
                    session.add(snapshot)
                await session.commit()
                logger.debug(f"Flushed {len(snapshots_to_write)} order book snapshots")
        except Exception as e:
            logger.error(f"Failed to flush order book snapshots: {e}")
            # Re-queue failed snapshots
            self._write_queue_orderbooks = snapshots_to_write + self._write_queue_orderbooks

    async def _aggregate_to_higher_timeframes(self, candle_1m: Candle):
        """
        Aggregate a closed 1m candle into higher timeframes (5m, 15m, 1h, 4h, 1d).

        Uses the TIMEFRAMES dict to determine aggregation boundaries.
        """
        for tf, seconds in self.TIMEFRAMES.items():
            if tf == "1m":
                continue  # Skip 1m - that's what we're aggregating from

            # Calculate the timeframe bucket this 1m candle belongs to
            tf_bucket = (candle_1m.timestamp // seconds) * seconds
            key = f"{candle_1m.exchange}:{candle_1m.asset}:{tf}"

            if key not in self._pending_candles:
                # Start new higher timeframe candle
                self._pending_candles[key] = Candle(
                    exchange=candle_1m.exchange,
                    asset=candle_1m.asset,
                    timeframe=tf,
                    timestamp=tf_bucket,
                    open=candle_1m.open,
                    high=candle_1m.high,
                    low=candle_1m.low,
                    close=candle_1m.close,
                    volume=candle_1m.volume or 0,
                    is_closed=False,
                )
            else:
                pending = self._pending_candles[key]

                # Check if this 1m candle belongs to a new bucket
                if tf_bucket > pending.timestamp:
                    # Close the old candle
                    pending.is_closed = True
                    is_valid, reason = self._validate_candle(pending)
                    if not is_valid:
                        logger.warning(
                            f"Rejecting invalid rollup candle {pending.asset} {tf} @ {pending.timestamp}: {reason}"
                        )
                    else:
                        self._write_queue_candles.append(pending)

                    # Start new candle
                    self._pending_candles[key] = Candle(
                        exchange=candle_1m.exchange,
                        asset=candle_1m.asset,
                        timeframe=tf,
                        timestamp=tf_bucket,
                        open=candle_1m.open,
                        high=candle_1m.high,
                        low=candle_1m.low,
                        close=candle_1m.close,
                        volume=candle_1m.volume or 0,
                        is_closed=False,
                    )
                else:
                    # Update existing candle
                    pending.high = max(pending.high, candle_1m.high)
                    pending.low = min(pending.low, candle_1m.low)
                    pending.close = candle_1m.close
                    pending.volume = (pending.volume or 0) + (candle_1m.volume or 0)

    async def _flush_batches(self):
        """Periodically flush all write queues to database with idempotent tick inserts."""
        has_data = (
            self._write_queue_candles
            or self._write_queue_trades
            or self._write_queue_ticks
            or self._write_queue_orderbooks
        )
        if not has_data:
            return

        # Take snapshots and clear queues immediately to prevent re-queue loops
        candles = self._write_queue_candles[:]
        trades = self._write_queue_trades[:]
        ticks = self._write_queue_ticks[:]
        orderbooks = self._write_queue_orderbooks[:]

        self._write_queue_candles = []
        self._write_queue_trades = []
        self._write_queue_ticks = []
        self._write_queue_orderbooks = []

        try:
            async with self.session_factory() as session:
                from sqlalchemy.dialects.postgresql import insert

                # Candles, trades, orderbooks use regular ORM add
                for c in candles:
                    session.add(c)
                for t in trades:
                    session.add(t)
                for ob in orderbooks:
                    session.add(ob)

                # Ticks use ON CONFLICT DO NOTHING to handle duplicates gracefully
                if ticks:
                    tick_dicts = [
                        {
                            "exchange": tick.exchange,
                            "symbol": tick.symbol,
                            "trade_id": tick.trade_id,
                            "time": tick.time,
                            "price": tick.price,
                            "size": tick.size,
                            "side": tick.side,
                        }
                        for tick in ticks
                    ]
                    stmt = insert(ExchangeTick).values(tick_dicts)
                    stmt = stmt.on_conflict_do_nothing(
                        index_elements=["exchange", "symbol", "trade_id"]
                    )
                    await session.execute(stmt)

                await session.commit()
                logger.debug(
                    f"Flushed batches: {len(candles)} candles, "
                    f"{len(trades)} trades, {len(ticks)} ticks, "
                    f"{len(orderbooks)} orderbooks"
                )
                # Check if we can resume collection after successful flush
                self._check_resume()
        except Exception as e:
            logger.error(f"Failed to flush batches: {e}")
            # DON'T re-queue - this prevents infinite loops on persistent errors
            # Data loss is acceptable; infinite error loops crashing the system are not

    async def flush_all(self):
        """Force flush all pending data (call on shutdown)."""
        # Finalize any in-progress minute candles
        for key, candle_data in list(self._minute_candles.items()):
            self._finalize_minute_candle(key, candle_data)
        self._minute_candles.clear()

        # Close any pending higher-timeframe candles
        for key, candle in list(self._pending_candles.items()):
            candle.is_closed = True
            is_valid, reason = self._validate_candle(candle)
            if not is_valid:
                logger.warning(f"Rejecting invalid pending candle {key}: {reason}")
                continue
            self._write_queue_candles.append(candle)
        self._pending_candles.clear()

        # Flush everything
        await self._flush_batches()
        logger.info("Flushed all pending collector data")
