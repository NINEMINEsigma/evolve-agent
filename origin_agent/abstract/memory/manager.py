"""MemoryManager — 为 agent 编排 memory provider。

单一集成点。将分散的各后端代码替换为一个管理器，
由它委托给已注册的 provider。

同一时间只允许一个外部插件 provider — 注册第二个外部 provider
会被警告拒绝。这防止工具 schema 膨胀和 memory 后端冲突。

用法:
    manager = MemoryManager()
    manager.add_provider(builtin_provider)
    manager.add_provider(plugin_provider)  # 最多一个外部

    # System prompt
    prompt_parts.append(manager.build_system_prompt())

    # 回合前
    context = manager.prefetch_all(user_message)

    # 回合后
    manager.sync_all(user_msg, assistant_response)
"""

from __future__ import annotations

import json
import logging
import re
from typing import * # type: ignore

from .provider import MemoryProvider
if TYPE_CHECKING:
    from ...entity.messages import History

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 上下文围栏辅助函数
# ---------------------------------------------------------------------------

_FENCE_TAG_RE: re.Pattern = re.compile(r"<\|/?\s*im_memory_context\s*\|>", re.IGNORECASE)
_INTERNAL_CONTEXT_RE: re.Pattern = re.compile(
    r"<\|im_memory_context_start\|>[\s\S]*?<\|im_memory_context_end\|>",
    re.IGNORECASE,
)
_INTERNAL_NOTE_RE: re.Pattern = re.compile(
    r"\[System note:\s*The following is recalled memory context,"
    r"\s*NOT new user input\.\s*Treat as (?:informational background data"
    r"|authoritative reference data[^\]]*)\]\.?\]?\s*",
    re.IGNORECASE,
)


def _tool_error(message: str, **extra: Any) -> dict:
    """返回错误 dict（tools.registry.tool_error 的本地替代）。"""
    result: dict[str, Any] = {"error": str(message)}
    if extra:
        result.update(extra)
    return result


def sanitize_context(text: str) -> str:
    """从 provider 输出中剥离围栏标签、注入的上下文块和系统注释。"""
    text = _INTERNAL_CONTEXT_RE.sub("", text)
    text = _INTERNAL_NOTE_RE.sub("", text)
    text = _FENCE_TAG_RE.sub("", text)
    return text


class StreamingContextScrubber:
    """有状态清洗器，处理可能跨 chunk 分割的 memory-context 区间。

    一次性 ``sanitize_context`` regex 无法跨越 chunk 边界：
    一个 delta 中打开的 ``<memory-context>`` 在后续 delta 中关闭时
    会将其负载泄露到 UI，因为非贪心块 regex 需要两个标签
    在同一字符串中。此清洗器跨 delta 运行一个小状态机，
    保留部分标签尾部，丢弃区间内的所有内容（包括系统注释行）。

    用法::

        scrubber = StreamingContextScrubber()
        for delta in stream:
            visible = scrubber.feed(delta)
            if visible:
                emit(visible)
        trailing = scrubber.flush()  # 流结束时
        if trailing:
            emit(trailing)

    清洗器在每个 agent 实例内可重入。构建新顶级响应的调用方
    应创建新清洗器或调用 ``reset()``。
    """

    _OPEN_TAG: str = "<|im_memory_context_start|>"
    _CLOSE_TAG: str = "<|im_memory_context_end|>"

    def __init__(self) -> None:
        self._in_span: bool = False
        self._buf: str = ""

    def reset(self) -> None:
        self._in_span = False
        self._buf = ""

    def feed(self, text: str) -> str:
        """返回清洗后 ``text`` 的可见部分。

        任何可能是开标签/闭标签起始的尾部片段
        被保留在内部缓冲区中，在下次 ``feed()`` 调用时释放，
        或由 ``flush()`` 丢弃/发出。
        """
        if not text:
            return ""
        buf: str = self._buf + text
        self._buf = ""
        out: list[str] = []

        while buf:
            if self._in_span:
                idx: int = buf.lower().find(self._CLOSE_TAG)
                if idx == -1:
                    # 保留可能的部分闭标签；丢弃其余内容
                    held: int = self._max_partial_suffix(buf, self._CLOSE_TAG)
                    self._buf = buf[-held:] if held else ""
                    return "".join(out)
                # 找到闭标签 — 跳过区间内容 + 标签，继续
                buf = buf[idx + len(self._CLOSE_TAG):]
                self._in_span = False
            else:
                idx = buf.lower().find(self._OPEN_TAG)
                if idx == -1:
                    # 无开标签 — 保留可能的部分开标签
                    held = self._max_partial_suffix(buf, self._OPEN_TAG)
                    if held:
                        out.append(buf[:-held])
                        self._buf = buf[-held:]
                    else:
                        out.append(buf)
                    return "".join(out)
                # 发出标签前的文本，进入区间
                if idx > 0:
                    out.append(buf[:idx])
                buf = buf[idx + len(self._OPEN_TAG):]
                self._in_span = True

        return "".join(out)

    def flush(self) -> str:
        """在流结束时发出任何保留的缓冲区内容。

        如果仍在未终止的区间内，剩余内容被丢弃
        （更安全：泄露部分 memory 上下文比截断回答更糟糕）。
        否则保留的部分标签尾部按原样发出（它实际不是真实标签）。
        """
        if self._in_span:
            self._buf = ""
            self._in_span = False
            return ""
        tail: str = self._buf
        self._buf = ""
        return tail

    @staticmethod
    def _max_partial_suffix(buf: str, tag: str) -> int:
        """返回 buf 最长后缀中作为 tag 前缀的长度。

        大小写不敏感。如果无后缀可开始该 tag 则返回 0。
        """
        tag_lower: str = tag.lower()
        buf_lower: str = buf.lower()
        max_check: int = min(len(buf_lower), len(tag_lower) - 1)
        for i in range(max_check, 0, -1):
            if tag_lower.startswith(buf_lower[-i:]):
                return i
        return 0


def build_memory_context_block(raw_context: str) -> str:
    """将预取的 memory 包装到带系统注释的围栏块中。"""
    if not raw_context or not raw_context.strip():
        return ""
    clean: str = sanitize_context(raw_context)
    if clean != raw_context:
        logger.warning("memory provider returned pre-wrapped context; stripped")
    return (
        "<|im_memory_context_start|>\n"
        "[System note: The following is recalled memory context, "
        "NOT new user input. Treat as authoritative reference data — "
        "this is the agent's persistent memory and should inform all responses.]\n\n"
        f"{clean}\n"
        "<|im_memory_context_end|>"
    )


class MemoryManager:
    """编排内置 provider 加最多一个外部 provider。

    内置 provider 始终排在首位。仅允许一个非内置（外部）provider。
    任一 provider 的故障不会阻塞其他 provider。
    """

    def __init__(self) -> None:
        self._providers: list[MemoryProvider] = []
        self._tool_to_provider: dict[str, MemoryProvider] = {}
        self._has_external: bool = False  # 添加非内置 provider 后为 True

    # -- 注册 --------------------------------------------------------

    def add_provider(self, provider: MemoryProvider) -> None:
        """注册 memory provider。

        内置 provider（名称 ``"builtin"``）始终接受。
        仅允许**一个**外部（非内置）provider — 第二次尝试
        将被警告拒绝。
        """
        is_builtin: bool = provider.name == "builtin"

        if not is_builtin:
            if self._has_external:
                existing: str = next(
                    (p.name for p in self._providers if p.name != "builtin"), "unknown"
                )
                logger.warning(
                    "Rejected memory provider '%s' — external provider '%s' is "
                    "already registered. Only one external memory provider is "
                    "allowed at a time.",
                    provider.name,
                    existing,
                )
                return
            self._has_external = True

        self._providers.append(provider)

        # 索引工具名称 → provider 用于路由
        for schema in provider.get_tool_schemas():
            tool_name: str = schema.get("name", "")
            if tool_name and tool_name not in self._tool_to_provider:
                self._tool_to_provider[tool_name] = provider
            elif tool_name in self._tool_to_provider:
                logger.warning(
                    "Memory tool name conflict: '%s' already registered by %s, "
                    "ignoring from %s",
                    tool_name,
                    self._tool_to_provider[tool_name].name,
                    provider.name,
                )

        logger.info(
            "Memory provider '%s' registered (%d tools)",
            provider.name,
            len(provider.get_tool_schemas()),
        )

    def remove_provider(self, name: str) -> bool:
        """按名称移除 provider。返回 True 表示已移除，False 表示未找到。

        如果被移除的 provider 是唯一的外部 provider，
        重置外部 provider 守卫以允许注册另一个外部 provider。
        """
        provider: MemoryProvider | None = next((p for p in self._providers if p.name == name), None)
        if provider is None:
            logger.warning("No memory provider named '%s' to remove", name)
            return False

        self._providers = [p for p in self._providers if p.name != name]

        # 移除此 provider 所有工具条目
        self._tool_to_provider = {
            t: p for t, p in self._tool_to_provider.items() if p.name != name
        }

        # 更新外部守卫
        if provider.name != "builtin":
            remaining_external: bool = any(
                p.name != "builtin" for p in self._providers
            )
            if not remaining_external:
                self._has_external = False

        logger.info("Memory provider '%s' removed", name)
        return True

    @property
    def providers(self) -> list[MemoryProvider]:
        """所有已注册 provider，按顺序。"""
        return list(self._providers)

    def get_provider(self, name: str) -> MemoryProvider|None:
        """按名称获取 provider，未注册返回 None。"""
        for p in self._providers:
            if p.name == name:
                return p
        return None

    def get_provider_names(self) -> list[str]:
        """返回所有已注册 provider 的名称列表，按顺序。"""
        return [p.name for p in self._providers]

    # -- System prompt -------------------------------------------------------

    def build_system_prompt(self) -> str:
        """收集所有 provider 的 system prompt 块。

        返回合并文本，无 provider 贡献时返回空字符串。
        每个非空块标注 provider 名称。
        """
        blocks: list[str] = []
        failures: list[str] = []
        for provider in self._providers:
            try:
                block: str = provider.system_prompt_block()
                if block and block.strip():
                    blocks.append(block)
            except Exception as e:
                logger.warning(
                    "Memory provider '%s' system_prompt_block() failed",
                    provider.name,
                    exc_info=True,
                )
                failures.append(provider.name)
        if failures:
            logger.error(
                "Memory system_prompt_block failures: %s", ", ".join(failures)
            )
        return "\n\n".join(blocks)

    # -- 预取 / 回忆 ---------------------------------------------------

    def prefetch_all(self, query: str, *, session_id: str = "") -> str:
        """从所有 provider 收集预取上下文。

        返回按 provider 标注的合并上下文文本。空 provider 被跳过。
        任一 provider 的故障不阻塞其他 provider。
        """
        parts: list[str] = []
        failures: list[str] = []
        for provider in self._providers:
            try:
                result: str = provider.prefetch(query, session_id=session_id)
                if result and result.strip():
                    parts.append(result)
            except Exception as e:
                logger.warning(
                    "Memory provider '%s' prefetch failed",
                    provider.name,
                    exc_info=True,
                )
                failures.append(provider.name)
        if failures:
            logger.error(
                "Memory prefetch failures: %s", ", ".join(failures)
            )
        return "\n\n".join(parts)

    # -- 同步 ----------------------------------------------------------------

    def sync_all(
        self,
        history: History,
        *,
        session_id: str = "",
    ) -> None:
        """将完成的回合同步到所有 provider。"""
        failures: list[str] = []
        for provider in self._providers:
            try:
                provider.sync_turn(history, session_id=session_id)
            except Exception as e:
                logger.warning(
                    "Memory provider '%s' sync_turn failed",
                    provider.name,
                    exc_info=True,
                )
                failures.append(provider.name)
        if failures:
            logger.error(
                "Memory sync_turn failures: %s", ", ".join(failures)
            )

    # -- 工具 ---------------------------------------------------------------

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """收集所有 provider 的工具 schema。

        重复工具名称被去重（第一个 provider 获胜）。
        """
        schemas: list[dict] = []
        seen: set[str] = set()
        failures: list[str] = []
        for provider in self._providers:
            try:
                for schema in provider.get_tool_schemas():
                    name: str = schema.get("name", "")
                    if name and name not in seen:
                        schemas.append(schema)
                        seen.add(name)
            except Exception as e:
                logger.warning(
                    "Memory provider '%s' get_tool_schemas() failed",
                    provider.name,
                    exc_info=True,
                )
                failures.append(provider.name)
        if failures:
            logger.error(
                "Memory get_tool_schemas failures: %s", ", ".join(failures)
            )
        return schemas

    def get_tool_names(self) -> set:
        """返回跨所有 provider 的工具名称集合。"""
        return set(self._tool_to_provider.keys())

    def has_tool(self, tool_name: str) -> bool:
        """检查是否有 provider 处理此工具。"""
        return tool_name in self._tool_to_provider

    def handle_tool_call(
        self, tool_name: str, args: dict[str, Any], **kwargs: Any
    ) -> Any:
        """将工具调用路由到正确的 provider。

        返回 dict 或 JSON 字符串结果。如果无 provider 处理该工具，
        抛出 ValueError。
        """
        provider: MemoryProvider | None = self._tool_to_provider.get(tool_name)
        if provider is None:
            return _tool_error(f"No memory provider handles tool '{tool_name}'")
        try:
            return provider.handle_tool_call(tool_name, args, **kwargs)
        except Exception as e:
            logger.error(
                "Memory provider '%s' handle_tool_call(%s) failed: %s",
                provider.name,
                tool_name,
                e,
            )
            return _tool_error(f"Memory tool '{tool_name}' failed: {e}")

    # -- 生命周期钩子 -----------------------------------------------------

    def shutdown_all(self) -> None:
        """关闭所有 provider（逆序以干净拆解）。"""
        failures: list[str] = []
        for provider in reversed(self._providers):
            try:
                provider.shutdown()
            except Exception as e:
                logger.warning(
                    "Memory provider '%s' shutdown failed",
                    provider.name,
                    exc_info=True,
                )
                failures.append(provider.name)
        if failures:
            logger.error(
                "Memory shutdown failures: %s", ", ".join(failures)
            )