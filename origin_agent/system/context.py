"""运行时上下文 — 所有配置的唯一真相来源。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict


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

    fix_path: Optional[Path] = None
    """mode=='fallback' 时，需要修复的目录（损坏的 fast）。"""

    fix_log_path: Optional[Path] = None
    """mode=='fallback' 时，需要参考的错误日志路径。"""

    # -- Gateway 配置 -----------------------------------------------------

    gateway_host: str = "127.0.0.1"
    gateway_port: int = 8765

    # -- LLM 配置（后续从 env / 配置文件填充） ----------------

    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"
    llm_max_context_tokens: int = 128_000  # 总上下文窗口
    llm_context_upbound: float = 0.7       # 压缩阈值比例
    llm_temperature: float = 0.7
    llm_max_output_tokens: int = 4096
    llm_reasoning_effort: str = ""
    """模型 reasoning_effort 参数值（如 "low" / "medium" / "high"），空字符串表示不启用。"""

    # -- 工具执行超时 ---------------------------------------------

    tool_timeout: int = 30
    """单个工具调用允许运行的最大秒数，超时后取消（0 = 无超时）。"""

    # -- MCP 配置 -------------------------------------------------

    mcp_config_path: Optional[str] = None
    """MCP server 配置文件的路径（JSON 格式）。为 None 时不启动 MCP server。"""