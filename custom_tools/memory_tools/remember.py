from __future__ import annotations

from easysave import save, load
import logging
from typing import * # type: ignore

from abstract.tools.registry import registry, tool_result

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext

logger = logging.getLogger(__name__)

__VERSION__ = "v0"


def _handle_remember(args: dict[str, Any], context: ToolContext | None = None) -> dict:
    """记住一条信息。"""
    id = args["id"]
    message = args["content"]
    is_overwrite = args["is_overwrite"]
    if context:
        memory_data_file = (context.runtime_context.agentspace/"memory_data.json").absolute()
        memory_data: dict[str, str]
        if memory_data_file.exists():
            memory_data = load(__VERSION__, str(memory_data_file), dict[str, str])
        else:
            memory_data = {}
        if id in memory_data and not is_overwrite:
            return tool_result(success=False, message=f"id {id} is already exists and overwrite is not allowed.Current content: {memory_data[id]}")
        memory_data[id] = message
        save(__VERSION__, str(memory_data_file), memory_data)
    return tool_result(success=True, message=f"id {id} has been remembered.")


# ── 注册 ─────────────────────────────────────────────────────

registry.register(
    name="remember",
    toolset="memory_tools",
    schema={
        # 将一条信息持久化到记忆存储，供后续会话通过 remember_memory hook 读取。
        # 使用 id 作为唯一键，content 作为记忆内容。
        # 若 id 已存在且 is_overwrite 为 false，则保留原内容并返回错误。
        # 前置条件：无。
        # 调用效果：将 {id: content} 写入 agentspace 中的记忆文件。
        # 返回值：{ success: bool, message: string }
        # 何时使用：保存用户偏好、长期事实、约定等需要跨会话保留的信息。
        # 副作用：修改磁盘上的记忆文件；重复调用同一 id 可能在 is_overwrite=true 时覆盖旧数据。
        "description": """Persist a piece of information to long-term memory so it can be recalled in future sessions via the remember_memory hook.

## Prerequisites
None.

## Effect
Stores the provided content under the given id in the agent's memory file. If the id already exists and is_overwrite is false, the existing entry is preserved and an error is returned.

## Returns
```json
{ "success": true, "message": "id <id> has been remembered." }
```
On conflict (overwrite disabled):
```json
{ "success": false, "message": "id <id> already exists and overwrite is not allowed. Current content: ..." }
```

## When to Use
- Saving user preferences, long-term facts, or agreements that should persist across sessions.
- Recording context that the agent should recall automatically later.

## Side Effects
Writes to the agent's memory file on disk. Repeated calls with the same id may overwrite existing data when is_overwrite is true.""",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    # 记忆项的唯一标识符。用于后续读取或删除。
                    "description": """A unique identifier for this memory entry. Used for later recall or deletion.""",
                },
                "content": {
                    "type": "string",
                    # 要保存的记忆内容。
                    "description": """The content to remember.""",
                },
                "is_overwrite": {
                    "type": "boolean",
                    # 当 id 已存在时，是否覆盖原有内容。默认 false。
                    "description": """Whether to overwrite an existing entry with the same id. Defaults to false.""",
                    "default": False,
                },
            },
            "required": ["id", "content"],
        },
    },
    handler=_handle_remember,
    is_async=False,
)