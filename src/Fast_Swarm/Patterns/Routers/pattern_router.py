from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import asc, desc, select
from sqlmodel.ext.asyncio.session import AsyncSession

from ...Database import get_session
from ..Models.pattern_models import (
    Pattern,
    PatternFitnessByRegimeResponse,
    PatternLeaderboardResponse,
    PatternsByOriginResponse,
    PatternsByTierResponse,
    PatternSummary,
    RegimePatternSummary,
    TopPatternsByRegimeResponse,
)
from ..Services import pattern_service

router = APIRouter(prefix="/patterns", tags=["Patterns"])

# Valid sort columns for leaderboard
SORT_COLUMNS = {
    "fitness_score": Pattern.fitness_score,
    "total_roi_pct": Pattern.total_roi_pct,
    "sharpe_ratio": Pattern.sharpe_ratio,
    "win_rate": Pattern.win_rate,
    "profit_factor": Pattern.profit_factor,
    "max_drawdown_pct": Pattern.max_drawdown_pct,
    "total_trades": Pattern.total_trades,
    "total_runs": Pattern.total_runs,
    "created_at": Pattern.created_at,
    "last_backtest_at": Pattern.last_backtest_at,
}


@router.get("/leaderboard", response_model=PatternLeaderboardResponse)
async def get_pattern_leaderboard(
    sort_by: str = Query("fitness_score", description="Column to sort by"),
    order: Literal["asc", "desc"] = Query("desc", description="Sort order"),
    origin: str | None = Query(None, description="Filter by origin (chaos/academic/technical/ai/hybrid)"),
    min_trades: int = Query(0, description="Minimum number of trades"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> PatternLeaderboardResponse:
    """
    Pattern leaderboard with sortable stats.

    Sortable columns: fitness_score, total_roi_pct, sharpe_ratio, win_rate,
    profit_factor, max_drawdown_pct, total_trades, total_runs, created_at, last_backtest_at
    """
    if sort_by not in SORT_COLUMNS:
        raise HTTPException(status_code=400, detail=f"Invalid sort_by. Must be one of: {list(SORT_COLUMNS.keys())}")

    column = SORT_COLUMNS[sort_by]
    order_func = desc if order == "desc" else asc

    statement = select(Pattern).where(Pattern.status != "archived")

    if origin:
        statement = statement.where(Pattern.origin == origin)

    if min_trades > 0:
        statement = statement.where(Pattern.total_trades >= min_trades)

    statement = statement.order_by(order_func(column).nulls_last())
    statement = statement.offset(offset).limit(limit)

    result = await session.execute(statement)
    patterns = result.scalars().all()

    return PatternLeaderboardResponse(
        count=len(patterns),
        sort_by=sort_by,
        order=order,
        patterns=[
            PatternSummary(
                pattern_id=p.pattern_id,
                name=p.name,
                origin=p.origin,
                status=p.status,
                fitness_score=float(p.fitness_score) if p.fitness_score else None,
                total_roi_pct=float(p.total_roi_pct) if p.total_roi_pct else None,
                sharpe_ratio=p.sharpe_ratio,
                sortino_ratio=p.sortino_ratio,
                win_rate=p.win_rate,
                profit_factor=p.profit_factor,
                max_drawdown_pct=p.max_drawdown_pct,
                total_trades=p.total_trades,
                total_runs=p.total_runs,
                symbol=p.symbol,
                timeframe=p.timeframe,
                last_backtest_at=p.last_backtest_at.isoformat() if p.last_backtest_at else None,
                created_at=p.created_at.isoformat() if p.created_at else None,
            )
            for p in patterns
        ],
    )


@router.get("", response_model=list[Pattern])
async def read_patterns(skip: int = 0, limit: int = 100, session: AsyncSession = Depends(get_session)):
    """
    Get all patterns, ordered by fitness score.
    """
    return await pattern_service.get_all_patterns(session, limit=limit, offset=skip)


@router.get("/stats/average")
async def get_average_pattern_stats(session: AsyncSession = Depends(get_session)):
    """
    Get average statistics for all active patterns.
    """
    from ..Services import pattern_stats_service

    return await pattern_stats_service.get_pattern_average_stats(session)


@router.get("/by-tier/{tier}", response_model=PatternsByTierResponse)
async def get_patterns_by_tier(
    tier: int, limit: int = Query(100, ge=1, le=500), session: AsyncSession = Depends(get_session)
) -> PatternsByTierResponse:
    """
    Get patterns by tier (1=Elite 80+, 2=Proven 60-79, 3=Untested <60).
    """
    if tier not in [1, 2, 3]:
        raise HTTPException(status_code=400, detail="Tier must be 1, 2, or 3")
    patterns = await pattern_service.get_patterns_by_tier(session, tier, limit)
    return PatternsByTierResponse(tier=tier, count=len(patterns), patterns=patterns)


@router.get("/by-origin/{origin}", response_model=PatternsByOriginResponse)
async def get_patterns_by_origin(
    origin: str, limit: int = Query(100, ge=1, le=500), session: AsyncSession = Depends(get_session)
) -> PatternsByOriginResponse:
    """
    Get patterns by origin (chaos/academic/technical/ai/hybrid).
    """
    patterns = await pattern_service.get_patterns_by_origin(session, origin, limit)
    return PatternsByOriginResponse(origin=origin, count=len(patterns), patterns=patterns)


@router.get("/top-by-regime/{regime}", response_model=TopPatternsByRegimeResponse)
async def get_top_patterns_by_regime(
    regime: str, limit: int = Query(20, ge=1, le=100), session: AsyncSession = Depends(get_session)
) -> TopPatternsByRegimeResponse:
    """
    Get top performing patterns for a specific regime.

    Supported regimes:
    - Canonical: crash, bull, bear, sideways, blowoff, recovery, volatile, winter, transition
    - Random windows: random_1m, random_5m, random_15m, random_1h, random_4h, random_1d

    Returns patterns sorted by fitness in that regime.
    """
    from sqlalchemy import text

    result = await session.execute(
        text("""
            SELECT pattern_id, name, origin, status, fitness_score,
                   fitness_by_regime->:regime->>'fitness' as regime_fitness,
                   fitness_by_regime->:regime->>'trades' as regime_trades,
                   fitness_by_regime->:regime->>'win_rate' as regime_win_rate,
                   fitness_by_regime->:regime->>'sharpe' as regime_sharpe
            FROM patterns
            WHERE status != 'archived'
              AND fitness_by_regime ? :regime
              AND (fitness_by_regime->:regime->>'fitness')::float > 0
            ORDER BY (fitness_by_regime->:regime->>'fitness')::float DESC
            LIMIT :limit
        """),
        {"regime": regime, "limit": limit},
    )
    rows = result.fetchall()

    if not rows:
        return TopPatternsByRegimeResponse(
            regime=regime, patterns=[], message=f"No patterns with fitness data for regime '{regime}'"
        )

    return TopPatternsByRegimeResponse(
        regime=regime,
        count=len(rows),
        patterns=[
            RegimePatternSummary(
                pattern_id=row[0],
                name=row[1],
                origin=row[2],
                status=row[3],
                overall_fitness=float(row[4]) if row[4] else 0.0,
                regime_fitness=float(row[5]) if row[5] else 0.0,
                regime_trades=int(row[6]) if row[6] else 0,
                regime_win_rate=float(row[7]) if row[7] else None,
                regime_sharpe=float(row[8]) if row[8] else None,
            )
            for row in rows
        ],
    )


@router.get("/{pattern_id}/fitness-by-regime", response_model=PatternFitnessByRegimeResponse)
async def get_pattern_fitness_by_regime(
    pattern_id: str, session: AsyncSession = Depends(get_session)
) -> PatternFitnessByRegimeResponse:
    """
    Get per-regime fitness breakdown for a specific pattern.

    Returns fitness scores across all tested regimes:
    - crash, bull, bear, sideways, blowoff, recovery (canonical periods)
    - random_1m, random_15m, random_1h, random_1d (random windows)
    """
    pattern = await pattern_service.get_pattern_by_id(session, pattern_id)
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")

    fitness_by_regime = pattern.fitness_by_regime or {}

    # Sort by fitness descending
    sorted_regimes = sorted(
        fitness_by_regime.items(), key=lambda x: x[1].get("fitness", 0) if isinstance(x[1], dict) else 0, reverse=True
    )

    return PatternFitnessByRegimeResponse(
        pattern_id=pattern.pattern_id,
        name=pattern.name,
        origin=pattern.origin,
        overall_fitness=float(pattern.fitness_score) if pattern.fitness_score else 0.0,
        best_regime=pattern.best_regime,
        best_regime_fitness=pattern.best_regime_fitness,
        regimes_tested=len(fitness_by_regime),
        fitness_by_regime=dict(sorted_regimes),
    )


@router.post("/discovery")
async def run_pattern_discovery(session: AsyncSession = Depends(get_session)):
    """
    Trigger pattern discovery cycle manually.

    Loads trades from backtest_trades_unified, generates 4 variants per trade
    (chaos, best_exit, worst_exit, perfect), extracts features via RandomForest,
    and uses LLM to generate new patterns.
    """
    from ..Services.discovery_service import PatternDiscoveryService

    service = PatternDiscoveryService()
    result = await service.run_discovery_cycle(session)
    return result


@router.post("/backtest")
async def run_pattern_backtest(
    batch_size: int = Query(50, ge=1, le=200),
    priority: str | None = Query(None, description="Priority filter: high, normal, low, or None for all"),
    session: AsyncSession = Depends(get_session),
):
    """
    Trigger pattern batch backtest manually.

    Tests patterns from the priority queue against the pre-generated window pool.
    """
    from ..Services.discovery_service import PatternDiscoveryService

    service = PatternDiscoveryService()
    result = await service.run_batch_backtest(session, batch_size=batch_size, priority_filter=priority)
    return result


@router.post("/cull")
async def cull_weak_patterns(session: AsyncSession = Depends(get_session)):
    """
    Cull patterns with 100+ trades and weak bottom-3 regime fitness.

    A pattern is culled if:
    - It has at least 100 total trades (sufficient sample size)
    - It has fitness_by_regime data with at least 3 regimes
    - The average fitness of its worst 3 regimes is below 20.0

    Culled patterns have status set to 'culled' and is_active set to False.
    """
    result = await session.execute(
        select(Pattern).where(Pattern.status != "archived").where(Pattern.status != "culled")
    )
    patterns = result.scalars().all()
    culled = []

    for p in patterns:
        # Must have 100+ backtest trades to be eligible
        total_tests = p.total_trades or 0
        if total_tests < 100:
            continue

        # Check regime fitness scores
        fbr = p.fitness_by_regime or {}
        if len(fbr) < 3:
            continue

        # Get numeric scores from regime fitness dict
        scores = []
        for val in fbr.values():
            if isinstance(val, (int, float)):
                scores.append(val)
            elif isinstance(val, dict):
                score = val.get("fitness", 0)
                if isinstance(score, (int, float)):
                    scores.append(score)

        if len(scores) < 3:
            continue

        scores.sort()
        bottom_3_avg = sum(scores[:3]) / 3

        # If average of worst 3 regimes is below 20, cull it
        if bottom_3_avg < 20.0:
            p.status = "culled"
            p.is_active = False
            session.add(p)
            culled.append(p.pattern_id)

    if culled:
        await session.commit()

    return {"culled_count": len(culled), "culled_ids": culled}


@router.get("/validation")
async def get_invalid_patterns(
    session: AsyncSession = Depends(get_session),
):
    """
    Get patterns flagged with unresolvable indicators.

    Returns patterns that can never generate trades because they reference
    indicators that don't exist (e.g., hold_candles, mswSine).
    Use this to review and fix/delete broken patterns.
    """
    from sqlalchemy import text as sa_text

    result = await session.execute(
        select(Pattern)
        .where(sa_text("validation_issues->>'status' = 'invalid'"))
        .order_by(Pattern.created_at.desc())
    )
    patterns = result.scalars().all()

    return [
        {
            "pattern_id": p.pattern_id,
            "name": p.name,
            "origin": p.origin,
            "unresolvable": (p.validation_issues or {}).get("unresolvable", []),
            "validated_at": (p.validation_issues or {}).get("validated_at"),
            "entry_conditions": p.entry_conditions,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in patterns
    ]


@router.delete("/validation/{pattern_id}")
async def delete_invalid_pattern(
    pattern_id: str,
    session: AsyncSession = Depends(get_session),
):
    """
    Delete a pattern flagged as invalid (unresolvable indicators).
    """
    pattern = await pattern_service.get_pattern_by_id(session, pattern_id)
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")

    vi = pattern.validation_issues or {}
    if vi.get("status") != "invalid":
        raise HTTPException(status_code=400, detail="Pattern is not flagged as invalid")

    await session.delete(pattern)
    await session.commit()
    return {"deleted": pattern_id, "unresolvable": vi.get("unresolvable", [])}


@router.post("/validation/revalidate")
async def revalidate_all_patterns(
    session: AsyncSession = Depends(get_session),
):
    """
    Re-run validation on all patterns (clears previous flags and re-checks).
    Useful after adding new indicator aliases.
    """
    from Fast_Swarm.local_agents.backtest.pattern_matcher import validate_pattern_conditions

    result = await session.execute(
        select(Pattern).where(Pattern.is_active.is_(True))
    )
    patterns = result.scalars().all()

    flagged = 0
    cleared = 0
    for p in patterns:
        validation = validate_pattern_conditions(p.entry_conditions or [])
        old_status = (p.validation_issues or {}).get("status")
        p.validation_issues = validation
        session.add(p)
        if validation["status"] == "invalid":
            flagged += 1
        elif old_status == "invalid":
            cleared += 1

    await session.commit()
    return {
        "total_checked": len(patterns),
        "flagged_invalid": flagged,
        "cleared": cleared,
    }


@router.get("/{pattern_id}", response_model=Pattern)
async def get_pattern(pattern_id: str, session: AsyncSession = Depends(get_session)):
    """
    Get a specific pattern by ID.
    """
    pattern = await pattern_service.get_pattern_by_id(session, pattern_id)
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")
    return pattern
