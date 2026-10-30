"""当前主会话变量池的只读整池工具；写入仍复用文件工具。"""

from __future__ import annotations

from interface.agentspace_service import IAgentspaceService
from interface.session_manager import ISessionManager

from typing import TYPE_CHECKING, Any

from abstract.tools.tool import BaseTool, BaseToolSet, ToolExecution, ToolHandlerResult, tool_error
from entity.constant import SESSION_VARIABLES_READ_TOOL_NAME, SESSION_VARIABLES_READ_TOOL_RESULT_MAX_CHARS
from entity.puretype import ToolAvailability, ToolDangerLevel

if TYPE_CHECKING:
    # 仅类型引用；运行期在 handler 内惰性导入，避免工具发现期的导入环。
    from entry.base_agent_loop import ToolContext


def _handle_read_session_variables(args: dict[str, Any], context: "ToolContext | None" = None) -> dict[str, Any]:
    from system.session_variables import SessionVariableError

    if context is None or not context.resource_session_id:
        return tool_error("A current main session context is required", code="invalid_context")
    session_id = context.resource_session_id
    manager = context.app.get_system(ISessionManager)
    if not manager.exists(session_id) or manager.is_session_deleting(session_id):
        return tool_error("Session not found", code="session_not_found")
    service = context.app.get_system(IAgentspaceService).session_variables
    try:
        result = service.read_pool(
            session_id, register_access=lambda path: context.agentspace_access([(path, False)])
        )
    except SessionVariableError as exc:
        return tool_error(str(exc), code=exc.code, logical_path=exc.logical_path)
    if not manager.exists(session_id) or manager.is_session_deleting(session_id):
        return tool_error("Session not found", code="session_not_found")
    return result.model_dump(mode="json")


_READ_SESSION_VARIABLES_SCHEMA = {
            "description": (
                "Read all numeric and string variables from the current main session variable pool, "
                "including nested groups, original values, normalized metadata, and diagnostic issues. "
                "Sub-agents read their parent main session pool. This is read-only: use ordinary file "
                "tools to modify JSON scalar files and sibling .meta files. Load the filesystem toolset first. "
                "Limits fail explicitly rather than silently truncating the pool. scan_complete=false means "
                "an unsupported subtree was excluded; inspect issues before relying on the state. "
                "This is not a transactional snapshot. Re-read current values before a settlement; "
                "only the main Agent should settle shared variables."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}


class ReadSessionVariablesTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            name=SESSION_VARIABLES_READ_TOOL_NAME,
            toolset="filesystem",
            schema=_READ_SESSION_VARIABLES_SCHEMA,
            is_async=False,
            danger_level=ToolDangerLevel.safe,
            availability=ToolAvailability.EVERY,
            max_result_size_chars=SESSION_VARIABLES_READ_TOOL_RESULT_MAX_CHARS,
        )

    def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        return ToolHandlerResult(_handle_read_session_variables(execution.arguments, execution.context))


TOOLSET = BaseToolSet(name="filesystem", tools=(ReadSessionVariablesTool(),))
