"""
Agent Definitions and Status Tracking
Defines all audit agents and their configurations.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pathlib import Path
import hashlib
import json


class AgentStatus(Enum):
    """Agent execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    STALLED = "stalled"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentPhase(Enum):
    """Audit phases."""
    BOOTSTRAP = 0
    SECTION_REVIEW = 1
    SYNTHESIS = 2
    DOCUMENTATION = 3
    FORK_ANALYSIS = 4
    RECONCILIATION = 5
    FINAL_REPORT = 6


@dataclass
class AgentDefinition:
    """Definition of an audit agent."""

    id: str                               # e.g., "1A", "2B"
    name: str                             # Human readable name
    phase: AgentPhase                     # Which phase this agent belongs to
    scope: List[str]                      # File patterns to analyze
    prompt_template: str                  # The agent's task prompt
    depends_on: List[str] = field(default_factory=list)  # Agent IDs this depends on
    output_schema: Dict[str, Any] = field(default_factory=dict)  # Expected output structure

    def get_prompt(self, context: Dict[str, Any]) -> str:
        """Generate the full prompt with context substitution."""
        return self.prompt_template.format(**context)


@dataclass
class AgentState:
    """Runtime state of an agent."""

    definition: AgentDefinition
    status: AgentStatus = AgentStatus.PENDING
    spawned_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    last_progress_at: Optional[datetime] = None
    last_output_hash: str = ""
    poke_count: int = 0
    retry_count: int = 0
    task_id: Optional[str] = None         # Claude Code task ID
    output_file: Optional[Path] = None    # Where output is written
    partial_output: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None

    @property
    def runtime_seconds(self) -> float:
        """How long the agent has been running."""
        if not self.spawned_at:
            return 0.0
        end_time = self.completed_at or datetime.now()
        return (end_time - self.spawned_at).total_seconds()

    @property
    def time_since_progress(self) -> float:
        """Seconds since last detected progress."""
        if not self.last_progress_at:
            return self.runtime_seconds
        return (datetime.now() - self.last_progress_at).total_seconds()

    def update_progress(self, output: str) -> bool:
        """
        Check if output changed, update progress tracking.
        Returns True if progress was made.
        """
        new_hash = hashlib.md5(output.encode()).hexdigest()
        if new_hash != self.last_output_hash:
            self.last_output_hash = new_hash
            self.last_progress_at = datetime.now()
            return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize state for storage."""
        return {
            "agent_id": self.definition.id,
            "agent_name": self.definition.name,
            "phase": self.definition.phase.value,
            "status": self.status.value,
            "spawned_at": self.spawned_at.isoformat() if self.spawned_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "runtime_seconds": self.runtime_seconds,
            "poke_count": self.poke_count,
            "retry_count": self.retry_count,
            "task_id": self.task_id,
            "error_message": self.error_message,
        }


# =============================================================================
# AGENT DEFINITIONS - All 24 Audit Agents
# =============================================================================

def get_tier1_agents() -> List[AgentDefinition]:
    """Phase 1: Section Code Review Agents."""

    return [
        AgentDefinition(
            id="1A",
            name="Agents Domain Reviewer",
            phase=AgentPhase.SECTION_REVIEW,
            scope=["src/Fast_Swarm/Agents/**/*.py"],
            prompt_template="""
You are reviewing the AGENTS domain of Fast_Swarm.

Scope: {scope}

Review Checklist:
- Models: SQLModel definitions, field types, relationships
- Services: Business logic, async patterns, error handling
- Routers: Endpoint design, validation, responses
- Hivemind/: Committee logic, voting, consensus
- Coaches/: Roster management, selection criteria

For each file, identify:
1. Public functions and classes
2. Internal and external dependencies
3. Dead code candidates (unused functions/imports)
4. Undocumented public APIs
5. Code smells (complexity, duplication, poor naming)
6. Security concerns
7. Performance concerns
8. Test coverage (which files have tests)

Output your findings as JSON matching this schema:
{output_schema}

Be thorough. Reference specific file:line for all findings.
""",
            output_schema={
                "domain": "Agents",
                "files_reviewed": ["list of files"],
                "total_lines": 0,
                "public_functions": [],
                "public_classes": [],
                "internal_dependencies": [],
                "external_dependencies": [],
                "dead_code_candidates": [],
                "undocumented_public_apis": [],
                "code_smells": [],
                "test_coverage_files": [],
                "missing_test_files": [],
                "security_concerns": [],
                "performance_concerns": [],
                "suggested_improvements": []
            }
        ),

        AgentDefinition(
            id="1B",
            name="Patterns Domain Reviewer",
            phase=AgentPhase.SECTION_REVIEW,
            scope=["src/Fast_Swarm/Patterns/**/*.py"],
            prompt_template="""
You are reviewing the PATTERNS domain of Fast_Swarm.

Scope: {scope}

Review Checklist:
- Pattern model structure and conditions
- Slot system implementation
- Discovery algorithms (chaos analysis)
- Pattern evaluation and promotion logic
- Tier system (quintile ranking 0-4)

For each file, identify:
1. Public functions and classes
2. Internal and external dependencies
3. Dead code candidates
4. Undocumented public APIs
5. Code smells
6. Security concerns
7. Performance concerns
8. Test coverage

Output your findings as JSON matching this schema:
{output_schema}

Be thorough. Reference specific file:line for all findings.
""",
            output_schema={
                "domain": "Patterns",
                "files_reviewed": [],
                "total_lines": 0,
                "public_functions": [],
                "public_classes": [],
                "internal_dependencies": [],
                "external_dependencies": [],
                "dead_code_candidates": [],
                "undocumented_public_apis": [],
                "code_smells": [],
                "test_coverage_files": [],
                "missing_test_files": [],
                "security_concerns": [],
                "performance_concerns": [],
                "suggested_improvements": []
            }
        ),

        AgentDefinition(
            id="1C",
            name="Infrastructure Domain Reviewer",
            phase=AgentPhase.SECTION_REVIEW,
            scope=[
                "src/Fast_Swarm/Infrastructure/**/*.py",
                "src/Fast_Swarm/exchanges/**/*.py"
            ],
            prompt_template="""
You are reviewing the INFRASTRUCTURE domain of Fast_Swarm.

Scope: {scope}

Review Checklist:
- WebSocket stream handlers (4 exchanges: Binance, Coinbase, dYdX, Hyperliquid)
- Data collection and storage
- Market data models
- Backfill mechanisms
- Connection resilience and reconnection

For each file, identify:
1. Public functions and classes
2. Internal and external dependencies
3. Dead code candidates
4. Undocumented public APIs
5. Code smells
6. Security concerns (API keys, connection handling)
7. Performance concerns (memory, throughput)
8. Test coverage

Output your findings as JSON matching this schema:
{output_schema}
""",
            output_schema={
                "domain": "Infrastructure",
                "files_reviewed": [],
                "total_lines": 0,
                "public_functions": [],
                "public_classes": [],
                "internal_dependencies": [],
                "external_dependencies": [],
                "dead_code_candidates": [],
                "undocumented_public_apis": [],
                "code_smells": [],
                "test_coverage_files": [],
                "missing_test_files": [],
                "security_concerns": [],
                "performance_concerns": [],
                "suggested_improvements": []
            }
        ),

        AgentDefinition(
            id="1D",
            name="Evolution Domain Reviewer",
            phase=AgentPhase.SECTION_REVIEW,
            scope=[
                "src/Fast_Swarm/Evolution/**/*.py",
                "src/Fast_Swarm/Main.py"
            ],
            prompt_template="""
You are reviewing the EVOLUTION domain of Fast_Swarm.

Scope: {scope}

Review Checklist:
- Evolution loop mechanics
- Reproduction and mutation logic
- Fitness calculation (Sortino, Alpha - NOT Sharpe)
- Selection pressure and culling
- Generation tracking
- Background loops in Main.py

For each file, identify:
1. Public functions and classes
2. Internal and external dependencies
3. Dead code candidates
4. Undocumented public APIs
5. Code smells
6. Security concerns
7. Performance concerns
8. Test coverage

IMPORTANT: Primary fitness metrics are Sortino and Alpha, NOT Sharpe ratio.

Output your findings as JSON matching this schema:
{output_schema}
""",
            output_schema={
                "domain": "Evolution",
                "files_reviewed": [],
                "total_lines": 0,
                "public_functions": [],
                "public_classes": [],
                "internal_dependencies": [],
                "external_dependencies": [],
                "dead_code_candidates": [],
                "undocumented_public_apis": [],
                "code_smells": [],
                "test_coverage_files": [],
                "missing_test_files": [],
                "security_concerns": [],
                "performance_concerns": [],
                "suggested_improvements": []
            }
        ),

        AgentDefinition(
            id="1E",
            name="System Domain Reviewer",
            phase=AgentPhase.SECTION_REVIEW,
            scope=[
                "src/Fast_Swarm/System/**/*.py",
                "src/Fast_Swarm/Database.py",
                "src/Fast_Swarm/Dependencies.py"
            ],
            prompt_template="""
You are reviewing the SYSTEM domain of Fast_Swarm.

Scope: {scope}

Review Checklist:
- Database connection management (PostgreSQL only, NO SQLite)
- Singleton/dependency injection patterns
- Health endpoints
- Robustness testing service
- Wisdom extraction (Crucible)
- Lifespan management

For each file, identify:
1. Public functions and classes
2. Internal and external dependencies
3. Dead code candidates
4. Undocumented public APIs
5. Code smells
6. Security concerns (connection strings, secrets)
7. Performance concerns (connection pooling, async)
8. Test coverage

Output your findings as JSON matching this schema:
{output_schema}
""",
            output_schema={
                "domain": "System",
                "files_reviewed": [],
                "total_lines": 0,
                "public_functions": [],
                "public_classes": [],
                "internal_dependencies": [],
                "external_dependencies": [],
                "dead_code_candidates": [],
                "undocumented_public_apis": [],
                "code_smells": [],
                "test_coverage_files": [],
                "missing_test_files": [],
                "security_concerns": [],
                "performance_concerns": [],
                "suggested_improvements": []
            }
        ),

        AgentDefinition(
            id="1F",
            name="Trades Domain Reviewer",
            phase=AgentPhase.SECTION_REVIEW,
            scope=[
                "src/Fast_Swarm/Trades/**/*.py",
                "src/Fast_Swarm/Trading/**/*.py"
            ],
            prompt_template="""
You are reviewing the TRADES domain of Fast_Swarm.

Scope: {scope}

Review Checklist:
- Trade model structure
- Trade history queries
- Backtest trade recording
- Paper trading implementation (if any)

For each file, identify:
1. Public functions and classes
2. Internal and external dependencies
3. Dead code candidates
4. Undocumented public APIs
5. Code smells
6. Security concerns
7. Performance concerns
8. Test coverage

Output your findings as JSON matching this schema:
{output_schema}
""",
            output_schema={
                "domain": "Trades",
                "files_reviewed": [],
                "total_lines": 0,
                "public_functions": [],
                "public_classes": [],
                "internal_dependencies": [],
                "external_dependencies": [],
                "dead_code_candidates": [],
                "undocumented_public_apis": [],
                "code_smells": [],
                "test_coverage_files": [],
                "missing_test_files": [],
                "security_concerns": [],
                "performance_concerns": [],
                "suggested_improvements": []
            }
        ),

        AgentDefinition(
            id="1G",
            name="Tests Domain Reviewer",
            phase=AgentPhase.SECTION_REVIEW,
            scope=["Tests/**/*.py"],
            prompt_template="""
You are reviewing the TESTS domain of Fast_Swarm.

Scope: {scope}

Review Checklist:
- Test organization (Unit/Integration/Soundness/Triage)
- Fixture patterns and conftest.py usage
- Test coverage per domain
- Skipped/broken tests
- Test naming conventions
- Mock usage patterns

For each test file, identify:
1. What source file(s) it tests
2. Test count and types
3. Fixtures used
4. Mocks used
5. Skipped tests and reasons
6. Broken/failing tests

Special output: Create a coverage map showing which source files have tests.

Output your findings as JSON matching this schema:
{output_schema}
""",
            output_schema={
                "domain": "Tests",
                "files_reviewed": [],
                "total_lines": 0,
                "coverage_map": {},
                "orphaned_tests": [],
                "missing_coverage": [],
                "skipped_tests": [],
                "broken_tests": [],
                "fixture_inventory": [],
                "suggested_improvements": []
            }
        ),

        AgentDefinition(
            id="1H",
            name="Scripts & Utilities Reviewer",
            phase=AgentPhase.SECTION_REVIEW,
            scope=[
                "src/Fast_Swarm/scripts/**/*.py",
                "*.py"
            ],
            prompt_template="""
You are reviewing the SCRIPTS & UTILITIES of Fast_Swarm.

Scope: {scope}

Review Checklist:
- Script purposes and documentation
- One-off vs recurring scripts
- Hardcoded paths/values
- Scripts that should be CLI commands
- Obsolete/unused scripts

For each script, identify:
1. Purpose (what does it do)
2. Usage pattern (one-off, recurring, manual, automated)
3. Dependencies
4. Hardcoded values that should be config
5. Whether it's still needed

Output your findings as JSON matching this schema:
{output_schema}
""",
            output_schema={
                "domain": "Scripts",
                "files_reviewed": [],
                "total_lines": 0,
                "scripts_inventory": [],
                "obsolete_scripts": [],
                "hardcoded_values": [],
                "suggested_improvements": []
            }
        ),
    ]


def get_tier2_agents() -> List[AgentDefinition]:
    """Phase 2: Synthesis Supervisor Agents."""

    tier1_ids = ["1A", "1B", "1C", "1D", "1E", "1F", "1G", "1H"]

    return [
        AgentDefinition(
            id="2A",
            name="Dead Code Synthesis Supervisor",
            phase=AgentPhase.SYNTHESIS,
            scope=[],
            depends_on=tier1_ids,
            prompt_template="""
You are the DEAD CODE SYNTHESIS SUPERVISOR.

Input: All "dead_code_candidates" from Tier 1 agents:
{tier1_outputs}

Tasks:
1. Aggregate all dead code candidates
2. Cross-reference: Is "dead" in Domain A actually used in Domain B?
3. Check for dynamic usage (getattr, importlib, string refs)
4. Check for FastAPI/pytest magic usage (routes, fixtures)
5. Categorize by confidence:
   - CERTAIN: Zero references anywhere, safe to delete
   - LIKELY: Only self-references, probably dead
   - UNCERTAIN: Possible dynamic usage, needs manual review
   - FALSE_POSITIVE: Actually used, remove from list

Output your findings as JSON matching this schema:
{output_schema}
""",
            output_schema={
                "certain_dead_code": [],
                "likely_dead_code": [],
                "uncertain_dead_code": [],
                "false_positives_corrected": [],
                "total_removable_lines": 0,
                "removal_risk_assessment": ""
            }
        ),

        AgentDefinition(
            id="2B",
            name="Dependency Graph Synthesis Supervisor",
            phase=AgentPhase.SYNTHESIS,
            scope=[],
            depends_on=tier1_ids,
            prompt_template="""
You are the DEPENDENCY GRAPH SYNTHESIS SUPERVISOR.

Input: All dependency data from Tier 1 agents:
{tier1_outputs}

Tasks:
1. Build complete internal dependency graph
2. Identify circular dependencies
3. Find unexpected cross-domain dependencies
4. Map external library usage per domain
5. Identify potential dependency injection points
6. Find tightly coupled components

Output your findings as JSON matching this schema:
{output_schema}
""",
            output_schema={
                "dependency_graph": {},
                "circular_dependencies": [],
                "unexpected_couplings": [],
                "external_libs_by_domain": {},
                "coupling_score_by_domain": {},
                "decoupling_opportunities": []
            }
        ),

        AgentDefinition(
            id="2C",
            name="Test Coverage Gap Synthesis Supervisor",
            phase=AgentPhase.SYNTHESIS,
            scope=[],
            depends_on=tier1_ids,
            prompt_template="""
You are the TEST COVERAGE GAP SYNTHESIS SUPERVISOR.

Input: Public APIs and coverage map from Tier 1:
{tier1_outputs}

Tasks:
1. Map every public API to its test(s)
2. Identify completely untested modules
3. Identify partially tested modules
4. Identify critical paths without tests
5. Calculate coverage percentage per domain
6. Prioritize testing gaps by risk

Output your findings as JSON matching this schema:
{output_schema}
""",
            output_schema={
                "coverage_by_domain": {},
                "completely_untested": [],
                "partially_tested": [],
                "critical_untested_paths": [],
                "test_priority_ranking": []
            }
        ),

        AgentDefinition(
            id="2D",
            name="Code Quality Synthesis Supervisor",
            phase=AgentPhase.SYNTHESIS,
            scope=[],
            depends_on=tier1_ids,
            prompt_template="""
You are the CODE QUALITY SYNTHESIS SUPERVISOR.

Input: Code smells, security, and performance concerns from Tier 1:
{tier1_outputs}

Tasks:
1. Categorize all issues by severity (Critical/High/Medium/Low)
2. Identify patterns of repeated issues
3. Cross-reference security concerns with external exposure
4. Estimate fix effort for each issue
5. Create prioritized fix list

Output your findings as JSON matching this schema:
{output_schema}
""",
            output_schema={
                "issues_by_severity": {
                    "critical": [],
                    "high": [],
                    "medium": [],
                    "low": []
                },
                "recurring_patterns": [],
                "security_exposure_map": [],
                "fix_effort_estimates": [],
                "prioritized_fix_list": []
            }
        ),

        AgentDefinition(
            id="2E",
            name="API Surface Synthesis Supervisor",
            phase=AgentPhase.SYNTHESIS,
            scope=[],
            depends_on=tier1_ids,
            prompt_template="""
You are the API SURFACE SYNTHESIS SUPERVISOR.

Input: Router and endpoint data from Tier 1:
{tier1_outputs}

Tasks:
1. Catalog complete API surface (all endpoints)
2. Map endpoints to service functions
3. Identify inconsistent patterns (naming, responses, errors)
4. Find endpoints without proper validation
5. Identify missing CRUD operations
6. Check OpenAPI documentation completeness

Output your findings as JSON matching this schema:
{output_schema}
""",
            output_schema={
                "endpoint_catalog": [],
                "endpoint_to_service_map": {},
                "inconsistencies": [],
                "validation_gaps": [],
                "incomplete_crud": [],
                "openapi_gaps": []
            }
        ),
    ]


def get_tier3_agents() -> List[AgentDefinition]:
    """Phase 3: Documentation Analysis Agents."""

    return [
        AgentDefinition(
            id="3A",
            name="CLAUDE.md Analyzer",
            phase=AgentPhase.DOCUMENTATION,
            scope=["CLAUDE.md", ".claude/CLAUDE.md"],
            prompt_template="""
You are the CLAUDE.MD ANALYZER.

Scope: {scope}

Tasks:
1. Extract all documented features/capabilities
2. Extract all documented constraints/rules
3. Extract all documented architecture claims
4. Note any TODOs or WIP markers
5. List all status indicators (checkmarks, WIP, etc)

Output your findings as JSON matching this schema:
{output_schema}
""",
            output_schema={
                "documented_features": [],
                "documented_constraints": [],
                "architecture_claims": [],
                "wip_items": [],
                "status_claims": {}
            }
        ),

        AgentDefinition(
            id="3B",
            name="Technical Docs Analyzer",
            phase=AgentPhase.DOCUMENTATION,
            scope=["docs/*.md"],
            prompt_template="""
You are the TECHNICAL DOCS ANALYZER.

Scope: {scope}

Tasks:
1. Parse each doc for system descriptions, component definitions, data flows
2. Build "as-designed" architecture model
3. Note version/date information
4. Identify cross-references between docs

Output your findings as JSON matching this schema:
{output_schema}
""",
            output_schema={
                "docs_inventory": [],
                "components_documented": [],
                "data_flows_documented": [],
                "integrations_documented": [],
                "as_designed_model": {},
                "doc_freshness": {}
            }
        ),

        AgentDefinition(
            id="3C",
            name="Inline Documentation Analyzer",
            phase=AgentPhase.DOCUMENTATION,
            scope=["src/Fast_Swarm/**/*.py"],
            prompt_template="""
You are the INLINE DOCUMENTATION ANALYZER.

Scope: {scope}

Tasks:
1. Extract all module-level docstrings
2. Extract all class docstrings
3. Extract all function docstrings
4. Identify public functions WITHOUT docstrings
5. Identify stale/incorrect docstrings
6. Extract significant inline comments

Output your findings as JSON matching this schema:
{output_schema}
""",
            output_schema={
                "documented_modules": [],
                "documented_classes": [],
                "documented_functions": [],
                "undocumented_public_apis": [],
                "stale_docstrings": [],
                "important_comments": []
            }
        ),

        AgentDefinition(
            id="3D",
            name="README & Config Analyzer",
            phase=AgentPhase.DOCUMENTATION,
            scope=["README.md", "pyproject.toml", ".env.example"],
            prompt_template="""
You are the README & CONFIG ANALYZER.

Scope: {scope}

Tasks:
1. Extract setup/installation instructions
2. Extract environment variable requirements
3. Extract dependency list and versions
4. Identify getting-started workflows
5. Check for outdated version references

Output your findings as JSON matching this schema:
{output_schema}
""",
            output_schema={
                "setup_instructions": [],
                "env_vars_documented": [],
                "dependencies_documented": [],
                "quickstart_available": False,
                "outdated_references": []
            }
        ),
    ]


def get_tier4_agents() -> List[AgentDefinition]:
    """Phase 4: Fork Inheritance Analysis Agents."""

    return [
        AgentDefinition(
            id="4A",
            name="Fork Inventory Agent",
            phase=AgentPhase.FORK_ANALYSIS,
            scope=["C:/Users/Admin/Documents/Coinswarm-1/local-utilities/**/*.py"],
            prompt_template="""
You are the FORK INVENTORY AGENT.

Scope: {scope}

Tasks:
1. Catalog ALL Python files with:
   - File path, line count, primary purpose
   - Last modified date
   - Key functions/classes defined
2. Categorize files by function:
   - Backfill scripts (backfill_*.py)
   - Migration scripts (migrate_*.py)
   - Data collectors
   - Trading/backtesting engines
   - Analysis tools
   - Dashboard/UI components
   - Database utilities
   - Pattern discovery
   - Monitoring/status tools
   - One-off scripts
   - Test files

Output your findings as JSON matching this schema:
{output_schema}
""",
            output_schema={
                "total_files": 0,
                "total_lines": 0,
                "files_by_category": {},
                "subdirectories": [],
                "file_details": []
            }
        ),

        AgentDefinition(
            id="4B",
            name="Fork-to-FastSwarm Comparison Agent",
            phase=AgentPhase.FORK_ANALYSIS,
            scope=[],
            depends_on=["4A", "1A", "1B", "1C", "1D", "1E", "1F", "1G", "1H"],
            prompt_template="""
You are the FORK-TO-FASTSWARM COMPARISON AGENT.

Input: Fork inventory from 4A and all Tier 1 outputs:
{tier1_outputs}
{fork_inventory}

Tasks:
1. For each file in local-utilities, determine status:
   - MIGRATED: Exists in Fast_Swarm (same or similar)
   - SUPERSEDED: Functionality replaced differently
   - MISSING_NEEDED: Not in Fast_Swarm but SHOULD be
   - MISSING_OBSOLETE: Not needed (SQLite-specific, Redis, etc)
   - PARTIAL: Some functionality migrated, some missing

2. For MISSING_NEEDED, assess urgency and effort

Output your findings as JSON matching this schema:
{output_schema}
""",
            output_schema={
                "migrated": [],
                "superseded": [],
                "missing_needed": [],
                "missing_obsolete": [],
                "partial": []
            }
        ),

        AgentDefinition(
            id="4C",
            name="Critical Scripts Deep-Dive Agent",
            phase=AgentPhase.FORK_ANALYSIS,
            scope=[],
            depends_on=["4B"],
            prompt_template="""
You are the CRITICAL SCRIPTS DEEP-DIVE AGENT.

Input: Missing-needed files from 4B:
{missing_needed}

For each MISSING_NEEDED file, analyze:
1. What it does (detailed)
2. External dependencies (pip packages)
3. Internal dependencies (other scripts)
4. Database interactions
5. API calls
6. Configuration requirements
7. Migration path: as-is / minor / major / rewrite
8. Conflicts with existing Fast_Swarm code

Output your findings as JSON matching this schema:
{output_schema}
""",
            output_schema={
                "critical_scripts": []
            }
        ),

        AgentDefinition(
            id="4D",
            name="Fork Data Files Analyzer",
            phase=AgentPhase.FORK_ANALYSIS,
            scope=["C:/Users/Admin/Documents/Coinswarm-1/local-utilities"],
            prompt_template="""
You are the FORK DATA FILES ANALYZER.

Scope: Non-Python files in local-utilities:
- *.json (patterns, configs, results)
- *.db, *.sqlite (databases)
- *.sql (schemas)
- *.html (dashboards)

Tasks:
1. Inventory all non-Python files
2. For JSON: What data? Config or results? Migrate?
3. For databases: Schema? Volume? Migrate to PostgreSQL?
4. For SQL schemas: Compare to current schema
5. For HTML dashboards: What do they show? Incorporate?

Output your findings as JSON matching this schema:
{output_schema}
""",
            output_schema={
                "json_files": [],
                "database_files": [],
                "schema_files": [],
                "dashboard_files": [],
                "migration_recommendations": []
            }
        ),

        AgentDefinition(
            id="4E",
            name="Fork Functionality Gap Synthesizer",
            phase=AgentPhase.FORK_ANALYSIS,
            scope=[],
            depends_on=["4A", "4B", "4C", "4D"],
            prompt_template="""
You are the FORK FUNCTIONALITY GAP SYNTHESIZER.

Input: All fork analysis outputs:
{fork_outputs}

Tasks:
1. Create "what we left behind" report
2. Categorize gaps by business function
3. Prioritize what to bring over:
   - MUST HAVE: Blocking current development
   - SHOULD HAVE: Would improve significantly
   - NICE TO HAVE: Useful but not critical
   - SKIP: Not worth migrating
4. Create migration roadmap with dependencies

Output your findings as JSON matching this schema:
{output_schema}
""",
            output_schema={
                "functionality_gaps": {},
                "prioritized_migrations": {},
                "migration_roadmap": [],
                "total_migration_effort": ""
            }
        ),
    ]


def get_tier5_agents() -> List[AgentDefinition]:
    """Phase 5: Architecture Reconciliation Agent."""

    all_previous = (
        ["1A", "1B", "1C", "1D", "1E", "1F", "1G", "1H"] +
        ["2A", "2B", "2C", "2D", "2E"] +
        ["3A", "3B", "3C", "3D"] +
        ["4A", "4B", "4C", "4D", "4E"]
    )

    return [
        AgentDefinition(
            id="5A",
            name="Architecture Reconciler",
            phase=AgentPhase.RECONCILIATION,
            scope=[],
            depends_on=all_previous,
            prompt_template="""
You are the ARCHITECTURE RECONCILER.

Input: ALL previous tier outputs:
{all_outputs}

Tasks:
1. Build "As-Built" Architecture Model from code analysis
2. Build "As-Designed" Architecture Model from documentation
3. Build "As-Inherited" Architecture Model from fork analysis
4. Perform THREE-WAY GAP ANALYSIS:
   A) Code exists, Docs missing, Fork had it: migrated but undocumented
   B) Code exists, Docs missing, Fork didn't: new, needs docs
   C) Docs exist, Code missing, Fork had it: should have migrated
   D) Docs exist, Code missing, Fork didn't: never implemented
   E) Fork had it, neither Code nor Docs: lost in fork
   F) Status mismatches across all three

Output your findings as JSON matching this schema:
{output_schema}
""",
            output_schema={
                "as_built_architecture": {},
                "as_designed_architecture": {},
                "as_inherited_architecture": {},
                "gap_analysis": {
                    "migrated_undocumented": [],
                    "new_undocumented": [],
                    "should_have_migrated": [],
                    "documented_never_built": [],
                    "lost_in_fork": [],
                    "status_mismatches": []
                }
            }
        ),
    ]


def get_tier6_agents() -> List[AgentDefinition]:
    """Phase 6: Final Report Generation Agent."""

    all_agents = (
        ["1A", "1B", "1C", "1D", "1E", "1F", "1G", "1H"] +
        ["2A", "2B", "2C", "2D", "2E"] +
        ["3A", "3B", "3C", "3D"] +
        ["4A", "4B", "4C", "4D", "4E"] +
        ["5A"]
    )

    return [
        AgentDefinition(
            id="6A",
            name="Final Report Generator",
            phase=AgentPhase.FINAL_REPORT,
            scope=[],
            depends_on=all_agents,
            prompt_template="""
You are the FINAL REPORT GENERATOR.

Input: ALL audit outputs:
{all_outputs}

Generate a comprehensive MARKDOWN report with these sections:

1. EXECUTIVE SUMMARY (2-3 paragraphs)
2. ARCHITECTURE AS-BUILT (components, flows, dependencies)
3. ARCHITECTURE AS-DESIGNED (from docs)
4. FORK INHERITANCE ANALYSIS (what was left behind)
5. GAP ANALYSIS (undocumented, unimplemented, mismatches)
6. DEAD CODE ANALYSIS (safe to remove, needs review)
7. UNDOCUMENTED FEATURES
8. FIXES NEEDED (critical, high, medium, low)
9. TOP 20 MOST IMPACTFUL IMPROVEMENTS (ranked by ROI)
10. TEST COVERAGE ANALYSIS
11. DEPENDENCY HEALTH
12. ACTIONABLE NEXT STEPS

Use ASCII-only formatting (no unicode). Use tables with |, -, + characters.

Output the full markdown report.
""",
            output_schema={}  # Output is markdown, not JSON
        ),
    ]


def get_all_agent_definitions() -> List[AgentDefinition]:
    """Get all 24 agent definitions."""
    return (
        get_tier1_agents() +
        get_tier2_agents() +
        get_tier3_agents() +
        get_tier4_agents() +
        get_tier5_agents() +
        get_tier6_agents()
    )
