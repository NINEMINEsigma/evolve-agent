"""Auto-discovery of tool modules via AST scanning.

Functions:
    discover_builtin_tools(tools_dir) -> List[str]
        Scan directory for .py files that contain registry.register() calls
        at module level, import them, return list of imported module names.

    _module_registers_tools(module_path) -> bool
        Use ast.parse to detect registry.register() at module level.

    _is_registry_register_call(node) -> bool
        Check if an AST node is a registry.register(...) call.

Pure Python stdlib — no external dependencies.
"""

import ast
import importlib
import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

_EXCLUDED_FILENAMES = frozenset({"__init__.py", "registry.py"})


def _is_registry_register_call(node: ast.AST) -> bool:
    """Return True when *node* is a ``registry.register(...)`` call expression."""
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return False
    func = node.value.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "register"
        and isinstance(func.value, ast.Name)
        and func.value.id == "registry"
    )


def _module_registers_tools(module_path: Path) -> bool:
    """Return True when the module contains a top-level ``registry.register(...)`` call.

    Only inspects module-body statements so that helper modules which happen
    to call ``registry.register()`` inside a function are not picked up.
    """
    try:
        source = module_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(module_path))
    except (OSError, SyntaxError):
        return False

    return any(_is_registry_register_call(stmt) for stmt in tree.body)


def discover_builtin_tools(tools_dir: str) -> List[str]:
    """Scan *tools_dir* for tool modules, import them, and return module names.

    Steps:
      1. List every ``.py`` file in the directory.
      2. Skip ``__init__.py``, ``registry.py``, and any file whose stem starts
         with ``_``.
      3. For each remaining file, AST-scan for a module-level
         ``registry.register(...)`` call (see ``_module_registers_tools``).
      4. Import each qualifying module by dotted name relative to the
         ``tools_dir`` parent package.
      5. Return a list of the successfully imported module names.

    Modules that fail to import are logged as warnings and skipped.
    """
    tools_path = Path(tools_dir).resolve()
    module_names: List[str] = []

    for path in sorted(tools_path.glob("*.py")):
        if path.name in _EXCLUDED_FILENAMES:
            continue
        if path.stem.startswith("_"):
            continue
        if not _module_registers_tools(path):
            continue

        # Derive a dotted module name relative to the containing package.
        # E.g. if tools_dir is /home/hermes/hermes-agent/tools/
        # and the file is my_tool.py, the module name is "tools.my_tool".
        parent_pkg = tools_path.parent.name
        mod_name = f"{parent_pkg}.{path.stem}"
        module_names.append(mod_name)

    imported: List[str] = []
    for mod_name in module_names:
        try:
            importlib.import_module(mod_name)
            imported.append(mod_name)
        except Exception as exc:
            logger.warning("Could not import tool module %s: %s", mod_name, exc)

    return imported
