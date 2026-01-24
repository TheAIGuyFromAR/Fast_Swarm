"""
Audit Supervisor Configuration
All timing, paths, and behavioral settings.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import os


@dataclass
class WatchdogConfig:
    """Watchdog timing and behavior settings."""

    heartbeat_interval_sec: int = 30      # How often to check each agent
    stall_threshold_sec: int = 120        # No progress = stalled
    poke_attempts: int = 3                # Times to poke before escalating
    poke_cooldown_sec: int = 15           # Wait between pokes
    meta_check_interval_sec: int = 300    # Watchdog self-check interval


@dataclass
class PathConfig:
    """File and directory paths."""

    # Fast_Swarm paths
    fast_swarm_root: Path = field(default_factory=lambda: Path("c:/fast_swarm"))
    fast_swarm_src: Path = field(default_factory=lambda: Path("c:/fast_swarm/src/Fast_Swarm"))

    # Fork paths (original Coinswarm)
    fork_root: Path = field(default_factory=lambda: Path("C:/Users/Admin/Documents/Coinswarm-1/local-utilities"))

    # Output paths
    output_dir: Path = field(default_factory=lambda: Path("c:/fast_swarm/audit_output"))
    state_file: Path = field(default_factory=lambda: Path("c:/fast_swarm/audit_output/audit_state.json"))
    dashboard_file: Path = field(default_factory=lambda: Path("c:/fast_swarm/audit_output/dashboard.txt"))
    final_report: Path = field(default_factory=lambda: Path("c:/fast_swarm/audit_output/AUDIT_REPORT.md"))

    def ensure_dirs(self) -> None:
        """Create output directories if they don't exist."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "agent_outputs").mkdir(exist_ok=True)
        (self.output_dir / "phase_results").mkdir(exist_ok=True)


@dataclass
class AgentConfig:
    """Agent spawning and management settings."""

    max_parallel_agents: int = 8          # Max agents running simultaneously
    agent_timeout_sec: int = 600          # 10 minute max per agent
    retry_failed_agents: bool = True      # Retry on failure
    max_retries: int = 2                  # Max retry attempts
    capture_partial_on_fail: bool = True  # Save partial results on failure


@dataclass
class AuditConfig:
    """Master configuration for the audit system."""

    watchdog: WatchdogConfig = field(default_factory=WatchdogConfig)
    paths: PathConfig = field(default_factory=PathConfig)
    agents: AgentConfig = field(default_factory=AgentConfig)

    # Audit scope flags
    include_fork_analysis: bool = True    # Analyze local-utilities fork
    include_dead_code: bool = True        # Run dead code detection
    include_test_coverage: bool = True    # Analyze test coverage
    include_doc_analysis: bool = True     # Analyze documentation

    # Output settings
    verbose: bool = True                  # Detailed logging
    save_intermediate: bool = True        # Save phase results

    @classmethod
    def from_env(cls) -> "AuditConfig":
        """Create config from environment variables."""
        config = cls()

        # Override paths from env if set
        if fork_path := os.getenv("AUDIT_FORK_PATH"):
            config.paths.fork_root = Path(fork_path)
        if output_path := os.getenv("AUDIT_OUTPUT_PATH"):
            config.paths.output_dir = Path(output_path)

        # Override flags from env
        config.include_fork_analysis = os.getenv("AUDIT_INCLUDE_FORK", "1") == "1"
        config.verbose = os.getenv("AUDIT_VERBOSE", "1") == "1"

        return config

    def validate(self) -> List[str]:
        """Validate configuration, return list of issues."""
        issues = []

        if not self.paths.fast_swarm_src.exists():
            issues.append(f"Fast_Swarm source not found: {self.paths.fast_swarm_src}")

        if self.include_fork_analysis and not self.paths.fork_root.exists():
            issues.append(f"Fork path not found: {self.paths.fork_root}")

        if self.watchdog.stall_threshold_sec <= self.watchdog.heartbeat_interval_sec:
            issues.append("Stall threshold must be > heartbeat interval")

        return issues
