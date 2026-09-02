"""MCP 输入 schema 的结构位置感知规范化。

MCP server 返回的 ``inputSchema`` 是 JSON Schema，但不同 server 和
OpenAI-compatible provider 对 JSON Schema 的支持范围并不完全一致。本模块
只处理 JSON-like 数据，不依赖 MCP SDK、ToolRegistry 或 LLM 客户端。

关键约束是区分 JSON Schema 的结构位置：``properties`` 的值是“属性名到
schema 的映射”，映射表本身不是 schema 节点。这样业务参数恰好命名为
``properties``、``type`` 或 ``required`` 时，也不会改变映射表的结构。
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# JSON Schema 中可作为裸 schema 类型缩写的类型名。``null`` 有意排除：
# 裸字符串 null 通常是损坏的 schema 载荷，不能直接生成容易被 provider
# 拒绝的 {"type": "null"}；显式的 {"type": "null"} 仍原样保留。
_SCHEMA_STRING_TYPES = frozenset({
    "object",
    "string",
    "number",
    "integer",
    "boolean",
    "array",
})

# 值为 schema 的单值关键字。它们的值进入 schema 节点位置；其余关键字
# 默认按字面量复制，避免 const/default/examples 等业务数据被再次解析。
_SCHEMA_VALUE_KEYS = frozenset({
    "items",
    "additionalItems",
    "contains",
    "propertyNames",
    "unevaluatedItems",
    "unevaluatedProperties",
    "additionalProperties",
    "if",
    "then",
    "else",
    "not",
    "contentSchema",
})

_SCHEMA_LIST_KEYS = frozenset({
    "prefixItems",
    "anyOf",
    "oneOf",
    "allOf",
})

_SCHEMA_MAP_KEYS = frozenset({
    "properties",
    "patternProperties",
    "$defs",
    "definitions",
    "dependentSchemas",
})

# 这些关键字的值是属性名、枚举值或其他任意 JSON 字面量，不是 schema。
_LITERAL_KEYS = frozenset({
    "required",
    "dependentRequired",
    "enum",
    "examples",
    "const",
    "default",
    "description",
    "title",
    "$id",
    "$schema",
    "$comment",
    "comment",
    "pattern",
    "format",
    "minLength",
    "maxLength",
    "patternProperties",  # 由 _SCHEMA_MAP_KEYS 分支优先处理；仅作文档标记
})


def _empty_object_schema() -> dict[str, Any]:
    """返回最小 provider 可传输的 object schema。"""
    return {"type": "object", "properties": {}}


def _rewrite_local_ref(value: str) -> str:
    """将旧 draft-07 definitions 引用改写为 $defs 引用。"""
    if value.startswith("#/definitions/"):
        return "#/$defs/" + value[len("#/definitions/"):]
    return value


def _emit(
    diagnostic: Callable[[str, str], None],
    path: str,
    code: str,
) -> None:
    """发送不含原始 schema 值的结构诊断。"""
    try:
        diagnostic(path, code)
    except Exception:
        # 诊断回调是非关键副作用，不能让 schema 规范化失败。
        logger.debug("MCP schema diagnostic callback failed", exc_info=True)


def _normalize_bare_schema_string(
    value: str,
    path: str,
    diagnostic: Callable[[str, str], None],
    *,
    for_additional_properties: bool = False,
) -> dict[str, Any] | bool:
    """把 schema 位置的裸字符串转换为合法 schema。"""
    if value in _SCHEMA_STRING_TYPES:
        _emit(diagnostic, path, "bare_schema_type_string")
        if value == "object":
            return _empty_object_schema()
        return {"type": value}

    # ``null`` 和未知字符串不能直接成为 JSON Schema 的 type 值。
    # additionalProperties 使用 true 保留“允许任意附加键”的语义；
    # 其他 schema 位置使用最小 object 作为安全可传输的降级形态。
    _emit(
        diagnostic,
        path,
        "invalid_additional_properties_string"
        if for_additional_properties
        else "invalid_bare_schema_string",
    )
    return True if for_additional_properties else _empty_object_schema()


def _normalize_schema_map(
    value: Any,
    path: str,
    diagnostic: Callable[[str, str], None],
) -> dict[Any, Any]:
    """规范化属性/定义映射的每个值，不规范化映射表本身。"""
    if not isinstance(value, dict):
        _emit(diagnostic, path, "invalid_schema_mapping")
        return {}

    result: dict[Any, Any] = {}
    for key, child in value.items():
        child_path = f"{path}.{key}"
        result[key] = _normalize_schema_node(child, child_path, diagnostic)
    return result


def _normalize_schema_list(
    value: Any,
    path: str,
    diagnostic: Callable[[str, str], None],
) -> list[Any]:
    """规范化组合关键字或 tuple-style 数组 schema 的成员。"""
    if not isinstance(value, list):
        _emit(diagnostic, path, "invalid_schema_list")
        return []
    return [
        _normalize_schema_node(item, f"{path}[{index}]", diagnostic)
        for index, item in enumerate(value)
    ]


def _normalize_additional_properties(
    value: Any,
    path: str,
    diagnostic: Callable[[str, str], None],
) -> Any:
    """规范化 additionalProperties，同时保留布尔值语义。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return _normalize_schema_node(value, path, diagnostic)
    if isinstance(value, str):
        return _normalize_bare_schema_string(
            value,
            path,
            diagnostic,
            for_additional_properties=True,
        )

    _emit(diagnostic, path, "invalid_additional_properties")
    # 无法解释的值采用 JSON Schema 的自由对象语义，避免把非法值传给
    # provider，也不收窄 add_node.properties 的动态属性容器。
    return True


def _normalize_dependencies(
    value: Any,
    path: str,
    diagnostic: Callable[[str, str], None],
) -> Any:
    """处理 draft-07 dependencies 的“数组或 schema”双重形态。"""
    if not isinstance(value, dict):
        return copy.deepcopy(value)

    result: dict[Any, Any] = {}
    for key, child in value.items():
        child_path = f"{path}.{key}"
        if isinstance(child, list):
            # 数组形态是属性名列表，不是 schema 列表。
            result[key] = copy.deepcopy(child)
        else:
            result[key] = _normalize_schema_node(child, child_path, diagnostic)
    return result


def _finalize_object_shape(
    node: dict[str, Any],
    path: str,
    diagnostic: Callable[[str, str], None],
) -> dict[str, Any]:
    """补齐 object 结构并清理当前节点范围内的 required。"""
    if node.get("type") != "object":
        return node

    properties = node.get("properties")
    if "properties" not in node or not isinstance(properties, dict):
        node["properties"] = {}
        _emit(diagnostic, path, "object_properties_filled")
        properties = node["properties"]

    required = node.get("required")
    if isinstance(required, list):
        valid = [
            item
            for item in required
            if isinstance(item, str) and item in properties
        ]
        if len(valid) != len(required):
            if valid:
                node["required"] = valid
            else:
                node.pop("required", None)
            _emit(diagnostic, path, "required_pruned")
    elif "required" in node:
        node.pop("required", None)
        _emit(diagnostic, path, "invalid_required_removed")

    return node


def _collapse_nullable_union(
    node: dict[str, Any],
    path: str,
    diagnostic: Callable[[str, str], None],
) -> dict[str, Any]:
    """保留现有兼容行为，折叠只有一个非 null 分支的 union。"""
    for keyword in ("anyOf", "oneOf"):
        variants = node.get(keyword)
        if not isinstance(variants, list):
            continue

        non_null = [
            variant
            for variant in variants
            if not (
                isinstance(variant, dict)
                and variant.get("type") == "null"
            )
        ]
        if len(non_null) != 1 or len(non_null) == len(variants):
            continue

        replacement = (
            copy.deepcopy(non_null[0])
            if isinstance(non_null[0], dict)
            else _empty_object_schema()
        )
        # 外层 schema 元数据保留；子分支已有同名字段时优先保留子分支。
        for key, value in node.items():
            if key != keyword and key not in replacement:
                replacement[key] = copy.deepcopy(value)
        replacement["nullable"] = True
        _emit(diagnostic, path, "nullable_union_collapsed")
        return _finalize_object_shape(replacement, path, diagnostic)

    return node


def _normalize_schema_node(
    node: Any,
    path: str,
    diagnostic: Callable[[str, str], None],
) -> Any:
    """在已知 schema 位置规范化一个节点。"""
    if isinstance(node, bool):
        # Boolean schema 是 JSON Schema 的合法形态，嵌套时保持原值。
        return node

    if isinstance(node, str):
        return _normalize_bare_schema_string(node, path, diagnostic)

    if not isinstance(node, dict):
        _emit(diagnostic, path, "invalid_schema_node")
        return _empty_object_schema()

    result: dict[Any, Any] = {}
    for key, value in node.items():
        key_path = f"{path}.{key}"

        if key == "$ref":
            result[key] = (
                _rewrite_local_ref(value)
                if isinstance(value, str)
                else copy.deepcopy(value)
            )
            continue

        if key in {"properties", "patternProperties"}:
            # 这是映射表边界：只递归每个属性定义，绝不把映射表当作
            # schema 节点，因此业务属性名 properties/type/required 不会
            # 触发 object-shape 推断。
            result[key] = _normalize_schema_map(value, key_path, diagnostic)
            continue

        if key in {"$defs", "definitions"}:
            normalized_defs = _normalize_schema_map(value, key_path, diagnostic)
            output_key = "$defs" if key == "definitions" else key
            if key == "definitions":
                _emit(diagnostic, key_path, "definitions_renamed")
            if isinstance(result.get(output_key), dict):
                result[output_key].update(normalized_defs)
            else:
                result[output_key] = normalized_defs
            continue

        if key in {"dependentSchemas"}:
            result[key] = _normalize_schema_map(value, key_path, diagnostic)
            continue

        if key == "dependencies":
            result[key] = _normalize_dependencies(value, key_path, diagnostic)
            continue

        if key == "dependentRequired":
            # 值是“属性名到属性名列表”的字面量映射。
            result[key] = copy.deepcopy(value)
            continue

        if key == "additionalProperties":
            result[key] = _normalize_additional_properties(
                value, key_path, diagnostic
            )
            continue

        if key in _SCHEMA_VALUE_KEYS:
            if isinstance(value, list) and key in {"items"}:
                result[key] = _normalize_schema_list(value, key_path, diagnostic)
            else:
                result[key] = _normalize_schema_node(
                    value, key_path, diagnostic
                )
            continue

        if key in _SCHEMA_LIST_KEYS:
            result[key] = _normalize_schema_list(value, key_path, diagnostic)
            continue

        if key in _LITERAL_KEYS:
            result[key] = copy.deepcopy(value)
            continue

        # 未知关键字不作 schema 猜测，按字面量复制，避免破坏 MCP server
        # 的扩展元数据或 default/const 类似的自定义载荷。
        result[key] = copy.deepcopy(value)

    # 在 schema 节点内部，只有显式 object 或具有 object 形状的节点才
    # 触发 object 修复；不会检查任意字典是否碰巧含有 properties 键。
    if not result.get("type") and (
        "properties" in result or "required" in result
    ):
        result["type"] = "object"
        _emit(diagnostic, path, "object_type_inferred")

    result = _finalize_object_shape(result, path, diagnostic)
    result = _collapse_nullable_union(result, path, diagnostic)
    return _finalize_object_shape(result, path, diagnostic)


def normalize_mcp_input_schema(
    schema: Any,
    *,
    diagnostic: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    """规范化 MCP 输入 schema，返回顶层 object schema。

    Args:
        schema: MCP ``Tool.inputSchema`` 的 JSON-like 值。
        diagnostic: 可选的 ``(path, code)`` 回调。回调内容只描述结构
            位置和修复类别，不包含完整 schema 或原始参数值。

    Returns:
        不与输入共享可变对象、且顶层为 ``type: object`` 的 schema 字典。
    """
    if diagnostic is None:
        diagnostic = lambda path, code: logger.debug(
            "MCP schema normalized at %s (%s)", path, code
        )

    if not isinstance(schema, dict):
        _emit(diagnostic, "$", "root_schema_fallback")
        return _empty_object_schema()

    normalized = _normalize_schema_node(schema, "$", diagnostic)
    if not isinstance(normalized, dict):
        _emit(diagnostic, "$", "root_schema_fallback")
        return _empty_object_schema()

    # MCP 工具输入参数必须是 object。即使 server 错误地声明了其他根
    # 类型，也在 provider 边界处降级为 object，避免整次工具请求失败。
    if normalized.get("type") != "object":
        normalized["type"] = "object"
        _emit(diagnostic, "$", "root_type_forced")
    return _finalize_object_shape(normalized, "$", diagnostic)


__all__ = ["normalize_mcp_input_schema"]