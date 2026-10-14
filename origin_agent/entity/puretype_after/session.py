"""Pure session data types that depend on defined message models."""

from pydantic import BaseModel

from entity.messages import BaseMessage


class ToolChainReplacement(BaseModel):
    """Prepared replacement for a half-open tool chain range; not persisted."""

    start: int
    end: int
    messages: list[BaseMessage]
