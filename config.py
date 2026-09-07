from typing import * # type: ignore
from collections.abc import Callable
import argparse
from third.easysave import save, load, contains
from pydantic import BaseModel

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

# 会话合并时直接拼接摘要的字符阈值，超过则截断
argparse_parser.add_argument("--merge_concat_threshold", type=int, default=argparse.SUPPRESS)

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
    gateway_host: str = "127.0.0.1"
    gateway_port: int = 8765
    merge_concat_threshold: int = 50000
    workspace_path: str = "workspace"
    agentspace_path_name: str = "agentspace"
    logs_path_name: str = "logs"
    mcp_config_path_name: str = "mcp_config.json"
    frontend_force_build: bool = False


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
    base_config = load(args.load or "default", "config.json", ignore_missing_fields=True)
    current_config = base_config.model_copy()
    for k, v in cli_overrides.items():
        setattr(current_config, k, v)
elif args.save:
    save(args.save, "config.json", current_config)
elif args.interactive:
    from config_tui import run_interactive
    current_config = run_interactive(current_config, cli_overrides)
#else:
elif False:
    config_field_key = input("config key：") or "default"
    if contains(config_field_key, "config.json"):
        base_config = load(config_field_key, "config.json", ignore_missing_fields=True)
        current_config = base_config.model_copy()
        for k, v in cli_overrides.items():
            setattr(current_config, k, v)
    else:
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
# merge
merge_concat_threshold: int     = current_config.merge_concat_threshold

#----------
# workspace
#----------
from pathlib import Path
workspace_path:         Path = Path(current_config.workspace_path)
agentspace_path_name:   Path = workspace_path / current_config.agentspace_path_name
logs_path_name:         Path = workspace_path / current_config.logs_path_name
mcp_config_path:        Path = agentspace_path_name / current_config.mcp_config_path_name