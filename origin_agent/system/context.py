"""运行时上下文 — 所有配置的唯一真相来源。"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from entity.constant import MERGE_CONCAT_THRESHOLD


class RuntimeContext(BaseModel):
    """不可变的运行时配置。

    由 __main__.py 从 CLI 参数填充。所有路径均解析为绝对形式，
    下游代码无需关心 CWD。
    """

    model_config = ConfigDict(frozen=True)

    # -- 路径（均为绝对路径） -----------------------------------------------

    workspace: Path
    """根工作空间目录（例如 ``workspace/``）。"""

    agentspace: Path
    """通用沙盒目录，用于 agent I/O（例如 ``workspace/agentspace/``）。

    映射到 ``ws:`` 命名空间。与 ``fork_path`` 和 ``fix_path`` 分离，
    确保 agent 文件操作不会与运行时代码目录重叠。
    """

    fork_path: Path
    """进化代码写入的目录（slow 目录）。"""

    log_path: Path
    """编排器产生的日志文件路径。"""

    # -- 运行时标志 ------------------------------------------------------

    mode: str = "fast"
    """执行模式：``"fast"``（正常）或 ``"fallback"``（修复）。"""

    console_log: bool = False

    # -- fallback 模式字段 -----------------------------------------------

    fix_path: Path | None = None
    """mode=='fallback' 时，需要修复的目录（损坏的 fast）。"""

    fix_log_path: Path | None = None
    """mode=='fallback' 时，需要参考的错误日志路径。"""

    # -- Gateway 配置 -----------------------------------------------------

    gateway_host: str = "127.0.0.1"
    gateway_port: int = 8765

    git_remotes: str = ""
    """宿主仓库 remote 列表（``name=url`` 每行一个），由 run.py 启动时读取注入。"""

    # -- 工具执行超时 ---------------------------------------------

    tool_timeout: int = 30
    """单个工具调用允许运行的最大秒数，超时后取消（0 = 无超时）。"""

    # -- MCP 配置 -------------------------------------------------

    mcp_config_path: str | None = None
    """MCP server 配置文件的路径（JSON 格式）。为 None 时不启动 MCP server。"""

    # -- 会话合并配置 ------------------------------------------------

    merge_concat_threshold: int = MERGE_CONCAT_THRESHOLD
    """会话合并时直接拼接摘要的字符阈值，超过则截断。"""

    yolo: bool = False
    """YOLO 模式：所有工具调用直接自动批准，包括 critical 级别。启动后不可退出。"""

    soul_file: str = "SOUL.md"
    """SOUL 文件名，默认 ``"SOUL.md"``。可通过启动参数 ``--soul_file`` 切换。"""


# ---------------------------------------------------------------------------
# 全局 RuntimeContext 单例
# ---------------------------------------------------------------------------

_runtime_ctx: RuntimeContext | None = None


def set_runtime_context(ctx: RuntimeContext) -> None:
    """设置进程级全局 RuntimeContext 单例。"""
    global _runtime_ctx
    _runtime_ctx = ctx


def get_runtime_context() -> RuntimeContext:
    """返回全局 RuntimeContext，必须确保在 set 之后调用。"""
    if _runtime_ctx is None:
        raise RuntimeError(
            "RuntimeContext not set. Call set_runtime_context(ctx) during startup."
        )
    return _runtime_ctx