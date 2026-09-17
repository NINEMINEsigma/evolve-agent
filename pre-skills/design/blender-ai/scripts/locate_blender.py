"""Locate a Blender executable without hardcoding version or drive letter.

Search order:
1. BLENDER_EXE environment variable
2. <workspace>/programs/blender-*/blender.exe (Windows) or blender (Unix)
3. PATH (`blender`)

Prints the resolved path to stdout. Exits 2 if not found.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _workspace_roots() -> list[Path]:
    roots: list[Path] = []
    ws = os.environ.get("EVOLVE_WS")
    if ws:
        roots.append(Path(ws))
    cwd = Path.cwd()
    roots.append(cwd)
    if cwd.name == "programs":
        roots.append(cwd.parent)
    seen: set[Path] = set()
    out: list[Path] = []
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(resolved)
    return out


def candidates() -> list[Path]:
    found: list[Path] = []
    env = os.environ.get("BLENDER_EXE")
    if env:
        found.append(Path(env))
    for root in _workspace_roots():
        programs = root / "programs"
        if not programs.is_dir():
            continue
        found.extend(sorted(programs.glob("blender-*/blender.exe"), reverse=True))
        found.extend(sorted(programs.glob("blender-*/blender"), reverse=True))
    which = shutil.which("blender")
    if which:
        found.append(Path(which))
    return found


def find_blender() -> Path | None:
    for path in candidates():
        try:
            if path.is_file():
                return path.resolve()
        except OSError:
            continue
    return None


if __name__ == "__main__":
    located = find_blender()
    if located is None:
        sys.stderr.write(
            "Blender executable not found.\n"
            "Set BLENDER_EXE, or extract a portable copy to "
            "<workspace>/programs/blender-<version>-<platform>/blender.exe\n"
        )
        sys.exit(2)
    sys.stdout.write(str(located) + "\n")
