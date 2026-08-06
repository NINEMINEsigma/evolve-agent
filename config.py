from typing import * # type: ignore
from collections.abc import Callable
import argparse
import json
import os
import logging
from pathlib import Path
from third.easysave import save, load, contains
from pydantic import BaseModel

logger = logging.getLogger(__name__)

argparse_parser = argparse.ArgumentParser()

group = argparse_parser.add_mutually_exclusive_group()
group.add_argument("--load", type=str, default="")
group.add_argument("--save", type=str, default="")
group.add_argument("--interactive", action="store_true", default=False)
argparse_parser.add_argument("--console_log", type=bool, default=argparse.SUPPRESS)
argparse_parser.add_argument("--fast_agent_space_path", type=str, default=argparse.SUPPRESS)
argparse_parser.add_argument("--slow_agent_space_path", type=str, default=argparse.SUPPRESS)
argparse_parser.add_argument("--force_init", action="store_true", default=argparse.SUPPRESS)
argparse_parser.add_argument("--frontend_force_build", action="store_true", default=argparse.SUPPRESS)
argparse_parser.add_argument("--gateway_host", type=str, default=argparse.SUPPRESS)
argparse_parser.add_argument("--gateway_port", type=int, default=argparse.SUPPRESS)

#----------
# llm
#----------
default_llm_base_url = "https://api.deepseek.com"
default_llm_model = "deepseek-v4-flash"
default_llm_api_key = os.getenv("OPENAI_API_KEY", "")
default_llm_max_context_tokens = 1000000
default_llm_max_output_tokens = 384000
default_llm_temperature = 0.95
default_llm_reasoning_effort = "medium"

argparse_parser.add_argument("--llm_base_url", type=str, default=argparse.SUPPRESS)
argparse_parser.add_argument("--llm_model", type=str, default=argparse.SUPPRESS)
argparse_parser.add_argument("--llm_api_key", type=str, default=argparse.SUPPRESS)
argparse_parser.add_argument("--llm_max_context_tokens", type=int, default=argparse.SUPPRESS)
argparse_parser.add_argument("--llm_max_output_tokens", type=int, default=argparse.SUPPRESS)
argparse_parser.add_argument("--llm_temperature", type=float, default=argparse.SUPPRESS)
# 可选值：e.g. "low" / "medium" / "high"，空字符串表示不启用
argparse_parser.add_argument("--llm_reasoning_effort", type=str, default=argparse.SUPPRESS)
# 选择 LLM 客户端实现模块（custom_llm_client 目录下对应名称的 .py 文件）
argparse_parser.add_argument("--llm_client_name", type=str, default=argparse.SUPPRESS)
# 会话合并时直接拼接摘要的字符阈值，超过则截断
argparse_parser.add_argument("--merge_concat_threshold", type=int, default=argparse.SUPPRESS)

# 冒险模式审批小模型 — 仅需文件名，agent 会自动从 custom_models/ 目录下加载
check_default_approval_model_path = ""
custom_models_dir = Path("custom_models")
if custom_models_dir.is_dir():
    for file_path in custom_models_dir.iterdir():
        if "mmproj" in file_path.name:
            continue
        if file_path.suffix == ".gguf":
            check_default_approval_model_path = file_path.name
            break
argparse_parser.add_argument("--approval_model", type=str, default=argparse.SUPPRESS)
argparse_parser.add_argument("--approval_model_n_ctx", type=int, default=argparse.SUPPRESS)
argparse_parser.add_argument("--approval_model_cuda", action="store_true", default=argparse.SUPPRESS)
argparse_parser.add_argument("--approval_model_port", type=int, default=argparse.SUPPRESS)
# 远程审批模型 — 本地模型不可用时 fallback 到 OpenAI 兼容端点
argparse_parser.add_argument("--approval_remote_base_url", type=str, default=argparse.SUPPRESS)
argparse_parser.add_argument("--approval_remote_api_key", type=str, default=argparse.SUPPRESS)
argparse_parser.add_argument("--approval_remote_model", type=str, default=argparse.SUPPRESS)
# 远程审批模型的 LLM 客户端插件名（custom_llm_client 目录下对应 .py 文件名）
argparse_parser.add_argument("--approval_remote_client_name", type=str, default=argparse.SUPPRESS)

#----------
# workspace
#----------
argparse_parser.add_argument("--workspace_path", type=str, default=argparse.SUPPRESS)
argparse_parser.add_argument("--logs_path_name", type=str, default=argparse.SUPPRESS)
argparse_parser.add_argument("--agentspace_path_name", type=str, default=argparse.SUPPRESS)
argparse_parser.add_argument("--mcp_config_path_name", type=str, default=argparse.SUPPRESS)

args = argparse_parser.parse_args()

class Config(BaseModel):
    console_log: bool = True
    fast_agent_space_path: str = "fast_agent_space"
    slow_agent_space_path: str = "slow_agent_space"
    force_init: bool = False
    # 兼容字段：历史拼写错误 fouce_init 的迁移载体，仅用于接收旧 config.json 中的旧键
    # （easysave 反序列化直接 setattr，未声明字段会触发 pydantic 错误）。
    # 迁移由 _migrate_legacy_force_init 完成；移除时机由用户决定。
    fouce_init: bool | None = None
    gateway_host: str = "127.0.0.1"
    gateway_port: int = 8765
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-v4-flash"
    llm_api_key: str = os.getenv("OPENAI_API_KEY") or ""
    llm_max_context_tokens: int = 1000000
    llm_max_output_tokens: int = 384000
    llm_temperature: float = 0.95
    llm_reasoning_effort: str = "medium"
    llm_client_name: str = "openai_client"
    merge_concat_threshold: int = 50000
    approval_model: str = check_default_approval_model_path
    approval_model_n_ctx: int = 65536
    approval_model_cuda: bool = True
    approval_model_port: int = 8081
    approval_remote_base_url: str = ""
    approval_remote_api_key: str = ""
    approval_remote_model: str = ""
    approval_remote_client_name: str = "openai_client"
    workspace_path: str = "workspace"
    agentspace_path_name: str = "agentspace"
    logs_path_name: str = "logs"
    mcp_config_path_name: str = "mcp_config.json"
    frontend_force_build: bool = False


# ── 旧拼写 fouce_init → force_init 兼容迁移 ──────────────────
# fouce_init 为历史拼写错误，已在代码中全面改为 force_init。config.json
# （easysave 格式）可能仍残留 fouce_init 键：加载时检测到旧键且未显式设置
# force_init 则隐式迁移，并一次性回写清理（避免错误被保留）。
# 兼容代码：移除时机由用户决定（确认存量 config.json 已无 fouce_init 键后）。
_LEGACY_CONFIG_FIELD: str = "fouce_init"


def _migrate_legacy_force_init(cfg: Config, profile_key: str | None) -> bool:
    """旧拼写 fouce_init → force_init 兼容迁移（以 config.json 原始键为判定依据）。

    旧键存在且 force_init 键不存在 → 迁移并回写，返回 True；
    旧键存在且 force_init 键已存在（新值优先）→ 仅清理旧键，返回 False；
    无旧键 / 文件缺失或结构不符 → 返回 False。回写失败仅告警不阻断。
    """
    if not profile_key:
        return False
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    root = data.get(profile_key, {}).get("__root", {})
    value = root.get("__value")
    if not isinstance(value, dict) or _LEGACY_CONFIG_FIELD not in value:
        return False
    migrated = False
    if "force_init" not in value:
        legacy_val = value[_LEGACY_CONFIG_FIELD]
        if legacy_val is not None:
            cfg.force_init = bool(legacy_val)
            value["force_init"] = cfg.force_init
            logger.warning(
                "config profile '%s': legacy field 'fouce_init' migrated to 'force_init'",
                profile_key,
            )
            migrated = True
        else:
            logger.info(
                "config profile '%s': removed empty legacy field 'fouce_init'", profile_key
            )
    else:
        logger.info(
            "config profile '%s': legacy field 'fouce_init' ignored, 'force_init' takes precedence",
            profile_key,
        )
    value.pop(_LEGACY_CONFIG_FIELD, None)
    try:
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except OSError as exc:
        logger.warning("failed to persist force_init migration: %s", exc)
    return migrated


base_config: Config|None = None
# 运行时类型转换器：将用户输入字符串转为对应类型
_type_converters: dict[type, Callable[[str], Any]] = {
    bool: lambda v: v.strip().lower() in ("true", "1", "yes", "on", "y"),
    int: int,
    float: float,
    str: str,
}
# 仅保留用户显式传递的参数（排除 load / save）
cli_overrides = {k: v for k, v in vars(args).items() if k not in ("load", "save", "interactive")}
current_config = Config.model_validate(cli_overrides)


if args.load:
    base_config = load(args.load or "default", "config.json")
    current_config = base_config.model_copy()
    _migrate_legacy_force_init(current_config, args.load)
    for k, v in cli_overrides.items():
        setattr(current_config, k, v)
elif args.save:
    save(args.save, "config.json", current_config)
elif args.interactive:
    from config_tui import run_interactive
    current_config = run_interactive(current_config, cli_overrides)
else:
    config_field_key = input("config key：") or "default"
    if contains(config_field_key, "config.json"):
        base_config = load(config_field_key, "config.json")
        current_config = base_config.model_copy()
        _migrate_legacy_force_init(current_config, config_field_key)
        for k, v in cli_overrides.items():
            setattr(current_config, k, v)
    else:
        #current_config = Config.model_validate(cli_overrides)
        save(config_field_key, "config.json", current_config)

print(current_config)


# log
console_log:            bool    = current_config.console_log
# path
fast_agent_space_path:  str     = current_config.fast_agent_space_path
slow_agent_space_path:  str     = current_config.slow_agent_space_path
# runtime
force_init:             bool    = current_config.force_init
frontend_force_build:   bool    = current_config.frontend_force_build
# gateway
gateway_host:           str     = current_config.gateway_host
gateway_port:           int     = current_config.gateway_port
# llm
llm_base_url:           str     = current_config.llm_base_url
llm_model:              str     = current_config.llm_model
llm_api_key:            str     = current_config.llm_api_key
llm_max_context_tokens: int     = current_config.llm_max_context_tokens
llm_max_output_tokens:  int     = current_config.llm_max_output_tokens
llm_temperature:        float   = current_config.llm_temperature
llm_reasoning_effort:   str     = current_config.llm_reasoning_effort 
llm_client_name:        str     = current_config.llm_client_name
# merge
merge_concat_threshold: int     = current_config.merge_concat_threshold
# approval model
approval_model:         str  = current_config.approval_model
approval_model_n_ctx:        int  = current_config.approval_model_n_ctx
approval_model_cuda:         bool = current_config.approval_model_cuda
approval_model_port:         int  = current_config.approval_model_port
approval_remote_base_url:    str  = current_config.approval_remote_base_url
approval_remote_api_key:     str  = current_config.approval_remote_api_key
approval_remote_model:       str  = current_config.approval_remote_model
approval_remote_client_name: str  = current_config.approval_remote_client_name

# ----------
# 审批模型本地/远程二选一，配置阶段完成判定与存在性检查
# ----------
_local_disabled_values = {"", "false", "0", "no"}
_local_path_raw = (approval_model or "").strip()
_use_local_approval = _local_path_raw.lower() not in _local_disabled_values

approval_model_path: str = ""
if _use_local_approval:
    _gguf_path = Path("custom_models") / _local_path_raw
    if not _gguf_path.is_file():
        logger.warning(
            "Configured approval_model_path not found: %s — falling back to remote approval backend",
            _gguf_path,
        )
        _use_local_approval = False
    else:
        # 标准化为纯文件名
        approval_model_path = _local_path_raw

# 远程模式下检查是否配置了远程后端
if not _use_local_approval:
    if not (approval_remote_base_url and approval_remote_model):
        logger.warning(
            "Local approval model disabled and no remote approval backend configured — "
            "handsfree mode will be unavailable."
        )


#----------
# workspace
#----------
workspace_path:         Path = Path(current_config.workspace_path)
agentspace_path_name:   Path = workspace_path / current_config.agentspace_path_name
logs_path_name:         Path = workspace_path / current_config.logs_path_name
mcp_config_path:        Path = workspace_path / current_config.mcp_config_path_name