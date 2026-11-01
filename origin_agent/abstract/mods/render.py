"""Single-pass, explicit-value mod templates; no expression evaluation."""

from __future__ import annotations

import re

from entity.error import ModTemplateError
from entity.puretype import ModDocument, ModRenderContext


def render_mod_document(document: ModDocument, context: ModRenderContext) -> str:
    values = {
        "session_id": context.resource_session_id,
        "resource_session_id": context.resource_session_id,
        "owner_intro": context.owner_intro,
        "gateway_port": str(context.gateway_port),
        "mcp_config_path": context.mcp_config_path,
        "files_prefix": context.files_prefix,
        "downloads_prefix": context.downloads_prefix,
        "local_font_prefix": context.local_font_prefix,
        "variables_dir": context.variables_dir,
    }

    def replace(match: re.Match[str]) -> str:
        if match.group(1):
            return match.group(0)[1:]
        key = match.group(2).strip()
        if key not in values or not values[key]:
            raise ModTemplateError(
                f"Unsupported or unavailable placeholder {key!r} in {document.metadata.name}",
                document.metadata.name,
            )
        return values[key]

    pattern = re.compile(r"(\\)?\{\{(.*?)\}\}", re.DOTALL)
    if "{{" in pattern.sub("", document.body):
        raise ModTemplateError("Unterminated mod placeholder", document.metadata.name)
    return pattern.sub(replace, document.body)
