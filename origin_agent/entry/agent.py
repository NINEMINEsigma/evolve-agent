"""Agent 主循环 — 接收用户消息，调用 LLM + 工具，返回回复。

将抽象层的三个子系统串联起来：
  - ``abstract.tools.registry`` — 工具 schema 发现与分发
  - ``abstract.memory.manager`` — memory 预取 / 同步
  - ``component.llm`` — LLM 客户端

每个 session 的消息历史保存在内存中。工具在启动时通过
``abstract.tools.discover.discover_builtin_tools`` 发现
（Stage 4 将注册具体工具）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List

from abstract.memory.manager import MemoryManager
from abstract.tools.registry import ToolEntry, registry as tool_registry
from component.approval import ApprovalResult, ask_agent_reason, is_adventure_mode, request_user_confirm
from component.llm import LLMClient, LLMResponse, ToolCall
from system.context import RuntimeContext
from system.prompt import build_system_prompt

logger = logging.getLogger(__name__)

# 每条消息的最大工具调用循环次数，防止无限循环。
_MAX_TOOL_TURNS = 90


# ---------------------------------------------------------------------------
# content block 错误处理辅助函数
# ---------------------------------------------------------------------------

def _is_content_block_error(exc: Exception) -> bool:
    """检测异常是否由 unsupported content blocks（如图片）引起。"""
    import openai as _openai
    msg: str = str(exc).lower()
    # OpenAI BadRequestError 是 400 类错误
    if isinstance(exc, _openai.BadRequestError):
        # 检查错误消息中是否提到与图片/内容类型相关的问题
        keywords: list[str] = [
            "image_url",
            "content type",
            "content block",
            "unsupported",
            "invalid content",
            "multimodal",
            "vision",
        ]
        return any(k in msg for k in keywords)
    # 通用的 HTTP 400 错误也可能是 content block 问题
    if isinstance(exc, _openai.APIStatusError):
        if getattr(exc, "status_code", 0) != 400:
            return False
        keywords400: list[str] = ["image", "content", "unsupported"]
        return any(k in msg for k in keywords400)
    return False


def _strip_image_blocks(messages: List[Dict[str, Any]], session_id: str) -> int:
    """移除消息列表中所有含 image_url 的 content blocks，转为纯文本。

    返回被剥离的图片数量。"""
    stripped: int = 0
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        new_blocks: list[dict] = []
        has_image: bool = False
        for block in content:
            if isinstance(block, dict) and block.get("type") == "image_url":
                has_image = True
                stripped += 1
                # Replace with hint text
                # 替换为提示文本
                new_blocks.append({
                    "type": "text",
                    "text": "[Image content stripped — current model does not support vision]",
                })
            else:
                new_blocks.append(block)
        if has_image:
            msg["content"] = new_blocks
    if stripped:
        logger = logging.getLogger(__name__)
        logger.info(
            "Stripped %d image_url block(s) from messages (session=%s)",
            stripped, session_id,
        )
    return stripped


# ---------------------------------------------------------------------------


class AgentLoop:
    """每个进程的单例，编排一次 LLM 会话回合。

    用法::

        loop = AgentLoop(ctx)
        reply = await loop.process_message(session_id, user_message)
    """

    def __init__(self, ctx: RuntimeContext, history_store_path: str | None = None) -> None:
        self._ctx: RuntimeContext = ctx
        self._llm: LLMClient = LLMClient(ctx)
        self._memory: MemoryManager = MemoryManager()
        # 记录哪些 session 已完成 memory provider 初始化
        self._memory_initialized: Dict[str, bool] = {}
        # 记录哪些 session 已收到中断请求
        self._interrupted: Dict[str, bool] = {}
        # 每个 session 的取消事件 — 由 interrupt() 设置，
        # 由 process_message() 检查，用于立即取消正在进行的 LLM HTTP 请求。
        self._cancel_events: Dict[str, asyncio.Event] = {}
        # 每个 session 的会话历史：session_id → OpenAI 格式的消息列表
        self._histories: Dict[str, List[Dict[str, Any]]] = {}
        # Skill prompt 缓存 — skill 被修改后失效
        self._skill_cache: list[str] = []
        # skill 缓存是否有效
        self._skill_cache_valid: bool = False
        # 累计 token 消耗，仅用于 dashboard 展示。
        # 压缩决策使用 _estimate_context_tokens() 替代。
        self._token_usage: Dict[str, int] = {}
        # 最近一次 LLM 调用返回的真实 prompt_tokens（上下文占用锚点）
        self._last_prompt_tokens: Dict[str, int] = {}
        # 缓存 system prompt 字符串，用于精确 token 估算
        self._cached_system_prompt: str | None = None
        # SessionManager 引用（由 server.py 注入），用于归档+旋转会话
        self._session_manager: Any | None = None
        # 会话旋转通知队列：old_sid -> new_sid（server.py 在 process_message 后检查并推送前端）
        self._session_rotated_notify: Dict[str, str] = {}
        # 工具调用统计，用于 dashboard 监控。
        # key 为工具名，value 为 {"calls": int, "errors": int}
        self._tool_stats: Dict[str, Dict[str, int]] = {}
        # 工具调用事件回调，在 tool_call / tool_result 时触发。
        # 签名：async (session_id, event_type, tool_name, payload) -> None
        self._tool_event_callback: Callable[[str, str, str, str], Awaitable[None]] | None = None
        # 消息历史的磁盘持久化目录
        self._history_store_dir: Path | None = Path(history_store_path) if history_store_path else None

    # -- 公开 API ----------------------------------------------------------

    def set_tool_event_callback(
        self,
        cb: Callable[[str, str, str, str], Awaitable[None]],
    ) -> None:
        """注册工具执行事件的异步回调。

        *cb* 调用参数为 ``(session_id, event_type, tool_name, payload)``，
        其中 *event_type* 为 ``"tool_call"`` 或 ``"tool_result"``，
        *payload* 为 JSON 字符串。
        """
        self._tool_event_callback = cb

    def set_session_manager(self, manager: Any) -> None:
        """注入 SessionManager 引用，用于归档会话。"""
        self._session_manager = manager

    def interrupt(self, session_id: str) -> None:
        """请求停止指定 session 的 agent 循环处理。

        同时拒绝该 session 所有待处理的 shell 命令确认请求，
        使阻塞中的 ``_request_user_confirm()`` 立即解除阻塞。
        """
        self._interrupted[session_id] = True
        # 设置取消事件，使正在进行的 LLM 调用立即中止，
        # 而不是等待 HTTP 响应完成。
        ev = self._cancel_events.get(session_id)
        if ev is not None:
            ev.set()
        try:
            from gateway.server import _deny_session_confirms
            _deny_session_confirms(session_id)
        except Exception:
            pass
        logger.info("Interrupt requested for session=%s", session_id)

    def is_interrupted(self, session_id: str) -> bool:
        """返回 True 表示该 session 存在活跃的中断请求。"""
        ev = self._cancel_events.get(session_id)
        return ev is not None and ev.is_set()

    async def process_message(
        self,
        session_id: str,
        user_message: str,
    ) -> str:
        """处理一条用户消息，返回助手的回复。

        核心 agent 循环：
          1. 预取 memory 上下文
          2. 构建带 system prompt 的消息历史
          3. 调用 LLM，执行工具调用，重复直到得到文本回复
          4. 将完成的本回合同步到 memory
        """
        # 清除上一回合残留的过期中断标记
        self._interrupted.pop(session_id, None)
        # ---- 持久化用户消息 ----
        self._append(session_id, "user", user_message)
        # ---- 延迟初始化 memory provider ----
        if session_id not in self._memory_initialized:
            for provider in self._memory.providers:
                try:
                    provider.initialize(session_id)
                except Exception:
                    pass
            self._memory_initialized[session_id] = True

        # ---- memory 预取 ----
        memory_ctx = self._memory.prefetch_all(
            user_message, session_id=session_id
        )

        # ---- 历史过长时进行会话旋转（归档+新会话）或压缩 ----
        _cur: int = self._last_prompt_tokens.get(session_id, 0)
        if _cur == 0:
            _cur = self._estimate_context_tokens(session_id)
        _SAFETY: int = 5000
        if (_cur + self._ctx.llm_max_output_tokens + _SAFETY) > self._ctx.llm_max_context_tokens:
            rotated: str | None = await self._rotate_session(session_id)
            if not rotated:
                await self._compress_history(session_id)
            else:
                await self._compress_history(session_id)  # 当前回合的旧上下文仍需压缩
            # 旋转后不切换 session_id：当前回合继续用旧 sid 保证工具事件路由正确，
            # 新会话从下一个用户消息开始生效（前端收到 session_rotated 后自动切换）

        # ---- 构建消息列表 ----
        messages = self._build_messages(session_id, user_message, memory_ctx)

        # ---- 工具调用循环 ----
        # 为每个 session 创建取消事件，使 interrupt() 能够
        # 立即中止正在进行的 LLM HTTP 请求。
        cancel_event: asyncio.Event = asyncio.Event()
        self._cancel_events[session_id] = cancel_event

        turn: int = 0
        try:
            while turn < _MAX_TOOL_TURNS:
                # ---- 响应中断 ----
                if cancel_event.is_set():
                    return "Cancelled."
                turn += 1

                # ---- 可取消的 LLM 调用 ----
                # 同时等待 LLM task 和取消事件，使中断能够
                # 穿透正在进行的 HTTP 请求，而不是等待其完成。
                llm_task: asyncio.Task[LLMResponse] = asyncio.create_task(
                    self._llm.chat(messages, tools=self._get_tool_definitions()),
                )
                cancel_task: asyncio.Task[bool] = asyncio.create_task(cancel_event.wait())

                done: set[asyncio.Task[Any]]
                pending: set[asyncio.Task[Any]]
                done, pending = await asyncio.wait(
                    [llm_task, cancel_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                # 取消仍处于 pending 状态的 task
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                if cancel_task in done:
                    # 中断已触发 — 丢弃 LLM 结果
                    return "Cancelled."

                # ---- 获取 LLM 响应（含图片 content block 兼容处理） ----
                try:
                    resp: LLMResponse = llm_task.result()
                except Exception as llm_exc:
                    # 检查是否因 content blocks（如 image_url）导致 API 拒绝
                    if _is_content_block_error(llm_exc):
                        stripped: int = _strip_image_blocks(messages, session_id)
                        if stripped > 0:
                            logger.warning(
                                "LLM rejected image content blocks — retrying with text-only "
                                "(stripped %d image(s) from session=%s)",
                                stripped, session_id,
                            )
                            continue  # 重新进入循环，用 text-only 消息重试
                    raise
                # 从 LLM 响应中追踪实际 token 消耗
                self._token_usage[session_id] = self._token_usage.get(session_id, 0) + resp.usage.total_tokens
                self._persist_token_usage(session_id)
                # 记录真实 prompt_tokens 作为上下文占用锚点
                self._last_prompt_tokens[session_id] = resp.usage.prompt_tokens

                if not resp.tool_calls:
                    # 纯文本回复 — 存储并返回
                    assistant_text = resp.content or ""
                    self._append(session_id, "assistant", assistant_text,
                                 reasoning_content=resp.reasoning_content)
                    self._memory.sync_all(
                        user_message, assistant_text, session_id=session_id,
                    )
                    return assistant_text

                # 将带 tool_calls 的 assistant 消息存入历史
                self._store_assistant_with_tools(session_id, resp)

                # 推送中间 assistant 文本到前端（非纯文本回复，避免重复）
                if resp.content and self._tool_event_callback:
                    asyncio.create_task(
                        self._tool_event_callback(
                            session_id, "assistant_text", "",
                            json.dumps({"content": resp.content, "reasoning": resp.reasoning_content}),
                        ) # type: ignore
                    )

                # 执行工具调用并将结果持久化到历史
                history: List[Dict[str, Any]] = self._get_history(session_id)
                for tc in resp.tool_calls:
                    tool_msg: Dict[str, Any] = await self._execute_tool(tc, session_id)
                    messages.append(tool_msg)
                    history.append(tool_msg)
                    self._persist_message(session_id, tool_msg)

                    # 如果 evolve_code 执行成功，干净退出循环。
                    # 无需继续 — run.py 编排器会重启我们。
                    if tc.name == "evolve_code":
                        try:
                            parsed: Any = json.loads(tool_msg["content"])
                            if parsed.get("evolved"):
                                self._append(session_id, "assistant", "Evolution complete, restarting to apply new code...")
                                return "Evolution complete, restarting to apply new code..."
                        except (json.JSONDecodeError, KeyError, TypeError):
                            pass

                # Mid-loop 压缩检查：工具结果追加后若接近上限则压缩
                est: int = self._last_prompt_tokens.get(session_id, 0)
                if est == 0:
                    est = self._estimate_context_tokens(session_id)
                SAFETY: int = 5000
                if (est + self._ctx.llm_max_output_tokens + SAFETY) > self._ctx.llm_max_context_tokens:
                    await self._compress_history(session_id)

                messages = self._get_full_history(session_id, memory_ctx)

        finally:
            # 始终清理取消事件，确保下一回合从干净状态开始
            self._cancel_events.pop(session_id, None)

        logger.warning(
            "Tool-call loop exceeded max turns (%d) for session=%s",
            _MAX_TOOL_TURNS, session_id,
        )
        return "I ran into an issue processing your request. Please try again."

    # -- 内部辅助方法 ----------------------------------------------------

    @staticmethod
    def _extract_text(content: Any) -> str:
        """从消息 content 中提取纯文本（处理 string 和 list 两种格式）。"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
            return "\n".join(parts)
        return str(content or "")

    def _supports_vision(self) -> bool:
        """检测当前模型是否支持图像 vision 功能。

        基于模型名称的启发式判断：
        - 包含 ``vision``、``vl``、``4o``、``turbo``、``gemini``、
          ``claude-3``、``claude-4``、``gpt-4o`` 等关键字的视为支持。
        - ``deepseek-chat``、``deepseek-v3``、``deepseek-reasoner``、
          ``gpt-3`` 等纯文本模型视为不支持。
        """
        model: str = (self._ctx.llm_model or "").lower()
        if not model:
            return False

        # 明确的非 vision 模型
        _non_vision = {
            "deepseek-chat",
            "deepseek-reasoner",
            "deepseek-v3",
            "gpt-3",
            "gpt-3.5",
            "text-davinci",
            "llama-3",
            "llama-2",
            "codellama",
            "mixtral",
        }
        for nv in _non_vision:
            if nv in model:
                return False

        # vision-capable 模型特征
        _vision_keywords = [
            "vision", "vl", "4o", "4-turbo", "gpt-4o",
            "gemini", "claude-3", "claude-4", "claude3", "claude4",
            "gpt-4-turbo", "gpt-4-vision",
            "glm-4v", "cogvlm", "llava",
            "qwen-vl", "yi-vision", "pixtral",
        ]
        for kw in _vision_keywords:
            if kw in model:
                return True

        # gpt-4（不含 o/turbo/vision 后缀）不支持 vision
        if "gpt-4" in model:
            return False

        # 默认保守策略：不支持
        return False

    def _get_history(self, session_id: str) -> List[Dict[str, Any]]:
        if session_id not in self._histories:
            # 先尝试从磁盘加载（重启后仍然可用）
            disk: list[dict] = self._load_history_from_disk(session_id)
            self._histories[session_id] = disk
        return self._histories[session_id]

    def _append(
        self, session_id: str, role: str, content: str,
        reasoning_content: str | None = None,
    ) -> None:
        entry: Dict[str, Any] = {"role": role, "content": content}
        if reasoning_content:
            entry["reasoning_content"] = reasoning_content
        self._get_history(session_id).append(entry)
        self._persist_message(session_id, entry)

    # -- 磁盘持久化辅助方法 -------------------------------------------

    def _history_path(self, session_id: str) -> Path | None:
        """返回 session 消息历史 JSONL 文件的路径。"""
        if not self._history_store_dir:
            return None
        return self._history_store_dir / session_id / "messages.jsonl"

    def _persist_message(self, session_id: str, entry: dict) -> None:
        """向 session 的 JSONL 文件追加一条消息。"""
        path: Path | None = self._history_path(session_id)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("Failed to persist message for session %s: %s", session_id, exc)

    def _load_history_from_disk(self, session_id: str) -> list[dict]:
        """从 JSONL 文件加载完整消息历史。"""
        path: Path | None = self._history_path(session_id)
        if path is None or not path.exists():
            return []
        try:
            entries: list[dict] = []
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
            return entries
        except Exception as exc:
            logger.warning("Failed to load history for session %s: %s", session_id, exc)
            return []

    # -- token 消耗持久化 -------------------------------------------

    def _token_usage_path(self, session_id: str) -> Path | None:
        """返回 session token 消耗 JSON 文件的路径。"""
        if not self._history_store_dir:
            return None
        return self._history_store_dir / session_id / "token_usage.json"

    def _persist_token_usage(self, session_id: str) -> None:
        """将 session 当前 token 消耗写入磁盘。"""
        path: Path | None = self._token_usage_path(session_id)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"token_usage": self._token_usage.get(session_id, 0)}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to persist token usage for session %s: %s", session_id, exc)

    def _load_token_usage_from_disk(self, session_id: str) -> int:
        """从磁盘加载 token 消耗，不存在则返回 0。"""
        path: Path | None = self._token_usage_path(session_id)
        if path is None or not path.exists():
            return 0
        try:
            data: dict = json.loads(path.read_text(encoding="utf-8"))
            return int(data.get("token_usage", 0))
        except Exception:
            return 0

    def clear_session(self, session_id: str) -> None:
        """从内存中移除 session，可选择清理磁盘文件。"""
        self._histories.pop(session_id, None)
        self._token_usage.pop(session_id, None)
        # 清理持久化的 token 消耗文件
        path: Path | None = self._token_usage_path(session_id)
        if path and path.exists():
            try:
                path.unlink()
            except Exception:
                pass

    async def auto_generate_title(self, session_id: str) -> str:
        """使用 LLM 从会话历史中生成简短标题。"""
        history: List[Dict[str, Any]] = self._get_history(session_id)
        if not history:
            return ""
        # 收集最近的 user/assistant 文本（跳过 system 和 tool 条目）
        lines: list[str] = []
        for msg in history[-20:]:
            role: str = msg.get("role", "")
            content: str = str(msg.get("content", "") or "")
            if not content:
                continue
            if role == "user":
                lines.append(f"User: {content[:300]}")
            elif role == "assistant":
                lines.append(f"Assistant: {content[:300]}")
        if not lines:
            return ""
        context: str = "\n".join(lines[-10:])

        # 从模板文件读取自动标题 prompt
        from system.pathutils import get_templates_dir
        templates: Path = get_templates_dir()
        zh_dir: Path = templates / "zh"
        use_zh: bool = zh_dir.is_dir()
        prompt_tpl: str = ""
        auto_file: Path = (zh_dir if use_zh else templates) / "auto_title.txt"
        if auto_file.is_file():
            try:
                prompt_tpl = auto_file.read_text(encoding="utf-8").strip()
            except OSError:
                pass
        if not prompt_tpl:
            # 硬编码回退
            prompt_tpl = (
                "Based on the following conversation, summarize the topic in no more than 20 characters. "
                "Output only the title, no extra content.\n\n{{context}}\n\nTitle: "
            )

        prompt: str = prompt_tpl.replace(r"{{context}}", context)
        try:
            resp: LLMResponse = await self._llm.chat(
                [{"role": "user", "content": prompt}],
                tools=[],
            )
            title: str = resp.content.strip()[:50] if resp.content else ""
            return title
        except Exception:
            return ""

    def _collect_skill_prompts(self) -> list[str]:
        """加载已启用的 skill，返回格式化后的 prompt 列表。"""
        if self._skill_cache_valid:
            return self._skill_cache
        blocks: list[str] = []
        try:
            from pathlib import Path
            from abstract.skills.loader import list_skills, load_skill
            skills: list[dict] = list_skills(skills_dir=Path("skills"))
            for s in skills:
                name: str = s.get("name", "")
                if not name:
                    continue
                try:
                    payload: dict = load_skill(name, skills_dir=Path("skills"))
                    if payload.get("success") and payload.get("content"):
                        blocks.append(
                            f"[Skill: {name}]\n{payload['content']}"
                        )
                except Exception:
                    pass
        except Exception:
            pass
        self._skill_cache = blocks
        self._skill_cache_valid = True
        return blocks

    def invalidate_skill_cache(self) -> None:
        """强制下次调用时重新加载 skill 缓存。"""
        self._skill_cache_valid = False
        self._cached_system_prompt = None

    def _estimate_context_tokens(self, session_id: str) -> int:
        """通过 tiktoken 计算历史 + system prompt 的实际上下文 token 数。

        用于驱动压缩决策 — 与仅用于 dashboard 展示的
        累计 ``_token_usage`` 计数器不同。
        """
        import tiktoken

        history: List[Dict[str, Any]] = self._get_history(session_id)
        if not history:
            return 0

        enc: tiktoken.Encoding | None = None
        try:
            enc = tiktoken.encoding_for_model(self._ctx.llm_model)
        except KeyError:
            # cl100k_base 覆盖 gpt-4、gpt-3.5-turbo 及大多数兼容模型
            enc = tiktoken.get_encoding("cl100k_base")

        total: int = 0
        for msg in history:
            # OpenAI 聊天消息开销：<|im_start|>role<|im_end|> ... <|im_end|>
            total += 4
            total += len(enc.encode(msg.get("role", "")))
            total += len(enc.encode(str(msg.get("content", ""))))
            rc: Any = msg.get("reasoning_content")
            if rc:
                total += 4
                total += len(enc.encode(str(rc)))
            tc: Any = msg.get("tool_calls")
            if tc:
                total += len(enc.encode(json.dumps(tc, ensure_ascii=False)))

        # 使用缓存的 system prompt 精确计数（而非固定 +2000）
        if self._cached_system_prompt is not None:
            total += len(enc.encode(self._cached_system_prompt))
        else:
            total += 2000

        return total

    async def _compress_history(self, session_id: str, keep_last: int = 5) -> None:
        """将较早的历史压缩为摘要，保留最近回合不变。

        当估算上下文 token 超过 LLM 窗口的 70% 时触发。
        使用轻量级 LLM 调用（无工具）来总结旧消息。
        """
        history: List[Dict[str, Any]] = self._get_history(session_id)
        if not history:
            return

        # 来自 RuntimeContext 的上下文限制（可配置）
        max_tokens: int = self._ctx.llm_max_context_tokens

        # 优先使用真实 prompt_tokens，首次调用 fallback 到估算
        current_tokens: int = self._last_prompt_tokens.get(session_id, 0)
        if current_tokens == 0:
            current_tokens = self._estimate_context_tokens(session_id)

        # 容量检查：当前上下文 + 最大输出 <= 窗口上限（含安全边距）
        SAFETY_MARGIN: int = 5000
        if (current_tokens + self._ctx.llm_max_output_tokens + SAFETY_MARGIN) <= max_tokens:
            return

        keep_msgs: int = keep_last * 2  # user+assistant 成对
        if len(history) <= keep_msgs:
            return

        old: List[Dict[str, Any]] = history[:-keep_msgs]
        recent: List[Dict[str, Any]] = history[-keep_msgs:]

        parts: list[str] = []
        for m in old:
            role: str = m.get("role", "unknown")
            content: str = self._extract_text(m.get("content", ""))[:500]
            if content:
                parts.append(f"[{role}]: {content}")

        if not parts:
            self._histories[session_id] = recent
            return

        old_text: str = "\n".join(parts[-50:])
        prompt: str
        fallback: str
        prefix: str
        prompt, fallback, prefix = self._compression_prompts()
        summary_prompt: str = prompt.replace(r"{{old_text}}", old_text)

        try:
            summary_resp: LLMResponse = await self._llm.chat(
                [{"role": "user", "content": summary_prompt}],
                tools=[],
            )
            summary: str = summary_resp.content.strip()[:300] if summary_resp.content else ""
        except Exception:
            summary = fallback

        self._histories[session_id] = (
            [{"role": "system", "content": f"{prefix}\n{summary}"}]
            + recent
        )

    def _compression_prompts(self) -> tuple[str, str, str]:
        """从模板文件返回 (prompt模板, 回退文本, 摘要前缀)。

        读取 templates/zh/compress.txt（中文）或 templates/compress.txt（英文）。
        """
        from system.pathutils import get_templates_dir
        templates: Path = get_templates_dir()
        zh_dir: Path = templates / "zh"
        use_zh: bool = zh_dir.is_dir()

        prompt_tpl: str = ""
        compress_file: Path = (zh_dir if use_zh else templates) / "compress.txt"
        if compress_file.is_file():
            try:
                prompt_tpl = compress_file.read_text(encoding="utf-8").strip()
            except OSError:
                pass

        if not prompt_tpl:
            prompt_tpl = (
                "Summarize the key content and decisions of the following conversation in no more than 200 characters. Output only the summary.\n\n"
                "Conversation:\n{{old_text}}\n\nSummary: "
            )

        if use_zh:
            return prompt_tpl, "(Conversation too long, auto-truncated)", "[Context Summary]"
        return prompt_tpl, "(History too long, truncated)", "[Context Summary]"

    async def _rotate_session(self, session_id: str) -> str | None:
        """归档当前会话并创建带摘要的新会话。

        由 _compress_history 在容量检查触发时调用。
        返回新 session_id，或 None 表示旋转失败。
        """
        if self._session_manager is None:
            return None

        sm = self._session_manager
        old_sid: str = session_id

        # 1. 对完整历史做 LLM 摘要
        summary: str = ""
        try:
            history: List[Dict[str, Any]] = self._get_history(old_sid)
            parts: list[str] = []
            for m in history:
                role: str = m.get("role", "unknown")
                content: str = self._extract_text(m.get("content", ""))[:500]
                if content:
                    parts.append(f"[{role}]: {content}")
            old_text: str = "\n".join(parts[-50:])
            if old_text.strip():
                prompt, fallback, _ = self._compression_prompts()
                summary_prompt: str = prompt.replace(r"{{old_text}}", old_text)
                summary_resp: LLMResponse = await self._llm.chat(
                    [{"role": "user", "content": summary_prompt}],
                    tools=[],
                )
                summary = summary_resp.content.strip()[:300] if summary_resp.content else ""
                if not summary:
                    summary = fallback
            if not summary:
                summary = "(Session context archived)"
        except Exception:
            summary = "(Session context archived)"

        # 2. 同步 memory
        try:
            self._memory.sync_all("", summary, session_id=old_sid)
        except Exception:
            pass

        # 3. 归档旧会话
        new_sid = sm.create_with_context(summary, old_sid)
        sm.archive(old_sid, continuation_sid=new_sid)

        # 4. 将新会话的历史加载到内存
        self._histories[new_sid] = self._load_history_from_disk(new_sid)
        self._last_prompt_tokens[new_sid] = 0
        self._session_rotated_notify[old_sid] = new_sid

        logger.info(
            "Session rotated | old=%s new=%s (summary=%d chars)",
            old_sid, new_sid, len(summary),
        )
        return new_sid

    def _build_messages(
        self,
        session_id: str,
        user_message: str,
        memory_ctx: str,
    ) -> List[Dict[str, Any]]:
        """构建当前回合的完整消息列表。"""
        # 收集已启用的 skill prompt
        skill_blocks: list[str] = self._collect_skill_prompts()

        system_prompt: str = build_system_prompt(
            mode=self._ctx.mode,
            memory_context=memory_ctx,
            extra_blocks=skill_blocks,
            lang="zh",
            workspace=self._ctx.workspace,
            agentspace=str(self._ctx.agentspace),
            fork_path=str(self._ctx.fork_path),
            fix_fork_path=str(self._ctx.fix_path) if self._ctx.fix_path else "",
            fix_log_path=str(self._ctx.fix_log_path or ""),
        )
        # 缓存 system prompt 用于 token 估算
        self._cached_system_prompt = system_prompt

        history: List[Dict[str, Any]] = self._get_history(session_id)
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        return messages

    def _get_full_history(self, session_id: str, memory_ctx: str = "") -> List[Dict[str, Any]]:
        """从存储的历史中重建完整消息列表（循环中间使用）。"""
        skill_blocks: list[str] = self._collect_skill_prompts()
        system_prompt: str = build_system_prompt(
            mode=self._ctx.mode,
            memory_context=memory_ctx,
            extra_blocks=skill_blocks,
            lang="zh",
            workspace=self._ctx.workspace,
            agentspace=str(self._ctx.agentspace),
            fork_path=str(self._ctx.fork_path),
            fix_fork_path=str(self._ctx.fix_path) if self._ctx.fix_path else "",
            fix_log_path=str(self._ctx.fix_log_path or ""),
        )
        history: List[Dict[str, Any]] = self._get_history(session_id)
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        messages.extend(history)
        return messages

    def _store_assistant_with_tools(
        self, session_id: str, resp: LLMResponse,
    ) -> None:
        """存储包含工具调用的 assistant 消息。"""
        tool_calls_data: list[dict] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in resp.tool_calls
        ]
        history: List[Dict[str, Any]] = self._get_history(session_id)
        entry: Dict[str, Any] = {
            "role": "assistant",
            "content": resp.content or None,
            "tool_calls": tool_calls_data,
        }
        if resp.reasoning_content:
            entry["reasoning_content"] = resp.reasoning_content
        history.append(entry)
        self._persist_message(session_id, entry)

    async def _execute_tool(self, tc: ToolCall, session_id: str = "") -> Dict[str, Any]:
        """执行单个工具调用，返回 OpenAI 格式的工具消息。"""
        # 响应中断 — 每次工具执行前检查。
        # 同时检查取消事件，以处理中断在前一个 LLM 调用期间到达的情况。
        cancel_ev: asyncio.Event | None = self._cancel_events.get(session_id)
        if (
            self._interrupted.pop(session_id, False)
            or (cancel_ev is not None and cancel_ev.is_set())
        ):
            return {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": "Cancelled.",
            }
        # 注入 session 上下文，使 run_command 等工具能够识别
        # 前端 session 以进行用户确认提示。
        args: dict = dict(tc.arguments) if tc.arguments else {}
        args["_session_id"] = session_id

        # 如果工具调用参数解析失败（例如因 max_tokens 太紧导致 JSON
        # 被截断），返回清晰的错误信息，使 LLM 理解原因并调整策略。
        if args.get("_parse_error"):
            logger.warning(
                "Tool call '%s' skipped — arguments JSON parse failed. "
                "Preview: %s", tc.name, args.get("_raw_preview", "")[:200],
            )
            _result: str = str(json.dumps({
                "error": (
                    "Tool call parameter parsing failed. Your arguments JSON is incomplete or malformed "
                    "(possibly truncated due to content being too long). Please try: "
                    "1) Split content into multiple writes, "
                    "2) Use edit_file for incremental edits, "
                    "3) Or reduce the amount of data written in a single call."
                ),
                "_parse_failed": True,
            }, ensure_ascii=False))
            # Fire-and-forget: 前端推送是尽力而为的副作用，
            # 不能因为 WebSocket 发送失败或阻塞就中断工具执行主链路。
            if self._tool_event_callback:
                asyncio.create_task(
                    self._tool_event_callback(
                        session_id, "tool_result", tc.name, _result,
                    ) # type: ignore
                )
            return {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": _result,
            }

        logger.info("Tool call: %s args=%s", tc.name, tc.arguments)

        # ---- 追踪工具调用统计 ----
        if tc.name not in self._tool_stats:
            self._tool_stats[tc.name] = {"calls": 0, "errors": 0}
        self._tool_stats[tc.name]["calls"] += 1

        # ---- 通知前端：tool_call (fire-and-forget) ----
        # 前端推送是尽力而为的副作用，不阻塞工具执行主链路。
        if self._tool_event_callback:
            asyncio.create_task(
                self._tool_event_callback(
                    session_id, "tool_call", tc.name,
                    json.dumps(tc.arguments, ensure_ascii=False),
                ) # type: ignore
            )

        # ---- 冒险模式写入审批 ----
        _skip_dispatch = False
        result: str = ""
        danger_level: str = tool_registry.get_danger_level(tc.name)
        if danger_level == "write" and is_adventure_mode(session_id):
            _approval_args = {k: v for k, v in args.items() if k != "_session_id"}

            approval = await request_user_confirm(
                session_id, tc.name, _approval_args,
                reason=str(args.get("reason", "")),
                content=f"Tool: {tc.name}\nParameters: {json.dumps(_approval_args, ensure_ascii=False)[:500]}",
                ask_agent_callback=lambda q: ask_agent_reason(self._llm, tc.name, _approval_args, q),
            )
            if approval.action == "deny":
                source_label = {"model": "approval model", "user": "user", "system": "system"}.get(approval.denied_by, "system")
                result = json.dumps({
                    "error": f"[{source_label} denied] {approval.deny_reason or 'unknown reason'}",
                    "denied": True,
                    "denied_by": approval.denied_by,
                }, ensure_ascii=False)
                _skip_dispatch = True

        if not _skip_dispatch:
            timeout: int = self._ctx.tool_timeout
            # 如果 memory 管理器拥有该工具，则路由过去
            if self._memory.has_tool(tc.name):
                try:
                    if timeout:
                        result = await asyncio.wait_for(
                            asyncio.to_thread(self._memory.handle_tool_call, tc.name, args),
                            timeout=timeout,
                        )
                    else:
                        result = self._memory.handle_tool_call(tc.name, args)
                except asyncio.TimeoutError:
                    result = json.dumps({"error": f"Tool execution timed out ({timeout}s)"}, ensure_ascii=False)
                except Exception as exc:
                    result = json.dumps({"error": str(exc)}, ensure_ascii=False)
            else:
                entry: ToolEntry | None = tool_registry.get_entry(tc.name)
                try:
                    if entry and entry.is_async:
                        coro: Any = entry.handler(args)
                    else:
                        coro = asyncio.to_thread(tool_registry.dispatch, tc.name, args)
                    if timeout:
                        result = await asyncio.wait_for(coro, timeout=timeout)
                    else:
                        result = await coro
                except asyncio.TimeoutError:
                    result = json.dumps({"error": f"Tool execution timed out ({timeout}s)"}, ensure_ascii=False)
                except Exception as exc:
                    result = json.dumps({"error": str(exc)}, ensure_ascii=False)

        # ---- 追踪工具错误统计 ----
        try:
            parsed: Any = json.loads(result)
            if isinstance(parsed, dict) and "error" in parsed:
                if tc.name in self._tool_stats:
                    self._tool_stats[tc.name]["errors"] += 1
        except (json.JSONDecodeError, TypeError):
            pass

        # ---- 工具结果大小截断 ----
        _MAX_RESULT_CHARS: int = 50_000
        if len(result) > _MAX_RESULT_CHARS:
            _ts: str = datetime.now().strftime("%Y%m%d_%H%M%S")
            _rel: str = f"tool_results/{_ts}_{tc.name}.txt"
            _full: Path = self._ctx.agentspace / _rel.replace("/", "\\")
            try:
                _full.parent.mkdir(parents=True, exist_ok=True)
                _full.write_text(result, encoding="utf-8")
                _preview: str = result[:2000]
                result = (
                    f"[Result too long ({len(result)} chars), full content written to ws:{_rel}]\n"
                    f"[First 2000 chars preview]:\n{_preview}"
                )
            except Exception as _exc:
                logger.warning("Failed to write tool result to file: %s", _exc)

        # ---- 通知前端：tool_result (fire-and-forget) ----
        # 前端推送是尽力而为的副作用，不阻塞工具执行主链路。
        if self._tool_event_callback:
            # 对含图片的结果，推送时不包含 base64 数据
            push_result: str = result
            try:
                pr: dict = json.loads(result)
                if "_image" in pr:
                    pr_copy: dict = dict(pr)
                    img_info: dict = pr_copy.pop("_image", {})
                    img_info.pop("base64", None)  # 不向前端发送 base64
                    pr_copy["_image"] = img_info
                    push_result = json.dumps(pr_copy, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                pass
            asyncio.create_task(
                self._tool_event_callback(
                    session_id, "tool_result", tc.name, push_result,
                ) # type: ignore
            )

        # ---- 构建 OpenAI 格式的工具消息 ----
        # 检查结果是否包含图片数据（_image 键）。
        # 如果有，将 content 格式化为 content blocks 列表，
        # 使 vision-capable LLM 能够通过 ToolMessage "看到"图片。
        content: Any = result
        try:
            parsed_result: dict = json.loads(result)
            img: dict | None = parsed_result.pop("_image", None)
            if img and isinstance(img, dict):
                b64: str = str(img.get("base64", ""))
                mime: str = str(img.get("mime_type", "image/png"))
                if b64 and self._supports_vision():
                    text_json: str = json.dumps(parsed_result, ensure_ascii=False)
                    content = [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        },
                        {"type": "text", "text": text_json},
                    ]
                elif b64:
                    # Model does not support vision — return text-only degraded result,
                    # clearly informing the agent that the current model cannot view images.
                    fallback: dict = dict(parsed_result)
                    fallback["_vision_unsupported"] = True
                    fallback["_model"] = self._ctx.llm_model
                    fallback["_hint"] = (
                        f"The current model ({self._ctx.llm_model}) does not support image vision analysis. "
                        f"You cannot view the content of this image. Below is the image metadata:\n"
                        f"Path={fallback.get('path', '?')}, "
                        f"Format={mime}, "
                        f"Size={fallback.get('size', '?')} bytes. "
                        f"If you need further processing of the image (e.g. OCR, format conversion), "
                        f"you can use run_command to call external tools "
                        f"(e.g. tesseract, ImageMagick) to extract text or convert formats."
                    )
                    # 不向 LLM 发送 base64 数据 — 模型无法处理且浪费 token
                    content = json.dumps(fallback, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError, KeyError):
            pass

        return {
            "role": "tool",
            "tool_call_id": tc.id,
            "content": content,
        }

    def _get_tool_definitions(self) -> List[Dict[str, Any]]:
        """返回 LLM 可用的工具 schema（registry + memory）。"""
        names: set[str] = set(tool_registry.get_all_tool_names())
        definitions: list[dict] = tool_registry.get_definitions(tool_names=names)

        # 合并 memory 工具 schema（包装为 OpenAI 格式）
        for schema in self._memory.get_tool_schemas():
            definitions.append({"type": "function", "function": schema})

        return definitions if definitions else None  # type: ignore[return-value]

    def get_session_messages(self, session_id: str) -> list[dict]:
        """返回格式化后的会话历史，供前端回放。"""
        # 如果尚未加载到内存，先从磁盘加载
        history: List[Dict[str, Any]] = self._get_history(session_id)
        messages: list[dict] = []
        for entry in history:
            role: str = entry.get("role", "")
            content: str = self._extract_text(entry.get("content", ""))
            if role == "user":
                messages.append({"role": "user", "content": content})
            elif role == "assistant":
                msg: dict = {"role": "agent", "content": content}
                if entry.get("reasoning_content"):
                    msg["reasoning_content"] = entry["reasoning_content"]
                messages.append(msg)
            elif role == "tool":
                messages.append({"role": "tool", "content": content})
        return messages

    def get_token_usage(self, session_id: str) -> int:
        """返回 session 当前的 prompt token 消耗。"""
        if session_id in self._token_usage:
            return self._token_usage[session_id]
        # 内存缺失 — 尝试从磁盘加载（支持重启/进化后恢复）
        disk_usage: int = self._load_token_usage_from_disk(session_id)
        if disk_usage:
            self._token_usage[session_id] = disk_usage
        return disk_usage

    def get_context_tokens(self, session_id: str) -> int:
        """返回 session 最近一次 LLM 调用的 prompt_tokens（已用上下文）。"""
        return self._last_prompt_tokens.get(session_id, 0)