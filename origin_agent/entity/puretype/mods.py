"""Pre-message data for local mod discovery and rendering."""

from pydantic import BaseModel


class ModMetadata(BaseModel):
    name: str
    description: str
    related: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()


class ModCatalog(BaseModel):
    entries: tuple[ModMetadata, ...] = ()


class ModDocument(BaseModel):
    metadata: ModMetadata
    body: str


class ModRenderContext(BaseModel):
    resource_session_id: str
    owner_intro: str
    gateway_port: int
    mcp_config_path: str
    files_prefix: str
    downloads_prefix: str
    local_font_prefix: str
    variables_dir: str


class ModReadRequest(BaseModel):
    names: tuple[str, ...] | None = None
