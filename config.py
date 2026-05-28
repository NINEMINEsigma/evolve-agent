# log
console_log:            bool    = True
# path
fast_agent_space_path:  str     = "fast_agent_space"
slow_agent_space_path:  str     = "slow_agent_space"
# runtime
fouce_init:             bool    = False
# gateway
gateway_host:           str     = "127.0.0.1"
gateway_port:           int     = 8765
# llm
llm_base_url:           str     = "https://api.deepseek.com"
llm_model:              str     = "deepseek-v4-flash"
# Note: llm_api_key should be set via the OPENAI_API_KEY env var, never in config.
llm_max_context_tokens: int     = 1000000
llm_context_upbound:    float   = 0.9
llm_max_output_tokens:  int     = 384000
llm_temperature:        float   = 0.95


#----------
# workspace
#----------
from pathlib import Path
workspace_path:         Path = Path("workspace")
agentspace_path:        Path = workspace_path / "agentspace"
logs_path:              Path = workspace_path / "logs"
mcp_config_path:        Path = workspace_path / "mcp_config.json"