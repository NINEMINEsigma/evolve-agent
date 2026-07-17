from __future__ import annotations

import logging
from typing import * # type: ignore

from abstract.tools.registry import registry, tool_result
from custom_tools.memory_tools._store import (
    FALLBACK_SESSION,
    load_all_memory,
    save_all_memory,
    find_key_in_chain,
    ensure_session_memory,
)

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext

logger = logging.getLogger(__name__)


def _handle_forget(args: dict[str, Any], context: ToolContext | None = None) -> dict:
    """忘记一条信息。"""
    id = args["id"]
    if context:
        memory_data_file = (context.runtime_context.agentspace / "memory_data.json").absolute()
        session_id = context.session_id or FALLBACK_SESSION
        data = load_all_memory(memory_data_file)
        # 确保父链引用已建立，使 BFS 搜索能遍历到父会话
        ensure_session_memory(data, session_id)
        # 沿父链 BFS 搜索第一个包含该 key 的 dict（可能是父会话的记忆）
        target_dict = find_key_in_chain(data, session_id, id)
        if target_dict is None:
            return tool_result(success=False, message=f"id {id} is not found.")
        del target_dict[id]
        save_all_memory(memory_data_file, data)
    return tool_result(success=True, message=f"id {id} has been forgotten.")


# ── 注册 ─────────────────────────────────────────────────────

registry.register(
    name="forget",
    toolset="memory_tools",
    schema={
        # 从记忆存储中删除指定 id 的记忆项。
        # 沿父会话引用链搜索：如果记忆来自父会话，则直接在父会话中删除，所有引用该父的子会话都会生效。
        # 前置条件：无。
        # 调用效果：沿父链 BFS 搜索，在第一个找到的 dict 中删除；否则返回错误。
        # 返回值：{ success: bool, message: string }
        # 何时使用：需要移除过期、错误或不再需要的记忆时。
        # 副作用：修改磁盘上的记忆文件；删除后的条目不再被 remember_memory hook 召回。
        #         如果删除的是父会话的记忆，所有继承该父的子会话也会失去该条目。
        "description": """Remove a memory entry from long-term memory by id.

## Prerequisites
None.

## Effect
Searches for the given id along the session's parent chain (BFS) and deletes it from the first dict that contains it. This means memories inherited from parent sessions can also be forgotten — the deletion occurs in the parent session's storage, affecting all child sessions that inherit from it.

## Returns
```json
{ "success": true, "message": "id <id> has been forgotten." }
```
When the id is not found:
```json
{ "success": false, "message": "id <id> is not found." }
```

## When to Use
- Removing outdated or incorrect memories.
- Cleaning up temporary entries that are no longer needed.
- Forgetting a memory that was inherited from a parent session.

## Side Effects
Writes to the agent's memory file on disk. Deleted entries are no longer recalled by the remember_memory hook. If the deleted memory belonged to a parent session, all child sessions inheriting from that parent will also lose the entry.""",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    # 要删除的记忆项的唯一标识符。可以是当前会话或任何父会话中的记忆。
                    "description": """The unique identifier of the memory entry to delete. Can be a memory from the current session or any parent session in the inheritance chain.""",
                },
            },
            "required": ["id"],
        },
    },
    handler=_handle_forget,
    is_async=False,
)