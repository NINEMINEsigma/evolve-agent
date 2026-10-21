"""五种文件工具复用的调用级成功记录器，不注册工具。"""

from abstract.tools.tool import ToolExecution
from entity.puretype import SessionFileChangeActor, SessionFileChangeOperation
from interface.agentspace_service import IAgentspaceService


class FileChangeRecorder:
    def __init__(self, execution: ToolExecution) -> None:
        self._execution = execution
        context = execution.context
        self._session_id = context.resource_session_id
        self._actor = SessionFileChangeActor(
            session_id=context.session_id,
            character_name=context.character_name or context.loop.current_character_agent,
        )
        self._store = context.app.get_system(IAgentspaceService).file_changes

    def is_cancelled(self) -> bool:
        return self._execution.cancel_requested or self._execution.context.is_interrupted

    def record(self, operation: SessionFileChangeOperation) -> bool:
        return self._store.record_success(
            self._session_id, self._actor, operation, is_cancelled=self.is_cancelled,
        )
