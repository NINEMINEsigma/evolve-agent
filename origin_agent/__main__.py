"""Evolve Agent — entry point.

Parses CLI arguments in the run.py orchestrator format (``--key value``
combined into single argv elements), creates a RuntimeContext, wires up
logging, and starts the async App.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Ensure the agent's own directory is first on sys.path so that imports
# like ``from main import App`` and ``from system.context import RuntimeContext``
# resolve correctly regardless of CWD or how the process was launched.
# This is critical when the orchestrator copies the agent source into
# workspace/fast_agent_space/ — the directory name differs from "origin_agent".
_AGENT_DIR = str(Path(__file__).resolve().parent)
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

from main import App  # noqa: E402
from system.context import RuntimeContext  # noqa: E402


# ---------------------------------------------------------------------------
# CLI parsing (run.py orchestrator format)
# ---------------------------------------------------------------------------

def _parse_cli() -> dict:
    """Parse ``--flag value`` combined arguments.

    The orchestrator (run.py) builds each flag+value as a single argv
    element, e.g. ``"--workspace /path/to/ws"``.  This parser splits on
    the **first** space inside a ``--`` prefixed argument.

    Flags without a value (``--flag`` alone) are stored as ``True``.
    """
    parsed: dict = {}
    for arg in sys.argv[1:]:
        if arg.startswith("--"):
            body = arg[2:]
            if " " in body:
                key, val = body.split(" ", 1)
                parsed[key] = val.strip()
            else:
                parsed[body] = True
    return parsed


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging(log_path: str | None, console: bool) -> None:
    """Configure root logger with a file handler and optional console handler."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(fmt)
        root.addHandler(fh)

    if console:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        root.addHandler(ch)


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def _coerce_bool(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("true", "1", "yes", "on")


def _build_context(cli: dict) -> RuntimeContext:
    """Build RuntimeContext from parsed CLI args.

    Paths are resolved to absolute form so downstream code never needs
    to worry about CWD changing.
    """
    return RuntimeContext(
        workspace=Path(cli.get("workspace", ".")).resolve(),
        self_path=Path(cli.get("self", ".")).resolve(),
        fork_path=Path(cli.get("evolve", ".")).resolve(),
        log_path=(
            Path(cli["log"]).resolve() if "log" in cli else Path("agent.log")
        ),
        mode=str(cli.get("mode", "fast")),
        console_log=_coerce_bool(cli.get("console_log", False)),
        # Fallback-mode only fields
        fix_path=(
            Path(cli["fix_fork"]).resolve() if "fix_fork" in cli else None
        ),
        fix_log_path=(
            Path(cli["fix"]).resolve() if "fix" in cli else None
        ),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    cli = _parse_cli()
    ctx = _build_context(cli)

    # Only create a log file if explicitly requested via --log.
    log_target = str(ctx.log_path) if "log" in cli else None
    _setup_logging(log_target, ctx.console_log)

    logger = logging.getLogger("agent")
    logger.info(
        "Evolve Agent starting | mode=%s workspace=%s self=%s",
        ctx.mode, ctx.workspace, ctx.self_path,
    )

    app = App(ctx)
    try:
        exit_code = asyncio.run(app.run())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        exit_code = 0

    logger.info("Evolve Agent exiting | code=%d", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())