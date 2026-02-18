# Fast_Swarm Architecture

**Framework**: FastAPI + PostgreSQL + Async SQLModel
**Purpose**: Control plane for evolutionary trading system
**Status**: Primary system (Cloudflare Workers is legacy)

---

## Philosophy

### Emergent Intelligence

> **"Alpha is emergent."** Instead of building one "perfect" predictor, we simulate an ecosystem of diverse, imperfect agents. Individually flawed, together they reveal high-probability market moves.

### Core Tenets

| Tenet | Description |
|-------|-------------|
| **Diversity > Optimization** | Over-optimizing leads to overfitting. We prioritize diverse strategies. |
| **Evolution over Design** | We code the rules of evolution, not winning strategies. The market is the fitness function. |
| **Signal from Noise** | Randomness is a feature. Window pools provide coverage, not determinism. |
| **Human-in-the-Loop** | 90% automation (lizard brain), 10% cognitive load (LLM/human for complexity). |

### The Goal

Create an **Antifragile** trading system that gets smarter as it encounters stress and volatility, rather than breaking.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLIENT (HTTP)                            │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     FASTAPI (Main.py)                            │
│                                                                  │
│  Lifespan Management:                                           │
│  - Database initialization                                       │
│  - Background loop startup                                       │
│  - WebSocket stream connections                                  │
└───────────────────────────────┬─────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌─────────────┐         ┌─────────────┐         ┌─────────────┐
│   ROUTERS   │         │  SERVICES   │         │   MODELS    │
│             │         │             │         │             │
│ agent_router│◄───────►│agent_service│◄───────►│   Agent     │
│pattern_router│◄───────►│pattern_svc │◄───────►│   Pattern   │
│ trade_router│◄───────►│trade_service│◄───────►│   Trade     │
│evolution_rtr│◄───────►│evolution_svc│◄───────►│   Cycle     │
│ system_rtr  │◄───────►│robustness   │         │             │
└─────────────┘         └──────┬──────┘         └─────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                  SQLMODEL / ASYNCPG                              │
│                                                                  │
│  Async session factory, connection pooling                       │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      POSTGRESQL                                  │
│                                                                  │
│  Tables: agents, patterns, backtest_trades_unified,             │
│          enhanced_candles, evolution_cycles, system_config       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Core Files

| File | Purpose |
|------|---------|
| `Main.py` | FastAPI app entry, lifespan, router registration |
| `Database.py` | Async PostgreSQL engine, session factory |
| `Dependencies.py` | Global singletons: StreamManager, DataCollector, RobustnessService |
| `Docker.py` | Auto-start PostgreSQL container |

---

## Domain Structure

Each domain follows `Models/ → Services/ → Routers/` pattern:

```
Fast_Swarm/
├── Main.py
├── Database.py
├── Dependencies.py
├── Docker.py
│
├── Agents/
│   ├── Models/
│   │   └── agent_models.py      # Agent SQLModel + Pydantic
│   ├── Services/
│   │   ├── agent_service.py     # High-level operations
│   │   ├── agent_crud.py        # Low-level DB ops
│   │   ├── spawn_service.py     # Agent creation
│   │   ├── cull_service.py      # Agent removal
│   │   ├── fitness_service.py   # Fitness calculation
│   │   ├── ranking_service.py   # Tier assignment
│   │   ├── backtest_service.py  # Run backtests
│   │   └── evolution_service.py # Evolution loop
│   ├── Routers/
│   │   ├── agent_router.py      # /agents endpoints
│   │   └── actions_router.py    # /actions endpoints
│   ├── Hivemind/                # Committee governance (partial)
│   └── Coaches/                 # Roster management
│
├── Patterns/
│   ├── Models/
│   ├── Services/
│   │   └── pattern_service.py   # Pattern discovery, backtest
│   └── Routers/
│
├── Trades/
│   ├── Models/
│   ├── Services/
│   └── Routers/
│
├── Infrastructure/
│   ├── Services/
│   │   ├── stream_manager_service.py  # WebSocket orchestration
│   │   ├── collector_service.py       # Data batching/writing
│   │   └── backfill_service.py        # Historical data gaps
│   └── Routers/
│
├── System/
│   ├── Services/
│   │   ├── robustness_service.py  # EDD, stress, data integrity
│   │   └── wisdom_service.py      # Crucible extraction
│   └── Routers/
│
├── exchanges/
│   ├── base_ws.py           # Abstract WebSocket client
│   ├── binance_ws.py        # Binance WebSocket
│   ├── coinbase_ws.py       # Coinbase WebSocket
│   ├── dydx_ws.py           # dYdX WebSocket
│   └── hyperliquid_ws.py    # Hyperliquid WebSocket
│
└── Tests/
    ├── Soundness/           # EDD tests (economic correctness)
    ├── Triage/              # Behavioral tests
    └── Router/              # API endpoint tests
```

---

## Background Loops

Started in `Main.py` lifespan:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database
    await init_db()

    # Start background loops
    asyncio.create_task(evolution_loop())           # Every 5 gen + cooldown
    asyncio.create_task(pattern_discovery_loop())   # Every 6 hours
    asyncio.create_task(pattern_backtest_loop())    # Every 10 minutes
    asyncio.create_task(window_pool_refresh_loop()) # Daily 3am

    # Start exchange streams
    await stream_manager.start(EXCHANGE_SYMBOLS)

    yield

    # Shutdown
    await stream_manager.stop()
    await data_collector.flush_all()
```

| Loop | Interval | Purpose |
|------|----------|---------|
| `evolution_loop()` | 5 gen + 2min cooldown | Evolve agent population |
| `pattern_discovery_loop()` | 6 hours | Chaos analysis pattern creation |
| `pattern_backtest_loop()` | 10 minutes | Test patterns on windows |
| `window_pool_refresh_loop()` | Daily 3am | Maintain window coverage |

---

## Database Schema

### Core Tables

| Table | Purpose |
|-------|---------|
| `agents` | Trading agents with JSONB traits |
| `patterns` | Trading patterns with conditions |
| `backtest_trades_unified` | All backtest trade records |
| `enhanced_candles` | OHLCV + pre-computed indicators |
| `evolution_cycles` | Evolution run tracking |
| `system_config` | Runtime configuration (JSONB) |

### Key Indexes

```sql
idx_agents_status_fitness    -- Fast agent queries
idx_agents_level             -- Filter by tier
idx_patterns_origin          -- Filter by discovery method
idx_patterns_tier            -- Filter by performance tier
idx_backtest_trades_agent    -- Trades by agent
idx_enhanced_candles_symbol  -- Candles by symbol/timeframe
```

### JSONB Usage

Flexible schema for traits and conditions:

```python
class Agent(SQLModel, table=True):
    traits: Dict[str, Any] = Field(default={}, sa_column=Column(JSONB))
    pattern_weights: Dict[str, float] = Field(default={}, sa_column=Column(JSONB))

class Pattern(SQLModel, table=True):
    conditions: Dict[str, Any] = Field(sa_column=Column(JSONB))
    fitness_by_regime: Dict[str, float] = Field(default={}, sa_column=Column(JSONB))
```

---

## Request Flow

```
1. HTTP Request arrives
       │
       ▼
2. FastAPI Router receives request
       │
       ▼
3. Dependency injection (get_session)
       │
       ▼
4. Router calls Service layer
       │
       ▼
5. Service executes business logic
       │
       ▼
6. Service uses SQLModel for DB operations
       │
       ▼
7. PostgreSQL returns data
       │
       ▼
8. Service returns Pydantic response model
       │
       ▼
9. FastAPI serializes to JSON
       │
       ▼
10. HTTP Response sent
```

---

## Exchange Integration

Four exchanges connected via WebSocket:

```
┌─────────────────────────────────────────────────────────────────┐
│                     StreamManager                                │
│              (stream_manager_service.py)                         │
│  Orchestrates all exchange connections                           │
├─────────────────────────────────────────────────────────────────┤
│                    Event Handlers                                │
│  on_trade()  │  on_kline()  │  on_order_book()                  │
└──────┬───────────────┬───────────────┬──────────────────────────┘
       │               │               │
       ▼               ▼               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    DataCollector                                 │
│               (collector_service.py)                             │
│  Batches and writes to database                                  │
└─────────────────────────────────────────────────────────────────┘
```

| Exchange | Status | Data Types |
|----------|--------|------------|
| Binance | ✅ Active | Klines, Trades |
| Coinbase | ✅ Active | Ticker, Trades |
| dYdX | ✅ Active | Perpetual trades |
| Hyperliquid | ✅ Active | Perpetual trades |

---

## Configuration

### Environment Variables

```bash
POSTGRES_USER=coinswarm
POSTGRES_PASSWORD=coinswarm_dev_2024
POSTGRES_DB=coinswarm
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

### Runtime Configuration

Stored in `system_config` table (JSONB):

```python
# Read config
config = await get_system_config(session)

# Update config
await set_system_config(session, {
    "evolution_enabled": True,
    "population_size": 500,
    "mutation_rate": 0.15
})
```

---

## API Routes

| Router | Prefix | Purpose |
|--------|--------|---------|
| `agent_router` | `/agents` | Agent CRUD and queries |
| `actions_router` | `/actions` | Spawn, backtest, cull |
| `evolution_router` | `/evolution` | Evolution control |
| `pattern_router` | `/patterns` | Pattern CRUD |
| `trade_router` | `/trades` | Trade history |
| `system_router` | `/system` | Health, robustness |
| `market_data_router` | `/market-data` | Candles, prices |
| `exchange_router` | `/exchanges` | Exchange state |

---

## Testing Strategy

### Test Categories

| Category | Location | Purpose |
|----------|----------|---------|
| **Soundness** | `Tests/Soundness/` | Economic correctness (EDD) |
| **Triage** | `Tests/Triage/` | Behavioral logic |
| **Router** | `Tests/Router/` | API endpoint tests |
| **Unit** | `Tests/` | Function-level tests |

### Running Tests

```bash
pytest Fast_Swarm/Tests/                    # All tests
pytest Fast_Swarm/Tests/Soundness/          # EDD tests
pytest Fast_Swarm/Tests/Triage/             # Behavioral tests
pytest Fast_Swarm/Tests/test_sanity.py -k test_name  # Specific
```

---

## What NOT to Do

Based on project requirements:

| Avoid | Reason |
|-------|--------|
| Train/test split | Pure backtesting, no ML training phases |
| Deterministic windows | Randomness is the point (signal from noise) |
| Sharpe as primary | Use Sortino (allows upside volatility) |
| Redis | PostgreSQL only |
| SQLite | PostgreSQL everywhere |

---

## Legacy Systems

See `docs/DEPRECATED.md` for historical reference:

- ❌ Cloudflare Workers architecture
- ❌ D1 database shards
- ❌ Redis memory system
- ❌ `local_agents/` directory (ported code)

---

## Lessons from Conductor (LLM Orchestration Spike)

A local LLM orchestration prototype (`conductor/`) was spiked using llama.cpp + Qwen3-Coder-Next. The design revealed patterns that map directly to Fast_Swarm gaps. These are the actionable takeaways.

### 1. Slot-Managed LLM Access

**Problem:** When agents hit `AI_REFLECT` zones during batch backtests, they all contend for one LLM endpoint with no queuing or priority. This creates an unmetered bottleneck.

**Solution:** Add a `SlotManager` to `llm_service.py` — a semaphore-based queue (3-5 concurrent slots) that assigns priority by agent tier (Tier 1 gets slots first) and tracks wait times as a metric. Prevents LLM saturation during batch backtests.

**Conductor reference:** `start-inference.sh` uses `-np 5` (5 parallel slots) with dedicated slot assignment per task type.

### 2. Prefix Cache Reuse

**Problem:** Every agent LLM call starts cold. But most share nearly identical system prompts (market context, role description, pattern conditions) — hundreds of redundant prompt-processing cycles.

**Solution:** Structure LLM prompts as shared prefix (system role + market regime) + variable suffix (agent traits + position). With Ollama's `keep_alive` this partially happens already. With vLLM or llama.cpp, explicit prefix caching gives 2-4x throughput on batch backtests.

**Conductor reference:** `--cache-reuse 256` reuses the first 256 tokens of common prefixes; `--slot-save-path ./kv-cache` persists KV state to disk.

### 3. Multi-Candidate Pattern Discovery (Ultra Think)

**Problem:** Pattern discovery asks the LLM once for one pattern, accepts it, and hopes it's good. No quality competition at the discovery stage.

**Solution:** During `pattern_discovery_loop`, generate 5 candidate patterns per cycle (parallel LLM calls or a single "give me 5 patterns" prompt). Quick-score each with a sanity backtest (1 asset, 5 windows). Keep only the top 1-2. Front-loads quality filtering before patterns enter the 10-minute backtest queue.

**Conductor reference:** Ultra Think generates N candidate responses, scores each independently, picks the best. Quality emerges from quantity + selection — the same principle that drives evolution itself.

### 4. Training Data Collection from Normal Operations

**Problem:** The Crucible captures agent snapshots and wisdom extraction is template-based. Neither formats data for model improvement. Every backtest generates LLM interaction data that's currently thrown away.

**Solution:** Log every LLM call during backtests as a training pair: `(market_context + agent_prompt) → (decision) → (outcome P&L)`. Store in a `training_pairs` table. Over time, this becomes a fine-tuning dataset — profitable decisions are positive examples, unprofitable ones are negative. The system teaches itself.

**Conductor reference:** `orchestrator/training/` directory designed to capture every input/output pair during normal use, building fine-tuning data automatically.

### 5. Validation Before Trust (LLM Preflight)

**Problem:** The evolution loop starts and assumes the LLM is available. If Ollama is down, agents silently fall back to heuristic mode without logging the degradation.

**Solution:** Add `llm_preflight()` to `Main.py` lifespan startup — ping the LLM, measure latency, log the actual AI mode. If unavailable, log it loudly rather than silently degrading. The robustness service should also periodically validate LLM health.

**Conductor reference:** `validate-engine.sh` runs a hello-world completion, checks `/health`, and measures baseline tok/s before any real work starts.

### 6. Review Gate for Pattern Quality

**Problem:** Discovered patterns enter the backtest queue immediately with no sanity check. Patterns with obvious issues (contradictory conditions, degenerate thresholds) waste 10-minute backtest cycles before being filtered out.

**Solution:** Add a lightweight review step after discovery: before a pattern enters the queue, check for basic sanity (buy != exit conditions, indicators not contradictory, thresholds within normal ranges). Either rule-based or a quick LLM pass. Reject obvious junk before it consumes backtest resources.

**Conductor reference:** Plan → Code → Review — the reviewer can reject work and trigger a redo, preventing garbage from propagating downstream.

### 7. Resource-Aware Loop Scheduling

**Problem:** Background loops run on fixed timers regardless of system load. Pattern backtest every 10 minutes + evolution cycle + discovery can all peak simultaneously.

**Solution:** Check `_active_evolution_run` before starting pattern backtests — if evolution is mid-cycle, reduce batch size or skip. Coordinate loops so they don't compete for compute at the same time.

**Conductor reference:** Q8_0 cache quantization, MoE offloading, tuned batch sizes — every parameter chosen to maximize throughput within hardware limits. Resource awareness is a first-class concern, not an afterthought.

### Priority Implementation Order

| Priority | Lesson | Impact | Effort |
|----------|--------|--------|--------|
| 1 | Slot-managed LLM access | High — unblocks batch backtests | Low |
| 2 | Multi-candidate pattern discovery | High — better pattern quality | Medium |
| 3 | Training pair collection | High — compounding improvement | Medium |
| 4 | LLM preflight validation | Medium — visibility | Low |
| 5 | Resource-aware scheduling | Medium — stability | Low |
| 6 | Prefix cache reuse | Medium — throughput | Medium |
| 7 | Pattern review gate | Medium — less waste | Low |

---

*Last Updated: 2026-02-18*
