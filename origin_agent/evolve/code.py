"""代码进化编排器 — 验证 fork 然后触发交换。

此模块由 ``evolve_code`` 工具 handler 在 LLM 已将
进化源码写入 fork: 命名空间后调用。

流程：
    1. 验证 fork: 中所有 .py 文件（语法 + 可选编译检查）
    2. 如果通过 → 通知 App 以退出码 -1 退出
    3. 编排器（run.py）捕获 -1，执行 slow→fast 交换，重启
"""

from __future__ import annotations

import json
import logging

from evolve.validator import validate_directory, summary
from system.sandbox import Sandbox
from typing import Any

logger = logging.getLogger(__name__)

# 告知编排器执行 slow→fast 交换的退出码。
_EXIT_CODE_EVOLVED: int = -1


def finalize_evolution(
    sandbox: Sandbox,
    *,
    deep: bool = True,
    compile_timeout: int = 30,
) -> dict:
    """验证 fork 目录，所有检查通过后触发热替换。

    返回适合 LLM 工具响应的 JSON 结果字符串：

    - 成功：``{"evolved": true, "validation": {"valid": true, ...}}``
      （返回后进程立即退出）
    - 失败：``{"evolved": false, "validation": {"valid": false, ...}}``
      （LLM 可以修复问题后重试）

    *deep=True* 在语法检查之外还运行 py_compile 检查。
    *compile_timeout* 是每个文件的 py_compile 子进程超时时间。

    仅在 'fast' 模式下可用。在 'fallback' 模式下返回错误而不退出。
    """
    # 将 fork: 解析为磁盘上的真实路径
    fork_resolved: Any
    try:
        fork_resolved = sandbox.resolve_read("fork:")
    except Exception as exc:
        return _json_error(f"Cannot resolve fork: namespace: {exc}")

    fork_dir: Any = fork_resolved.real
    if not fork_dir.is_dir():
        return _json_error(f"Fork directory does not exist: {fork_dir}")

    logger.info("Validating evolved code in %s (deep=%s)", fork_dir, deep)

    # ---- 1. 验证所有 .py 文件 ----
    results: list[dict] = validate_directory(fork_dir, deep=deep, timeout=compile_timeout)
    report: dict = summary(results)

    if not report["valid"]:
        logger.warning(
            "Evolution validation FAILED: %d/%d files have errors",
            report["errors"], report["total"],
        )
        return {
                "evolved": False,
                "validation": report,
                "hint": (
                    "Fix the errors above using write_fork, then call "
                    "validate_code to check syntax, then call evolve_code "
                    "again when all files pass."
                ),
            }

    # ---- 2. 验证通过 — 触发交换 ----
    logger.info(
        "Evolution validation PASSED (%d files ok). Triggering swap.",
        report["total"],
    )

    # 在此处导入避免模块级循环依赖。
    from main import request_evolution

    request_evolution()

    return {
            "evolved": True,
            "validation": report,
            "message": (
                "All {n} files validated. The orchestrator will now swap "
                "slow→fast and restart with the evolved code."
            ).format(n=report["total"]),
    }


def _json_error(message: str) -> dict[str, Any]:
    return {"evolved": False, "error": str(message)}