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
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List

from abstract.memory.manager import MemoryManager
from abstract.tools.registry import registry as tool_registry
from component.llm import LLMClient, LLMResponse
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
                # 替换为提示文本
                new_blocks.append({
                    "type": "text",
                    "text": "[图片内容已剥离 — 当前模型不支持 vision 功能]",
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

        # ---- 历史过长时进行压缩 ----
        await self._compress_history(session_id)

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
                    return "已中断。"
                turn += 1

                # ---- 可取消的 LLM 调用 ----
                # 同时等待 LLM task 和取消事件，使中断能够
                # 穿透正在进行的 HTTP 请求，而不是等待其完成。
                llm_task: asyncio.Task[LLMResponse] = asyncio.create_task(
                    self._llm.chat(messages, tools=self._get_tool_definitions()),
                )
                cancel_task: asyncio.Task[None] = asyncio.create_task(cancel_event.wait())

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
                    return "已中断。"

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
                                self._append(session_id, "assistant", "进化已完成，正在重启以应用新代码...")
                                return "进化已完成，正在重启以应用新代码..."
                        except (json.JSONDecodeError, KeyError, TypeError):
                            pass

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
                lines.append(f"用户: {content[:300]}")
            elif role == "assistant":
                lines.append(f"助手: {content[:300]}")
        if not lines:
            return ""
        context: str = "\n".join(lines[-10:])

        # 从模板文件读取自动标题 prompt
        templates: Path = Path(__file__).resolve().parent.parent / "templates"
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
                "根据以下对话内容，用不超过20个字概括对话主题。"
                "只输出标题，不要多余内容。\n\n{{context}}\n\n标题："
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

    def _estimate_context_tokens(self, session_id: str) -> int:
        """通过 tiktoken 计算历史 + system prompt 的实际上下文 token 数。

        用于驱动压缩决策 — 与仅用于 dashboard 展示的
        累计 ``_token_usage`` 计数器不同。
        """
        import tiktoken

        history: List[Dict[str, Any]] = self._get_history(session_id)
        if not history:
            return 0

        try:
            enc: Any = tiktoken.encoding_for_model(self._ctx.llm_model)
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

        # 加上 system prompt 估算值（由 _build_messages 构建）
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
        threshold_tokens: int = int(max_tokens * self._ctx.llm_context_upbound)

        # 使用实际上下文大小估算 — 而非累计 _token_usage
        current_tokens: int = self._estimate_context_tokens(session_id)
        if current_tokens < threshold_tokens:
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
        from pathlib import Path
        templates: Path = Path(__file__).resolve().parent.parent / "templates"
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
                "请用200字以内总结以下对话的关键内容和决策点。只输出总结。\n\n"
                "对话内容：\n{{old_text}}\n\n总结："
            )

        if use_zh:
            return prompt_tpl, "（历史对话过长，已自动截断）", "[上下文摘要]"
        return prompt_tpl, "(History too long, truncated)", "[Context Summary]"

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

    async def _execute_tool(self, tc: Any, session_id: str = "") -> Dict[str, Any]:
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
                "content": "已中断。",
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
            result: str = json.dumps({
                "error": (
                    "工具调用参数解析失败。你的 arguments JSON 不完整或格式错误"
                    "（可能因为内容太长被截断）。请尝试："
                    "1) 拆分内容为多段写入，"
                    "2) 使用 edit_file 做增量修改，"
                    "3) 或者减少单次写入的数据量。"
                ),
                "_parse_failed": True,
            })
            # Fire-and-forget: 前端推送是尽力而为的副作用，
            # 不能因为 WebSocket 发送失败或阻塞就中断工具执行主链路。
            if self._tool_event_callback:
                asyncio.create_task(
                    self._tool_event_callback(
                        session_id, "tool_result", tc.name, result,
                    )
                )
            return {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
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
                )
            )

        # 如果 memory 管理器拥有该工具，则路由过去
        if self._memory.has_tool(tc.name):
            try:
                if timeout := self._ctx.tool_timeout:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(self._memory.handle_tool_call, tc.name, args),
                        timeout=timeout,
                    )
                else:
                    result = self._memory.handle_tool_call(tc.name, args)
            except asyncio.TimeoutError:
                result = json.dumps({"error": f"工具执行超时（{timeout}秒）"})
            except Exception as exc:
                result = json.dumps({"error": str(exc)})
        else:
            entry: Any = tool_registry.get_entry(tc.name)
            try:
                if entry and entry.is_async:
                    coro: Any = entry.handler(args)
                else:
                    coro = asyncio.to_thread(tool_registry.dispatch, tc.name, args)
                if timeout := self._ctx.tool_timeout:
                    result = await asyncio.wait_for(coro, timeout=timeout)
                else:
                    result = await coro
            except asyncio.TimeoutError:
                result = json.dumps({"error": f"工具执行超时（{timeout}秒）"})
            except Exception as exc:
                result = json.dumps({"error": str(exc)})

        # ---- 追踪工具错误统计 ----
        try:
            parsed: Any = json.loads(result)
            if isinstance(parsed, dict) and "error" in parsed:
                if tc.name in self._tool_stats:
                    self._tool_stats[tc.name]["errors"] += 1
        except (json.JSONDecodeError, TypeError):
            pass

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
                )
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
                    # 模型不支持 vision — 返回纯文本降级结果，
                    # 明确告知 agent 当前模型无法查看图片。
                    fallback: dict = dict(parsed_result)
                    fallback["_vision_unsupported"] = True
                    fallback["_model"] = self._ctx.llm_model
                    fallback["_hint"] = (
                        f"当前模型 ({self._ctx.llm_model}) 不支持图像视觉分析。"
                        f"你无法查看此图片的内容。以下是图片文件的元数据信息："
                        f"路径={fallback.get('path', '?')}、"
                        f"格式={mime}、"
                        f"大小={fallback.get('size', '?')} bytes。"
                        f"如果你需要对图片做进一步处理（如 OCR、格式转换），"
                        f"可以使用 run_command 调用外部工具（如 tesseract、ImageMagick）"
                        f"来提取图片中的文本或转换格式。"
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
                messages.append({"role": "agent", "content": content})
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