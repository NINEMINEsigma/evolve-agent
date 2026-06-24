"""压缩/解压工具 — 支持多种格式（zip、tar、gztar、bztar、xztar）。

模块导入时通过 ``registry.register()`` 注册。
所有路径均为逻辑路径（命名空间前缀），通过沙盒解析。
"""

from __future__ import annotations

import logging
import os
import shutil
import tarfile
import zipfile
from pathlib import Path
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from component.tools.filesystem import _s as _get_sandbox
from system.sandbox import SandboxError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 格式映射
# ---------------------------------------------------------------------------

# shutil.make_archive 的 format 参数
_SHUTIL_FORMATS: frozenset[str] = frozenset({"zip", "tar", "gztar", "bztar", "xztar"})

# tarfile 的 mode 映射
_TAR_WRITE_MODES: dict[str, str] = {
    "tar": "w",
    "gztar": "w:gz",
    "bztar": "w:bz2",
    "xztar": "w:xz",
}
_TAR_READ_MODES: dict[str, str] = {
    "tar": "r",
    "gztar": "r:gz",
    "bztar": "r:bz2",
    "xztar": "r:xz",
}


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _infer_format(path: Path) -> str:
    """根据文件名后缀推断压缩格式。"""
    name = path.name.lower()
    if name.endswith(".zip"):
        return "zip"
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        return "gztar"
    if name.endswith(".tar.bz2") or name.endswith(".tbz2"):
        return "bztar"
    if name.endswith(".tar.xz") or name.endswith(".txz"):
        return "xztar"
    if name.endswith(".tar"):
        return "tar"
    return ""


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _handle_compress(args: dict[str, Any]) -> dict:
    source: str = str(args.get("source", "")).strip()
    output: str = str(args.get("output", "")).strip()
    fmt: str = str(args.get("format", "")).strip().lower()

    if not source:
        return tool_error("source is required", source=source)
    if not output:
        return tool_error("output is required", output=output)
    if not fmt:
        return tool_error("format is required", format=fmt)
    if fmt not in _SHUTIL_FORMATS:
        return tool_error(
            f"Unsupported format '{fmt}'. "
            f"Supported: {sorted(_SHUTIL_FORMATS)}",
            format=fmt,
        )

    try:
        sandbox = _get_sandbox()
        r_src = sandbox.resolve_read(source)
        r_out = sandbox.resolve_write(output)
    except SandboxError as exc:
        return tool_error(str(exc))

    if not r_src.real.exists():
        return tool_error(f"Source does not exist: {source}", source=source)

    r_out.real.parent.mkdir(parents=True, exist_ok=True)

    # 如果输出路径已存在，先删除
    if r_out.real.exists():
        if r_out.real.is_dir():
            shutil.rmtree(str(r_out.real))
        else:
            r_out.real.unlink()

    try:
        if fmt == "zip":
            with zipfile.ZipFile(str(r_out.real), "w", zipfile.ZIP_DEFLATED) as zf:
                if r_src.real.is_file():
                    zf.write(r_src.real, r_src.real.name)
                else:
                    for root, _dirs, files in os.walk(r_src.real):
                        for f in files:
                            abs_path = Path(root) / f
                            arcname = abs_path.relative_to(r_src.real)
                            zf.write(abs_path, arcname)
        else:
            with tarfile.open(str(r_out.real), _TAR_WRITE_MODES[fmt]) as tf: # type: ignore
                tf.add(r_src.real, arcname=r_src.real.name)
    except Exception as exc:
        return tool_error(f"Compression failed: {exc}", source=source, output=output, format=fmt)

    return tool_result(
        success=True,
        source=source,
        output=output,
        format=fmt,
        source_is_dir=r_src.real.is_dir(),
    )


def _handle_decompress(args: dict[str, Any]) -> dict:
    source: str = str(args.get("source", "")).strip()
    output_dir: str = str(args.get("output_dir", "")).strip()
    fmt: str = str(args.get("format", "")).strip().lower()

    if not source:
        return tool_error("source is required", source=source)
    if not output_dir:
        return tool_error("output_dir is required", output_dir=output_dir)

    try:
        sandbox = _get_sandbox()
        r_src = sandbox.resolve_read(source)
        r_out = sandbox.resolve_write(output_dir)
    except SandboxError as exc:
        return tool_error(str(exc))

    if not r_src.real.exists():
        return tool_error(f"Source does not exist: {source}", source=source)
    if not r_src.real.is_file():
        return tool_error(f"Source is not a file: {source}", source=source)

    # 自动推断格式
    if not fmt:
        fmt = _infer_format(r_src.real)
    if not fmt:
        return tool_error(
            f"Cannot infer format from filename '{r_src.real.name}'. "
            f"Please specify format explicitly.",
            source=source,
        )
    if fmt not in _SHUTIL_FORMATS:
        return tool_error(
            f"Unsupported format '{fmt}'. "
            f"Supported: {sorted(_SHUTIL_FORMATS)}",
            format=fmt,
        )

    r_out.real.mkdir(parents=True, exist_ok=True)

    try:
        if fmt == "zip":
            with zipfile.ZipFile(str(r_src.real), "r") as zf:
                zf.extractall(r_out.real)
        else:
            with tarfile.open(str(r_src.real), _TAR_READ_MODES[fmt]) as tf: # type: ignore
                tf.extractall(r_out.real)
    except Exception as exc:
        return tool_error(f"Decompression failed: {exc}", source=source, output_dir=output_dir, format=fmt)

    return tool_result(
        success=True,
        source=source,
        output_dir=output_dir,
        format=fmt,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

registry.register(
    name="compress",
    toolset="archive",
    schema={
        # 将文件或目录压缩为指定格式的压缩包。
        # ⚠️ 如果 output 已存在，会被自动删除后重新创建。
        #
        # ## 前置条件
        # - source 文件或目录必须存在。
        # - output 路径所在命名空间必须是可写的。
        #
        # ## 调用效果
        # 将 source（文件或目录）压缩为指定格式的压缩包到 output 路径。
        # 如果 output 已存在（无论文件还是目录），会被删除后重新创建。
        # 返回 source_is_dir 表示源是文件还是目录。
        #
        # ## 返回
        # ```json
        # {"success": true, "source": "ws:src", "output": "ws:src.zip", "format": "zip", "source_is_dir": true}
        # ```
        #
        # ## 何时使用
        # - 打包多份文件以便用 publish_file 一次性发送。
        # - 打包文件或目录用于传输或归档。
        # - 备份目录结构。
        #
        # ## 副作用/注意
        # - ⚠️ output 已存在时被无条件删除后重新创建。
        # - 压缩目录时，压缩包内包含目录本身作为根条目（非仅内容）。
        # - 目录压缩自动递归处理。
        "description": """Compress a file or directory into an archive. Supported formats: zip, tar, gztar, bztar, xztar. ⚠️ If the output path already exists, it is automatically deleted and recreated.

## Prerequisites
- The source file or directory must exist.
- The output path namespace must be writable.

## Effect
Compresses the source (file or directory) into an archive at the output path. If the output already exists (file or directory), it is deleted first and recreated. Returns `source_is_dir` indicating whether the source was a file or directory.

## Returns
```json
{"success": true, "source": "ws:src", "output": "ws:src.zip", "format": "zip", "source_is_dir": true}
```

## When to Use
- Package multiple files so they can be sent as a single archive via publish_file.
- Package files or directories for transfer or archiving.
- Back up a directory structure.

## Side Effects / Notes
- ⚠️ If output already exists, it is unconditionally deleted and recreated.
- When compressing a directory, the archive contains the directory itself as the root entry (not just its contents).
- Directory compression is recursive.""",
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    # 要压缩的文件或目录逻辑路径（命名空间前缀）。
                    "description": "File or directory logical path to compress (namespace prefix).",
                },
                "output": {
                    "type": "string",
                    # 输出压缩包逻辑路径（命名空间前缀 + 文件名）。
                    "description": "Output archive logical path (namespace prefix + filename).",
                },
                "format": {
                    "type": "string",
                    # 压缩格式：zip、tar、gztar、bztar、xztar。
                    "description": "Archive format. Supported: zip, tar, gztar, bztar, xztar.",
                    "enum": ["zip", "tar", "gztar", "bztar", "xztar"],
                },
            },
            "required": ["source", "output", "format"],
        },
    },
    handler=_handle_compress,
    emoji="📦",
    danger_level="readonly",
)

registry.register(
    name="decompress",
    toolset="archive",
    schema={
        # 将压缩包解压到指定目录。支持格式自动推断（根据文件名后缀）。
        # format 留空时自动从文件后缀推断：.zip → zip、.tar.gz/.tgz → gztar 等。
        #
        # ## 前置条件
        # - source 压缩包必须存在。
        # - output_dir 路径所在命名空间必须是可写的。
        #
        # ## 调用效果
        # 将压缩包解压到目标目录。自动创建目标目录（如不存在）。
        # format 可选，留空时根据文件后缀自动推断。
        #
        # ## 返回
        # ```json
        # {"success": true, "source": "ws:src.zip", "output_dir": "ws:extracted/", "format": "zip"}
        # ```
        #
        # ## 何时使用
        # - 解压 .zip、.tar.gz 等压缩包。
        #
        # ## 副作用/注意
        # - 写入文件系统。目标目录自动创建。
        # - format 自动推断规则：.zip→zip, .tar.gz/.tgz→gztar, .tar.bz2/.tbz2→bztar, .tar.xz/.txz→xztar, .tar→tar。
        # - 无法推断格式时需明确指定 format。
        "description": """Decompress an archive into a directory. Supported formats: zip, tar, gztar, bztar, xztar. Format is auto-inferred from filename suffix when not specified.

## Prerequisites
- The source archive must exist.
- The output_dir namespace must be writable.

## Effect
Decompresses the archive into the target directory. The target directory is automatically created if it does not exist. The format can be left empty to auto-infer from the file suffix.

## Returns
```json
{"success": true, "source": "ws:src.zip", "output_dir": "ws:extracted/", "format": "zip"}
```

## When to Use
- Extract .zip, .tar.gz, and other compressed archives.

## Side Effects / Notes
- Writes to the file system. Target directory is auto-created.
- Auto-inference: .zip→zip, .tar.gz/.tgz→gztar, .tar.bz2/.tbz2→bztar, .tar.xz/.txz→xztar, .tar→tar.
- If format cannot be inferred, specify it explicitly.""",
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    # 压缩包逻辑路径（命名空间前缀）。
                    "description": "Archive file logical path to decompress (namespace prefix).",
                },
                "output_dir": {
                    "type": "string",
                    # 解压目标目录逻辑路径（命名空间前缀）。
                    "description": "Destination directory logical path (namespace prefix).",
                },
                "format": {
                    "type": "string",
                    # 压缩格式。留空时自动根据文件名后缀推断。
                    "description": "Archive format. Leave empty to auto-infer from filename suffix. Supported: zip, tar, gztar, bztar, xztar.",
                    "enum": ["", "zip", "tar", "gztar", "bztar", "xztar"],
                    "default": "",
                },
            },
            "required": ["source", "output_dir"],
        },
    },
    handler=_handle_decompress,
    emoji="📂",
    danger_level="readonly",
)