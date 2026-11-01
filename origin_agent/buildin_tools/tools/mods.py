"""Read feature guidance through the ordinary, permission-neutral tool pipeline."""

from __future__ import annotations

import json
import re
from typing import Any

from abstract.mods.loader import discover_mods, read_mod_documents, resolve_related_names
from abstract.mods.render import render_mod_document
from abstract.tools.tool import BaseTool, BaseToolSet, ToolExecution, ToolHandlerResult, tool_error
from entity.constant import MOD_MAX_REQUEST_NAMES, MOD_NAME_PATTERN, MOD_MAX_RENDERED_BYTES
from entity.error import ModRequestError, ModBudgetExceededError
from entity.messages import ModTextBlock, ToolResultMessage
from entity.puretype import ModReadRequest, Role, ToolAvailability, ToolDangerLevel
from system.mods import get_mods_root, build_mod_render_context


class RecallModTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            name="RecallMod", toolset="core", availability=ToolAvailability.EVERY,
            danger_level=ToolDangerLevel.safe,
            schema={
                "description": (
                    "Read system-feature guidance. Omit names to list available mods; "
                    "supply a non-empty names array to read full guides and their recursive "
                    "related guides in one call. Repeated explicit reads return current full "
                    "content. Reading does not execute features, load toolsets or grant permissions."
                ),
                "parameters": {
                    "type": "object", "additionalProperties": False,
                    "properties": {"names": {"type": "array", "minItems": 1,
                        "maxItems": MOD_MAX_REQUEST_NAMES, "items": {"type": "string"}}},
                },
            },
        )

    def ensure_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        # 内部reason/审批字段由已有分发协议处理，不属于公开工具参数。
        from entity.constant import TOOL_INTERNAL_ARG_KEYS
        unknown = arguments.keys() - {"names", "reason", *TOOL_INTERNAL_ARG_KEYS}
        if unknown:
            raise ModRequestError(f"Unknown RecallMod arguments: {sorted(unknown)}")
        if "names" not in arguments:
            return {}
        names = arguments["names"]
        if not isinstance(names, list) or not 1 <= len(names) <= MOD_MAX_REQUEST_NAMES:
            raise ModRequestError(f"names must contain 1 to {MOD_MAX_REQUEST_NAMES} strings")
        for name in names:
            if not isinstance(name, str) or re.fullmatch(MOD_NAME_PATTERN, name) is None:
                raise ModRequestError(f"Invalid mod name: {name!r}")
        return {"names": list(names)}

    def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        root = get_mods_root()
        catalog = discover_mods(root)
        request = ModReadRequest(
            names=tuple(execution.arguments["names"]) if "names" in execution.arguments else None,
        )
        if request.names is None:
            return ToolHandlerResult({
                "mods": [entry.model_dump() for entry in catalog.entries], "total": len(catalog.entries),
            })
        try:
            order = resolve_related_names(catalog, request.names)
        except ModRequestError as error:
            return ToolHandlerResult(tool_error(str(error)))
        context = execution.context
        character = context.character_name or context.loop.current_character_agent
        render_context = build_mod_render_context(context.runtime_context, context.resource_session_id)
        documents = read_mod_documents(root, catalog, order)
        blocks = tuple(ModTextBlock(
            text=render_mod_document(document, render_context), mod_name=document.metadata.name,
            resource_session_id=context.resource_session_id, visible_characters=(character,),
        ) for document in documents)
        result = {"success": True, "requested": list(dict.fromkeys(request.names)), "order": list(order)}
        transient = ToolResultMessage(
            role=Role.TOOL, character_name=character, tool_call_id=execution.tool_call_id,
            content=result, result_text_blocks=list(blocks),
        )
        content = transient.as_content(character)
        size = len(json.dumps(content, ensure_ascii=False).encode("utf-8"))
        if size > MOD_MAX_RENDERED_BYTES:
            raise ModBudgetExceededError("Complete mod result exceeds its encoded content budget")
        return ToolHandlerResult(result, result_text_blocks=blocks)


TOOLSET = BaseToolSet(name="core", tools=(RecallModTool(),))
