"""
Audit Orchestrator
Main coordinator that runs the multi-phase audit using the configured backend.
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import time

from .config import AuditConfig
from .agents import (
    AgentDefinition, AgentState, AgentStatus, AgentPhase,
    get_tier1_agents, get_tier2_agents, get_tier3_agents,
    get_tier4_agents, get_tier5_agents, get_tier6_agents,
    get_all_agent_definitions,
)
from .watchdog import WatchdogSupervisor, EscalationEvent
from .llm_backend import (
    LLMBackend, BackendConfig, create_backend,
    get_printer, set_printer, AuditPrinter, PrintLevel,
)


class AuditOrchestrator:
    """
    Master orchestrator for the multi-phase code audit.

    Coordinates:
    - Agent spawning (parallel within phases)
    - Phase transitions
    - Result collection
    - Watchdog supervision
    - Final report generation
    """

    def __init__(
        self,
        config: Optional[AuditConfig] = None,
        backend_config: Optional[BackendConfig] = None,
    ):
        # Configuration
        self.config = config or AuditConfig()
        self.config.paths.ensure_dirs()

        # Printer
        self.printer = AuditPrinter(
            verbose=self.config.verbose,
            min_level=PrintLevel.DEBUG if self.config.verbose else PrintLevel.INFO,
        )
        set_printer(self.printer)

        # Backend
        self.backend = create_backend(backend_config)

        # Agent definitions and states
        self.agent_definitions = {a.id: a for a in get_all_agent_definitions()}
        self.agent_states: Dict[str, AgentState] = {}

        # Phase management
        self.current_phase = AgentPhase.BOOTSTRAP
        self.phase_results: Dict[AgentPhase, Dict[str, Any]] = {}

        # Watchdog
        self.watchdog = WatchdogSupervisor(
            config=self.config,
            backend=self.backend,
            on_escalation=self._handle_escalation,
        )

        # State
        self._start_time: Optional[datetime] = None
        self._is_running = False

        # GUI callback (optional)
        self.gui_callback: Optional[callable] = None

        self.printer.info("AuditOrchestrator initialized")
        self.printer.debug(
            "Configuration",
            include_fork=self.config.include_fork_analysis,
            verbose=self.config.verbose,
        )

    # ==========================================================================
    # MAIN ENTRY POINT
    # ==========================================================================

    async def run_audit(self) -> Path:
        """
        Run the complete audit.
        Returns path to final report.
        """
        self.printer.banner("FAST_SWARM COMPREHENSIVE AUDIT")
        self._start_time = datetime.now()
        self._is_running = True

        try:
            # Phase 0: Bootstrap
            await self._run_bootstrap()

            # Start watchdog
            await self.watchdog.start()

            # Phase 1: Section Reviews (parallel)
            await self._run_phase(AgentPhase.SECTION_REVIEW, get_tier1_agents())

            # Phase 2: Synthesis (parallel)
            await self._run_phase(AgentPhase.SYNTHESIS, get_tier2_agents())

            # Phase 3: Documentation Analysis (parallel)
            if self.config.include_doc_analysis:
                await self._run_phase(AgentPhase.DOCUMENTATION, get_tier3_agents())

            # Phase 4: Fork Analysis (parallel)
            if self.config.include_fork_analysis:
                await self._run_phase(AgentPhase.FORK_ANALYSIS, get_tier4_agents())

            # Phase 5: Reconciliation (sequential)
            await self._run_phase(AgentPhase.RECONCILIATION, get_tier5_agents())

            # Phase 6: Final Report (sequential)
            await self._run_phase(AgentPhase.FINAL_REPORT, get_tier6_agents())

            # Stop watchdog
            await self.watchdog.stop()

            # Save results
            report_path = self._save_final_report()

            self.printer.banner("AUDIT COMPLETE")
            self.printer.info(f"Report saved to: {report_path}")

            return report_path

        except Exception as e:
            self.printer.critical(f"Audit failed: {e}")
            await self.watchdog.stop()
            raise

        finally:
            self._is_running = False

    # ==========================================================================
    # BOOTSTRAP
    # ==========================================================================

    async def _run_bootstrap(self):
        """Phase 0: Establish baseline metrics."""
        self.printer.banner("PHASE 0: BOOTSTRAP")
        self.current_phase = AgentPhase.BOOTSTRAP

        self.printer.info("Gathering baseline metrics...")

        # Count files
        fast_swarm_files = list(self.config.paths.fast_swarm_src.rglob("*.py"))
        self.printer.info(f"Fast_Swarm Python files: {len(fast_swarm_files)}")

        # Count fork files if enabled
        fork_files = []
        if self.config.include_fork_analysis:
            fork_files = list(self.config.paths.fork_root.rglob("*.py"))
            self.printer.info(f"Fork Python files: {len(fork_files)}")

        # Line counts
        total_lines = 0
        for f in fast_swarm_files[:100]:  # Sample first 100
            try:
                total_lines += len(f.read_text().splitlines())
            except:
                pass
        estimated_total = total_lines * len(fast_swarm_files) // min(100, len(fast_swarm_files))
        self.printer.info(f"Estimated total lines: {estimated_total:,}")

        # Store bootstrap results
        self.phase_results[AgentPhase.BOOTSTRAP] = {
            "fast_swarm_file_count": len(fast_swarm_files),
            "fork_file_count": len(fork_files),
            "estimated_lines": estimated_total,
            "start_time": self._start_time.isoformat(),
        }

        # Initialize agent states
        for agent_id, definition in self.agent_definitions.items():
            self.agent_states[agent_id] = AgentState(definition=definition)

        self.printer.info("Bootstrap complete")
        self._notify_gui("phase", "BOOTSTRAP COMPLETE")

    # ==========================================================================
    # PHASE EXECUTION
    # ==========================================================================

    async def _run_phase(self, phase: AgentPhase, agent_defs: List[AgentDefinition]):
        """Run a single phase with its agents."""
        self.printer.banner(f"PHASE {phase.value}: {phase.name}")
        self.current_phase = phase
        self._notify_gui("phase", phase.name)

        # Filter agents for this phase
        phase_agents = [a for a in agent_defs if a.phase == phase]
        self.printer.info(f"Agents in phase: {len(phase_agents)}")

        # Check dependencies
        for agent_def in phase_agents:
            for dep_id in agent_def.depends_on:
                dep_state = self.agent_states.get(dep_id)
                if dep_state and dep_state.status != AgentStatus.COMPLETED:
                    self.printer.warning(
                        f"Agent {agent_def.id} depends on incomplete {dep_id}"
                    )

        # Spawn agents in parallel
        spawn_tasks = []
        for agent_def in phase_agents:
            agent_state = self.agent_states[agent_def.id]
            spawn_tasks.append(self._spawn_agent(agent_def, agent_state))

        # Wait for all to complete
        if spawn_tasks:
            results = await asyncio.gather(*spawn_tasks, return_exceptions=True)

            # Process results
            for i, result in enumerate(results):
                agent_id = phase_agents[i].id
                if isinstance(result, Exception):
                    self.printer.error(f"Agent {agent_id} failed: {result}")
                    self.agent_states[agent_id].status = AgentStatus.FAILED
                    self.agent_states[agent_id].error_message = str(result)
                else:
                    self.printer.info(f"Agent {agent_id} completed")

        # Collect phase results
        phase_outputs = {}
        for agent_def in phase_agents:
            state = self.agent_states[agent_def.id]
            if state.status == AgentStatus.COMPLETED:
                phase_outputs[agent_def.id] = state.partial_output

        self.phase_results[phase] = phase_outputs

        # Update GUI
        completed = sum(1 for s in self.agent_states.values() if s.status == AgentStatus.COMPLETED)
        total = len(self.agent_states)
        self._notify_gui("agents", completed, total)

        self.printer.info(f"Phase {phase.name} complete")

    async def _spawn_agent(self, definition: AgentDefinition, state: AgentState):
        """Spawn a single agent and wait for completion."""
        self.printer.progress(f"Spawning agent {definition.id}: {definition.name}")

        state.status = AgentStatus.RUNNING
        state.spawned_at = datetime.now()

        # Register with watchdog
        self.watchdog.register_agent(state)

        # Build prompt with context
        context = {
            "scope": ", ".join(definition.scope),
            "output_schema": json.dumps(definition.output_schema, indent=2),
        }

        # Add tier1 outputs for synthesis agents
        if definition.depends_on:
            tier1_outputs = {}
            for dep_id in definition.depends_on:
                dep_state = self.agent_states.get(dep_id)
                if dep_state and dep_state.partial_output:
                    tier1_outputs[dep_id] = dep_state.partial_output
            context["tier1_outputs"] = json.dumps(tier1_outputs, indent=2)

        prompt = definition.get_prompt(context)

        # Spawn via backend
        try:
            task_info = await self.backend.spawn_agent(
                agent_id=definition.id,
                prompt=prompt,
                run_in_background=False,  # Wait for completion
            )

            state.task_id = task_info.get("task_id")
            state.completed_at = datetime.now()

            # Parse output
            output = task_info.get("output", "")
            if output:
                try:
                    # Try to parse as JSON
                    state.partial_output = json.loads(output)
                except json.JSONDecodeError:
                    # Store as raw text
                    state.partial_output = {"raw_output": output}

            state.status = AgentStatus.COMPLETED
            self.printer.info(
                f"Agent {definition.id} completed",
                runtime=f"{state.runtime_seconds:.1f}s",
            )

        except Exception as e:
            state.status = AgentStatus.FAILED
            state.error_message = str(e)
            state.completed_at = datetime.now()
            self.printer.error(f"Agent {definition.id} failed: {e}")
            raise

        finally:
            self.watchdog.unregister_agent(definition.id)

        return state

    # ==========================================================================
    # ESCALATION HANDLING
    # ==========================================================================

    def _handle_escalation(self, event: EscalationEvent):
        """Handle watchdog escalation."""
        self.printer.critical(
            f"ESCALATION: Agent {event.agent_id}",
            issue=event.issue,
            recommended=event.recommended_action,
        )

        # For now, mark as failed and continue
        # In a more sophisticated system, we could:
        # - Retry the agent
        # - Split the work
        # - Ask user for guidance

        state = self.agent_states.get(event.agent_id)
        if state:
            state.status = AgentStatus.FAILED
            state.error_message = event.issue

        self._notify_gui("error", f"Agent {event.agent_id} failed: {event.issue}")

    # ==========================================================================
    # REPORT GENERATION
    # ==========================================================================

    def _save_final_report(self) -> Path:
        """Save the final audit report."""
        self.printer.info("Generating final report...")

        # Get report content from Phase 6 agent
        report_state = self.agent_states.get("6A")
        if report_state and report_state.partial_output:
            report_content = report_state.partial_output.get(
                "raw_output",
                json.dumps(report_state.partial_output, indent=2)
            )
        else:
            # Generate fallback report
            report_content = self._generate_fallback_report()

        # Save report
        report_path = self.config.paths.final_report
        report_path.write_text(report_content)

        # Save raw results
        results_path = self.config.paths.output_dir / "audit_results.json"
        results_data = {
            "metadata": {
                "start_time": self._start_time.isoformat() if self._start_time else None,
                "end_time": datetime.now().isoformat(),
                "config": {
                    "include_fork": self.config.include_fork_analysis,
                    "include_docs": self.config.include_doc_analysis,
                },
            },
            "agents": {
                agent_id: state.to_dict()
                for agent_id, state in self.agent_states.items()
            },
            "phase_results": {
                phase.name: data
                for phase, data in self.phase_results.items()
            },
            "watchdog_summary": self.watchdog.get_summary(),
        }
        results_path.write_text(json.dumps(results_data, indent=2, default=str))

        self.printer.info(f"Results saved to: {results_path}")

        return report_path

    def _generate_fallback_report(self) -> str:
        """Generate a fallback report if the report agent failed."""
        lines = [
            "# Fast_Swarm Audit Report",
            f"Generated: {datetime.now().isoformat()}",
            "",
            "## Status",
            "",
        ]

        # Agent summary
        completed = sum(1 for s in self.agent_states.values() if s.status == AgentStatus.COMPLETED)
        failed = sum(1 for s in self.agent_states.values() if s.status == AgentStatus.FAILED)
        total = len(self.agent_states)

        lines.append(f"- Agents completed: {completed}/{total}")
        lines.append(f"- Agents failed: {failed}/{total}")
        lines.append("")

        # Phase summaries
        lines.append("## Phase Results")
        lines.append("")

        for phase, results in self.phase_results.items():
            lines.append(f"### {phase.name}")
            if isinstance(results, dict):
                for key, value in results.items():
                    if isinstance(value, dict):
                        lines.append(f"- {key}: {len(value)} items")
                    else:
                        lines.append(f"- {key}: {value}")
            lines.append("")

        return "\n".join(lines)

    # ==========================================================================
    # GUI INTEGRATION
    # ==========================================================================

    def set_gui_callback(self, callback: callable):
        """Set callback for GUI updates."""
        self.gui_callback = callback

    def _notify_gui(self, msg_type: str, *args):
        """Send update to GUI if connected."""
        if self.gui_callback:
            self.gui_callback(msg_type, *args)


# ==============================================================================
# CLI ENTRY POINT
# ==============================================================================

async def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Fast_Swarm Code Audit")
    parser.add_argument("--no-fork", action="store_true", help="Skip fork analysis")
    parser.add_argument("--no-docs", action="store_true", help="Skip doc analysis")
    parser.add_argument("--quiet", action="store_true", help="Less verbose output")
    parser.add_argument("--backend", choices=["openai", "claude_cli"], default="openai")
    parser.add_argument("--model", default="claude-sonnet-4-20250514", help="Model to use")
    parser.add_argument("--api-key", help="API key (or use env var)")
    parser.add_argument("--base-url", help="API base URL")

    args = parser.parse_args()

    # Build config
    config = AuditConfig()
    config.include_fork_analysis = not args.no_fork
    config.include_doc_analysis = not args.no_docs
    config.verbose = not args.quiet

    # Backend config
    if args.backend == "claude_cli":
        backend_config = BackendConfig.for_claude_code()
    else:
        import os
        api_key = args.api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")
        backend_config = BackendConfig(
            api_key=api_key,
            base_url=args.base_url,
            model=args.model,
        )

    # Run audit
    orchestrator = AuditOrchestrator(config=config, backend_config=backend_config)
    report_path = await orchestrator.run_audit()

    print(f"\n{'='*60}")
    print(f"Audit complete! Report: {report_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
