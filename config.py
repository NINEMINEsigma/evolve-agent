import argparse
from third.filesystem import File
argparse_parser = argparse.ArgumentParser()

argparse_parser.add_argument("--console_log", type=bool, default=True)
argparse_parser.add_argument("--fast_agent_space_path", type=str, default="fast_agent_space")
argparse_parser.add_argument("--slow_agent_space_path", type=str, default="slow_agent_space")
argparse_parser.add_argument("--fouce_init", action="store_true")
argparse_parser.add_argument("--gateway_host", type=str, default="127.0.0.1")
argparse_parser.add_argument("--gateway_port", type=int, default=8765)
argparse_parser.add_argument("--llm_base_url", type=str, default="https://api.deepseek.com")
argparse_parser.add_argument("--llm_model", type=str, default="deepseek-v4-flash")
argparse_parser.add_argument("--llm_max_context_tokens", type=int, default=1000000)
argparse_parser.add_argument("--llm_max_output_tokens", type=int, default=384000)
argparse_parser.add_argument("--llm_temperature", type=float, default=0.95)
# 可选值：e.g. "low" / "medium" / "high"，空字符串表示不启用
argparse_parser.add_argument("--llm_reasoning_effort", type=str, default="medium")

# 冒险模式审批小模型 — 仅需文件名，agent 会自动从 custom_models/ 目录下加载
check_default_approval_model_path = ""
for file in File("custom_models/").childs():
    if file.suffix == "gguf" or file.suffix == ".gguf":
        check_default_approval_model_path = str(file)
        break
argparse_parser.add_argument("--approval_model_path", type=str, default=check_default_approval_model_path)
argparse_parser.add_argument("--approval_model_n_ctx", type=int, default=65536)
argparse_parser.add_argument("--approval_model_cuda", action="store_true")

#----------
# workspace
#----------
argparse_parser.add_argument("--workspace_path", type=str, default="workspace")
argparse_parser.add_argument("--logs_path_name", type=str, default="logs")
argparse_parser.add_argument("--agentspace_path_name", type=str, default="agentspace")
argparse_parser.add_argument("--mcp_config_path_name", type=str, default="mcp_config.json")

args = argparse_parser.parse_args()


# log
console_log:            bool    = args.console_log
# path
fast_agent_space_path:  str     = args.fast_agent_space_path
slow_agent_space_path:  str     = args.slow_agent_space_path
# runtime
fouce_init:             bool    = args.fouce_init
# gateway
gateway_host:           str     = args.gateway_host
gateway_port:           int     = args.gateway_port
# llm
llm_base_url:           str     = args.llm_base_url
llm_model:              str     = args.llm_model
# Note: llm_api_key should be set via the OPENAI_API_KEY env var, never in config.
llm_max_context_tokens: int     = args.llm_max_context_tokens
llm_max_output_tokens:  int     = args.llm_max_output_tokens
llm_temperature:        float   = args.llm_temperature
llm_reasoning_effort:   str     = args.llm_reasoning_effort 
# approval model
approval_model_path:    str  = args.approval_model_path
approval_model_n_ctx:   int  = args.approval_model_n_ctx
approval_model_cuda:    bool = args.approval_model_cuda


#----------
# workspace
#----------
from pathlib import Path
workspace_path:         Path = Path(args.workspace_path)
agentspace_path:        Path = workspace_path / args.agentspace_path_name
logs_path:              Path = workspace_path / args.logs_path_name
mcp_config_path:        Path = workspace_path / args.mcp_config_path_name