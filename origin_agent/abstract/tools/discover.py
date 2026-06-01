"""工具模块自动发现 — 通过 AST 扫描。

函数:
    discover_builtin_tools(tools_dir, package_prefix) -> List[str]
        扫描目录中的 .py 文件，寻找模块级别包含 registry.register() 调用的文件，
        导入它们，返回已导入模块名称列表。
        *tools_dir* 是磁盘上的目录路径，*package_prefix* 是该目录对应的 Python 包名
        （例如 tools_dir="component/tools/"、package_prefix="component.tools"）。

    _module_registers_tools(module_path) -> bool
        使用 ast.parse 检测模块级别的 registry.register()。

    _is_registry_register_call(node) -> bool
        检查 AST 节点是否为 registry.register(...) 调用。

纯 Python stdlib — 无外部依赖。
"""

import ast
import importlib
import logging
from pathlib import Path
from typing import List, Sequence

logger = logging.getLogger(__name__)

_EXCLUDED_FILENAMES: frozenset[str] = frozenset({"__init__.py", "registry.py"})


def _is_registry_register_call(node: ast.AST) -> bool:
    """当 *node* 是 ``registry.register(...)`` 调用表达式时返回 True。"""
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return False
    func: ast.AST = node.value.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "register"
        and isinstance(func.value, ast.Name)
        and func.value.id == "registry"
    )


def _module_registers_tools(module_path: Path) -> bool:
    """当模块包含顶层 ``registry.register(...)`` 调用时返回 True。

    仅检查模块体语句，因此恰好在函数内部
    调用 ``registry.register()`` 的辅助模块不会被检测到。
    """
    try:
        source: str = module_path.read_text(encoding="utf-8")
        tree: ast.Module = ast.parse(source, filename=str(module_path))
    except (OSError, SyntaxError):
        return False

    return any(_is_registry_register_call(stmt) for stmt in tree.body)


def discover_builtin_tools(tools_dir: str, package_prefix: str) -> List[str]:
    """扫描 *tools_dir* 查找工具模块，通过 *package_prefix* 推导模块名并导入。

    步骤:
      1. 列出目录中所有 ``.py`` 文件。
      2. 跳过 ``__init__.py``、``registry.py`` 以及任何以下划线
         开头的文件。
      3. 对每个剩余文件，AST 扫描模块级别的
         ``registry.register(...)`` 调用（参见 ``_module_registers_tools``）。
      4. 模块名推导为 ``{package_prefix}.{filename}`` 并导入。
      5. 返回成功导入的模块名称列表。

    导入失败的模块记录警告并跳过。
    """
    tools_path: Path = Path(tools_dir).resolve()
    if not tools_path.is_dir():
        logger.info("discover_builtin_tools: skip (not a dir) %s", tools_path)
        return []

    logger.info("discover_builtin_tools: scanning %s (prefix=%s)", tools_path, package_prefix)
    module_names: List[str] = []

    for path in sorted(tools_path.rglob("*.py")):
        if path.name in _EXCLUDED_FILENAMES:
            continue
        if path.stem.startswith("_"):
            continue
        if not _module_registers_tools(path):
            logger.info("discover_builtin_tools: skip (no registry.register) %s", path.name)
            continue

        rel_parts: Sequence[str] = path.relative_to(tools_path).with_suffix("").parts
        mod_name: str = f"{package_prefix}.{'.'.join(rel_parts)}"
        module_names.append(mod_name)
        logger.info("discover_builtin_tools: found %s -> %s", path.name, mod_name)

    imported: List[str] = []
    for mod_name in module_names:
        try:
            importlib.import_module(mod_name)
            imported.append(mod_name)
            logger.info("discover_builtin_tools: imported %s", mod_name)
        except Exception as exc:
            logger.warning("discover_builtin_tools: could not import %s: %s", mod_name, exc)

    logger.info("discover_builtin_tools: done (%d imported from %s)", len(imported), tools_path)
    return imported