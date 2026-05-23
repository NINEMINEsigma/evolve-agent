"""Code evolution orchestrator — validate fork then trigger the swap.

This module is called by the ``evolve_code`` tool handler after the LLM has
written evolved source files to the fork: namespace.

Flow:
    1. Validate all .py files in fork: (syntax + optional compile check)
    2. If valid → signal the App to exit with code -1
    3. The orchestrator (run.py) catches -1, swaps slow→fast, restarts
"""

from __future__ import annotations

import json
import logging

from evolve.validator import validate_directory, summary
from system.sandbox import Sandbox

logger = logging.getLogger(__name__)

# Exit code that tells the orchestrator to swap slow→fast.
_EXIT_CODE_EVOLVED = -1


def finalize_evolution(
    sandbox: Sandbox,
    *,
    deep: bool = True,
    compile_timeout: int = 30,
) -> str:
    """Validate fork directory and trigger the hot swap if all checks pass.

    Returns a JSON result string suitable for the LLM tool response:

    - On success: ``{"evolved": true, "validation": {"valid": true, ...}}``
      (process exits immediately after returning)
    - On failure: ``{"evolved": false, "validation": {"valid": false, ...}}``
      (LLM can fix issues and retry)

    *deep=True* runs py_compile checks in addition to syntax checks.
    *compile_timeout* is the per-file timeout for py_compile subprocesses.

    Only usable in 'fast' mode.  In 'fallback' mode, returns an error
    without exiting.
    """
    # Resolve fork: to the real path on disk
    try:
        fork_resolved = sandbox.resolve_read("fork:")
    except Exception as exc:
        return _json_error(f"Cannot resolve fork: namespace: {exc}")

    fork_dir = fork_resolved.real
    if not fork_dir.is_dir():
        return _json_error(f"Fork directory does not exist: {fork_dir}")

    logger.info("Validating evolved code in %s (deep=%s)", fork_dir, deep)

    # ---- 1. Validate all .py files ----
    results = validate_directory(fork_dir, deep=deep, timeout=compile_timeout)
    report = summary(results)

    if not report["valid"]:
        logger.warning(
            "Evolution validation FAILED: %d/%d files have errors",
            report["errors"], report["total"],
        )
        return json.dumps(
            {
                "evolved": False,
                "validation": report,
                "hint": (
                    "Fix the errors above using write_fork, then call "
                    "validate_code to check syntax, then call evolve_code "
                    "again when all files pass."
                ),
            },
            ensure_ascii=False,
        )

    # ---- 2. Validation passed — trigger the swap ----
    logger.info(
        "Evolution validation PASSED (%d files ok). Triggering swap.",
        report["total"],
    )

    # Import here to avoid circular dependency at module level.
    from main import request_evolution

    request_evolution()

    return json.dumps(
        {
            "evolved": True,
            "validation": report,
            "message": (
                "All {n} files validated. The orchestrator will now swap "
                "slow→fast and restart with the evolved code."
            ).format(n=report["total"]),
        },
        ensure_ascii=False,
    )


def _json_error(message: str) -> str:
    return json.dumps({"evolved": False, "error": str(message)}, ensure_ascii=False)