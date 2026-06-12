import argparse
import os
from third.filesystem import File
from third.easysave import save, load
from pydantic import BaseModel
argparse_parser = argparse.ArgumentParser()

argparse_parser.add_argument("--load", type=str, default="")
argparse_parser.add_argument("--save", type=str, default="")
argparse_parser.add_argument("--console_log", type=bool, default=True)
argparse_parser.add_argument("--fast_agent_space_path", type=str, default="fast_agent_space")
argparse_parser.add_argument("--slow_agent_space_path", type=str, default="slow_agent_space")
argparse_parser.add_argument("--fouce_init", action="store_true")
argparse_parser.add_argument("--gateway_host", type=str, default="127.0.0.1")
argparse_parser.add_argument("--gateway_port", type=int, default=8765)

#----------
# llm
#----------
default_llm_base_url = "https://api.deepseek.com"
default_llm_model = "deepseek-v4-flash"
default_llm_api_key = os.getenv("OPENAI_API_KEY")
default_llm_max_context_tokens = 1000000
default_llm_max_output_tokens = 384000
default_llm_temperature = 0.95
default_llm_reasoning_effort = "medium"

argparse_parser.add_argument("--llm_base_url", type=str, default=default_llm_base_url)
argparse_parser.add_argument("--llm_model", type=str, default=default_llm_model)
argparse_parser.add_argument("--llm_api_key", type=str, default=default_llm_api_key)
argparse_parser.add_argument("--llm_max_context_tokens", type=int, default=default_llm_max_context_tokens)
argparse_parser.add_argument("--llm_max_output_tokens", type=int, default=default_llm_max_output_tokens)
argparse_parser.add_argument("--llm_temperature", type=float, default=default_llm_temperature)
# 可选值：e.g. "low" / "medium" / "high"，空字符串表示不启用
argparse_parser.add_argument("--llm_reasoning_effort", type=str, default=default_llm_reasoning_effort)
# 会话合并时直接拼接摘要的字符阈值，超过则截断
argparse_parser.add_argument("--merge_concat_threshold", type=int, default=50000)

# 冒险模式审批小模型 — 仅需文件名，agent 会自动从 custom_models/ 目录下加载
check_default_approval_model_path = ""
for file in File("custom_models/").childs():
    if "mmproj" in file.name:
        continue
    if file.suffix == "gguf" or file.suffix == ".gguf":
        check_default_approval_model_path = str(file.name)
        break
argparse_parser.add_argument("--approval_model_path", type=str, default=check_default_approval_model_path)
argparse_parser.add_argument("--approval_model_n_ctx", type=int, default=65536)
argparse_parser.add_argument("--approval_model_cuda", action="store_true")
argparse_parser.add_argument("--approval_model_port", type=int, default=8081)

#----------
# workspace
#----------
argparse_parser.add_argument("--workspace_path", type=str, default="workspace")
argparse_parser.add_argument("--logs_path_name", type=str, default="logs")
argparse_parser.add_argument("--agentspace_path_name", type=str, default="agentspace")
argparse_parser.add_argument("--mcp_config_path_name", type=str, default="mcp_config.json")

args = argparse_parser.parse_args()

class Config(BaseModel):
    # 这个load只是占位符
    load: str = "default"
    console_log: bool = True
    fast_agent_space_path: str = "fast_agent_space"
    slow_agent_space_path: str = "slow_agent_space"
    fouce_init: bool = False
    gateway_host: str = "127.0.0.1"
    gateway_port: int = 8765
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-v4-flash"
    llm_api_key: str = os.getenv("OPENAI_API_KEY") or ""
    llm_max_context_tokens: int = 1000000
    llm_max_output_tokens: int = 384000
    llm_temperature: float = 0.95
    llm_reasoning_effort: str = "medium"
    merge_concat_threshold: int = 50000
    approval_model_path: str = "Qwen3.5-0.8B-Q8_0.gguf"
    approval_model_n_ctx: int = 65536
    approval_model_cuda: bool = True
    approval_model_port: int = 8081
    workspace_path: str = "workspace"
    agentspace_path_name: str = "agentspace"
    logs_path_name: str = "logs"
    mcp_config_path_name: str = "mcp_config.json"

current_config: Config = Config.model_validate(vars(args))

if args.load:
    current_config = load(args.load or "default", "config.json")
else:
    save(args.save or "default", "config.json", current_config)


# log
console_log:            bool    = current_config.console_log
# path
fast_agent_space_path:  str     = current_config.fast_agent_space_path
slow_agent_space_path:  str     = current_config.slow_agent_space_path
# runtime
fouce_init:             bool    = current_config.fouce_init
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
# merge
merge_concat_threshold: int     = current_config.merge_concat_threshold
# approval model
approval_model_path:    str  = current_config.approval_model_path
approval_model_n_ctx:   int  = current_config.approval_model_n_ctx
approval_model_cuda:    bool = current_config.approval_model_cuda
approval_model_port:    int  = current_config.approval_model_port


#----------
# workspace
#----------
from pathlib import Path
workspace_path:         Path = Path(current_config.workspace_path)
agentspace_path:        Path = workspace_path / current_config.agentspace_path_name
logs_path:              Path = workspace_path / current_config.logs_path_name
mcp_config_path:        Path = workspace_path / current_config.mcp_config_path_name