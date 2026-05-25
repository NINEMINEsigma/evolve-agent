"""Shared path utilities — find project root.

Used by prompt.py, memory/provider.py, and shell.py to locate
the project root consistently (by walking up to find run.py).
"""

from pathlib import Path


def find_repo_root() -> Path:
    """Walk up from this module to find the project root (where run.py lives)."""
    p = Path(__file__).resolve()
    for _ in range(6):
        p = p.parent
        if (p / "run.py").exists():
            return p
    return Path(__file__).resolve().parents[3]  # fallback