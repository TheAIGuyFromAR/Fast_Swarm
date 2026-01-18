# Windows + psycopg3 fix: must use SelectorEventLoop, not ProactorEventLoop
import sys

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# =============================================================================
# OpenTelemetry Tracing Setup
# =============================================================================
# Set OTEL_ENABLED=1 to enable tracing, OTEL_EXPORTER=jaeger for Jaeger export
OTEL_ENABLED = os.getenv("OTEL_ENABLED", "0") == "1"

if OTEL_ENABLED:
    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

        # Create tracer provider with service name
        resource = Resource.create({"service.name": "fast-swarm"})
        provider = TracerProvider(resource=resource)

        # Choose exporter based on env var
        if os.getenv("OTEL_EXPORTER") == "jaeger":
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                exporter = OTLPSpanExporter(endpoint=os.getenv("OTEL_ENDPOINT", "localhost:4317"))
                print("[OTel] Using OTLP/Jaeger exporter")
            except ImportError:
                exporter = ConsoleSpanExporter()
                print("[OTel] Jaeger exporter not installed, falling back to console")
        else:
            exporter = ConsoleSpanExporter()
            print("[OTel] Using console exporter (set OTEL_EXPORTER=jaeger for Jaeger)")

        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        OTEL_TRACER = trace.get_tracer("fast-swarm")
        print("[OTel] Tracing enabled")
    except ImportError as e:
        print(f"[OTel] OpenTelemetry not installed: {e}")
        print("[OTel] Install with: pip install opentelemetry-api opentelemetry-sdk opentelemetry-instrumentation-fastapi")
        OTEL_ENABLED = False
        OTEL_TRACER = None
else:
    OTEL_TRACER = None

from Fast_Swarm.Agents.Hivemind.Routers import governance_router
from Fast_Swarm.Agents.Routers import actions_router, evolution_router

# Import Domain Routers
from Fast_Swarm.Agents.Routers import agent_router as agents_router
from Fast_Swarm.Agents.Services.evolution_service import reset_evolution_flag
from Fast_Swarm.Database import init_db
from Fast_Swarm.Dependencies import data_collector, robustness_service, stream_manager
from Fast_Swarm.Docker import ensure_database
from Fast_Swarm.Evolution.Routers import evolution_router as evolution_monitor_router
from Fast_Swarm.Infrastructure.Routers import exchange_router as exchanges_router
from Fast_Swarm.Infrastructure.Routers import market_data_router, sentiment_router
from Fast_Swarm.Infrastructure.Services.backfill_service import startup_backfill

# Window pool for backtest - pre-generated at startup, refreshed daily
from Fast_Swarm.local_agents.backtest.windows import initialize as init_window_pool
from Fast_Swarm.local_agents.backtest.windows import refresh_and_extend as refresh_window_pool
from Fast_Swarm.Patterns.Routers import pattern_router as patterns_router
from Fast_Swarm.System.Routers import system_router
from Fast_Swarm.System.Services.orchestrator import get_orchestrator
from Fast_Swarm.Tests.Router import router as test_runner_router
from Fast_Swarm.Trades.Routers import trade_router as trades_router

# =============================================================================
# REMOVED: Separate concurrent loops (evolution_loop, pattern_discovery_loop,
# pattern_backtest_loop) - these caused resource contention.
#
# REPLACED WITH: BacktestOrchestrator - runs phases sequentially:
# 1. Load windows ONCE from pool
# 2. Test batch of patterns on those windows
# 3. Test batch of agents on those SAME windows (reusing preloaded data)
# 4. Run evolution cycle
# 5. Run pattern discovery
# 6. Cooldown, then repeat
#
# P0 (Data Collection) runs independently - never blocked by P2 operations.
# =============================================================================


async def window_pool_refresh_loop():
    """
    Background loop to refresh window pool daily at 3am.

    Checks coverage thresholds and generates new windows only for
    pairs that fall below targets (e.g., when new data is added).
    """
    from datetime import datetime
    from datetime import time as dt_time

    # Wait for initial setup
    await asyncio.sleep(300)  # 5 minutes

    while True:
        try:
            now = datetime.now()
            # Calculate seconds until 3am
            target = datetime.combine(now.date(), dt_time(3, 0))
            if now >= target:
                # Already past 3am today, wait until tomorrow
                target = datetime.combine(now.date() + timedelta(days=1), dt_time(3, 0))

            wait_seconds = (target - now).total_seconds()
            print(f"[Window Pool] Next refresh at 3am ({wait_seconds / 3600:.1f} hours)")
            await asyncio.sleep(wait_seconds)

            # Refresh window pool
            print("[Window Pool] Starting daily refresh...")
            result = await refresh_window_pool()
            print(
                f"[Window Pool] Refresh complete: {result.get('status')}, "
                f"+{result.get('windows_added', 0)} windows, "
                f"pool size: {result.get('pool_size', 0)}"
            )

        except Exception as e:
            print(f"[Window Pool] Error: {e}")
            await asyncio.sleep(3600)  # Retry in 1 hour


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 0. Ensure Docker and PostgreSQL are running
    print("Starting up CoinSwarm FastAPI...")
    await ensure_database()

    # 1. Startup: Initialize Database
    await init_db()

    # 1.1. Reset evolution global flag (prevents stuck flag after crash)
    reset_evolution_flag()
    print("[Startup] Evolution flag reset (prevents stuck flag after crash)")

    # 1.5. Initialize window pool for backtesting (queries DB for data ranges)
    try:
        await init_window_pool(seed=42)
    except Exception as e:
        print(f"[Startup] WARNING: Window pool init failed: {e}")
        print("[Startup] Backtests will fail until window pool is initialized")

    # 2. Configure symbols
    symbols = {"binance": ["BTCUSDT", "ETHUSDT", "SOLUSDT"], "coinbase": ["BTC-USD", "ETH-USD"]}

    # 3. Start Data Collection
    # Link events to collector
    stream_manager.on_trade(data_collector.handle_live_trade)
    stream_manager.on_kline(data_collector.handle_live_kline)
    stream_manager.on_order_book(data_collector.handle_order_book)

    # First: Live Stream
    await stream_manager.start(symbols)

    # Second: Health Check & Backfill
    await data_collector.verify_and_backfill(symbols)

    # Third: Start historical OHLCV backfill in background
    # This fills gaps in BTC/ETH/SOL data for backtesting
    asyncio.create_task(startup_backfill())

    # 4. Robustness Chaos Loop (disabled - runs random EDD tests periodically)
    # robustness_service.register_test(data_collector._flush_batches)
    # robustness_service.register_test(robustness_service.validate_economic_assumptions)
    # asyncio.create_task(robustness_service.start_chaos_loop())

    # 5. Start Backtest Orchestrator (P2 - sequential pipeline)
    # This replaces the old concurrent loops (evolution_loop, pattern_discovery_loop,
    # pattern_backtest_loop) which caused resource contention.
    #
    # Priority System:
    # - P0: Data collection (above) - runs independently, never blocked
    # - P1: Live trades - not implemented yet
    # - P2: Backtesting/Evolution - handled by orchestrator sequentially
    print("[Startup] Starting backtest orchestrator (P2 sequential pipeline)...")
    orchestrator = get_orchestrator()
    await orchestrator.start()

    # 6. Start Window Pool Refresh Loop (daily at 3am, low impact)
    print("[Startup] Starting window pool refresh loop...")
    asyncio.create_task(window_pool_refresh_loop())

    yield

    # Shutdown logic
    print("Shutting down...")

    # Stop orchestrator first (graceful shutdown of P2 operations)
    await orchestrator.stop()

    await stream_manager.stop()
    await data_collector.flush_all()  # Flush all pending data
    await robustness_service.stop()


app = FastAPI(
    title="CoinSwarm FastAPI",
    description="FastAPI wrapper for Coinswarm trading system",
    version="1.0.0",
    lifespan=lifespan,
    redirect_slashes=False,  # Don't redirect /patterns to /patterns/ (breaks dashboard fetch)
)

# Instrument FastAPI with OpenTelemetry (must be after app creation)
if OTEL_ENABLED:
    try:
        FastAPIInstrumentor.instrument_app(app)
        print("[OTel] FastAPI instrumentation active")
    except Exception as e:
        print(f"[OTel] FastAPI instrumentation failed: {e}")

# Add CORS middleware for dashboard access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(agents_router.router)
app.include_router(evolution_router.router)
app.include_router(actions_router.router)
app.include_router(patterns_router.router)
app.include_router(trades_router.router)
app.include_router(evolution_monitor_router.router)
app.include_router(governance_router.router)
app.include_router(market_data_router.router)
app.include_router(exchanges_router.router)
app.include_router(sentiment_router.router)
app.include_router(system_router.router)
app.include_router(test_runner_router.router)

# Mount static files for dashboard
DASHBOARD_DIR = Path(__file__).parent / "Dashboard"
app.mount("/dashboard/css", StaticFiles(directory=DASHBOARD_DIR / "css"), name="css")
app.mount("/dashboard/js", StaticFiles(directory=DASHBOARD_DIR / "js"), name="js")


@app.get("/", tags=["System"])
async def root():
    return {"message": "CoinSwarm API is running", "status": "active"}


@app.get("/dashboard", tags=["Dashboard"])
async def dashboard():
    """Serve the main dashboard."""
    return FileResponse(DASHBOARD_DIR / "index.html")


@app.get("/dashboard/", tags=["Dashboard"])
async def dashboard_slash():
    """Serve the main dashboard (with trailing slash)."""
    return FileResponse(DASHBOARD_DIR / "index.html")


@app.get("/dashboard/evolution", tags=["Dashboard"])
async def evolution_dashboard():
    """Serve the evolution progress dashboard."""
    return FileResponse(DASHBOARD_DIR / "evolution.html")
