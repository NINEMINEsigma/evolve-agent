"""可插拔 memory provider 的抽象基类。

Memory provider 为 agent 提供跨 session 的持久化回忆。

生命周期（预期调用方协议）：
  initialize()          -- 连接、创建资源、预热
  system_prompt_block() -- system prompt 的静态文本
  prefetch(query)       -- 每个回合前的后台回忆
  sync_turn(user, asst) -- 持久化完成的回合
  get_tool_schemas()    -- 暴露给模型的工具 schema
  handle_tool_call()    -- 分发工具调用
  shutdown()            -- 干净退出

可选钩子（重写以选择加入）：
  on_turn_start(turn, message, **kwargs)    -- 每回合计时
  on_session_end(messages)                  -- session 结束提取
  on_session_switch(new_session_id, **kwargs) -- 进程中的 session 轮换
  on_pre_compress(messages) -> str          -- 上下文压缩前提取
  on_memory_write(action, target, content)  -- 镜像内置 memory 写入
  on_delegation(task, result, **kwargs)     -- 父代理对子代理工作的观察
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MemoryProvider(ABC):
    """Memory provider 的抽象基类。

    子类化此类以实现自定义 memory 后端。所有抽象方法必须实现；
    可选钩子可按需重写。
    """

    # ------------------------------------------------------------------
    # 核心生命周期 — 每个 provider 必须实现
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """此 provider 的简短标识符（如 'builtin'、'honcho'、'hindsight'）。

        返回
        -------
        str
            用于日志、配置和调试的人类可读标识符。
        """

    @abstractmethod
    def is_available(self) -> bool:
        """返回 True 表示此 provider 已配置且就绪。

        在 agent 初始化期间调用，用于决定是否激活此 provider。
        不应进行网络调用 — 仅检查配置键和已安装的依赖项。

        返回
        -------
        bool
            True 表示 provider 具备运行所需的一切。
        """

    @abstractmethod
    def initialize(self, session_id: str, **kwargs: Any) -> None:
        """为 session 初始化 provider。

        在 agent 启动时调用一次。可能创建资源（表、索引、
        文档存储），建立连接，启动后台线程等。

        参数
        ----------
        session_id : str
            对话 session 的唯一标识符，provider 应将自身限定在此范围内。

        **kwargs : Any
            agent 传递的环境上下文。常见键包括：

            hermes_home (str)
                活跃的 HERMES_HOME 目录路径。使用此路径进行
                按 profile 隔离的存储，而非硬编码路径。
            platform (str)
                ``"cli"``、``"telegram"``、``"discord"``、``"cron"`` 等。
            agent_context (str)
                ``"primary"``、``"subagent"``、``"cron"`` 或 ``"flush"``。
                provider 对非 primary 上下文应跳过写入。
            agent_identity (str)
                Profile 名称（如 ``"coder"``）。用于按 profile
                隔离 provider 身份。
            agent_workspace (str)
                共享 workspace 名称（如 ``"hermes"``）。
            parent_session_id (str)
                对子代理而言，父代理的 session_id。
            user_id (str)
                平台用户标识符（gateway session）。
        """

    @abstractmethod
    def system_prompt_block(self) -> str:
        """返回要包含在 system prompt 中的静态文本。

        这是*静态* provider 信息（指令、状态）。
        预取的回忆上下文通过 :meth:`prefetch` 单独注入。

        返回
        -------
        str
            要注入的文本，跳过则返回空字符串。
        """

    @abstractmethod
    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """为即将到来的回合回忆相关上下文。

        在每次 API 调用前调用。返回要作为上下文注入的格式化文本，
        未找到相关内容时返回空字符串。
        实现应快速 — 使用后台线程执行实际回忆，
        此处返回缓存结果。

        参数
        ----------
        query : str
            用户的最新消息（或等效查询字符串），用作搜索/回忆 prompt。
        session_id : str
            为服务并发 session 的 provider 提供 session 标识符。
            不需要按 session 隔离的 provider 可忽略。

        返回
        -------
        str
            格式化后的回忆文本，或空字符串。
        """

    @abstractmethod
    def sync_turn(
        self,
        user_message: str,
        assistant_response: str,
        *,
        session_id: str = "",
    ) -> None:
        """将完成的回合持久化到后端。

        在每次对话回合后调用。应非阻塞 —
        如果后端有延迟，排队到后台处理。

        参数
        ----------
        user_message : str
            本回合的用户消息。
        assistant_response : str
            本回合的助手响应。
        session_id : str
            为服务并发 session 的 provider 提供 session 标识符。
        """

    @abstractmethod
    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """返回此 provider 暴露的工具 schema。

        每个 schema 遵循 OpenAI function-calling 格式::

            {"name": "...", "description": "...", "parameters": {...}}

        如果此 provider 无工具（仅上下文），返回空列表。

        返回
        -------
        list[dict[str, Any]]
            OpenAI 兼容的工具定义字典列表。
        """

    @abstractmethod
    def handle_tool_call(self, tool_name: str, args: Dict[str, Any]) -> dict:
        """处理对此 provider 某个工具的工具调用。

        仅对之前由 :meth:`get_tool_schemas` 返回的工具名称调用。

        参数
        ----------
        tool_name : str
            被调用的工具名称。
        args : dict[str, Any]
            提供给工具的实参。

        返回
        -------
        dict
            工具结果 dict。
        """

    @abstractmethod
    def shutdown(self) -> None:
        """干净关闭 — 刷新队列、关闭连接、释放资源。

        在 agent 或 session 结束时调用。实现应确保
        所有待处理写入被刷新，连接优雅关闭。
        """

    # ------------------------------------------------------------------
    # 可选钩子 — 重写这些方法以选择加入生命周期事件
    # ------------------------------------------------------------------

    def on_turn_start(self, turn_number: int, message: str, **kwargs: Any) -> None:
        """每个回合开始时使用用户消息调用。

        用于回合计数、作用域管理或定期维护。

        参数
        ----------
        turn_number : int
            当前 session 的基于 1 的回合计数。
        message : str
            本回合的用户消息。
        **kwargs : Any
            运行时上下文。可能包含键如 ``remaining_tokens``、
            ``model``、``platform``、``tool_count``。
        """

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        """session 结束时调用（显式退出或超时）。

        用于 session 结束时的知识提取、摘要等。

        参数
        ----------
        messages : list[dict[str, Any]]
            正在结束的 session 的完整对话历史。

        Note
        ----
        并非每个回合后调用 — 仅在真正的 session 边界
        （CLI 退出、``/reset``、gateway session 过期）。
        """

    def on_session_switch(
        self,
        new_session_id: str,
        *,
        parent_session_id: str = "",
        reset: bool = False,
        **kwargs: Any,
    ) -> None:
        """agent 在进程中切换 session_id 时调用。

        在 ``/resume``、``/branch``、``/reset``、``/new`` 和上下文
        压缩时触发 — 即任何重新分配 session 标识符而不拆除
        provider 的路径。

        在 :meth:`initialize` 中缓存按 session 状态的 provider
        （``_session_id``、``_document_id``、累积回合缓冲区、计数器）
        应在此处更新或重置状态，使后续写入落在正确的 session 记录中。

        参数
        ----------
        new_session_id : str
            agent 刚切换到的 session_id。
        parent_session_id : str
            有血统意义时的前一个 session_id — 对 ``/branch``
            （fork 血统）、上下文压缩（延续血统）和 ``/resume``
            （我们正在离开的 session）设置。无血统适用时为空字符串。
        reset : bool
            ``True`` 表示这是真正的新对话而非恢复。
            由 ``/reset`` / ``/new`` 触发。设置时 provider 应
            刷新累积的按 session 缓冲区。``False`` 用于
            ``/resume`` / ``/branch`` / 压缩，这些场景下逻辑对话
            在新 id 下继续。
        **kwargs : Any
            附加上下文。
        """

    def on_pre_compress(self, messages: List[Dict[str, Any]]) -> str:
        """在上下文压缩丢弃旧消息前调用。

        用于从即将被压缩的消息中提取洞察。

        参数
        ----------
        messages : list[dict[str, Any]]
            将被摘要/丢弃的消息列表。

        返回
        -------
        str
            要包含在压缩摘要 prompt 中的文本，使压缩器
            保留 provider 提取的洞察。无贡献时返回空字符串
            （向后兼容的默认值）。
        """
        return ""

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """内置 memory 工具写入条目时调用。

        用于将内置 memory 写入镜像到你的后端。

        参数
        ----------
        action : str
            ``"add"``、``"replace"`` 或 ``"remove"``。
        target : str
            ``"memory"`` 或 ``"user"``。
        content : str
            条目内容。
        metadata : dict[str, Any] 或 None
            写入的结构化溯源信息（可用时）。常见键包括
            ``write_origin``、``execution_context``、``session_id``、
            ``parent_session_id``、``platform`` 和 ``tool_name``。
        """

    def on_delegation(
        self,
        task: str,
        result: str,
        *,
        child_session_id: str = "",
        **kwargs: Any,
    ) -> None:
        """子代理完成时在*父*代理上调用。

        父代理的 memory provider 接收 task+result 对作为
        委托了什么和返回了什么的一次观察。子代理本身
        通常无 provider session。

        参数
        ----------
        task : str
            发送给子代理的委托 prompt。
        result : str
            子代理的最终响应。
        child_session_id : str
            子代理的 session_id（可用时）。
        **kwargs : Any
            附加上下文。
        """