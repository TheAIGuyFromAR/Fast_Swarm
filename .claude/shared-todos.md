# Shared Todo List

All non-trivial todos from Claude sessions are logged here.

---

## Active Todos

### PostgreSQL Migration for live_collector.py (Current Priority)
- [x] Update live_collector.py imports to use PostgreSQL store
- [x] Add extended data tables schema to postgres_store.py
- [x] Add extended data classes (MarkPrice, LargeTrade, etc.) to postgres_store.py
- [x] Add ExtendedDataStorePostgres class with insert methods
- [ ] Update LiveCollector.__init__ to not pass db_path to PostgreSQL store
- [ ] Update LiveCollector to use ExtendedDataStorePostgres instead of SQLite extended store
- [ ] Remove --db argument from live_collector.py CLI (not needed for PostgreSQL)
- [ ] Verify PostgreSQL connection works with POSTGRES_PASSWORD env var
- [ ] Kill old collector processes still using SQLite
- [ ] Start live_collector.py with PostgreSQL backend
- [ ] Verify data is flowing into PostgreSQL tables

### Multi-Brokerage + Dashboard + Decision Feed (Current)
- [x] Create llm_logger.py with LLMResponseRecord dataclass and log_llm_response function
- [x] Add log_llm_response calls to _decide_with_llm (SUCCESS + PARSE FAIL)
- [x] Add log_llm_response calls to _decide_with_llm_async (SUCCESS + PARSE FAIL)
- [x] Configure llm_responses logger with FileHandler in Main.py lifespan
- [x] Fix pattern stats: add sortino_ratio to PatternSummary model
- [x] Fix pattern stats: update leaderboard response mapping in pattern_router.py
- [x] Fix pattern stats: update renderPatternsTable() in app.js to handle nulls
- [x] Fix trading buttons: add error handling and empty-state to populateAgentDropdown()
- [x] Add CULL WEAK + DISCOVER buttons to pattern page in index.html
- [x] Add SPAWN + CULL + EVOLVE buttons to agent page in index.html
- [x] Add cullWeakPatterns() + triggerPatternDiscovery() JS functions
- [x] Add spawnAgents() + cullAgents() + runEvolution() JS functions
- [x] Add POST /patterns/cull endpoint in pattern_router.py
- [x] Create decision_feed_service.py with DecisionEvent + DecisionFeedService
- [x] Add SSE /decisions/feed endpoint to trading_router.py
- [x] Add GET /decisions/recent endpoint to trading_router.py
- [ ] Emit DecisionEvent from paper_trading_service after zone decision
- [ ] Emit DecisionEvent from paper_trading_service after LLM result
- [ ] Add decision feed HTML panel to trading page in index.html
- [ ] Add connectDecisionFeed() + appendDecisionEvent() JS functions
- [ ] Add approveDecision() + rejectDecision() JS functions
- [ ] Add decision feed CSS styling to cyberpunk.css
- [x] Add asyncio.sleep(0.01) yield in pattern backtest loop
- [x] Add AssetClass + AccountType enums to portfolio_agent_service.py
- [x] Add is_market_open() + classify_asset() to ExchangeClient ABC
- [x] Create exchanges/assets.py with BITCOIN_ECOSYSTEM, EXCHANGE_FEES, MARKET_HOURS
- [x] Create exchanges/alpaca_client.py implementing ExchangeClient ABC
- [x] Create exchanges/alpaca_portfolio_agent.py with notional orders + market clock
- [x] Create exchanges/ibkr_client.py implementing ExchangeClient ABC
- [x] Create exchanges/ibkr_portfolio_agent.py with IRA constraints + contract details
- [x] Create exchanges/cryptocom_portfolio_agent.py wrapping existing REST client
- [ ] Add PortfolioState.total_equity and agent_allocations for balance pot
- [ ] Add balance pot display to dashboard trading panel
- [ ] Install alpaca-py and ib_insync dependencies

### Deep Trace (Deferred)
- [x] Fix remaining test_crucible.py failures (CrucibleEntry signature, pattern storage tests)
- [x] Test Deep Trace failures: HAS_LOCAL_BACKTEST=False, empty entry_conditions, missing indicators
- [x] Test agent_state.py: EpisodicMemory S-curve, SemanticMemory aggregation, WisdomMemory triggers
- [x] Property tests: trait bounds [0,1], fitness bounds [0,100], no NaN/Infinity propagation
- [x] Deep trace: Pattern creation branches (chaos, affinity, discovery, ML)
- [x] Deep trace: Backtest error paths and edge cases
- [x] Deep trace: Agent lifecycle (spawn, mutate, die, resurrect)
- [x] Deep trace: Pattern loading and caching paths
- [x] Deep trace: Pattern matching condition evaluation
- [x] Deep trace: Agent-pattern assignment mechanisms
- [x] Deep trace: Database read/write for patterns
- [x] Deep trace: Database read/write for agents
- [x] Deep trace: Exchange execution linked to patterns
- [ ] Deep trace: All imports and dependencies
- [ ] Deep trace: exchange_selector.py routing algorithm (discovered in exchange trace)
- [ ] Deep trace: position_manager.py position tracking (discovered in exchange trace)
- [ ] Deep trace: risk_manager.py circuit breakers (discovered in exchange trace)
- [ ] Deep trace: indicators_extra JSONB flow (discovered in pattern matching)
- [ ] Deep trace: _get_indicator_fuzzy fallback chains
- [ ] Deep trace: walk_forward pattern simulation paths
- [ ] Deep trace: Committee.evaluate_pattern live trading flow
- [ ] Deep trace: genesis_spawn_agent external module flow
- [ ] Deep trace: Agent.from_dict() deserialization paths
- [ ] Deep trace: Coach roster assignment to committees
- [ ] Deep trace: Pattern crossover/inheritance during reproduction
- [ ] Deep trace: backtest_results table lifecycle (discovered in pattern DB trace)
- [ ] Deep trace: exit_strategy column migrations (discovered in pattern DB trace)
- [ ] Deep trace: LRU cache for candle data (discovered in pattern DB trace)
- [ ] Deep trace: coach_rosters table lifecycle (discovered in agent DB trace)
- [ ] Deep trace: agent_vote_accuracy table (discovered in agent DB trace)
- [ ] Deep trace: paper_trades table lifecycle (discovered in agent DB trace)
- [ ] Compile comprehensive code path map

## Completed

| Task | Session | Completed |
|------|---------|-----------|
| Fix test_crucible.py failures | Master Test Admin | 2026-01-02 |
| Test Deep Trace failures | Master Test Admin | 2026-01-02 |
| Test agent_state.py memory system | Master Test Admin | 2026-01-02 |
| Property tests (bounds, NaN/Inf) | Master Test Admin | 2026-01-02 |
