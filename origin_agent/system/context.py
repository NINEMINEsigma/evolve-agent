"""Runtime context — single source of truth for all configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict


class RuntimeContext(BaseModel):
    """Immutable runtime configuration.

    Populated by __main__.py from CLI arguments.  All paths are resolved to
    absolute form so downstream code never has to worry about CWD.
    """

    model_config = ConfigDict(frozen=True)

    # -- Paths (all absolute) -----------------------------------------------

    workspace: Path
    """Root workspace directory (e.g. ``workspace/``)."""

    self_path: Path
    """Directory containing the agent's own source code (fast directory)."""

    fork_path: Path
    """Directory where evolved code is written (slow directory)."""

    log_path: Path
    """Path to the log file produced by the orchestrator."""

    # -- Runtime flags ------------------------------------------------------

    mode: str = "fast"
    """Execution mode: ``"fast"`` (normal) or ``"fallback"`` (repair)."""

    console_log: bool = False

    # -- Fallback-mode fields -----------------------------------------------

    fix_path: Optional[Path] = None
    """When mode=='fallback', the directory to repair (the broken fast)."""

    fix_log_path: Optional[Path] = None
    """When mode=='fallback', path to the error log to consult."""

    # -- Gateway config -----------------------------------------------------

    gateway_host: str = "127.0.0.1"
    gateway_port: int = 8765

    # -- LLM config (populated later from env / config file) ----------------

    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"
    llm_temperature: float = 0.7
    llm_max_tokens: int = 4096