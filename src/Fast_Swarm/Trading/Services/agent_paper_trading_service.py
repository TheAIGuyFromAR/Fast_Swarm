"""
Agent Paper Trading Service - Direct agent -> paper trading bridge for MVP.

This service bypasses the coach/trio system and allows a single agent
to paper trade directly against live market data.

Flow:
1. Agent evaluates market conditions using its patterns
2. Agent generates a signal (buy/sell/hold)
3. Service executes paper trade at current market price
4. Trade is recorded to LiveTradeUnified table

This is the MVP path: Pattern -> Agent -> Paper Trade -> (later) Live Trade
The full path (Coach -> Trio -> Vote) is added post-MVP.
"""

import asyncio
import logging
import types
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ...Agents.Models.agent_models import Agent
from ...Infrastructure.Models.exchange_models import LiveTradeUnified
from ...Patterns.Models.pattern_models import Pattern
from Fast_Swarm.Trading.Services.decision_feed_service import get_decision_feed_service, DecisionEvent

logger = logging.getLogger(__name__)


class AgentPaperTradingService:
    """
    Direct agent -> paper trading bridge.

    For MVP: One agent trades directly without coach/trio overhead.

    Fill Simulation:
        Uses forward-looking limit order simulation. When a signal fires,
        a pending limit order is created at price +/- buffer (0.1%).
        On subsequent candles, the order checks if OHLC would have filled it:
        - Buy: candle.low <= limit_price -> filled
        - Sell: candle.high >= limit_price -> filled
        - After 24 candles unfilled -> cancelled (stale)
    """

    LIMIT_BUFFER_PCT = 0.001  # 0.1% buffer from signal price
    MAX_PENDING_CANDLES = 24  # Cancel unfilled orders after 24 candles

    MAX_LOSS_PCT = 0.10  # 10% stop-loss (default, overridden by agent traits)
    AGENT_CACHE_REFRESH_INTERVAL = 60  # Refresh cached agent data every 60 candles

    def __init__(self):
        self.active_positions: dict[str, dict] = {}  # agent_id -> position info
        self.pending_orders: dict[str, dict] = {}  # order_id -> pending order info
        self._lock = asyncio.Lock()  # Protect against concurrent candle processing
        self._agent_cache: dict[str, dict] = {}  # agent_id -> {agent, candle_count}

        # 3-zone AI consultation handler (real LLM via Ollama)
        try:
            from Fast_Swarm.local_agents.shared.llm_client import AIZoneHandler, AIZoneMode
            self.ai_zone_handler = AIZoneHandler(mode=AIZoneMode.LLM)
        except Exception as e:
            logger.warning(f"[PaperTrade] AIZoneHandler init failed, AI_REFLECT zone disabled: {e}")
            self.ai_zone_handler = None

    async def _get_cached_agent(self, session: AsyncSession, agent_id: str) -> Agent | None:
        """Get agent from cache, refreshing from DB periodically."""
        cache_entry = self._agent_cache.get(agent_id)
        if cache_entry:
            cache_entry["candle_count"] += 1
            if cache_entry["candle_count"] < self.AGENT_CACHE_REFRESH_INTERVAL:
                return cache_entry["agent"]

        # Cache miss or stale - fetch from DB
        result = await session.exec(select(Agent).where(Agent.agent_id == agent_id))
        agent = result.first()
        if agent:
            self._agent_cache[agent_id] = {"agent": agent, "candle_count": 0}
        return agent

    def _invalidate_agent_cache(self, agent_id: str):
        """Remove agent from cache (on start/stop)."""
        self._agent_cache.pop(agent_id, None)

    async def start_paper_trading(
        self,
        session: AsyncSession,
        agent_id: str,
        symbols: list[str] | None = None,
        initial_balance: float = 10000.0,
    ) -> dict:
        """
        Start paper trading for an agent.

        Args:
            session: Database session
            agent_id: Agent to start trading
            symbols: Symbols to trade (default: BTC-USDT)
            initial_balance: Starting paper balance

        Returns:
            Status dict with agent info
        """
        # Get agent
        result = await session.exec(select(Agent).where(Agent.agent_id == agent_id))
        agent = result.first()

        if not agent:
            return {"error": "Agent not found", "agent_id": agent_id}

        if agent.status != "active":
            return {"error": "Agent not active", "status": agent.status}

        symbols = symbols or ["BTC-USDT"]

        # Initialize position tracking
        self.active_positions[agent_id] = {
            "agent_id": agent_id,
            "agent_name": agent.name,
            "balance": initial_balance,
            "initial_balance": initial_balance,
            "symbols": symbols,
            "positions": {},  # symbol -> position
            "started_at": datetime.now(timezone.utc),
            "trades_count": 0,
            "total_pnl": 0.0,
        }

        # --- Bootstrap / Resume Logic ---
        needs_bootstrap = agent.paper_watermark_ms is None
        bootstrap_info = {"mode": "bootstrap" if needs_bootstrap else "resume"}

        if needs_bootstrap:
            # FIRST PAPER TRADE: Run full backtest from earliest data to now
            logger.info(
                "Bootstrap backtest for agent %s (first paper trade)",
                agent_id[:8],
            )
            bootstrap_result = await self._run_bootstrap_backtest(
                session, agent, symbols, initial_balance
            )
            if bootstrap_result:
                self.active_positions[agent_id]["balance"] = bootstrap_result["final_balance"]
                self.active_positions[agent_id]["positions"] = bootstrap_result["open_positions"]
                self.active_positions[agent_id]["trades_count"] = bootstrap_result["trades_count"]
                self.active_positions[agent_id]["total_pnl"] = bootstrap_result["total_pnl"]
                agent.paper_watermark_ms = bootstrap_result["watermark_ms"]
                session.add(agent)
                await session.commit()
                bootstrap_info["trades"] = bootstrap_result["trades_count"]
                bootstrap_info["watermark_ms"] = bootstrap_result["watermark_ms"]
                bootstrap_info["open_positions"] = len(bootstrap_result["open_positions"])
                logger.info(
                    "Bootstrap complete for %s: %d trades, %d open positions, watermark=%d",
                    agent_id[:8],
                    bootstrap_result["trades_count"],
                    len(bootstrap_result["open_positions"]),
                    bootstrap_result["watermark_ms"],
                )
        else:
            # RESUME: Reclaim DB positions + catch up from watermark
            watermark_ms = agent.paper_watermark_ms

            # 1. Reclaim orphaned positions from DB
            stmt = select(LiveTradeUnified).where(
                LiveTradeUnified.agent_id == agent_id,
                LiveTradeUnified.status == "open",
            )
            result = await session.exec(stmt)
            orphaned = result.all()

            reclaimed_value = 0.0
            for pos in orphaned:
                sym = pos.symbol
                size_usd = float(pos.size_usd) if pos.size_usd else 0.0
                self.active_positions[agent_id]["positions"][sym] = {
                    "trade_id": pos.trade_id,
                    "side": pos.side,
                    "entry_price": float(pos.entry_price) if pos.entry_price else 0.0,
                    "size": float(pos.size) if pos.size else 0.0,
                    "size_usd": size_usd,
                    "entry_time": pos.entry_time or datetime.now(timezone.utc),
                }
                reclaimed_value += size_usd
                if sym not in self.active_positions[agent_id]["symbols"]:
                    self.active_positions[agent_id]["symbols"].append(sym)

            if reclaimed_value > 0:
                self.active_positions[agent_id]["balance"] = max(0, initial_balance - reclaimed_value)
                self.active_positions[agent_id]["trades_count"] = len(orphaned)

            logger.info(
                "Resume agent %s: reclaimed %d positions ($%.2f)",
                agent_id[:8], len(orphaned), reclaimed_value,
            )

            # 2. Catch-up backtest from watermark to now
            catchup_result = await self._run_catchup_backtest(
                session, agent, symbols,
                self.active_positions[agent_id]["balance"], watermark_ms,
            )
            if catchup_result:
                self.active_positions[agent_id]["balance"] = catchup_result["final_balance"]
                self.active_positions[agent_id]["positions"].update(catchup_result["open_positions"])
                self.active_positions[agent_id]["trades_count"] += catchup_result["trades_count"]
                self.active_positions[agent_id]["total_pnl"] += catchup_result["total_pnl"]
                agent.paper_watermark_ms = catchup_result["watermark_ms"]
                session.add(agent)
                await session.commit()
                bootstrap_info["catchup_trades"] = catchup_result["trades_count"]

            bootstrap_info["reclaimed_positions"] = len(orphaned)
            bootstrap_info["watermark_ms"] = agent.paper_watermark_ms

        logger.info(
            "Started paper trading for agent %s (%s) with $%.2f on %s [%s]",
            agent_id[:8],
            agent.name,
            self.active_positions[agent_id]["balance"],
            symbols,
            bootstrap_info["mode"],
        )

        return {
            "status": "started",
            "agent_id": agent_id,
            "agent_name": agent.name,
            "balance": self.active_positions[agent_id]["balance"],
            "symbols": symbols,
            "bootstrap": bootstrap_info,
        }

    async def stop_paper_trading(self, agent_id: str) -> dict:
        """Stop paper trading for an agent. Also cancels any pending orders."""
        if agent_id not in self.active_positions:
            return {"error": "Agent not actively trading", "agent_id": agent_id}

        # Cancel any pending orders for this agent
        cancelled = self.cancel_pending_orders(agent_id)

        position_info = self.active_positions.pop(agent_id)
        self._invalidate_agent_cache(agent_id)
        duration = datetime.now(timezone.utc) - position_info["started_at"]

        return {
            "status": "stopped",
            "agent_id": agent_id,
            "duration_seconds": duration.total_seconds(),
            "trades_count": position_info["trades_count"],
            "total_pnl": position_info["total_pnl"],
            "final_balance": position_info["balance"],
            "pending_orders_cancelled": cancelled,
        }

    # =========================================================================
    # Bootstrap / Catch-up Backtest Methods
    # =========================================================================

    async def _hydrate_agent_patterns(self, session: AsyncSession, agent: Agent) -> list[dict]:
        """
        Load and hydrate patterns for an agent (same logic as backtest_service).

        Returns list of pattern dicts with entry_conditions/exit_conditions.
        """
        agent_patterns = []
        reference_ids = []
        assigned = agent.assigned_patterns or {}

        if isinstance(assigned, dict):
            base_patterns = assigned.get("base", [])
            for p in base_patterns:
                if isinstance(p, str):
                    reference_ids.append(p)
                elif isinstance(p, dict):
                    if p.get("entry_conditions"):
                        agent_patterns.append(p)
                    else:
                        pid = p.get("pattern_id", p.get("id", ""))
                        if pid:
                            reference_ids.append(pid)
        elif isinstance(assigned, list):
            for item in assigned:
                if isinstance(item, str):
                    reference_ids.append(item)

        # Hydrate reference IDs from Pattern table
        if reference_ids:
            pattern_result = await session.exec(
                select(Pattern).where(Pattern.pattern_id.in_(reference_ids))
            )
            fetched_patterns = pattern_result.all()
            for p in fetched_patterns:
                hydrated = {
                    "pattern_id": p.pattern_id,
                    "name": p.name,
                    "entry_conditions": p.entry_conditions,
                    "exit_conditions": p.exit_conditions,
                }
                agent_patterns.append(hydrated)

        return agent_patterns

    def _normalize_symbol_for_loader(self, symbol: str) -> str:
        """Convert dashboard symbol format to loader format.

        Dashboard uses 'BTC-USDT', loader wants 'BTC'.
        """
        # Strip quote currency suffixes
        for suffix in ("-USDT", "-USD", "/USDT", "/USD", "USDT", "USD"):
            if symbol.upper().endswith(suffix):
                return symbol[:len(symbol) - len(suffix)]
        return symbol

    async def _run_bootstrap_backtest(
        self,
        session: AsyncSession,
        agent: Agent,
        symbols: list[str],
        initial_balance: float,
    ) -> dict | None:
        """
        Run full backtest from earliest available data to now.
        Records trades as source='paper', trading_mode='bootstrap'.
        Returns final state including open positions and watermark.
        """
        from Fast_Swarm.local_agents.backtest.data import OHLCVLoader
        from Fast_Swarm.local_agents.backtest.engine import LocalBacktestEngine, BacktestConfig
        from Fast_Swarm.local_agents.core.state import AgentRecord
        from Fast_Swarm.local_agents.core.traits import AgentTraits
        from Fast_Swarm.local_agents.shared.llm_client import AIZoneMode
        from dataclasses import fields as dataclass_fields

        # Hydrate patterns
        agent_patterns = await self._hydrate_agent_patterns(session, agent)
        if not agent_patterns:
            logger.warning("Agent %s has no patterns, skipping bootstrap", agent.agent_id[:8])
            return None

        # Build AgentRecord for the engine
        traits_dict = agent.traits if isinstance(agent.traits, dict) else {}
        known_fields = {f.name for f in dataclass_fields(AgentTraits)}
        filtered_traits = {k: v for k, v in traits_dict.items() if k in known_fields}

        agent_record = AgentRecord(
            agent_id=agent.agent_id,
            agent_name=agent.name,
            generation=agent.generation,
            traits=traits_dict,
            pattern_ids=[p["pattern_id"] for p in agent_patterns],
            pattern_weights=agent.pattern_weights or {},
            trading_philosophy=agent.trading_philosophy or "",
        )

        pattern_dict = {p["pattern_id"]: p for p in agent_patterns}
        agent_traits = AgentTraits(**filtered_traits)
        config = BacktestConfig.from_traits(agent_traits)

        # Create engine (skip AI for speed during bootstrap)
        loader = OHLCVLoader()
        engine = LocalBacktestEngine(
            loader=loader,
            config=config,
            patterns=pattern_dict,
            ai_zone_mode=AIZoneMode.SKIP,
        )

        # Run backtest across all symbols (blocking -> run in thread)
        clean_assets = [self._normalize_symbol_for_loader(s) for s in symbols]
        dataset = {"assets": clean_assets, "timeframe": "1m"}

        all_trades = await asyncio.to_thread(engine.run, agent_record, dataset)

        # Record trades to DB and track final state
        total_trades = 0
        final_balance = initial_balance
        open_positions = {}
        last_watermark = 0

        for trade in all_trades:
            await self._record_bootstrap_trade(session, agent, trade)
            total_trades += 1
            # Only closed trades affect balance
            if trade.exit_price > 0:
                pnl_usd = (trade.pnl_pct / 100.0) * (initial_balance * (trade.position_size_pct / 100.0))
                final_balance += pnl_usd
            else:
                # Open position at end of data
                asset_key = trade.asset
                open_positions[asset_key] = {
                    "trade_id": trade.trade_id,
                    "side": trade.direction,
                    "entry_price": trade.entry_price,
                    "size": initial_balance * (trade.position_size_pct / 100.0) / trade.entry_price if trade.entry_price > 0 else 0,
                    "size_usd": initial_balance * (trade.position_size_pct / 100.0),
                    "entry_time": datetime.fromtimestamp(trade.entry_timestamp / 1000, tz=timezone.utc) if trade.entry_timestamp > 0 else datetime.now(timezone.utc),
                }

            # Track watermark (latest timestamp seen)
            ts = trade.exit_timestamp if trade.exit_timestamp > 0 else trade.entry_timestamp
            if ts > last_watermark:
                last_watermark = ts

        # If no trades, still set watermark to latest candle available
        if last_watermark == 0:
            # Query latest candle timestamp for these assets
            for asset in clean_assets:
                df = await asyncio.to_thread(
                    loader.load_candles, asset=asset, timeframe="1m", limit=1
                )
                if df is not None and len(df) > 0 and "timestamp" in df.columns:
                    ts = int(df["timestamp"].iloc[-1])
                    if ts > last_watermark:
                        last_watermark = ts

        await session.commit()

        return {
            "final_balance": final_balance,
            "open_positions": open_positions,
            "trades_count": total_trades,
            "total_pnl": final_balance - initial_balance,
            "watermark_ms": last_watermark,
        }

    async def _run_catchup_backtest(
        self,
        session: AsyncSession,
        agent: Agent,
        symbols: list[str],
        current_balance: float,
        watermark_ms: int,
    ) -> dict | None:
        """
        Catch up from watermark to now. Same as bootstrap but date-filtered.
        Only processes candles after the watermark timestamp.
        """
        from Fast_Swarm.local_agents.backtest.data import OHLCVLoader
        from Fast_Swarm.local_agents.backtest.engine import LocalBacktestEngine, BacktestConfig
        from Fast_Swarm.local_agents.core.state import AgentRecord
        from Fast_Swarm.local_agents.core.traits import AgentTraits
        from Fast_Swarm.local_agents.shared.llm_client import AIZoneMode
        from dataclasses import fields as dataclass_fields

        agent_patterns = await self._hydrate_agent_patterns(session, agent)
        if not agent_patterns:
            return None

        traits_dict = agent.traits if isinstance(agent.traits, dict) else {}
        known_fields = {f.name for f in dataclass_fields(AgentTraits)}
        filtered_traits = {k: v for k, v in traits_dict.items() if k in known_fields}

        agent_record = AgentRecord(
            agent_id=agent.agent_id,
            agent_name=agent.name,
            generation=agent.generation,
            traits=traits_dict,
            pattern_ids=[p["pattern_id"] for p in agent_patterns],
            pattern_weights=agent.pattern_weights or {},
            trading_philosophy=agent.trading_philosophy or "",
        )

        pattern_dict = {p["pattern_id"]: p for p in agent_patterns}
        agent_traits = AgentTraits(**filtered_traits)
        config = BacktestConfig.from_traits(agent_traits)

        loader = OHLCVLoader()
        engine = LocalBacktestEngine(
            loader=loader,
            config=config,
            patterns=pattern_dict,
            ai_zone_mode=AIZoneMode.SKIP,
        )

        # Run from watermark+1 to now
        clean_assets = [self._normalize_symbol_for_loader(s) for s in symbols]
        dataset = {
            "assets": clean_assets,
            "timeframe": "1m",
            "start_ts": watermark_ms + 1,  # Only candles AFTER watermark
        }

        all_trades = await asyncio.to_thread(engine.run, agent_record, dataset)

        total_trades = 0
        final_balance = current_balance
        open_positions = {}
        last_watermark = watermark_ms

        for trade in all_trades:
            await self._record_bootstrap_trade(session, agent, trade)
            total_trades += 1
            if trade.exit_price > 0:
                pnl_usd = (trade.pnl_pct / 100.0) * (current_balance * (trade.position_size_pct / 100.0))
                final_balance += pnl_usd
            else:
                asset_key = trade.asset
                open_positions[asset_key] = {
                    "trade_id": trade.trade_id,
                    "side": trade.direction,
                    "entry_price": trade.entry_price,
                    "size": current_balance * (trade.position_size_pct / 100.0) / trade.entry_price if trade.entry_price > 0 else 0,
                    "size_usd": current_balance * (trade.position_size_pct / 100.0),
                    "entry_time": datetime.fromtimestamp(trade.entry_timestamp / 1000, tz=timezone.utc) if trade.entry_timestamp > 0 else datetime.now(timezone.utc),
                }

            ts = trade.exit_timestamp if trade.exit_timestamp > 0 else trade.entry_timestamp
            if ts > last_watermark:
                last_watermark = ts

        await session.commit()

        return {
            "final_balance": final_balance,
            "open_positions": open_positions,
            "trades_count": total_trades,
            "total_pnl": final_balance - current_balance,
            "watermark_ms": last_watermark,
        }

    async def _record_bootstrap_trade(
        self, session: AsyncSession, agent: Agent, trade
    ):
        """Convert a TradeRecord from the backtest engine to a LiveTradeUnified DB record."""
        entry_time = (
            datetime.fromtimestamp(trade.entry_timestamp / 1000, tz=timezone.utc)
            if trade.entry_timestamp > 0
            else datetime.now(timezone.utc)
        )
        exit_time = (
            datetime.fromtimestamp(trade.exit_timestamp / 1000, tz=timezone.utc)
            if trade.exit_timestamp > 0
            else None
        )

        record = LiveTradeUnified(
            trade_id=trade.trade_id,
            source="paper",
            agent_id=agent.agent_id,
            agent_name=agent.name,
            pattern_id=trade.pattern_id,
            exchange="paper",
            venue_type="paper",
            symbol=trade.asset,
            side=trade.direction,
            entry_time=entry_time,
            exit_time=exit_time,
            entry_price=Decimal(str(trade.entry_price)) if trade.entry_price else None,
            exit_price=Decimal(str(trade.exit_price)) if trade.exit_price else None,
            pnl_pct=trade.pnl_pct if trade.exit_price > 0 else None,
            status="closed" if trade.exit_price > 0 else "open",
            exit_reason=trade.exit_reason or "",
            regime=trade.entry_regime or "unknown",
            trading_mode="bootstrap",
            confidence=trade.entry_confidence,
            created_at=entry_time,
        )
        session.add(record)

    async def evaluate_and_trade(
        self,
        session: AsyncSession,
        agent_id: str,
        symbol: str,
        current_price: float,
        candle_data: dict,
        regime: str = "unknown",
    ) -> dict | None:
        """
        Evaluate market conditions and potentially execute a paper trade.

        This method performs two phases:
        1. CHECK PENDING ORDERS: Verify if any pending limit orders from previous
           candles are now filled (using current candle's OHLC as fill proof).
        2. EVALUATE NEW SIGNALS: If no open position and no pending order exists,
           evaluate patterns for new entry signals.

        Args:
            session: Database session
            agent_id: Agent making the decision
            symbol: Trading symbol
            current_price: Current market price
            candle_data: OHLCV + indicators for pattern matching
            regime: Current market regime

        Returns:
            Trade/order info if action was taken, None otherwise
        """
        if agent_id not in self.active_positions:
            return None

        # Check if agent is paused
        if self.active_positions[agent_id].get("paused", False):
            return None

        # Get agent (cached to avoid DB query every 1m candle)
        agent = await self._get_cached_agent(session, agent_id)

        if not agent or not agent.assigned_patterns:
            return None

        # =================================================================
        # Phase 1: Check pending limit orders against current candle OHLC
        # =================================================================
        fill_results = await self.check_pending_orders(session, symbol, candle_data)
        if fill_results:
            # Report the first meaningful result (fill or expiry)
            for fr in fill_results:
                if fr["action"] == "order_filled":
                    return fr  # Position opened via fill - done for this cycle

        position_info = self.active_positions[agent_id]
        current_position = position_info["positions"].get(symbol)

        # =================================================================
        # Stop-Loss Check - Protect against unlimited losses
        # =================================================================
        if current_position is not None and current_price > 0:
            entry_price = current_position["entry_price"]
            side = current_position["side"]
            if entry_price > 0:
                if side == "long":
                    unrealized_pnl_pct = (current_price - entry_price) / entry_price
                else:
                    unrealized_pnl_pct = (entry_price - current_price) / entry_price

                max_loss = (agent.traits or {}).get("max_loss_pct", self.MAX_LOSS_PCT)
                if unrealized_pnl_pct <= -max_loss:
                    logger.warning(
                        "STOP-LOSS: Agent %s %s %s hit %.1f%% loss (limit: %.1f%%)",
                        agent_id[:8], side, symbol,
                        unrealized_pnl_pct * 100, max_loss * 100,
                    )
                    return await self._close_position(
                        session, agent, symbol, current_price, candle_data, "stop_loss"
                    )

        # =================================================================
        # Bear Protection Check - VETO POWER
        # If defensive_trigger is active, block new positions and may force exit
        # =================================================================
        defensive_trigger = candle_data.get("defensive_trigger")
        if defensive_trigger == 1:
            logger.warning(
                "BEAR PROTECTION: Blocking trade for %s - defensive_trigger active "
                "(acc=%.2f, adx_jerk=%.2f)",
                symbol,
                candle_data.get("close_acceleration_zscore", 0),
                candle_data.get("adx_14_jerk_zscore", 0),
            )
            # Cancel any pending orders for this symbol (defensive = no new entries)
            self.cancel_pending_orders(agent_id, symbol)

            # If we have an open position during defensive trigger, force close
            if current_position is not None:
                logger.warning("BEAR PROTECTION: Force closing position for %s", symbol)
                return await self._close_position(
                    session, agent, symbol, current_price, candle_data, "defensive"
                )
            # Block new positions during defensive mode
            return None

        # =================================================================
        # Phase 2: Evaluate patterns for new signals
        # =================================================================
        signal = await self._evaluate_patterns(agent, candle_data, has_position=(current_position is not None), symbol=symbol)

        if signal == "hold":
            return None

        # Check if there's already a pending order for this agent/symbol
        has_pending = any(
            o["agent_id"] == agent_id and o["symbol"] == symbol
            for o in self.pending_orders.values()
        )

        # Determine action
        if current_position is None and not has_pending and signal in ("buy", "long"):
            return await self._open_position(
                session, agent, symbol, "long", current_price, candle_data, regime
            )
        elif current_position is None and not has_pending and signal in ("sell", "short"):
            return await self._open_position(
                session, agent, symbol, "short", current_price, candle_data, regime
            )
        elif current_position is not None and signal == "close":
            return await self._close_position(
                session, agent, symbol, current_price, candle_data, regime
            )

        return None

    async def _evaluate_patterns(self, agent: Agent, candle_data: dict, has_position: bool = False, symbol: str = "") -> str:
        """
        Evaluate agent's patterns against current market data using PatternMatcher.

        Args:
            agent: Agent with assigned_patterns (dict of pattern_id -> pattern_data)
            candle_data: Dict containing indicator values (close, rsi14, macdHistogram, etc.)
            has_position: Whether the agent currently holds a position (skip exits if False)

        Returns: "buy", "sell", "close", or "hold"
        """
        if not agent.assigned_patterns:
            return "hold"

        # Import pattern matcher
        try:
            from Fast_Swarm.local_agents.backtest.pattern_matcher import evaluate_conditions
        except ImportError:
            logger.warning("PatternMatcher not available - returning hold")
            return "hold"

        # Weighted voting from patterns
        buy_votes = 0.0
        sell_votes = 0.0
        close_votes = 0.0

        # assigned_patterns is {"base": [pattern1, pattern2, ...], ...}
        # Flatten all categories into individual pattern dicts
        all_patterns = []
        for category, patterns_list in agent.assigned_patterns.items():
            if isinstance(patterns_list, list):
                all_patterns.extend(patterns_list)
            elif isinstance(patterns_list, dict):
                # Legacy format: category is pattern_id, value is pattern data
                all_patterns.append({**patterns_list, "pattern_id": category})

        if not all_patterns:
            logger.warning(
                "[PaperTrade] Agent %s has assigned_patterns but 0 flattened! "
                "Format: %s",
                agent.agent_id[:8],
                type(agent.assigned_patterns).__name__,
            )
            return "hold"

        # Log available indicators ONCE per agent
        diag_key = f"diag_{agent.agent_id}"
        if not hasattr(self, '_diag_logged'):
            self._diag_logged = set()
        if diag_key not in self._diag_logged:
            avail_keys = sorted(candle_data.keys())[:30]
            logger.info(
                "[PaperTrade] DIAG %s: candle_data has %d keys, sample: %s",
                agent.agent_id[:8], len(candle_data), avail_keys
            )
            self._diag_logged.add(diag_key)

        for pattern_data in all_patterns:
            pattern_id = pattern_data.get("pattern_id", "unknown")
            # Get weight: prefer agent's override, fallback to pattern's own weight
            weight = (agent.pattern_weights or {}).get(pattern_id, pattern_data.get("weight", 1.0))

            # Extract conditions from pattern
            entry_conditions = pattern_data.get("entry_conditions", [])
            exit_conditions = pattern_data.get("exit_conditions", [])
            direction = pattern_data.get("direction", "long")

            # Evaluate entry conditions
            if entry_conditions:
                try:
                    entry_result = evaluate_conditions(entry_conditions, candle_data)
                    if entry_result.matched:
                        # Full match: all conditions met
                        if direction == "long":
                            buy_votes += weight * entry_result.confidence
                        else:
                            sell_votes += weight * entry_result.confidence
                    elif entry_result.conditions_total > 0 and entry_result.conditions_met > 0:
                        # Partial match: proportional signal from fraction met
                        # Paper trading allows partial matches for pipeline testing
                        fraction = entry_result.conditions_met / entry_result.conditions_total
                        if direction == "long":
                            buy_votes += weight * fraction
                        else:
                            sell_votes += weight * fraction
                    # Per-pattern confidence: how close to matching
                    frac = entry_result.conditions_met / entry_result.conditions_total if entry_result.conditions_total > 0 else 0
                    pattern_name = pattern_data.get("name", pattern_id[:12])
                    logger.info(
                        "[PaperTrade] %s | %s: %d/%d met (%.0f%%) w=%.2f conf=%.3f dir=%s",
                        agent.agent_id[:8], pattern_name,
                        entry_result.conditions_met, entry_result.conditions_total,
                        frac * 100, weight, entry_result.confidence, direction,
                    )
                except Exception as e:
                    logger.info(f"[PaperTrade] Entry eval EXCEPTION for pattern {pattern_id[:12]}: {e}")

            # Evaluate exit conditions (only when holding a position)
            if exit_conditions and has_position:
                try:
                    exit_result = evaluate_conditions(exit_conditions, candle_data)
                    if exit_result.matched:
                        close_votes += weight * exit_result.confidence
                except Exception as e:
                    logger.debug(f"Exit eval error for pattern {pattern_id}: {e}")

        # Log pattern evaluation summary
        logger.info(
            "[PaperTrade] Pattern eval for %s: %d patterns, "
            "buy=%.2f sell=%.2f close=%.2f",
            agent.agent_id[:8], len(all_patterns),
            buy_votes, sell_votes, close_votes,
        )

        # Close takes priority if strongly signaled and we have a position
        if close_votes > 0.5 and has_position:
            return "close"

        # No entry signals at all
        total_entry_votes = buy_votes + sell_votes
        if total_entry_votes == 0:
            return "hold"

        # Require clear directional majority (1.5x) before considering trade.
        # Conflicting signals with no clear winner = hold (economic soundness).
        if buy_votes > 0 and sell_votes > 0:
            if not (buy_votes > sell_votes * 1.5 or sell_votes > buy_votes * 1.5):
                logger.debug(
                    "[PaperTrade] %s: hold (conflicting: buy=%.2f sell=%.2f, no 1.5x majority)",
                    agent.agent_id[:8], buy_votes, sell_votes,
                )
                return "hold"

        # --- 3-Zone Decision System ---
        # Determine the best entry confidence and direction
        best_confidence = max(buy_votes, sell_votes)
        best_direction = "buy" if buy_votes >= sell_votes else "sell"

        # Build traits namespace for determine_zone (needs .min_threshold, .ai_threshold)
        traits_ns = types.SimpleNamespace(
            min_threshold=agent.traits.get("min_threshold", 0.35) if agent.traits else 0.35,
            ai_threshold=agent.traits.get("ai_threshold", 0.65) if agent.traits else 0.65,
        )

        try:
            from Fast_Swarm.local_agents.core.decision import determine_zone, DecisionZone
            zone_result = determine_zone(best_confidence, traits_ns)
            zone = zone_result.zone

            logger.info(
                "[PaperTrade] %s: Zone=%s confidence=%.3f (thresholds: skip<%.3f, exec>=%.3f) dir=%s",
                agent.agent_id[:8], zone.name, best_confidence,
                traits_ns.min_threshold, traits_ns.ai_threshold, best_direction,
            )

            # Emit zone_decision event to decision feed
            try:
                feed = get_decision_feed_service()
                pattern_names_list = [p.get("name", p.get("pattern_id", "?")[:12]) for p in all_patterns]
                await feed.emit(DecisionEvent(
                    event_id=str(uuid.uuid4()),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    agent_id=agent.agent_id,
                    agent_name=agent.name or agent.agent_id[:8],
                    symbol=symbol,
                    timeframe="",
                    event_type="zone_decision",
                    patterns_evaluated=len(all_patterns),
                    buy_confidence=buy_votes,
                    sell_confidence=sell_votes,
                    zone=zone.name,
                    zone_thresholds={"min": traits_ns.min_threshold, "ai": traits_ns.ai_threshold},
                    pattern_names=pattern_names_list,
                ))
            except Exception:
                pass  # Never block trading on feed errors

            if zone == DecisionZone.EXECUTE:
                return best_direction

            elif zone == DecisionZone.AI_REFLECT:
                # Consult LLM for borderline confidence
                if self.ai_zone_handler is not None:
                    try:
                        # Gather context for AI decision
                        pattern_names = [p.get("name", p.get("pattern_id", "?")[:12]) for p in all_patterns]
                        should_trade, reasoning, ai_consulted = await self.ai_zone_handler.decide_async(
                            confidence=best_confidence,
                            pattern_name=", ".join(pattern_names),
                            indicators=candle_data,
                            traits=agent.traits or {},
                            recent_trades=[],
                        )
                        logger.info(
                            "[PaperTrade] %s: AI_REFLECT -> %s (reason: %s, consulted=%s)",
                            agent.agent_id[:8],
                            best_direction if should_trade else "hold",
                            reasoning[:80] if reasoning else "none",
                            ai_consulted,
                        )
                        # Emit llm_result event to decision feed
                        try:
                            llm_feed = get_decision_feed_service()
                            llm_decision = "enter" if should_trade else "hold"
                            await llm_feed.emit(DecisionEvent(
                                event_id=str(uuid.uuid4()),
                                timestamp=datetime.now(timezone.utc).isoformat(),
                                agent_id=agent.agent_id,
                                agent_name=agent.name or agent.agent_id[:8],
                                symbol=symbol,
                                timeframe="",
                                event_type="llm_result",
                                buy_confidence=buy_votes,
                                sell_confidence=sell_votes,
                                llm_decision=llm_decision,
                                llm_reason=reasoning[:200] if reasoning else "",
                                llm_parsed=True,
                                side=best_direction if should_trade else "",
                                pattern_names=pattern_names,
                            ))
                        except Exception:
                            pass
                        if should_trade:
                            return best_direction
                        return "hold"
                    except Exception as e:
                        logger.warning("[PaperTrade] AI consultation failed: %s - defaulting to hold", e)
                        return "hold"
                else:
                    logger.debug("[PaperTrade] %s: AI_REFLECT but no handler - hold", agent.agent_id[:8])
                    return "hold"

            else:  # SKIP
                return "hold"

        except ImportError:
            logger.warning("[PaperTrade] decision module not available, using fallback thresholds")
            # Fallback: simple threshold if imports fail
            if best_confidence >= 0.5:
                return best_direction
            return "hold"

    async def _open_position(
        self,
        session: AsyncSession,
        agent: Agent,
        symbol: str,
        side: str,
        price: float,
        candle_data: dict,
        regime: str,
    ) -> dict:
        """
        Create a pending limit order for a new paper position.

        Instead of immediately filling at market price, this simulates a limit
        order with a 0.1% buffer. The order will only fill when a subsequent
        candle's OHLC confirms the price was available:
        - Buy: next candle's low <= limit_price
        - Sell: next candle's high >= limit_price

        If not filled within 24 candles, the order is cancelled (stale).
        """
        position_info = self.active_positions[agent.agent_id]

        # Calculate position size (use Kelly or fixed fraction)
        kelly_fraction = (agent.traits or {}).get("kelly_fraction", 0.1)
        position_size_usd = position_info["balance"] * kelly_fraction
        size = position_size_usd / price if price > 0 else 0

        # Calculate limit price with buffer
        # Buy: willing to pay up to 0.1% more (limit above signal price)
        # Sell/Short: willing to accept up to 0.1% less (limit below signal price)
        if side == "long":
            limit_price = price * (1 + self.LIMIT_BUFFER_PCT)
        else:
            limit_price = price * (1 - self.LIMIT_BUFFER_PCT)

        order_id = str(uuid.uuid4())

        # Store pending order (NOT yet in database - only persisted on fill)
        self.pending_orders[order_id] = {
            "order_id": order_id,
            "agent_id": agent.agent_id,
            "symbol": symbol,
            "side": side,
            "signal_price": price,
            "limit_price": limit_price,
            "size": size,
            "size_usd": position_size_usd,
            "regime": regime,
            "candles_waited": 0,
            "created_at": datetime.now(timezone.utc),
        }

        logger.info(
            "Agent %s pending %s %s: signal=%.2f, limit=%.2f (buffer=%.1f%%, expires in %d candles)",
            agent.agent_id[:8],
            side,
            symbol,
            price,
            limit_price,
            self.LIMIT_BUFFER_PCT * 100,
            self.MAX_PENDING_CANDLES,
        )

        return {
            "action": "pending_order",
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "signal_price": price,
            "limit_price": limit_price,
            "size": size,
            "size_usd": position_size_usd,
            "max_candles": self.MAX_PENDING_CANDLES,
        }

    async def _close_position(
        self,
        session: AsyncSession,
        agent: Agent,
        symbol: str,
        price: float,
        candle_data: dict,
        regime: str,
    ) -> dict:
        """Close an existing paper position."""
        position_info = self.active_positions[agent.agent_id]
        position = position_info["positions"].get(symbol)

        if not position:
            return {"error": "No position to close", "symbol": symbol}

        # Calculate P&L
        entry_price = position["entry_price"]
        size = position["size"]
        side = position["side"]

        # Guard against division by zero (corrupted data)
        if entry_price <= 0:
            logger.error(f"Invalid entry_price {entry_price} for {symbol}")
            pnl_pct = 0.0
        elif side == "long":
            pnl_pct = (price - entry_price) / entry_price
        else:  # short
            pnl_pct = (entry_price - price) / entry_price

        pnl_usd = position["size_usd"] * pnl_pct
        duration = (datetime.now(timezone.utc) - position["entry_time"]).total_seconds()

        # Update trade record
        result = await session.exec(
            select(LiveTradeUnified).where(
                LiveTradeUnified.trade_id == position["trade_id"]
            )
        )
        trade = result.first()

        if trade:
            trade.exit_time = datetime.now(timezone.utc)
            trade.exit_price = Decimal(str(price))
            trade.pnl_pct = pnl_pct * 100  # Store as percentage
            trade.pnl_usd = Decimal(str(pnl_usd))
            trade.realized_pnl = Decimal(str(pnl_usd))
            trade.duration_seconds = int(duration)
            trade.status = "closed"
            trade.exit_reason = "signal"
            trade.updated_at = datetime.now(timezone.utc)

            session.add(trade)
            await session.commit()

        # Update local tracking
        position_info["balance"] += pnl_usd
        position_info["total_pnl"] += pnl_usd
        del position_info["positions"][symbol]

        logger.info(
            "Agent %s closed %s %s @ %.2f (P&L: %.2f%%, $%.2f)",
            agent.agent_id[:8],
            side,
            symbol,
            price,
            pnl_pct * 100,
            pnl_usd,
        )

        return {
            "action": "close",
            "trade_id": position["trade_id"],
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "exit_price": price,
            "pnl_pct": pnl_pct * 100,
            "pnl_usd": pnl_usd,
            "duration_seconds": duration,
        }

    async def check_pending_orders(
        self,
        session: AsyncSession,
        symbol: str,
        candle_data: dict,
    ) -> list[dict]:
        """
        Check all pending limit orders against the current candle's OHLC.

        Called at the start of each evaluation cycle. For each pending order:
        1. Increment candles_waited counter
        2. Check fill condition against candle OHLC:
           - Buy/Long: candle.low <= limit_price (price dipped to our limit)
           - Sell/Short: candle.high >= limit_price (price rose to our limit)
        3. If filled -> create actual position + DB record
        4. If candles_waited >= 24 -> cancel (stale order)

        Args:
            session: Database session for persisting filled trades
            symbol: Symbol to check orders for
            candle_data: Current candle with OHLC data

        Returns:
            List of fill/cancel results
        """
        results = []
        orders_to_remove = []

        candle_low = candle_data.get("low", float("inf"))
        candle_high = candle_data.get("high", 0.0)

        for order_id, order in list(self.pending_orders.items()):
            # Only check orders for this symbol
            if order["symbol"] != symbol:
                continue

            # Increment candle counter
            order["candles_waited"] += 1

            # Check expiry first (24 candles without fill)
            if order["candles_waited"] >= self.MAX_PENDING_CANDLES:
                orders_to_remove.append(order_id)
                logger.info(
                    "Agent %s order EXPIRED: %s %s (waited %d candles, limit=%.2f)",
                    order["agent_id"][:8],
                    order["side"],
                    symbol,
                    order["candles_waited"],
                    order["limit_price"],
                )
                results.append({
                    "action": "order_expired",
                    "order_id": order_id,
                    "symbol": symbol,
                    "side": order["side"],
                    "limit_price": order["limit_price"],
                    "candles_waited": order["candles_waited"],
                })
                continue

            # Check fill condition
            filled = False
            if order["side"] == "long" and candle_low <= order["limit_price"]:
                filled = True
            elif order["side"] == "short" and candle_high >= order["limit_price"]:
                filled = True

            if filled:
                # Fill the order at the limit price (best case within buffer)
                fill_result = await self._fill_pending_order(session, order)
                if fill_result:
                    results.append(fill_result)
                orders_to_remove.append(order_id)

        # Clean up processed orders
        for order_id in orders_to_remove:
            self.pending_orders.pop(order_id, None)

        return results

    async def _fill_pending_order(
        self,
        session: AsyncSession,
        order: dict,
    ) -> dict | None:
        """
        Fill a pending limit order - create the actual position and DB record.

        The fill price is the limit price (represents the worst-case fill
        within the buffer, which is a conservative simulation).

        Args:
            session: Database session
            order: Pending order dict with all order details

        Returns:
            Fill result dict, or None on error
        """
        agent_id = order["agent_id"]
        if agent_id not in self.active_positions:
            logger.warning("Agent %s no longer active, discarding fill", agent_id[:8])
            return None

        position_info = self.active_positions[agent_id]
        symbol = order["symbol"]

        # Don't fill if agent already has a position in this symbol
        if symbol in position_info["positions"]:
            logger.debug(
                "Agent %s already has %s position, skipping fill",
                agent_id[:8], symbol,
            )
            return None

        fill_price = order["limit_price"]
        trade_id = str(uuid.uuid4())

        # Calculate slippage from signal to fill
        slippage_pct = abs(fill_price - order["signal_price"]) / order["signal_price"] * 100

        # Create trade record in database
        trade = LiveTradeUnified(
            trade_id=trade_id,
            source="paper",
            agent_id=agent_id,
            exchange="paper",
            venue_type="paper",
            symbol=symbol,
            side=order["side"],
            entry_time=datetime.now(timezone.utc),
            entry_price=Decimal(str(fill_price)),
            requested_price=Decimal(str(order["signal_price"])),
            size=Decimal(str(order["size"])),
            size_usd=Decimal(str(order["size_usd"])),
            status="open",
            order_type="limit_buffer",
            slippage_pct=slippage_pct,
            regime=order.get("regime", "unknown"),
            trading_mode="mvp_direct",
            created_at=order["created_at"],
        )

        session.add(trade)
        await session.commit()
        await session.refresh(trade)

        # Track position locally
        position_info["positions"][symbol] = {
            "trade_id": trade_id,
            "side": order["side"],
            "entry_price": fill_price,
            "size": order["size"],
            "size_usd": order["size_usd"],
            "entry_time": datetime.now(timezone.utc),
        }

        position_info["trades_count"] += 1

        logger.info(
            "Agent %s FILLED %s %s @ %.2f (signal=%.2f, waited %d candles, slippage=%.3f%%)",
            agent_id[:8],
            order["side"],
            symbol,
            fill_price,
            order["signal_price"],
            order["candles_waited"],
            slippage_pct,
        )

        return {
            "action": "order_filled",
            "trade_id": trade_id,
            "order_id": order["order_id"],
            "symbol": symbol,
            "side": order["side"],
            "signal_price": order["signal_price"],
            "fill_price": fill_price,
            "size": order["size"],
            "size_usd": order["size_usd"],
            "candles_waited": order["candles_waited"],
            "slippage_pct": slippage_pct,
        }

    def get_pending_orders(self, agent_id: str | None = None) -> list[dict]:
        """
        Get all pending (unfilled) limit orders, optionally filtered by agent.

        Args:
            agent_id: Optional filter by agent

        Returns:
            List of pending order dicts
        """
        orders = list(self.pending_orders.values())
        if agent_id:
            orders = [o for o in orders if o["agent_id"] == agent_id]
        return orders

    def cancel_pending_orders(self, agent_id: str, symbol: str | None = None) -> int:
        """
        Cancel pending orders for an agent (optionally filtered by symbol).

        Used when stopping trading or on bear protection defensive trigger.

        Args:
            agent_id: Agent whose orders to cancel
            symbol: Optional symbol filter (cancel all if None)

        Returns:
            Number of orders cancelled
        """
        to_cancel = [
            oid for oid, o in self.pending_orders.items()
            if o["agent_id"] == agent_id
            and (symbol is None or o["symbol"] == symbol)
        ]
        for oid in to_cancel:
            self.pending_orders.pop(oid, None)

        if to_cancel:
            logger.info(
                "Cancelled %d pending orders for agent %s%s",
                len(to_cancel),
                agent_id[:8],
                f" ({symbol})" if symbol else "",
            )
        return len(to_cancel)

    async def get_active_agents(self) -> list[dict]:
        """Get all agents currently paper trading with detailed info."""
        result = []
        for info in self.active_positions.values():
            initial_balance = info.get("initial_balance", info["balance"])
            total_pnl = info["total_pnl"]
            total_pnl_pct = (total_pnl / initial_balance * 100) if initial_balance > 0 else 0.0

            # Build open positions summary (per lot)
            open_positions = []
            now = datetime.now(timezone.utc)
            for symbol, pos in info["positions"].items():
                entry_time = pos.get("entry_time")
                duration = (now - entry_time).total_seconds() if entry_time else None
                entry_time_str = entry_time.isoformat() if entry_time else None
                open_positions.append({
                    "trade_id": pos.get("trade_id", ""),
                    "symbol": symbol,
                    "side": pos.get("side", "long"),
                    "size": pos.get("size", 0),
                    "size_usd": pos.get("size_usd", 0),
                    "entry_price": pos.get("entry_price", 0),
                    "entry_time": entry_time_str,
                    "unrealized_pnl_pct": pos.get("unrealized_pnl_pct"),
                    "duration_seconds": duration,
                })

            # Determine status
            status = "paused" if info.get("paused", False) else "trading"

            # Format started_at
            started_at = info.get("started_at")
            started_at_str = started_at.isoformat() if started_at else None

            # Count pending orders for this agent
            agent_id = info["agent_id"]
            agent_pending = [
                o for o in self.pending_orders.values()
                if o["agent_id"] == agent_id
            ]

            result.append({
                "agent_id": agent_id,
                "agent_name": info["agent_name"],
                "balance": info["balance"],
                "initial_balance": initial_balance,
                "positions": len(info["positions"]),
                "pending_orders": len(agent_pending),
                "trades_count": info["trades_count"],
                "total_pnl": total_pnl,
                "total_pnl_pct": total_pnl_pct,
                "symbols": info.get("symbols", []),
                "status": status,
                "open_positions": open_positions,
                "pending_order_details": [
                    {
                        "symbol": o["symbol"],
                        "side": o["side"],
                        "limit_price": o["limit_price"],
                        "candles_waited": o["candles_waited"],
                    }
                    for o in agent_pending
                ],
                "last_evaluation": info.get("last_evaluation"),
                "started_at": started_at_str,
            })
        return result

    async def get_agent_positions(self, agent_id: str) -> dict | None:
        """Get current positions and pending orders for an agent."""
        if agent_id not in self.active_positions:
            return None

        info = self.active_positions[agent_id]
        return {
            "agent_id": agent_id,
            "balance": info["balance"],
            "positions": info["positions"],
            "pending_orders": self.get_pending_orders(agent_id),
            "trades_count": info["trades_count"],
            "total_pnl": info["total_pnl"],
        }

    async def force_close_position(
        self,
        session: AsyncSession,
        agent_id: str,
        symbol: str,
        current_price: float,
    ) -> dict:
        """
        Force close a position (user override).

        Works in two modes:
        1. Active session: uses in-memory position data (fast path)
        2. Orphaned position: queries DB directly (session stopped but position persists)

        Args:
            session: Database session
            agent_id: Agent ID
            symbol: Symbol to close
            current_price: Current market price

        Returns:
            Close result dict matching ClosePositionResponse shape
        """
        # Fast path: agent has active in-memory session
        if agent_id in self.active_positions:
            stmt = select(Agent).where(Agent.agent_id == agent_id)
            result = await session.exec(stmt)
            agent = result.first()
            if not agent:
                return {"error": "Agent not found"}
            return await self._close_position(
                session, agent, symbol, current_price, {}, "manual_override"
            )

        # DB-only path: position exists in DB but no active session
        stmt = select(LiveTradeUnified).where(
            LiveTradeUnified.agent_id == agent_id,
            LiveTradeUnified.symbol == symbol,
            LiveTradeUnified.status == "open",
        )
        result = await session.exec(stmt)
        trade = result.first()

        if not trade:
            return {"error": f"No open position for {symbol}"}

        # Calculate P&L from DB entry data
        entry_price = float(trade.entry_price) if trade.entry_price else 0.0
        if entry_price <= 0:
            pnl_pct = 0.0
        elif trade.side == "long":
            pnl_pct = (current_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - current_price) / entry_price

        size_usd = float(trade.size_usd) if trade.size_usd else 0.0
        pnl_usd = size_usd * pnl_pct
        duration = (datetime.now(timezone.utc) - trade.entry_time).total_seconds() if trade.entry_time else 0.0

        # Update DB record
        trade.exit_time = datetime.now(timezone.utc)
        trade.exit_price = Decimal(str(current_price))
        trade.pnl_pct = pnl_pct * 100
        trade.pnl_usd = Decimal(str(pnl_usd))
        trade.realized_pnl = Decimal(str(pnl_usd))
        trade.duration_seconds = int(duration)
        trade.status = "closed"
        trade.exit_reason = "manual_override"
        trade.updated_at = datetime.now(timezone.utc)

        session.add(trade)
        await session.commit()

        logger.info(
            "DB-close: agent %s closed %s %s @ %.2f (P&L: %.2f%%, $%.2f)",
            agent_id[:8], trade.side, symbol, current_price, pnl_pct * 100, pnl_usd,
        )

        return {
            "action": "close",
            "trade_id": trade.trade_id,
            "symbol": symbol,
            "side": trade.side,
            "entry_price": entry_price,
            "exit_price": current_price,
            "pnl_pct": pnl_pct * 100,
            "pnl_usd": pnl_usd,
            "duration_seconds": duration,
        }

    async def pause_trading(self, agent_id: str) -> dict:
        """
        Pause trading for an agent (keeps positions, stops new trades).

        Args:
            agent_id: Agent to pause

        Returns:
            Status dict
        """
        if agent_id not in self.active_positions:
            return {"error": "Agent not actively trading"}

        position_info = self.active_positions[agent_id]

        if position_info.get("paused", False):
            return {"error": "Agent already paused", "agent_id": agent_id}

        position_info["paused"] = True
        position_info["paused_at"] = datetime.now(timezone.utc)

        logger.info("Paused trading for agent %s", agent_id[:8])

        return {
            "status": "paused",
            "agent_id": agent_id,
            "open_positions": len(position_info["positions"]),
            "balance": position_info["balance"],
        }

    async def resume_trading(self, agent_id: str) -> dict:
        """
        Resume trading for a paused agent.

        Args:
            agent_id: Agent to resume

        Returns:
            Status dict
        """
        if agent_id not in self.active_positions:
            return {"error": "Agent not actively trading"}

        position_info = self.active_positions[agent_id]

        if not position_info.get("paused", False):
            return {"error": "Agent not paused", "agent_id": agent_id}

        position_info["paused"] = False
        paused_at = position_info.pop("paused_at", None)
        pause_duration = 0
        if paused_at:
            pause_duration = (datetime.now(timezone.utc) - paused_at).total_seconds()

        logger.info("Resumed trading for agent %s (paused %.0fs)", agent_id[:8], pause_duration)

        return {
            "status": "resumed",
            "agent_id": agent_id,
            "pause_duration_seconds": pause_duration,
        }

    async def close_all_positions(
        self,
        session: AsyncSession,
        agent_id: str,
        current_prices: dict[str, float],
    ) -> dict:
        """
        Close all positions for an agent (emergency exit).

        Args:
            session: Database session
            agent_id: Agent ID
            current_prices: Dict of symbol -> current price

        Returns:
            Summary of closed positions
        """
        if agent_id not in self.active_positions:
            return {"error": "Agent not actively trading"}

        result = await session.exec(select(Agent).where(Agent.agent_id == agent_id))
        agent = result.first()

        if not agent:
            return {"error": "Agent not found"}

        # Cancel all pending orders for this agent
        cancelled_orders = self.cancel_pending_orders(agent_id)

        position_info = self.active_positions[agent_id]
        positions_to_close = list(position_info["positions"].keys())

        if not positions_to_close:
            return {
                "status": "no_positions",
                "agent_id": agent_id,
                "message": "No open positions to close",
                "pending_orders_cancelled": cancelled_orders,
            }

        closed = []
        errors = []

        for symbol in positions_to_close:
            price = current_prices.get(symbol)
            if price is None:
                errors.append({"symbol": symbol, "error": "No price provided"})
                continue

            close_result = await self._close_position(
                session, agent, symbol, price, {}, "close_all_override"
            )

            if "error" in close_result:
                errors.append({"symbol": symbol, "error": close_result["error"]})
            else:
                closed.append(close_result)

        total_pnl = sum(c.get("pnl_usd", 0) for c in closed)

        logger.info(
            "Closed all positions for agent %s: %d closed, %d errors, P&L: $%.2f",
            agent_id[:8],
            len(closed),
            len(errors),
            total_pnl,
        )

        return {
            "status": "closed_all",
            "agent_id": agent_id,
            "positions_closed": len(closed),
            "pending_orders_cancelled": cancelled_orders,
            "total_pnl_usd": total_pnl,
            "closed": closed,
            "errors": errors if errors else None,
        }

    def is_paused(self, agent_id: str) -> bool:
        """Check if an agent is paused."""
        if agent_id not in self.active_positions:
            return False
        return self.active_positions[agent_id].get("paused", False)

    def get_all_active_agents(self) -> dict[str, dict]:
        """
        Return all agents currently registered for paper trading.

        Used by the background trading loop to iterate over active agents.

        Returns:
            Dict of {agent_id: {symbols, balance, paused, positions, ...}}
        """
        return dict(self.active_positions)

    # =================================================================
    # Tick-driven paper trading (candle close handler)
    # =================================================================

    def handle_candle_close(
        self, exchange: str, symbol: str, timeframe: str, candle: dict, history: list[dict]
    ):
        """
        Callback for DataCollectorService.on_candle_close().

        Fired every time a candle closes on any timeframe. Checks if any active
        agents are trading this symbol, then schedules async enrichment + evaluation.

        This is a SYNC callback (collector fires it from sync context).
        """
        if not self.active_positions:
            return

        # Only evaluate on 1m closes - higher TFs are rolled up from 1m
        # and would cause redundant evaluations
        if timeframe != "1m":
            return

        # Find agents interested in this symbol
        matching_agents = self._find_agents_for_symbol(symbol)
        if not matching_agents:
            logger.debug(f"[PaperTrade] No matching agents for {symbol}")
            return

        # Need enough history for core indicators (RSI_14, MACD_26, Bollinger_20, etc.)
        # EMA_200 will be NaN until 200 candles - pattern matcher handles missing values.
        # 60 candles is sufficient for all indicators except long-period EMAs.
        if len(history) < 60:
            logger.debug(f"[PaperTrade] Not enough history for {symbol}: {len(history)}/60")
            return

        logger.debug(
            f"[PaperTrade] Candle close: {symbol} C={candle.get('close', '?')} "
            f"history={len(history)} agents={matching_agents}"
        )

        # Schedule async processing
        asyncio.create_task(
            self._process_candle_for_agents(exchange, symbol, timeframe, candle, history, matching_agents)
        )

    def _find_agents_for_symbol(self, exchange_symbol: str) -> list[str]:
        """
        Find active agents whose symbol config matches the exchange symbol.

        Handles format differences: exchange sends "BTCUSDT", agent config has "BTC-USDT".
        """
        # Normalize: strip separators, uppercase
        norm = exchange_symbol.replace("-", "").replace("_", "").upper()
        # Also try without USD suffix for matching
        base = norm.replace("USDT", "").replace("USD", "").replace("PERP", "")

        matching = []
        for agent_id, info in self.active_positions.items():
            if info.get("paused", False):
                continue
            for agent_symbol in info.get("symbols", []):
                agent_norm = agent_symbol.replace("-", "").replace("_", "").upper()
                agent_base = agent_norm.replace("USDT", "").replace("USD", "").replace("PERP", "")
                if norm == agent_norm or base == agent_base:
                    matching.append(agent_id)
                    break
        return matching

    async def _process_candle_for_agents(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        candle: dict,
        history: list[dict],
        agent_ids: list[str],
    ):
        """
        Enrich candle history with indicators and evaluate each agent.

        Pipeline: history buffer -> DataFrame -> calculate_indicators_fast() ->
                  rename columns -> last row as candle_data -> evaluate_and_trade()
        """
        import pandas as pd

        from ...Database import async_session_maker
        from ...Infrastructure.Services.indicator_calculation_service import calculate_indicators_fast
        from ...Infrastructure.Services.indicator_enrichment_service import compute_derived_for_candle

        try:
            # Convert history to DataFrame
            df = pd.DataFrame(history)
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            if len(df) < 50:
                return

            # Compute all indicators
            df = calculate_indicators_fast(df, verbose=False)

            # Rename indicator columns to DB-style names
            col_renames = {
                "MACD_12_26_9": "macd_line",
                "MACDs_12_26_9": "macd_signal",
                "MACDh_12_26_9": "macd_histogram",
                "BBL_20_2.0": "bb_lower",
                "BBM_20_2.0": "bb_middle",
                "BBU_20_2.0": "bb_upper",
                "BBB_20_2.0": "bb_bandwidth",
                "BBP_20_2.0": "bb_percent",
                "STOCHk_14_3_3": "stoch_k",
                "STOCHd_14_3_3": "stoch_d",
                "STOCHRSIk_14_14_3_3": "stochrsi_k",
                "STOCHRSId_14_14_3_3": "stochrsi_d",
                "DMP_14": "plus_di",
                "DMN_14": "minus_di",
                "ATRr_7": "atr_7",
                "ATRr_14": "atr_14",
                "NATR_14": "natr_14",
                "TRUERANGE_14": "true_range",
                "AROONU_14": "aroon_up",
                "AROOND_14": "aroon_down",
                "AROONOSC_14": "aroon_osc",
                "CCI_14": "cci_14",
                "WILLR_14": "willr_14",
                "ROC_10": "roc_10",
                "CMF_20": "cmf_20",
                "MFI_14": "mfi_14",
                "EMV_14": "emv_14",
                "VHF_28": "vhf_28",
                "FISHERT_9": "fisher",
                "FISHERTs_9": "fisher_signal",
                "MASSI_9_25": "massi",
                "SUPERTREND_DIR": "supertrend_direction",
            }
            df.columns = [c.lower() if c not in col_renames else c for c in df.columns]
            df.rename(columns={k: v for k, v in col_renames.items() if k in df.columns}, inplace=True)
            # Dedup after rename (keep last = computed values over any pre-existing)
            df = df.loc[:, ~df.columns.duplicated(keep='last')]

            # Get last row as candle_data dict (filter out NaN)
            last_row = df.iloc[-1]
            candle_data = {}
            for k, v in last_row.items():
                if v is None:
                    continue
                try:
                    if pd.isna(v):
                        continue
                except (TypeError, ValueError):
                    pass
                candle_data[k] = v

            # Add metadata
            candle_data["exchange"] = exchange
            candle_data["symbol"] = symbol
            candle_data["timeframe"] = timeframe

            # Compute derived indicators
            derived = compute_derived_for_candle(candle_data)
            candle_data.update(derived)

            current_price = candle_data.get("close", 0.0)
            if current_price <= 0:
                return

            regime = candle_data.get("regime", "unknown")

            # Evaluate each agent (lock protects shared state from concurrent candle tasks)
            async with self._lock:
                session = async_session_maker()
                try:
                    for agent_id in agent_ids:
                        try:
                            result = await self.evaluate_and_trade(
                                session=session,
                                agent_id=agent_id,
                                symbol=symbol,
                                current_price=current_price,
                                candle_data=candle_data,
                                regime=regime,
                            )

                            # Update last_evaluation timestamp
                            if agent_id in self.active_positions:
                                self.active_positions[agent_id]["last_evaluation"] = datetime.now(timezone.utc).isoformat()

                            if result:
                                logger.info(
                                    "[PaperTrade] %s %s/%s: %s @ %.2f",
                                    agent_id[:8], symbol, timeframe,
                                    result.get("action", "action"), current_price
                                )
                        except Exception as e:
                            logger.error("[PaperTrade] Error evaluating %s: %s", agent_id[:8], e)
                finally:
                    await session.close()

        except Exception as e:
            logger.error("[PaperTrade] Candle processing error for %s/%s: %s", symbol, timeframe, e)


# Singleton instance for use across the application
paper_trading_service = AgentPaperTradingService()
