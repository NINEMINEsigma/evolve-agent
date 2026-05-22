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
llm_base_url:           str     = "https://api.openai.com/v1"
llm_model:              str     = "gpt-4o"
# Note: llm_api_key should be set via the OPENAI_API_KEY env var, never in config.