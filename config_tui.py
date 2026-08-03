"""
interactive 配置向导 — 基于 rich 的分组交互式配置编辑。

流程: 选择 profile → 加载+CLI覆盖 → 分组逐项编辑 → 确认保存 → 返回 Config
"""

import json
import os
from typing import Any, Callable, TypeVar

from pydantic import BaseModel
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm

from third.easysave import save, load, contains
from config import _migrate_legacy_force_init


# ── 字段分组 ──────────────────────────────────────────────
FIELD_GROUPS: dict[str, list[str]] = {
    "LLM 核心": [
        "llm_base_url", "llm_model", "llm_api_key",
        "llm_max_context_tokens", "llm_max_output_tokens",
        "llm_temperature", "llm_reasoning_effort", "llm_client_name",
    ],
    "审批模型": [
        "approval_model", "approval_model_n_ctx",
        "approval_model_cuda", "approval_model_port",
        "approval_remote_base_url", "approval_remote_api_key",
        "approval_remote_model",
    ],
    "Workspace": [
        "workspace_path", "agentspace_path_name",
        "logs_path_name", "mcp_config_path_name",
    ],
    "网关": [
        "gateway_host", "gateway_port",
    ],
    "运行时": [
        "console_log", "force_init",
        "frontend_force_build", "merge_concat_threshold",
    ],
}

# ── 类型转换器 ────────────────────────────────────────────
_type_converters: dict[type, Callable[[str], Any]] = {
    bool: lambda v: v.strip().lower() in ("true", "1", "yes", "on", "y"),
    int: int,
    float: float,
    str: str,
}

# ── 业务校验器 ────────────────────────────────────────────
# (raw_input: str, current_value: Any) -> (is_valid: bool, error_msg: str)

def _validate_port(raw: str, _: Any) -> tuple[bool, str]:
    try:
        v = int(raw)
    except ValueError:
        return False, f"需要整数, 得到 '{raw}'"
    if not (1 <= v <= 65535):
        return False, f"端口范围 1-65535, 得到 {v}"
    return True, ""

def _validate_temperature(raw: str, _: Any) -> tuple[bool, str]:
    try:
        v = float(raw)
    except ValueError:
        return False, f"需要浮点数, 得到 '{raw}'"
    if not (0.0 <= v <= 2.0):
        return False, f"温度范围 0.0-2.0, 得到 {v}"
    return True, ""

def _validate_positive_int(raw: str, _: Any) -> tuple[bool, str]:
    try:
        v = int(raw)
    except ValueError:
        return False, f"需要正整数, 得到 '{raw}'"
    if v <= 0:
        return False, f"需要正整数, 得到 {v}"
    return True, ""

def _validate_reasoning_effort(raw: str, _: Any) -> tuple[bool, str]:
    v = raw.strip().lower()
    if v not in ("low", "medium", "high", ""):
        return False, f"可选值: low / medium / high / 空, 得到 '{raw}'"
    return True, ""

def _validate_url(raw: str, _: Any) -> tuple[bool, str]:
    v = raw.strip()
    if v and not v.startswith(("http://", "https://")):
        return False, f"URL 需以 http:// 或 https:// 开头, 得到 '{raw}'"
    return True, ""

def _validate_bool(raw: str, _: Any) -> tuple[bool, str]:
    v = raw.strip().lower()
    if v not in ("true", "false", "1", "0", "yes", "no", "on", "off", "y", "n"):
        return False, f"布尔值: true/false/1/0/yes/no/on/off/y/n, 得到 '{raw}'"
    return True, ""

FIELD_VALIDATORS: dict[str, Callable[[str, Any], tuple[bool, str]]] = {
    "gateway_port":              _validate_port,
    "approval_model_port":       _validate_port,
    "llm_temperature":            _validate_temperature,
    "llm_max_context_tokens":     _validate_positive_int,
    "llm_max_output_tokens":      _validate_positive_int,
    "approval_model_n_ctx":       _validate_positive_int,
    "merge_concat_threshold":    _validate_positive_int,
    "llm_reasoning_effort":      _validate_reasoning_effort,
    "llm_base_url":               _validate_url,
    "approval_remote_base_url":  _validate_url,
    "console_log":                _validate_bool,
    "force_init":                 _validate_bool,
    "approval_model_cuda":       _validate_bool,
    "frontend_force_build":       _validate_bool,
}


# ── 内部函数 ──────────────────────────────────────────────

def _list_profiles(config_path: str = "config.json") -> list[str]:
    """读取 config.json 顶层 key 列表"""
    if not os.path.exists(config_path):
        return []
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return list(data.keys())
    except (json.JSONDecodeError, OSError):
        return []


def _select_profile(console: Console, config_path: str = "config.json") -> str:
    """渲染已有 profile 列表, 获取用户选择的 profile 名"""
    profiles = _list_profiles(config_path)

    if profiles:
        table = Table(title="已有配置", show_header=True, header_style="bold cyan")
        table.add_column("Profile", style="bold")
        for name in profiles:
            table.add_row(name)
        console.print(table)
    else:
        console.print("[yellow]暂无已存配置, 将创建新的[/yellow]")

    return Prompt.ask("输入 profile 名称", default="default")


def _edit_field(
    console: Console,
    model: BaseModel,
    field_name: str,
    field_type: type,
) -> None:
    """单字段编辑: 回车保持当前值, 输入新值则校验+转换"""
    current_value = getattr(model, field_name)
    current_str = str(current_value)
    validator = FIELD_VALIDATORS.get(field_name)

    while True:
        raw = Prompt.ask(f"  {field_name}", default=current_str)

        # 用户接受默认值 = 无变更
        if raw == current_str:
            return

        # 有业务校验器: 校验器内部处理类型转换 + 业务规则
        if validator:
            is_valid, error_msg = validator(raw, current_value)
            if not is_valid:
                console.print(f"  [red]✗ {error_msg}[/red]")
                continue
            converter = _type_converters.get(field_type, str)
            converted = converter(raw)
        else:
            # 无业务校验器: 仅做类型转换
            converter = _type_converters.get(field_type, str)
            try:
                converted = converter(raw)
            except (ValueError, TypeError):
                console.print(
                    f"  [red]✗ 无法将 '{raw}' 转换为 {field_type.__name__}[/red]"
                )
                continue

        setattr(model, field_name, converted)
        return


def _edit_group(
    console: Console,
    model: BaseModel,
    group_name: str,
    field_names: list[str],
) -> None:
    """渲染分组 Panel, 组内逐字段编辑"""
    console.print()
    console.print(Panel(group_name, style="bold blue"))

    for field_name in field_names:
        field_type = type(model).model_fields[field_name].annotation
        _edit_field(console, model, field_name, field_type)  # type: ignore[arg-type]


def _confirm_save(console: Console) -> bool:
    """保存确认"""
    return Confirm.ask("是否保存到 profile?")


# ── 主入口 ────────────────────────────────────────────────

ConfigT = TypeVar("ConfigT", bound=BaseModel)


def run_interactive(
    current_config: ConfigT,
    cli_overrides: dict,
    config_path: str = "config.json",
) -> ConfigT:
    """
    interactive 模式主入口:
    1. 选择/新建 profile
    2. 加载 profile 值 + 叠加 CLI 覆盖
    3. 分组逐项编辑
    4. 确认是否保存
    5. 返回最终 Config
    """
    console = Console()
    Config = type(current_config)

    # Step 1: 选择 profile
    console.print()
    console.print(Panel.fit("Evolve Agent 配置向导", style="bold magenta"))
    profile_key = _select_profile(console, config_path)

    # Step 2: 加载 + CLI 覆盖
    if contains(profile_key, config_path):
        working = load(profile_key, config_path)
        _migrate_legacy_force_init(working, profile_key)
        console.print(f"[green]已加载 profile '{profile_key}'[/green]")
    else:
        working = Config()
        console.print(f"[green]新建 profile '{profile_key}' (使用默认值)[/green]")

    for k, v in cli_overrides.items():
        setattr(working, k, v)

    # Step 3: 分组编辑
    for group_name, field_names in FIELD_GROUPS.items():
        _edit_group(console, working, group_name, field_names)

    # Step 4: 保存确认
    console.print()
    if _confirm_save(console):
        save(profile_key, config_path, working)
        console.print(f"[green]已保存到 profile '{profile_key}'[/green]")
    else:
        console.print("[yellow]未保存, 使用当前配置继续[/yellow]")

    return working