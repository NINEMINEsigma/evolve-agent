"""Invocation-local message replacements; never persisted as a separate store."""

from pydantic import BaseModel
from entity.messages import BaseMessage


class ModMessageReplacement(BaseModel):
    index: int
    original: BaseMessage
    replacement: BaseMessage
