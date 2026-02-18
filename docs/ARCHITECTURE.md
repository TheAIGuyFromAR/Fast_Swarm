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

## Lessons from Prior Architecture (Coinswarm-1 Orchestration Plans)

Two documents from the Cloudflare Workers era (`master-orchestration-plan.md` and `autonomous-swarm-orchestration-plan.md`) contain designs that were never fully implemented. Many map directly to current Fast_Swarm gaps. These are the actionable takeaways, organized by source.

### From the Master Orchestration Plan (Feature Ideas)

The 47-task, 5-wave plan designed features for the evolution system. Several were implemented during the port to FastAPI. These were not:

#### 1. Alpha Decay Detection

**What it was:** Track `rolling_30d_roi / lifetime_roi` ratio per pattern. Status: healthy (>0.7), degrading (>0.5), decayed (<0.5).

**Why it matters now:** Patterns can lose their edge as market structure changes. Fast_Swarm currently promotes patterns by fitness score but never detects when a once-good pattern has gone stale. Stale Tier 1 patterns consume backtest resources and get assigned to agents that then underperform.

**Implementation:** Add `last_30d_fitness` and `decay_ratio` columns to patterns table. Check during `pattern_backtest_loop`. Demote decayed patterns from Tier 1 → Tier 3 for re-evaluation instead of letting them sit indefinitely.

#### 2. Agent Correlation Matrix

**What it was:** Pearson correlation of daily returns between top agents. Prevent correlated agents from dominating the population.

**Why it matters now:** Fast_Swarm checks `_are_same_lineage()` during crossbreeding to prevent inbreeding, but lineage is a proxy for correlation — it doesn't catch unrelated agents that converged on the same strategy. Two agents from different lineages can still be 0.95 correlated if they both learned the same pattern.

**Implementation:** After evolution cycles, calculate return correlation for top 50 agents. Add correlation penalty to fitness: if an agent is >0.8 correlated with a higher-fitness agent, reduce its spawn eligibility. This preserves diversity without the blunt instrument of random culling.

#### 3. Diversity Metrics

**What it was:** Personality entropy, pattern usage Gini coefficient, trait variance across population.

**Why it matters now:** Fast_Swarm's "Diversity > Optimization" tenet has no measurement. We say we value diversity but don't track it. A population could silently converge to a monoculture and we'd only notice when a regime change wipes everyone out.

**Implementation:** Add a `diversity_check()` call at the end of each evolution cycle. Track: (a) trait variance across population, (b) pattern assignment concentration (Gini), (c) number of distinct lineage roots. Alert if any metric drops below threshold. Consider a diversity bonus in fitness scoring.

#### 4. Circuit Breakers

**What it was:** Portfolio-level (20% daily loss), single-position (15% loss), exchange API failure handling, consensus timeout behavior.

**Why it matters now:** Fast_Swarm has no circuit breakers at all. When live trading is eventually implemented, there's no safety net. But even for backtesting, circuit breaker logic should be part of the backtest simulation — agents that would have been stopped out in production should be stopped out in testing too.

**Implementation:** Add circuit breaker evaluation to `backtest_service.py`. Track cumulative daily drawdown during simulated trading. If an agent hits 20% daily loss, halt its trading for that simulated day. This makes backtest results more realistic and penalizes agents with catastrophic loss profiles.

#### 5. Token Specialization Tracking

**What it was:** Per-asset, per-timeframe performance breakdown for each agent. Schema: `agent_token_performance` table with regime-tagged results.

**Why it matters now:** Fast_Swarm tracks `fitness_by_regime` (bull/bear/chop/flat) but not per-asset. An agent might be excellent at BTC and terrible at ETH, but the aggregate fitness hides this. When Hivemind votes on a specific asset, it should weight agents by their performance *on that asset*, not their overall fitness.

**Implementation:** Add per-asset fitness tracking to backtest results. Use it in Hivemind governance: when voting on BTC direction, weight by BTC-specific fitness rather than aggregate fitness. This makes committee decisions more precise.

#### 6. Wave-Based Parallel Execution

**What it was:** 5 waves of parallel work, each wave waiting for the previous to complete before starting. Dependency-aware task scheduling.

**Why it matters now:** Fast_Swarm's background loops are independent timers with no coordination. `evolution_loop()`, `pattern_discovery_loop()`, and `pattern_backtest_loop()` can all fire simultaneously, competing for database connections and LLM access.

**Implementation:** Introduce loop phases: (1) Pattern Discovery produces candidates, (2) Pattern Backtest evaluates them, (3) Evolution uses the evaluated patterns. Use `asyncio.Event` signals between loops so discovery → backtest → evolution flows as a pipeline rather than racing.

### From the Autonomous Swarm Orchestration Plan (Architectural Patterns)

The 21-agent autonomous development swarm had architectural patterns for multi-agent coordination that map directly to Hivemind committee governance.

#### 7. 2/3 Majority Voting with Veto

**What it was:** Code review required 2/3 majority (2 of 3 reviewers approve). Auditor had veto power over the whole process.

**Why it matters now:** Hivemind governance uses ELO-weighted aggregation, which is good, but has no concept of quorum *quality*. If 10 low-ELO agents vote and 2 high-ELO agents abstain, the decision proceeds on weak signal. The original plan's majority + veto model adds a quality floor.

**Implementation:** Add a `min_elite_votes` threshold to Hivemind decisions. Require at least N Tier 1 agents in the voting pool before a decision is valid. If a single agent has ELO > 2200 (top performer), give it veto power — it can block a decision if its confidence in the opposing direction is > 0.9.

#### 8. Checkpoint and Recovery System

**What it was:** Save full system state every 30 minutes. On crash, load last checkpoint and resume. Git commit at each checkpoint.

**Why it matters now:** Fast_Swarm's evolution loop resets `_active_evolution_run` flag on startup to prevent stuck states, but doesn't save progress. If the server crashes mid-evolution (after select + clone but before crossbreed), cloned agents exist without crossbreed partners. The system restarts but doesn't know where in the cycle it stopped.

**Implementation:** At the start of each evolution phase (select, clone, crossbreed, cull), write the phase name + agent IDs to a `evolution_checkpoint` row in `system_config`. On recovery, check if a checkpoint exists and resume from that phase instead of starting over. This prevents duplicate clones and orphaned agents.

#### 9. File-Based Message Bus / Escalation Path

**What it was:** Agents communicate via `.state/messages/inbox/{agent}.jsonl`. When blocked > 30 minutes, write to `human-todo.md` for human attention.

**Why it matters now:** Fast_Swarm's background loops log errors but have no structured escalation. If `pattern_discovery_loop` fails 10 times in a row (e.g., LLM is down), it just keeps retrying silently every 6 hours. Nobody notices until they check logs.

**Implementation:** Add a `failure_counter` to each background loop. After N consecutive failures, write a structured alert to a `system_alerts` table with severity, loop name, last error, and timestamp. Surface these on the dashboard (WIP). This is the "human-todo.md" concept adapted for FastAPI — the system asks for help when it can't self-heal.

#### 10. Supervisory Layers (Build → Review → Audit)

**What it was:** Build agents do work, supervisors validate it, reviewers check quality, auditor gives final approval. Four distinct layers before anything ships.

**Why it matters now:** Fast_Swarm's pattern pipeline is: discover → queue → backtest → promote. There's no review step between discovery and queue, and no audit step between backtest and promote. Patterns with obvious economic nonsense (entry condition = exit condition, threshold of 0.0) waste backtest cycles.

**Implementation:** Add two gates:
- **Post-discovery review:** Before queuing, check pattern sanity (entry != exit, thresholds within normal indicator ranges, no contradictory conditions). Rule-based, no LLM needed. Reject obvious junk.
- **Post-backtest audit:** Before promoting from Tier 3 → Tier 2, verify the pattern's win distribution isn't degenerate (e.g., one giant win masking many small losses). Check that positive fitness isn't from a single lucky window.

### From the Conductor Spike (LLM Infrastructure)

A local LLM orchestration prototype (`conductor/`) using llama.cpp + Qwen3-Coder-Next revealed additional LLM-specific patterns.

#### 11. Slot-Managed LLM Access

**Problem:** When agents hit `AI_REFLECT` zones during batch backtests, they all contend for one LLM endpoint with no queuing or priority.

**Solution:** Add a `SlotManager` to `llm_service.py` — a semaphore-based queue (3-5 concurrent slots) that assigns priority by agent tier. Track wait times as a metric.

#### 12. Training Data Collection from Normal Operations

**Problem:** Every backtest LLM call generates a training pair (prompt + decision + outcome P&L) that's currently thrown away.

**Solution:** Log these to a `training_pairs` table. Over time, this becomes a fine-tuning dataset — profitable decisions are positive examples, unprofitable ones negative. The system teaches itself.

#### 13. LLM Preflight Validation

**Problem:** If Ollama is down, agents silently fall back to heuristic mode without logging the degradation.

**Solution:** Add `llm_preflight()` to `Main.py` lifespan startup — ping the LLM, measure latency, log the actual AI mode. Log loudly rather than silently degrading.

### Priority Implementation Order

| Priority | Lesson | Source | Impact | Effort |
|----------|--------|--------|--------|--------|
| 1 | Alpha decay detection | Master Plan | High — stops stale patterns | Low |
| 2 | Agent correlation matrix | Master Plan | High — preserves diversity | Medium |
| 3 | Checkpoint and recovery | Swarm Plan | High — prevents data corruption | Medium |
| 4 | Circuit breakers in backtest | Master Plan | High — realistic simulation | Medium |
| 5 | Diversity metrics | Master Plan | Medium — measures core tenet | Low |
| 6 | Post-discovery pattern review | Swarm Plan | Medium — less backtest waste | Low |
| 7 | Slot-managed LLM access | Conductor | Medium — unblocks batch runs | Low |
| 8 | Structured failure escalation | Swarm Plan | Medium — visibility | Low |
| 9 | Training pair collection | Conductor | Medium — compounding gains | Medium |
| 10 | Token specialization | Master Plan | Medium — better Hivemind votes | Medium |
| 11 | Loop phase coordination | Master Plan | Low — stability | Medium |
| 12 | Hivemind majority + veto | Swarm Plan | Low — better governance | Low |
| 13 | LLM preflight validation | Conductor | Low — visibility | Low |

---

*Last Updated: 2026-02-18*
