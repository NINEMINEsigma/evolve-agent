"""Runtime values and compact discovery text for local mod guidance."""

from pathlib import Path

from abstract.mods.loader import discover_mods
from entity.constant import (
    MODS_DIR_NAME, STATIC_FILE_HTTP_PREFIX, DOWNLOADS_HTTP_PREFIX,
    LOCAL_FONT_HTTP_PREFIX, SESSION_VARIABLES_DIR_NAME,
)
from entity.puretype import ModCatalog, ModRenderContext
from system.context import RuntimeContext
from util.pathutils import find_repo_root


def get_mods_root() -> Path:
    return find_repo_root() / MODS_DIR_NAME


def build_mod_render_context(
    runtime_context: RuntimeContext,
    resource_session_id: str,
) -> ModRenderContext:
    if not resource_session_id:
        raise ValueError("Mod rendering requires a resource main session")
    agentspace = runtime_context.agentspace.resolve()
    mcp_path = Path(runtime_context.mcp_config_path).resolve() if runtime_context.mcp_config_path is not None else None
    mcp_logical_path = (
        f"ws:{mcp_path.relative_to(agentspace).as_posix()}"
        if mcp_path is not None and mcp_path.is_relative_to(agentspace) else ""
    )
    return ModRenderContext(
        resource_session_id=resource_session_id,
        owner_intro=(
            f"These resources belong to main session {resource_session_id}. "
            "For a separate sub-session this is the parent main session ID, not your own."
        ),
        gateway_port=runtime_context.gateway_port,
        mcp_config_path=mcp_logical_path,
        files_prefix=STATIC_FILE_HTTP_PREFIX,
        downloads_prefix=DOWNLOADS_HTTP_PREFIX,
        local_font_prefix=LOCAL_FONT_HTTP_PREFIX,
        variables_dir=SESSION_VARIABLES_DIR_NAME,
    )


def build_mod_catalog_block(catalog: ModCatalog) -> str:
    if not catalog.entries:
        return ""
    lines = [
        "Available mods (system-feature guidance):",
        "Use RecallMod without names to list, or names=[...] to read multiple full guides.",
        "Related guides are read recursively. Reading grants no tools or permissions.",
        "Read relevant full guidance before relying on its detailed procedures.",
        "",
    ]
    lines.extend(f"- {entry.name}: {entry.description}" for entry in catalog.entries)
    return "\n".join(lines)


def load_mod_catalog_block() -> str:
    return build_mod_catalog_block(discover_mods(get_mods_root()))
