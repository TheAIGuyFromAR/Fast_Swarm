# Parallel Todo Loop

Execute all pending todos by spawning up to 5 concurrent Task agents for non-conflicting work, with optional TDD+EDD quality gates.

## Modes

- **standard** - Parallel execution, no test requirements
- **tdd-edd** - Tests must exist and pass before a todo can be marked complete. A Gatekeeper agent reviews test quality.

Check `.claude/parallel-todo-state.md` Config section for the active mode.

---

## Coordination Files (Absolute Paths)

| File | Purpose |
|------|---------|
| `c:\fast_swarm\.claude\shared-todos.md` | Master task list (`- [ ]` / `- [x]`) |
| `c:\fast_swarm\.claude\shared-context.md` | Shared discoveries, warnings, request tracker |
| `c:\fast_swarm\.claude\parallel-todo-state.md` | Runtime state: running agents, locks, config |
| `c:\fast_swarm\.claude\agent-progress\<TASK_ID>.md` | Per-agent progress logs |
| `c:\fast_swarm\.claude\scripts\check-file-lock.py` | Lock enforcement script |
| `c:\fast_swarm\.claude\scripts\check-todo-tests.py` | TDD+EDD test gate script |

---

## Algorithm

### STEP 0 - INITIALIZE

1. Read `.claude/shared-todos.md` - sync internal TodoWrite state
2. Read `.claude/parallel-todo-state.md` - check config and any resumed state
3. Read `.claude/shared-context.md` - load shared context for agent prompts
4. Note `MAX_PARALLEL` from config (default 5)
5. Note `mode` from config (standard or tdd-edd)

### STEP 1 - CHECK RUNNING AGENTS

For each agent in the state file's "Running Agents" table:

1. Use `Read` tool to check the agent's output file path
2. If output shows the agent has completed:
   - Read the agent's progress log at `agent-progress/<TASK_ID>.md`
   - If mode is `tdd-edd`: run the TDD+EDD gate (see STEP 6 below) BEFORE marking done
   - If mode is `standard` or TDD gate passed:
     - Mark the corresponding `- [ ]` as `- [x]` in shared-todos.md
     - Remove from Running Agents table in parallel-todo-state.md
     - Add to Completed This Session table
     - Append any discoveries to shared-context.md
   - If TDD gate FAILED:
     - Keep task as `- [ ]`
     - Append "[NEEDS TESTS]" to the task line
     - Remove from Running Agents, release locks
     - Log failure in shared-context.md Warnings
3. If output shows error or agent failed:
   - Log error in shared-context.md under Warnings
   - Remove from Running Agents, release locks
   - Keep task as `- [ ]` for retry
   - Increment retry count in Retries table (if retry_limit exceeded, mark task with "[SKIP - MAX RETRIES]")

### STEP 2 - ANALYZE PENDING TASKS (Hybrid File Scope Detection)

For each pending `- [ ]` task (in order, skipping [SKIP] tasks):

**Fast path (regex first):**
- Check if task description contains explicit file paths (e.g., `src/Fast_Swarm/Trading/...`)
- Map module names to directories:
  - "trading" -> `src/Fast_Swarm/Trading/`
  - "pattern" -> `src/Fast_Swarm/Patterns/`
  - "agent" -> `src/Fast_Swarm/Agents/`
  - "infrastructure" -> `src/Fast_Swarm/Infrastructure/`
  - "system" -> `src/Fast_Swarm/System/`
  - "backtest" -> `src/Fast_Swarm/Backtest/`, `src/Fast_Swarm/local_agents/backtest/`
  - "exchange" -> `src/Fast_Swarm/exchanges/`
  - "dashboard" -> `src/Fast_Swarm/Dashboard/`, `Dashboard/`
  - "metric" -> `src/Fast_Swarm/Metrics/`
  - "database" -> `src/Fast_Swarm/Database.py`
  - "main" -> `src/Fast_Swarm/Main.py`
- If explicit paths or module keywords found: use these as the predicted file set

**Smart path (haiku fallback):**
- If regex finds nothing useful, spawn a haiku-model Task agent:
  ```
  Analyze this task for a Python FastAPI codebase rooted at c:\fast_swarm.
  Task: "[task text]"

  Which files would likely be WRITTEN TO (not just read)?
  Use Grep and Glob to identify actual files.
  Return a JSON array of file paths (absolute).
  Be conservative - include files that MIGHT be touched.
  Include test files if the task involves testing.
  ```
- Store predicted file set per task in memory for STEP 3

### STEP 3 - DETERMINE NON-CONFLICTING BATCH

1. Get currently locked files from Running Agents table
2. For each pending task (in priority order):
   - If `predicted_files` INTERSECTS `locked_files` -> SKIP (conflicting)
   - If no conflict AND `running_count < MAX_PARALLEL` -> QUEUE for spawn
   - Add task's predicted files to locked_files set
3. Result: batch of 0-N tasks safe to run in parallel

### STEP 4 - SPAWN AGENTS

For each task in the non-conflicting batch:

1. Generate TASK_ID: first 8 chars of the task description's hash (use Python: `hashlib.md5(task.encode()).hexdigest()[:8]` via Bash if needed, or just use a truncated readable slug)
2. Select the appropriate prompt template based on mode:
   - standard mode: use STANDARD AGENT PROMPT (below)
   - tdd-edd mode: use TDD+EDD AGENT PROMPT (below)
3. Spawn a Task agent with `run_in_background: true`, `subagent_type: 'general-purpose'`
4. Record in parallel-todo-state.md Running Agents table:
   - Task (truncated to 60 chars)
   - Task ID
   - Agent ID (from Task tool response)
   - Output File (from Task tool response)
   - Locked Files (predicted set from STEP 2, comma-separated)
   - Started (current timestamp)

### STEP 5 - WAIT AND LOOP

1. If running agents > 0: wait approximately 15 seconds (use `timeout 15` on Windows or proceed to next check)
2. If ALL tasks are `- [x]` (no pending, no running): output completion and stop
3. Otherwise: go to STEP 1

### STEP 6 - TDD+EDD GATE (tdd-edd mode only)

When an agent completes in tdd-edd mode:

1. Read the agent's progress log to get list of modified files
2. Run `check-todo-tests.py` logic:
   - For each modified source file, find corresponding test file
   - If test file missing: FAIL (agent must write tests)
   - Run pytest on all found test files
   - If any test fails: FAIL
3. If tests pass: spawn GATEKEEPER AGENT (see prompt below) to review test quality
4. Read gatekeeper's output:
   - If verdict is APPROVED: mark todo complete
   - If verdict is REJECTED: keep todo pending, log issues, retry with "[FIX TESTS]" prepended

---

## PROMPT TEMPLATES

---

### STANDARD AGENT PROMPT

```
===============================================================
PARALLEL TODO AGENT - TASK ASSIGNMENT
===============================================================

YOUR TASK:
{TASK_TEXT}

TASK ID: {TASK_ID}

===============================================================
COORDINATION FILES (absolute paths - use these exactly)
===============================================================

1. YOUR PROGRESS LOG (create immediately, update as you work):
   c:\fast_swarm\.claude\agent-progress\{TASK_ID}.md

2. SHARED TODO LIST (mark your task done when complete):
   c:\fast_swarm\.claude\shared-todos.md

3. SHARED CONTEXT (read first, append discoveries when done):
   c:\fast_swarm\.claude\shared-context.md

4. ORCHESTRATOR STATE (read-only, see who else is running):
   c:\fast_swarm\.claude\parallel-todo-state.md

===============================================================
PROTOCOL - FOLLOW THIS EXACTLY
===============================================================

ON START:
1. Read shared-context.md - understand what other agents have done
2. Read parallel-todo-state.md - see what files are locked by others
3. Create your progress log at agent-progress/{TASK_ID}.md with:
   - Status: IN_PROGRESS
   - Started: {TIMESTAMP}
   - Current Step: "Starting task analysis"

WHILE WORKING:
4. Update your progress log's "Current Step" section periodically
5. Add files to "Files Modified" as you edit them
6. Do NOT modify files listed in parallel-todo-state.md "Locked Files"
   that are not assigned to your task

ON COMPLETION:
7. Update your progress log:
   - Status: COMPLETED
   - Finished: {TIMESTAMP}
   - Final list of all files modified
8. Edit shared-todos.md: change your task from "- [ ]" to "- [x]"
9. Append to shared-context.md under "## Agent Discoveries":
   - [{TASK_ID}] [one-line summary of what changed]
10. Append to shared-context.md under "## Completed Changes":
    - [{TIMESTAMP}] [file]: [what changed]

ON ERROR:
11. Update your progress log:
    - Status: FAILED
    - Errors: [what went wrong]
12. Do NOT mark the todo as complete
13. Append to shared-context.md under "## Warnings":
    - [{TASK_ID}] FAILED: [error summary]

===============================================================
CONTEXT FROM OTHER AGENTS
===============================================================

{SHARED_CONTEXT_CONTENTS}

===============================================================
RULES
===============================================================

- Work autonomously - do not ask questions
- Complete the task fully before marking done
- ONLY modify files within your assigned scope
- If you discover something other agents need to know, log it
- Use plain ASCII output only (no unicode/emoji - Windows cp1252)
- Follow the codebase conventions in CLAUDE.md
- Read CLAUDE.md at the project root before starting work
```

---

### TDD+EDD AGENT PROMPT

```
===============================================================
PARALLEL TODO AGENT - TDD+EDD MODE
===============================================================

YOUR TASK:
{TASK_TEXT}

TASK ID: {TASK_ID}

===============================================================
TDD+EDD REQUIREMENTS - READ CAREFULLY
===============================================================

You are operating in TDD+EDD (Test-Driven + Evidence-Driven Development) mode.
Your work will be REJECTED if tests are missing, failing, or low quality.

WORKFLOW (strict order):
1. FIRST: Write tests that define the expected behavior
2. THEN: Implement the feature/fix to make tests pass
3. FINALLY: Verify all tests pass before marking complete

TEST REQUIREMENTS:
- Every modified source file MUST have a corresponding test file
- Test file location: Tests/Unit/<Domain>/test_<filename>.py
  OR Tests/Soundness/<Domain>/test_<filename>.py for EDD tests
- Tests must ACTUALLY exercise the code (not mock everything away)

EDD (Evidence-Driven Development) REQUIREMENTS:
Your tests MUST include these evidence categories where applicable:

a) DETERMINISM - Same inputs produce same outputs
   - Call the function twice with identical args, assert results match

b) DIVISION SAFETY - No crashes on zero/empty inputs
   - Test with zero values, empty lists, None where possible
   - Assert no ZeroDivisionError, no NaN propagation

c) BOUNDARY CONDITIONS - Edge cases handled
   - Test with minimum/maximum expected values
   - Test with single-element collections
   - Test with negative numbers if applicable

d) STATISTICAL SANITY - Outputs in reasonable ranges
   - Sortino ratio between -5 and 10 (not infinity)
   - Drawdown between 0 and 1 (not negative, not > 100%)
   - Percentages between 0 and 100

e) ECONOMIC VALIDITY - No impossible trading results
   - No negative position sizes
   - No trades before start date
   - Returns bounded by physical limits

WHAT GETS YOUR WORK REJECTED (Gatekeeper checks):
- Excessive mock.patch that hides real behavior
- Trivial assertions: assert True, assert x is not None, assert len(x) >= 0
- No edge case coverage
- Tests that pass regardless of implementation (tautologies)
- Missing EDD evidence categories for the code type

===============================================================
COORDINATION FILES (absolute paths - use these exactly)
===============================================================

1. YOUR PROGRESS LOG (create immediately, update as you work):
   c:\fast_swarm\.claude\agent-progress\{TASK_ID}.md

2. SHARED TODO LIST (mark your task done when complete):
   c:\fast_swarm\.claude\shared-todos.md

3. SHARED CONTEXT (read first, append discoveries when done):
   c:\fast_swarm\.claude\shared-context.md

4. ORCHESTRATOR STATE (read-only, see who else is running):
   c:\fast_swarm\.claude\parallel-todo-state.md

===============================================================
PROTOCOL - FOLLOW THIS EXACTLY
===============================================================

ON START:
1. Read shared-context.md - understand what other agents have done
2. Read parallel-todo-state.md - see what files are locked by others
3. Create your progress log at agent-progress/{TASK_ID}.md with:
   - Status: IN_PROGRESS
   - Started: {TIMESTAMP}
   - Current Step: "Writing tests first (TDD)"

TDD WORKFLOW:
4. Analyze the task - what behavior needs to exist?
5. Write test file FIRST:
   - Create Tests/Unit/<Domain>/test_<name>.py or Tests/Soundness/<Domain>/test_<name>.py
   - Include all EDD evidence categories applicable to this code
   - Tests should FAIL initially (code not yet written)
6. Update progress log: "Current Step: Implementing feature"
7. Write the implementation to make tests pass
8. Run tests: `python -m pytest <test_file> -v`
9. Fix any failures until all tests pass
10. Update progress log with test results

ON COMPLETION:
11. Update your progress log:
    - Status: COMPLETED
    - Finished: {TIMESTAMP}
    - Files Modified: [all files]
    - Test Results: [pytest output summary]
12. Edit shared-todos.md: change your task from "- [ ]" to "- [x]"
13. Append discoveries/changes to shared-context.md

ON ERROR:
14. Update progress log with Status: FAILED and error details
15. Do NOT mark the todo as complete
16. Log warning in shared-context.md

===============================================================
CONTEXT FROM OTHER AGENTS
===============================================================

{SHARED_CONTEXT_CONTENTS}

===============================================================
RULES
===============================================================

- Work autonomously - do not ask questions
- TESTS FIRST - write tests before implementation
- Complete the task fully before marking done
- ONLY modify files within your assigned scope
- Use plain ASCII output only (no unicode/emoji - Windows cp1252)
- Follow the codebase conventions in CLAUDE.md
- Read CLAUDE.md at the project root before starting work
- Your tests WILL be reviewed by a Gatekeeper agent - do not cut corners
```

---

### GATEKEEPER AGENT PROMPT

```
===============================================================
TEST QUALITY GATEKEEPER
===============================================================

You are the Gatekeeper. Your job is to review test quality for a completed task.
You must REJECT sham tests that provide false confidence.

TASK THAT WAS COMPLETED:
{TASK_TEXT}

TASK ID: {TASK_ID}

FILES MODIFIED BY THE AGENT:
{MODIFIED_FILES_LIST}

TEST FILES TO REVIEW:
{TEST_FILES_LIST}

===============================================================
REVIEW CRITERIA - BE STRICT
===============================================================

For each test file, check ALL of the following:

1. MOCK ABUSE (auto-reject if excessive)
   - Count mock.patch / MagicMock / AsyncMock usage
   - If > 50% of test functions use mocking: SUSPICIOUS
   - If mocks hide the actual logic being tested: REJECT
   - Acceptable mocking: external APIs, database calls, network I/O
   - Unacceptable mocking: the function under test, its core dependencies

2. TRIVIAL ASSERTIONS (auto-reject if found)
   - assert True
   - assert result is not None (without checking the value)
   - assert len(x) >= 0 (always true)
   - assert isinstance(x, object) (always true)
   - assert x == x (tautology)
   - Any assertion that CANNOT FAIL regardless of implementation

3. EDD EVIDENCE (required for metrics/trading/backtest code)
   a) Determinism check - same input -> same output (at least 1 test)
   b) Division safety - zero/empty input handling (at least 1 test)
   c) Boundary conditions - edge cases (at least 2 tests)
   d) Statistical sanity - output ranges validated (if applicable)
   e) Economic validity - no impossible results (if applicable)

4. COVERAGE QUALITY
   - Happy path tested: YES/NO
   - Error path tested: YES/NO
   - Edge cases tested: YES/NO
   - Integration point tested (if touching multiple components): YES/NO

5. TEST INDEPENDENCE
   - Tests should not depend on execution order
   - Tests should not share mutable state
   - Each test should set up its own fixtures

===============================================================
OUTPUT FORMAT
===============================================================

Write your review to: c:\fast_swarm\.claude\agent-progress\{TASK_ID}-gatekeeper.md

Use this exact format:

# Gatekeeper Review: {TASK_ID}

## Verdict: APPROVED | REJECTED

## Test Files Reviewed
- [list each file]

## Mock Usage
- Total test functions: N
- Functions using mocks: N
- Mock ratio: N%
- Assessment: ACCEPTABLE | EXCESSIVE

## Assertion Quality
- Trivial assertions found: [list or "None"]
- Tautological tests: [list or "None"]
- Assessment: GOOD | POOR

## EDD Evidence
- Determinism: PRESENT | MISSING
- Division Safety: PRESENT | MISSING | N/A
- Boundary Conditions: PRESENT | MISSING
- Statistical Sanity: PRESENT | MISSING | N/A
- Economic Validity: PRESENT | MISSING | N/A

## Coverage Quality
- Happy path: YES | NO
- Error path: YES | NO
- Edge cases: YES | NO

## Issues Found
[numbered list of specific problems, or "None"]

## Recommendations
[what the agent should fix if REJECTED]

===============================================================
RULES
===============================================================

- Read each test file completely before judging
- Read the SOURCE files too - understand what is being tested
- Be STRICT but FAIR - tests don't need to be perfect, but they must be real
- A test that can never fail is worse than no test (false confidence)
- Mocking external I/O is fine; mocking the logic under test is not
- Use plain ASCII output only (no unicode/emoji - Windows cp1252)
- Your verdict determines if the task is accepted or sent back for rework
```

---

### HAIKU FILE ANALYZER PROMPT

Used in STEP 2 when regex cannot determine file scope:

```
Analyze this task for a Python FastAPI codebase rooted at c:\fast_swarm.

Task: "{TASK_TEXT}"

The codebase structure:
- src/Fast_Swarm/ - main source
  - Agents/ (Models/, Services/, Routers/, Hivemind/, Coaches/)
  - Patterns/ (Models/, Services/, Routers/)
  - Trading/ (Services/, Routers/)
  - Infrastructure/ (Models/, Services/, Routers/)
  - System/ (Services/, Routers/)
  - Backtest/ (Services/)
  - Metrics/ (Services/)
  - exchanges/ (WebSocket clients)
  - local_agents/ (legacy backtest code)
  - Dashboard/ (HTML/CSS/JS)
- Tests/ (Unit/, Soundness/, Triage/)
- Dashboard/ (standalone copy)

Which files would likely be WRITTEN TO (not just read)?
Use Grep and Glob to identify actual files that exist.
Return ONLY a JSON array of absolute file paths.
Be conservative - include files that MIGHT be touched.
Include test files if the task involves testing.

Example: ["c:\\fast_swarm\\src\\Fast_Swarm\\Trading\\Services\\trading_service.py"]
```

---

## Progress Log Format (Per Agent)

Each agent creates this at `agent-progress/<TASK_ID>.md`:

```markdown
# Progress: [task description truncated to 50 chars]

## Status: IN_PROGRESS | COMPLETED | FAILED
Started: 2026-01-24T10:00:00Z
Finished: (pending)

## Current Step
[What the agent is currently doing]

## Files Modified
- path/to/file.py (description of change)

## Test Results
(TDD+EDD mode only)
- pytest output summary
- Tests passed: N/N

## Discoveries
[Anything other agents should know about]

## Errors
[Any errors encountered]
```

---

## Completion Signal

When ALL tasks in shared-todos.md are `- [x]` and no agents are running:

Output: `ALL TODOS COMPLETED - [N] tasks finished, [M] agents spawned this session`

Then update parallel-todo-state.md to clear the Running Agents table.

---

## Edge Cases

1. **All tasks conflict**: Falls back to sequential (spawn 1 at a time)
2. **Agent hangs**: After 10 minutes with no progress log update, consider it failed
3. **Agent modifies unexpected file**: Detected by gatekeeper or on next poll
4. **New todos added during run**: Picked up on next STEP 0 sync
5. **Shared context grows large**: Focus on last 50 entries when building agent prompts
6. **Gatekeeper rejects repeatedly**: After 2 rejections, mark task with "[NEEDS HUMAN]" and skip
7. **No test file mapping found**: In TDD+EDD mode, agent must create the test file in the correct location

---

## Rules

- Sync shared-todos.md EVERY iteration
- Use absolute file paths always
- Plain ASCII only (Windows cp1252)
- Follow CLAUDE.md conventions
- Never spawn more than MAX_PARALLEL concurrent agents
- In TDD+EDD mode, NEVER mark a task done without passing tests AND gatekeeper approval
- Keep parallel-todo-state.md updated as the single source of truth for locks
