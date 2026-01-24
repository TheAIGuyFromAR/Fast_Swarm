"""
Watchdog Supervisor
Monitors all agents for progress, detects stalls, pokes stuck agents.
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import time

from .config import AuditConfig, WatchdogConfig
from .agents import AgentState, AgentStatus
from .llm_backend import LLMBackend, get_printer, AuditPrinter


# ==============================================================================
# POKE MESSAGES
# ==============================================================================

POKE_LEVEL_1 = """
WATCHDOG CHECK-IN: You have been working on [{task_name}] for [{elapsed}] minutes.
Current status check requested.
- If processing: Reply with brief progress update
- If blocked: Describe the blocker
- If waiting: Describe what you're waiting for
Continue with your task.
"""

POKE_LEVEL_2 = """
WATCHDOG ALERT: No progress detected for [{elapsed}] minutes.
REQUIRED: Output your current partial results NOW.
Include:
- What you have completed so far
- What you are currently stuck on
- What you need to continue
If you cannot continue, output what you have and mark status as BLOCKED.
"""

POKE_LEVEL_3 = """
WATCHDOG CRITICAL: Agent appears stuck. Forcing checkpoint.
MANDATORY ACTIONS:
1. Output ALL partial results immediately in the required JSON format
2. List all files you successfully analyzed
3. List all files you did NOT analyze
4. Describe the exact point of failure
The supervisor will decide whether to restart you or reassign your work.
"""


@dataclass
class WatchdogState:
    """Current state of the watchdog."""

    is_running: bool = False
    started_at: Optional[datetime] = None
    last_check_at: Optional[datetime] = None
    check_count: int = 0
    poke_count: int = 0
    escalation_count: int = 0
    health_status: str = "healthy"  # healthy, degraded, critical


@dataclass
class EscalationEvent:
    """Record of an escalation."""

    timestamp: datetime
    agent_id: str
    task_name: str
    issue: str
    partial_output: str
    recommended_action: str
    alternatives: List[str]


class WatchdogSupervisor:
    """
    Monitors all spawned agents for progress.
    Detects stalls, pokes stuck agents, escalates failures.
    """

    def __init__(
        self,
        config: AuditConfig,
        backend: LLMBackend,
        on_escalation: Optional[Callable[[EscalationEvent], None]] = None,
    ):
        self.config = config
        self.watchdog_config = config.watchdog
        self.backend = backend
        self.printer = get_printer()
        self.on_escalation = on_escalation

        # State
        self.state = WatchdogState()
        self.agents: Dict[str, AgentState] = {}
        self.escalations: List[EscalationEvent] = []

        # Control
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

        self.printer.info("WatchdogSupervisor initialized")
        self.printer.debug(
            "Watchdog config",
            heartbeat=f"{self.watchdog_config.heartbeat_interval_sec}s",
            stall_threshold=f"{self.watchdog_config.stall_threshold_sec}s",
            poke_attempts=self.watchdog_config.poke_attempts,
        )

    # ==========================================================================
    # AGENT REGISTRATION
    # ==========================================================================

    def register_agent(self, agent_state: AgentState) -> None:
        """Register an agent for monitoring."""
        agent_id = agent_state.definition.id
        self.agents[agent_id] = agent_state

        self.printer.info(
            f"Agent registered for monitoring",
            agent_id=agent_id,
            name=agent_state.definition.name,
        )

    def unregister_agent(self, agent_id: str) -> None:
        """Remove an agent from monitoring."""
        if agent_id in self.agents:
            del self.agents[agent_id]
            self.printer.info(f"Agent unregistered", agent_id=agent_id)

    def get_agent(self, agent_id: str) -> Optional[AgentState]:
        """Get agent state by ID."""
        return self.agents.get(agent_id)

    # ==========================================================================
    # MAIN LOOP
    # ==========================================================================

    async def start(self) -> None:
        """Start the watchdog monitoring loop."""
        if self.state.is_running:
            self.printer.warning("Watchdog already running")
            return

        self.printer.banner("WATCHDOG STARTING")
        self.state.is_running = True
        self.state.started_at = datetime.now()
        self._stop_event.clear()

        self._task = asyncio.create_task(self._monitoring_loop())
        self.printer.info("Watchdog monitoring loop started")

    async def stop(self) -> None:
        """Stop the watchdog monitoring loop."""
        if not self.state.is_running:
            self.printer.warning("Watchdog not running")
            return

        self.printer.info("Stopping watchdog...")
        self._stop_event.set()

        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self.printer.warning("Watchdog stop timed out, cancelling")
                self._task.cancel()

        self.state.is_running = False
        self.printer.info("Watchdog stopped")

    async def _monitoring_loop(self) -> None:
        """Main monitoring loop."""
        self.printer.debug("Entering monitoring loop")

        while not self._stop_event.is_set():
            try:
                # Perform health check
                await self._check_all_agents()
                self.state.check_count += 1
                self.state.last_check_at = datetime.now()

                # Update health status
                self._update_health_status()

                # Emit dashboard
                self._emit_dashboard()

                # Wait for next interval
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.watchdog_config.heartbeat_interval_sec
                    )
                    # If we get here, stop was requested
                    break
                except asyncio.TimeoutError:
                    # Normal timeout, continue loop
                    pass

            except Exception as e:
                self.printer.error(f"Monitoring loop error: {e}")
                await asyncio.sleep(5)  # Brief pause before retry

        self.printer.debug("Exited monitoring loop")

    # ==========================================================================
    # AGENT CHECKING
    # ==========================================================================

    async def _check_all_agents(self) -> None:
        """Check all registered agents for progress."""
        self.printer.debug(f"Checking {len(self.agents)} agents")

        for agent_id, agent_state in list(self.agents.items()):
            await self._check_agent(agent_id, agent_state)

    async def _check_agent(self, agent_id: str, agent_state: AgentState) -> None:
        """Check a single agent for progress."""
        # Skip completed/failed agents
        if agent_state.status in (AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.SKIPPED):
            return

        # Skip pending agents (not yet started)
        if agent_state.status == AgentStatus.PENDING:
            return

        # Check for progress by reading output
        if agent_state.task_id:
            task_info = await self.backend.check_agent(agent_state.task_id)
            output = task_info.get("output", "")

            # Did output change?
            made_progress = agent_state.update_progress(output)

            if made_progress:
                self.printer.debug(
                    f"Agent progress detected",
                    agent_id=agent_id,
                    output_len=len(output),
                )
                agent_state.poke_count = 0  # Reset poke counter
                return

        # No progress - check if stalled
        time_since_progress = agent_state.time_since_progress

        if time_since_progress > self.watchdog_config.stall_threshold_sec:
            self.printer.warning(
                f"Agent appears stalled",
                agent_id=agent_id,
                stalled_for=f"{time_since_progress:.0f}s",
                poke_count=agent_state.poke_count,
            )

            if agent_state.poke_count < self.watchdog_config.poke_attempts:
                # Poke the agent
                await self._poke_agent(agent_id, agent_state)
            else:
                # Escalate
                await self._escalate_agent(agent_id, agent_state)

    # ==========================================================================
    # POKING
    # ==========================================================================

    async def _poke_agent(self, agent_id: str, agent_state: AgentState) -> None:
        """Poke a stalled agent."""
        poke_level = agent_state.poke_count + 1
        elapsed_mins = agent_state.time_since_progress / 60

        self.printer.warning(
            f"POKING AGENT",
            agent_id=agent_id,
            level=poke_level,
            elapsed=f"{elapsed_mins:.1f}min",
        )

        # Select poke message based on level
        if poke_level == 1:
            poke_template = POKE_LEVEL_1
        elif poke_level == 2:
            poke_template = POKE_LEVEL_2
        else:
            poke_template = POKE_LEVEL_3

        poke_message = poke_template.format(
            task_name=agent_state.definition.name,
            elapsed=f"{elapsed_mins:.1f}",
        )

        # Send poke
        if agent_state.task_id:
            self.printer.debug(f"Sending poke to task {agent_state.task_id}")
            result = await self.backend.poke_agent(agent_state.task_id, poke_message)

            agent_state.poke_count += 1
            self.state.poke_count += 1

            self.printer.info(
                f"Poke sent",
                agent_id=agent_id,
                poke_count=agent_state.poke_count,
                response_len=len(result.get("output", "")),
            )

            # Update partial output
            if result.get("output"):
                agent_state.partial_output["last_poke_response"] = result["output"]

            # Wait cooldown before next poke
            await asyncio.sleep(self.watchdog_config.poke_cooldown_sec)

    # ==========================================================================
    # ESCALATION
    # ==========================================================================

    async def _escalate_agent(self, agent_id: str, agent_state: AgentState) -> None:
        """Escalate a stalled agent to the supervisor."""
        self.printer.critical(
            f"ESCALATING AGENT",
            agent_id=agent_id,
            pokes_exhausted=agent_state.poke_count,
        )

        agent_state.status = AgentStatus.STALLED
        self.state.escalation_count += 1

        # Build escalation event
        event = EscalationEvent(
            timestamp=datetime.now(),
            agent_id=agent_id,
            task_name=agent_state.definition.name,
            issue=f"No progress for {agent_state.time_since_progress:.0f}s after {agent_state.poke_count} pokes",
            partial_output=json.dumps(agent_state.partial_output, indent=2),
            recommended_action="RESTART",
            alternatives=["REASSIGN", "SKIP", "MANUAL"],
        )

        self.escalations.append(event)

        # Notify callback if registered
        if self.on_escalation:
            self.printer.debug("Calling escalation callback")
            self.on_escalation(event)

        self.printer.error(
            f"Agent escalated",
            agent_id=agent_id,
            recommended=event.recommended_action,
        )

    # ==========================================================================
    # HEALTH STATUS
    # ==========================================================================

    def _update_health_status(self) -> None:
        """Update overall health status based on agent states."""
        stalled_count = sum(1 for a in self.agents.values() if a.status == AgentStatus.STALLED)
        failed_count = sum(1 for a in self.agents.values() if a.status == AgentStatus.FAILED)
        running_count = sum(1 for a in self.agents.values() if a.status == AgentStatus.RUNNING)

        if stalled_count > 2 or failed_count > 2:
            self.state.health_status = "critical"
        elif stalled_count > 0 or failed_count > 0:
            self.state.health_status = "degraded"
        else:
            self.state.health_status = "healthy"

        self.printer.debug(
            f"Health status updated",
            status=self.state.health_status,
            running=running_count,
            stalled=stalled_count,
            failed=failed_count,
        )

    # ==========================================================================
    # DASHBOARD OUTPUT
    # ==========================================================================

    def _emit_dashboard(self) -> None:
        """Print the status dashboard."""
        if not self.config.verbose:
            return

        # Build status counts
        status_counts = {s: 0 for s in AgentStatus}
        for agent in self.agents.values():
            status_counts[agent.status] += 1

        # Print header
        print("\n" + "=" * 78)
        print(f" WATCHDOG STATUS - {datetime.now().strftime('%H:%M:%S')} ".center(78, "="))
        print("=" * 78)

        # Health status
        health_indicator = {
            "healthy": "[OK]",
            "degraded": "[!!]",
            "critical": "[XX]",
        }
        print(f"\nOVERALL HEALTH: {health_indicator.get(self.state.health_status, '[??]')} {self.state.health_status.upper()}")

        # Stats
        print(f"\nSTATS: checks={self.state.check_count} | pokes={self.state.poke_count} | escalations={self.state.escalation_count}")

        # Agent counts by status
        print(f"\nAGENT STATUS SUMMARY:")
        print(f"  PENDING:   {status_counts[AgentStatus.PENDING]:3}")
        print(f"  RUNNING:   {status_counts[AgentStatus.RUNNING]:3}")
        print(f"  COMPLETED: {status_counts[AgentStatus.COMPLETED]:3}")
        print(f"  STALLED:   {status_counts[AgentStatus.STALLED]:3}")
        print(f"  FAILED:    {status_counts[AgentStatus.FAILED]:3}")

        # Agent details table
        print(f"\nAGENT DETAILS:")
        print("+--------+------------------------------+------------+----------+-------+")
        print("| ID     | Name                         | Status     | Runtime  | Pokes |")
        print("+--------+------------------------------+------------+----------+-------+")

        for agent_id, agent in sorted(self.agents.items()):
            name = agent.definition.name[:28]
            status = agent.status.value.upper()
            runtime = agent.runtime_seconds
            pokes = agent.poke_count
            flag = " <--" if agent.status == AgentStatus.STALLED else ""

            print(f"| {agent_id:6} | {name:28} | {status:10} | {runtime:6.1f}s | {pokes:5} |{flag}")

        print("+--------+------------------------------+------------+----------+-------+")

        # Recent escalations
        if self.escalations:
            recent = self.escalations[-3:]  # Last 3
            print(f"\nRECENT ESCALATIONS:")
            for esc in recent:
                print(f"  [{esc.timestamp.strftime('%H:%M:%S')}] {esc.agent_id}: {esc.issue[:50]}")

        print("=" * 78 + "\n")

    # ==========================================================================
    # STATE PERSISTENCE
    # ==========================================================================

    def save_state(self, path: Optional[Path] = None) -> None:
        """Save watchdog state to file."""
        if path is None:
            path = self.config.paths.output_dir / "watchdog_state.json"

        state_data = {
            "watchdog": {
                "is_running": self.state.is_running,
                "started_at": self.state.started_at.isoformat() if self.state.started_at else None,
                "last_check_at": self.state.last_check_at.isoformat() if self.state.last_check_at else None,
                "check_count": self.state.check_count,
                "poke_count": self.state.poke_count,
                "escalation_count": self.state.escalation_count,
                "health_status": self.state.health_status,
            },
            "agents": {
                agent_id: agent.to_dict()
                for agent_id, agent in self.agents.items()
            },
            "escalations": [
                {
                    "timestamp": esc.timestamp.isoformat(),
                    "agent_id": esc.agent_id,
                    "task_name": esc.task_name,
                    "issue": esc.issue,
                    "recommended_action": esc.recommended_action,
                }
                for esc in self.escalations
            ],
        }

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(state_data, f, indent=2)

        self.printer.debug(f"State saved", path=str(path))

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of watchdog state for reporting."""
        return {
            "health_status": self.state.health_status,
            "check_count": self.state.check_count,
            "poke_count": self.state.poke_count,
            "escalation_count": self.state.escalation_count,
            "agents_monitored": len(self.agents),
            "agents_completed": sum(1 for a in self.agents.values() if a.status == AgentStatus.COMPLETED),
            "agents_failed": sum(1 for a in self.agents.values() if a.status in (AgentStatus.FAILED, AgentStatus.STALLED)),
        }
