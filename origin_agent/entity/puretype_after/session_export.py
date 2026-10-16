"""与 live History 隔离的离线导出输入，只供当前请求计算使用。"""

from pydantic import BaseModel

from entity.messages import BaseMessage


class SessionExportHistorySource(BaseModel):
    loop_instance_id: str
    export_epoch: int
    history_count: int
    fallback_character: str
    messages: tuple[BaseMessage, ...]
