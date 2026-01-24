#!/usr/bin/env python3
"""
CODE-O-MATIC 5000 - Fast_Swarm Audit Supervisor

Usage:
    python -m Fast_Swarm.scripts.audit_supervisor.run_audit          # Headless
    python -m Fast_Swarm.scripts.audit_supervisor.run_audit --gui    # Retro GUI

Options:
    --gui           Launch CODE-O-MATIC 5000 retro terminal GUI
    --output-dir    Output directory for reports (default: c:/fast_swarm/audit_output)
"""

import argparse
import asyncio
import sys
import threading
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from Fast_Swarm.scripts.audit_supervisor.config import AuditConfig
from Fast_Swarm.scripts.audit_supervisor.llm_backend import BackendConfig
from Fast_Swarm.scripts.audit_supervisor.orchestrator import AuditOrchestrator


def run_with_gui(orchestrator: AuditOrchestrator):
    """Run the audit with the CODE-O-MATIC 5000 GUI - 80s desk scene."""
    from Fast_Swarm.scripts.audit_supervisor.retro_gui_apple2 import Apple2TerminalGUI as GUI

    # Event to signal stop
    stop_event = threading.Event()

    def on_stop():
        """Emergency stop handler."""
        print("EMERGENCY STOP - Halting audit...")
        stop_event.set()

    def on_input(text: str):
        """User input handler."""
        if text == "START":
            # Start the audit
            thread = threading.Thread(target=orchestrator_thread, daemon=True)
            thread.start()

    # Create GUI
    gui = GUI(on_stop=on_stop, on_user_input=on_input)

    # Connect orchestrator to GUI
    def gui_callback(msg_type: str, *args):
        if msg_type == "phase":
            gui.set_phase(str(args[0]))
        elif msg_type == "stats":
            gui.set_stats(int(args[0]), int(args[1]), int(args[2]))
        elif msg_type == "spider":
            gui.write_spider(str(args[0]), str(args[1]))
        elif msg_type == "complete":
            gui.write_complete(str(args[0]))
        elif msg_type == "message":
            gui.write(str(args[0]))

    orchestrator.set_gui_callback(gui_callback)

    # Run orchestrator in background thread
    async def run_orchestrator():
        try:
            gui.set_phase("SCANNING")

            # Check for stop
            while not stop_event.is_set():
                try:
                    await asyncio.wait_for(
                        orchestrator.run_audit(),
                        timeout=1.0
                    )
                    break  # Completed
                except asyncio.TimeoutError:
                    continue  # Check stop flag again

            if stop_event.is_set():
                gui.write("  *** AUDIT STOPPED ***", (255, 50, 50))
            else:
                gui.set_phase("COMPLETE")
                gui.write(f"  Report: {orchestrator.config.paths.final_report}")

        except Exception as e:
            gui.write(f"  ERROR: {e}", (255, 50, 50))

    def orchestrator_thread():
        asyncio.run(run_orchestrator())

    # Run GUI (blocking) - user types START to begin
    gui.start()


def run_headless(orchestrator: AuditOrchestrator):
    """Run the audit without GUI."""
    asyncio.run(orchestrator.run_audit())


def main():
    parser = argparse.ArgumentParser(
        description="Fast_Swarm Code Audit - CODE-O-MATIC 5000",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch CODE-O-MATIC 5000 retro terminal GUI (requires pygame)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory for reports"
    )

    args = parser.parse_args()

    # Build config with sensible defaults
    config = AuditConfig()
    config.include_fork_analysis = False  # Skip fork by default

    if args.output_dir:
        config.paths.output_dir = args.output_dir
        config.paths.state_file = args.output_dir / "audit_state.json"
        config.paths.dashboard_file = args.output_dir / "dashboard.txt"
        config.paths.final_report = args.output_dir / "AUDIT_REPORT.md"

    # Always use Claude Code CLI backend
    backend_config = BackendConfig.for_claude_code(
        working_directory=config.paths.fast_swarm_root
    )

    # Create orchestrator
    orchestrator = AuditOrchestrator(
        config=config,
        backend_config=backend_config,
    )

    # Run
    print("=" * 60)
    print(" CODE-O-MATIC 5000 - Fast_Swarm Audit ".center(60))
    print("=" * 60)
    print(f"  Mode:    {'GUI' if args.gui else 'Headless'}")
    print(f"  Output:  {config.paths.output_dir}")
    print("=" * 60)

    if args.gui:
        try:
            run_with_gui(orchestrator)
        except ImportError as e:
            print(f"GUI unavailable: {e}")
            print("Install pygame: pip install pygame")
            print("Running headless instead...")
            run_headless(orchestrator)
    else:
        run_headless(orchestrator)


if __name__ == "__main__":
    main()
