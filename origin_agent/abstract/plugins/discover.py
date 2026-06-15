"""基于目录的插件发现系统。

纯 Python stdlib — 无外部依赖。

扫描目录查找插件子目录，通过启发式源码分析检测插件类型，
读取 plugin.yaml 元数据，处理名称去重（冲突时第一个目录获胜）。

用法::

    from abstract.plugins.discover import scan_plugins, is_plugin_dir, \
        detect_plugin_type, read_plugin_metadata

    plugins = scan_plugins("/path/to/plugins", "/other/plugin/dir")
    for p in plugins:
        print(p["name"], p["type"], p["metadata"])
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# 核心函数
# ---------------------------------------------------------------------------

def scan_plugins(*scan_dirs: str) -> list[Dict]:
    """扫描一个或多个目录查找插件子目录。

    每个包含 ``__init__.py`` 的子目录视为候选。
    名称冲突时（多个扫描目录中出现相同目录名），
    最先出现的获胜。

    返回
    -------
    list of dict
        每个 dict 包含键 ``name``、``path``、``type``、``metadata``。
    """
    seen: dict[str, Dict] = {}

    for scan_dir in scan_dirs:
        scan_path: Path = Path(scan_dir)
        if not scan_path.is_dir():
            continue

        for child in sorted(scan_path.iterdir()):
            if not child.is_dir():
                continue
            name: str = child.name

            # 跳过隐藏目录和 Python 包目录
            if name.startswith("__") or name.startswith("."):
                continue

            if not is_plugin_dir(str(child)):
                continue

            # 名称冲突时第一个目录获胜
            if name in seen:
                continue

            plugin_type: str = detect_plugin_type(str(child))
            metadata: dict = read_plugin_metadata(str(child))

            seen[name] = {
                "name": name,
                "path": str(child.resolve()),
                "type": plugin_type,
                "metadata": metadata,
            }

    return list(seen.values())


def is_plugin_dir(plugin_dir: str) -> bool:
    """检查目录是否看起来像插件。

    有效的插件目录必须包含带有非平凡内容
    （不仅仅是 docstring 或空白）的 ``__init__.py``。

    参数
    ----------
    plugin_dir : str
        候选插件目录的路径。

    返回
    -------
    bool
        如果目录有包含真实代码的 ``__init__.py`` 则返回 ``True``。
    """
    init_file: Path = Path(plugin_dir) / "__init__.py"
    if not init_file.is_file():
        return False

    # 要求至少一行非注释、非空白、非 docstring 的代码
    text: str
    try:
        text = init_file.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return False

    for line in text.splitlines():
        stripped: str = line.strip()
        if not stripped:
            continue
        # 跳过纯注释行
        if stripped.startswith("#"):
            continue
        # 跳过三引号 docstring（开头或结尾）
        if stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        # 跳过 ``from __future__`` 导入（样板代码）
        if stripped.startswith("from __future__"):
            continue
        return True

    return False


def detect_plugin_type(plugin_dir: str) -> str:
    """通过扫描源码启发式确定插件类型。

    读取指定目录中的 ``__init__.py``，查找类定义模式。
    类型按优先级返回：

    * ``"memory"`` — 如果源码引用 ``MemoryProvider``
    * ``"context_engine"`` — 如果源码引用 ``ContextEngine``
    * ``"model_provider"`` — 如果源码引用 ``ModelProvider``
    * ``"tool_provider"`` — 如果源码引用 ``ToolProvider``
    * ``"plugin"`` — 如果源码引用 ``Plugin``
    * ``"register"`` — 如果源码定义 ``register()`` 函数
    * ``"image_gen"`` — 如果源码引用 ``ImageGenProvider``
    * ``"unknown"`` — 以上均未匹配

    参数
    ----------
    plugin_dir : str
        包含 ``__init__.py`` 的插件目录路径。

    返回
    -------
    str
        上述类型字符串之一。
    """
    init_file: Path = Path(plugin_dir) / "__init__.py"
    if not init_file.is_file():
        return "unknown"

    source: str
    try:
        source = init_file.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return "unknown"

    # 按特异性排序 — 先检查更具体的再检查通用的 "Plugin"
    patterns: list[tuple[str, str]] = [
        (r"\bMemoryProvider\b", "memory"),
        (r"\bContextEngine\b", "context_engine"),
        (r"\bModelProvider\b", "model_provider"),
        (r"\bToolProvider\b", "tool_provider"),
        (r"\bImageGenProvider\b", "image_gen"),
        (r"\bAudioGenProvider\b", "audio_gen"),
        (r"\bProvider\b", "provider"),
        (r"\bclass\s+\w*Plugin\w*", "plugin"),
        (r"\bdef\s+register\s*\(", "register"),
    ]

    for pattern, plugin_type in patterns:
        if re.search(pattern, source):
            return plugin_type

    return "unknown"


def read_plugin_metadata(plugin_dir: str) -> dict:
    """从插件目录读取 ``plugin.yaml`` 元数据。

    由于此模块仅使用 Python stdlib（无 PyYAML 依赖），
    ``plugin.yaml`` 使用简单的基于行的读取器解析，
    处理插件清单中常用的 ``key: value`` 格式。
    嵌套 YAML 结构（列表、字典）**不会**被解析 — 它们存储为
    原始文本字符串。

    如果文件不存在或无法解析则返回空字典。

    参数
    ----------
    plugin_dir : str
        插件目录路径。

    返回
    -------
    dict
        解析后的元数据或 ``{}``。
    """
    yaml_file: Path = Path(plugin_dir) / "plugin.yaml"
    if not yaml_file.is_file():
        return {}

    text: str
    try:
        text = yaml_file.read_text(encoding="utf-8-sig", errors="replace")
    except (OSError, UnicodeDecodeError):
        return {}

    metadata: Dict = {}
    lines: list[str] = text.splitlines()
    i: int = 0
    n: int = len(lines)

    while i < n:
        line: str = lines[i]
        stripped: str = line.strip()

        # 跳过空白和注释行
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        # 匹配 key: value 或 key:
        match: re.Match | None = re.match(r"^(\S[^:]*?):\s*(.*)", stripped)
        if not match:
            i += 1
            continue

        key: str = match.group(1).strip()
        value: str = match.group(2).strip()

        # 如果值为空，可能是多行块的开始
        # （以短横线开头的列表项或普通续行）。
        if value == "":
            # 收集续行（相对于此键缩进）
            continuation: list[str] = []
            j: int = i + 1
            base_indent: int = len(line) - len(line.lstrip())
            while j < n:
                next_line: str = lines[j]
                if not next_line.strip():
                    j += 1
                    continue
                next_indent: int = len(next_line) - len(next_line.lstrip())
                if next_indent <= base_indent:
                    break
                continuation.append(next_line)
                j += 1
            if continuation:
                value = "\n".join(line.rstrip() for line in continuation)
            i = j
        else:
            # 尝试收集以列表开头的值的续行
            if value == "-" and i + 1 < n:
                continuation = []
                j = i + 1
                base_indent = len(line) - len(line.lstrip())
                while j < n:
                    next_line = lines[j]
                    if not next_line.strip():
                        j += 1
                        continue
                    next_indent = len(next_line) - len(next_line.lstrip())
                    if next_indent <= base_indent:
                        break
                    continuation.append(next_line)
                    j += 1
                if continuation:
                    value = "\n".join(line.rstrip() for line in continuation)
                i = j
            else:
                i += 1

        # 存储简单标量值
        metadata[key] = _coerce_yaml_scalar(value)

    return metadata


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------

def _coerce_yaml_scalar(value: str):
    """将 YAML 标量字符串强制转换为适当的 Python 类型。

    * 带引号的字符串原样返回（剥去引号）。
    * ``true``/``false``（大小写不敏感）→ ``True``/``False``。
    * 数字字符串 → ``int`` 或 ``float``。
    * ``null``/``~`` → ``None``。
    * 其他所有情况返回去空白的字符串。
    """
    v: str = value.strip()

    # 处理带引号的字符串
    if (v.startswith('"') and v.endswith('"')) or (
        v.startswith("'") and v.endswith("'")
    ):
        return v[1:-1]

    # 处理 null
    if v.lower() in ("null", "~"):
        return None

    # 处理布尔值
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False

    # 处理数字
    try:
        if "." in v or "e" in v.lower():
            return float(v)
        return int(v)
    except (ValueError, TypeError):
        pass

    return v