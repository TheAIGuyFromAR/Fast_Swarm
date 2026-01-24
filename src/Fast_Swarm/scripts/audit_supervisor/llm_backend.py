"""
LLM Backend Abstraction
Supports multiple backends:
1. Claude Code CLI (subprocess)
2. OpenAI SDK (works with OpenAI, Anthropic, local models, any compatible API)

Note: Uses asyncio.create_subprocess_exec (not shell) for security.
"""

import asyncio
import json
import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
import time


# ==============================================================================
# LOGGING / PRINTING UTILITIES
# ==============================================================================

class PrintLevel(Enum):
    DEBUG = 0
    INFO = 1
    PROGRESS = 2
    WARNING = 3
    ERROR = 4
    CRITICAL = 5


class AuditPrinter:
    """Centralized printer with levels and formatting."""

    def __init__(self, verbose: bool = True, min_level: PrintLevel = PrintLevel.INFO):
        self.verbose = verbose
        self.min_level = min_level
        self._start_time = datetime.now()

    def _timestamp(self) -> str:
        elapsed = (datetime.now() - self._start_time).total_seconds()
        return f"[{elapsed:8.1f}s]"

    def _format(self, level: PrintLevel, prefix: str, msg: str, **kwargs) -> str:
        ts = self._timestamp()
        level_str = f"[{level.name:8}]"
        formatted = f"{ts} {level_str} {prefix} {msg}"

        # Add any extra key=value pairs
        if kwargs:
            extras = " | ".join(f"{k}={v}" for k, v in kwargs.items())
            formatted += f" | {extras}"

        return formatted

    def _print(self, level: PrintLevel, prefix: str, msg: str, **kwargs):
        if level.value >= self.min_level.value:
            print(self._format(level, prefix, msg, **kwargs))
            sys.stdout.flush()

    def debug(self, msg: str, **kwargs):
        self._print(PrintLevel.DEBUG, "[DEBUG]", msg, **kwargs)

    def info(self, msg: str, **kwargs):
        self._print(PrintLevel.INFO, "[INFO ]", msg, **kwargs)

    def progress(self, msg: str, **kwargs):
        self._print(PrintLevel.PROGRESS, "[PROG ]", msg, **kwargs)

    def warning(self, msg: str, **kwargs):
        self._print(PrintLevel.WARNING, "[WARN ]", msg, **kwargs)

    def error(self, msg: str, **kwargs):
        self._print(PrintLevel.ERROR, "[ERROR]", msg, **kwargs)

    def critical(self, msg: str, **kwargs):
        self._print(PrintLevel.CRITICAL, "[CRIT ]", msg, **kwargs)

    def banner(self, title: str, char: str = "="):
        width = 78
        line = char * width
        padded_title = f" {title} "
        centered = padded_title.center(width, char)
        print(f"\n{line}")
        print(centered)
        print(f"{line}\n")
        sys.stdout.flush()

    def section(self, title: str):
        print(f"\n--- {title} ---")
        sys.stdout.flush()

    def agent_status(self, agent_id: str, status: str, runtime: float, extra: str = ""):
        status_indicators = {
            "PENDING": ".",
            "RUNNING": ">",
            "COMPLETED": "+",
            "STALLED": "!",
            "FAILED": "X",
        }
        indicator = status_indicators.get(status, "?")
        line = f"  [{indicator}] Agent {agent_id:4} | {status:10} | {runtime:6.1f}s"
        if extra:
            line += f" | {extra}"
        print(line)
        sys.stdout.flush()

    def progress_bar(self, current: int, total: int, label: str = "", width: int = 30):
        if total == 0:
            pct = 0
        else:
            pct = current / total
        filled = int(width * pct)
        bar = "=" * filled + "-" * (width - filled)
        print(f"  [{bar}] {current}/{total} {label}")
        sys.stdout.flush()


# Global printer instance
_printer: Optional[AuditPrinter] = None


def get_printer() -> AuditPrinter:
    global _printer
    if _printer is None:
        _printer = AuditPrinter()
    return _printer


def set_printer(printer: AuditPrinter):
    global _printer
    _printer = printer


# ==============================================================================
# BACKEND CONFIGURATION
# ==============================================================================

class BackendType(Enum):
    CLAUDE_CODE_CLI = "claude_code_cli"
    OPENAI_SDK = "openai_sdk"


@dataclass
class BackendConfig:
    """Configuration for LLM backend."""

    backend_type: BackendType = BackendType.OPENAI_SDK

    # OpenAI SDK settings (works with any compatible API)
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: str = "claude-sonnet-4-20250514"

    # Claude Code CLI settings
    claude_code_path: str = "claude"
    working_directory: Optional[Path] = None

    # Common settings
    max_tokens: int = 8192
    temperature: float = 0.0
    timeout_seconds: int = 300

    @classmethod
    def from_env(cls) -> "BackendConfig":
        """Create config from environment variables."""
        config = cls()

        backend_str = os.getenv("AUDIT_BACKEND", "openai_sdk")
        if backend_str == "claude_code_cli":
            config.backend_type = BackendType.CLAUDE_CODE_CLI
        else:
            config.backend_type = BackendType.OPENAI_SDK

        config.api_key = os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        config.base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("LLM_BASE_URL")
        config.model = os.getenv("AUDIT_MODEL", "claude-sonnet-4-20250514")
        config.claude_code_path = os.getenv("CLAUDE_CODE_PATH", "claude")

        return config

    @classmethod
    def for_anthropic(cls, api_key: str, model: str = "claude-sonnet-4-20250514") -> "BackendConfig":
        """Quick config for Anthropic API via OpenAI SDK."""
        return cls(
            backend_type=BackendType.OPENAI_SDK,
            api_key=api_key,
            base_url="https://api.anthropic.com/v1",
            model=model,
        )

    @classmethod
    def for_openai(cls, api_key: str, model: str = "gpt-4o") -> "BackendConfig":
        """Quick config for OpenAI API."""
        return cls(
            backend_type=BackendType.OPENAI_SDK,
            api_key=api_key,
            base_url="https://api.openai.com/v1",
            model=model,
        )

    @classmethod
    def for_local(cls, base_url: str = "http://localhost:8000/v1", model: str = "local-model") -> "BackendConfig":
        """Quick config for local LLM server."""
        return cls(
            backend_type=BackendType.OPENAI_SDK,
            api_key="not-needed",
            base_url=base_url,
            model=model,
        )

    @classmethod
    def for_claude_code(cls, working_directory: Optional[Path] = None) -> "BackendConfig":
        """Quick config for Claude Code CLI."""
        return cls(
            backend_type=BackendType.CLAUDE_CODE_CLI,
            working_directory=working_directory,
        )


# ==============================================================================
# LLM BACKEND ABSTRACT BASE
# ==============================================================================

@dataclass
class LLMResponse:
    """Response from LLM backend."""
    content: str
    success: bool
    error_message: Optional[str] = None
    tokens_used: int = 0
    elapsed_seconds: float = 0.0
    raw_response: Optional[Any] = None


class LLMBackend(ABC):
    """Abstract base for LLM backends."""

    def __init__(self, config: BackendConfig):
        self.config = config
        self.printer = get_printer()

    @abstractmethod
    async def complete(self, prompt: str, system_prompt: Optional[str] = None) -> LLMResponse:
        """Send a completion request."""
        pass

    @abstractmethod
    async def spawn_agent(
        self,
        agent_id: str,
        prompt: str,
        run_in_background: bool = False
    ) -> Dict[str, Any]:
        """Spawn an agent task."""
        pass

    @abstractmethod
    async def check_agent(self, task_id: str) -> Dict[str, Any]:
        """Check status of a spawned agent."""
        pass

    @abstractmethod
    async def poke_agent(self, task_id: str, poke_message: str) -> Dict[str, Any]:
        """Send a follow-up message to a running agent."""
        pass


# ==============================================================================
# OPENAI SDK BACKEND
# ==============================================================================

class OpenAIBackend(LLMBackend):
    """Backend using OpenAI SDK (works with any compatible API)."""

    def __init__(self, config: BackendConfig):
        super().__init__(config)
        self._client = None
        self._async_client = None
        self._active_tasks: Dict[str, Dict[str, Any]] = {}

    def _get_client(self):
        """Lazy-load the OpenAI client."""
        if self._client is None:
            try:
                from openai import OpenAI
                self.printer.debug(f"Initializing OpenAI client", base_url=self.config.base_url)
                self._client = OpenAI(
                    api_key=self.config.api_key,
                    base_url=self.config.base_url,
                )
                self.printer.info(f"OpenAI client initialized", model=self.config.model)
            except ImportError:
                self.printer.error("OpenAI SDK not installed. Run: pip install openai")
                raise
        return self._client

    async def _get_async_client(self):
        """Lazy-load the async OpenAI client."""
        if self._async_client is None:
            try:
                from openai import AsyncOpenAI
                self.printer.debug(f"Initializing AsyncOpenAI client", base_url=self.config.base_url)
                self._async_client = AsyncOpenAI(
                    api_key=self.config.api_key,
                    base_url=self.config.base_url,
                )
            except ImportError:
                self.printer.error("OpenAI SDK not installed. Run: pip install openai")
                raise
        return self._async_client

    async def complete(self, prompt: str, system_prompt: Optional[str] = None) -> LLMResponse:
        """Send a completion request."""
        start_time = time.time()
        self.printer.debug(f"Sending completion request", prompt_len=len(prompt))

        try:
            client = await self._get_async_client()

            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            self.printer.debug(f"Calling chat.completions.create", model=self.config.model)

            response = await client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
            )

            elapsed = time.time() - start_time
            content = response.choices[0].message.content or ""
            tokens = response.usage.total_tokens if response.usage else 0

            self.printer.info(
                f"Completion received",
                tokens=tokens,
                elapsed=f"{elapsed:.1f}s",
                response_len=len(content)
            )

            return LLMResponse(
                content=content,
                success=True,
                tokens_used=tokens,
                elapsed_seconds=elapsed,
                raw_response=response,
            )

        except Exception as e:
            elapsed = time.time() - start_time
            self.printer.error(f"Completion failed: {e}")
            return LLMResponse(
                content="",
                success=False,
                error_message=str(e),
                elapsed_seconds=elapsed,
            )

    async def spawn_agent(
        self,
        agent_id: str,
        prompt: str,
        run_in_background: bool = False
    ) -> Dict[str, Any]:
        """Spawn an agent task."""
        self.printer.progress(f"Spawning agent {agent_id}", background=run_in_background)

        task_info = {
            "task_id": f"openai-{agent_id}-{int(time.time())}",
            "agent_id": agent_id,
            "status": "running",
            "spawned_at": datetime.now().isoformat(),
            "prompt": prompt,
            "output": "",
            "error": None,
        }

        if run_in_background:
            self.printer.debug(f"Creating background task for {agent_id}")

            async def background_work():
                self.printer.debug(f"Background task started for {agent_id}")
                response = await self.complete(prompt)
                task_info["status"] = "completed" if response.success else "failed"
                task_info["output"] = response.content
                task_info["error"] = response.error_message
                task_info["completed_at"] = datetime.now().isoformat()
                self.printer.progress(f"Background task {agent_id} completed", status=task_info["status"])

            asyncio.create_task(background_work())
        else:
            self.printer.debug(f"Running synchronous task for {agent_id}")
            response = await self.complete(prompt)
            task_info["status"] = "completed" if response.success else "failed"
            task_info["output"] = response.content
            task_info["error"] = response.error_message
            task_info["completed_at"] = datetime.now().isoformat()

        self._active_tasks[task_info["task_id"]] = task_info
        self.printer.info(f"Agent {agent_id} spawned", task_id=task_info["task_id"])

        return task_info

    async def check_agent(self, task_id: str) -> Dict[str, Any]:
        """Check status of a spawned agent."""
        if task_id not in self._active_tasks:
            self.printer.warning(f"Task not found: {task_id}")
            return {"status": "not_found", "task_id": task_id}

        task = self._active_tasks[task_id]
        self.printer.debug(f"Checking agent status", task_id=task_id, status=task["status"])
        return task

    async def poke_agent(self, task_id: str, poke_message: str) -> Dict[str, Any]:
        """Send a follow-up to a running agent."""
        self.printer.warning(f"Poking agent", task_id=task_id)

        if task_id not in self._active_tasks:
            return {"status": "not_found", "task_id": task_id}

        task = self._active_tasks[task_id]
        original_prompt = task["prompt"]
        previous_output = task.get("output", "")

        continuation = f"""
{original_prompt}

PREVIOUS PROGRESS:
{previous_output}

WATCHDOG POKE:
{poke_message}

Continue from where you left off. Output your current progress.
"""

        self.printer.debug(f"Sending poke continuation", continuation_len=len(continuation))
        response = await self.complete(continuation)

        task["output"] = response.content
        task["poke_count"] = task.get("poke_count", 0) + 1
        task["last_poke_at"] = datetime.now().isoformat()

        self.printer.info(f"Poke completed", task_id=task_id, poke_count=task["poke_count"])

        return task


# ==============================================================================
# CLAUDE CODE CLI BACKEND
# ==============================================================================

class ClaudeCodeBackend(LLMBackend):
    """Backend using Claude Code CLI (uses safe subprocess_exec, not shell)."""

    def __init__(self, config: BackendConfig):
        super().__init__(config)
        self._active_tasks: Dict[str, Dict[str, Any]] = {}

    async def complete(self, prompt: str, system_prompt: Optional[str] = None) -> LLMResponse:
        """Send a completion request via Claude Code CLI."""
        start_time = time.time()
        self.printer.debug(f"Sending CLI completion", prompt_len=len(prompt))

        try:
            # Build command args list (safe - no shell interpolation)
            cmd_args = [self.config.claude_code_path, "--print"]

            if system_prompt:
                cmd_args.extend(["--system-prompt", system_prompt])

            self.printer.debug(f"Executing subprocess", cmd=cmd_args[0])

            # Use create_subprocess_exec (NOT shell) for security
            process = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.working_directory,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=prompt.encode()),
                timeout=self.config.timeout_seconds
            )

            elapsed = time.time() - start_time
            content = stdout.decode()

            if process.returncode != 0:
                error_msg = stderr.decode()
                self.printer.error(f"CLI returned non-zero", code=process.returncode)
                return LLMResponse(
                    content=content,
                    success=False,
                    error_message=error_msg,
                    elapsed_seconds=elapsed,
                )

            self.printer.info(f"CLI completion received", elapsed=f"{elapsed:.1f}s", response_len=len(content))

            return LLMResponse(
                content=content,
                success=True,
                elapsed_seconds=elapsed,
            )

        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            self.printer.error(f"CLI timeout after {elapsed:.1f}s")
            return LLMResponse(
                content="",
                success=False,
                error_message=f"Timeout after {self.config.timeout_seconds}s",
                elapsed_seconds=elapsed,
            )
        except Exception as e:
            elapsed = time.time() - start_time
            self.printer.error(f"CLI error: {e}")
            return LLMResponse(
                content="",
                success=False,
                error_message=str(e),
                elapsed_seconds=elapsed,
            )

    async def spawn_agent(
        self,
        agent_id: str,
        prompt: str,
        run_in_background: bool = False
    ) -> Dict[str, Any]:
        """Spawn an agent via Claude Code CLI."""
        self.printer.progress(f"Spawning CLI agent {agent_id}", background=run_in_background)

        task_prompt = f"""
Use the Task tool to spawn an agent:

Agent ID: {agent_id}
Run in background: {run_in_background}

Task:
{prompt}
"""

        task_info = {
            "task_id": f"claude-{agent_id}-{int(time.time())}",
            "agent_id": agent_id,
            "status": "running",
            "spawned_at": datetime.now().isoformat(),
            "prompt": prompt,
            "output": "",
            "error": None,
        }

        if run_in_background:
            async def background_work():
                self.printer.debug(f"CLI background task started for {agent_id}")
                response = await self.complete(task_prompt)
                task_info["status"] = "completed" if response.success else "failed"
                task_info["output"] = response.content
                task_info["error"] = response.error_message
                task_info["completed_at"] = datetime.now().isoformat()
                self.printer.progress(f"CLI background task {agent_id} done", status=task_info["status"])

            asyncio.create_task(background_work())
        else:
            response = await self.complete(task_prompt)
            task_info["status"] = "completed" if response.success else "failed"
            task_info["output"] = response.content
            task_info["error"] = response.error_message
            task_info["completed_at"] = datetime.now().isoformat()

        self._active_tasks[task_info["task_id"]] = task_info
        self.printer.info(f"CLI agent {agent_id} spawned", task_id=task_info["task_id"])

        return task_info

    async def check_agent(self, task_id: str) -> Dict[str, Any]:
        """Check status via Claude Code."""
        if task_id not in self._active_tasks:
            self.printer.warning(f"Task not found: {task_id}")
            return {"status": "not_found", "task_id": task_id}

        task = self._active_tasks[task_id]
        self.printer.debug(f"CLI checking agent", task_id=task_id, status=task["status"])
        return task

    async def poke_agent(self, task_id: str, poke_message: str) -> Dict[str, Any]:
        """Poke via Claude Code resume."""
        self.printer.warning(f"CLI poking agent", task_id=task_id)

        if task_id not in self._active_tasks:
            return {"status": "not_found", "task_id": task_id}

        task = self._active_tasks[task_id]

        poke_prompt = f"""
Resume the agent with task_id {task_id}.

Send this poke message:
{poke_message}
"""
        response = await self.complete(poke_prompt)

        task["output"] = response.content
        task["poke_count"] = task.get("poke_count", 0) + 1
        task["last_poke_at"] = datetime.now().isoformat()

        self.printer.info(f"CLI poke completed", task_id=task_id)

        return task


# ==============================================================================
# FACTORY FUNCTION
# ==============================================================================

def create_backend(config: Optional[BackendConfig] = None) -> LLMBackend:
    """Create the appropriate backend based on config."""
    if config is None:
        config = BackendConfig.from_env()

    printer = get_printer()
    printer.info(f"Creating LLM backend", type=config.backend_type.value)

    if config.backend_type == BackendType.OPENAI_SDK:
        printer.info(f"Using OpenAI SDK backend", base_url=config.base_url, model=config.model)
        return OpenAIBackend(config)
    elif config.backend_type == BackendType.CLAUDE_CODE_CLI:
        printer.info(f"Using Claude Code CLI backend", path=config.claude_code_path)
        return ClaudeCodeBackend(config)
    else:
        raise ValueError(f"Unknown backend type: {config.backend_type}")
