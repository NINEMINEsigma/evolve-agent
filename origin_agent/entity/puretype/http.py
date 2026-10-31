"""Non-persistent HTTP error transport data."""

from pydantic import BaseModel, ConfigDict


class HTTPErrorDetail(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str
    message: str
