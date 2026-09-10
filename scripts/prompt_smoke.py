"""Estimate one first-turn prompt for the Evolve Agent.

This is a local, read-only smoke estimator. It loads an LLM Profile from
workspace/agentspace/llm_profiles.es, builds the main-agent system prompt,
discovers tools, and reports message/tool-schema sizes. It does not call an
LLM endpoint and never prints API keys.

Run from the repository root, for example:
    python scripts/prompt_smoke.py
    python scripts/prompt_smoke.py --profile mimo --message "你好"
    python scripts/prompt_smoke.py --json

The reported token count is an estimate unless a compatible tokenizer is
available. The provider's prompt_tokens from a real request remains the
source of truth.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "origin_agent"
AGENTSPACE_DIR = ROOT / "workspace" / "agentspace"

# Import the source-of-truth implementation, never the disposable workspace
# copy. The script itself does not modify either tree.
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "third") not in sys.path:
    sys.path.insert(0, str(ROOT / "third"))

from easysave import contains, load  # noqa: E402
from entity.messages import BaseMessage, CharacterSystemMessage  # noqa: E402
from entity.puretype import LLMProfile, Role, ToolAvailability  # noqa: E402
from entity.typeref import make_config  # noqa: E402
from abstract.llm.formats import messages_to_openai_list  # noqa: E402
from abstract.tools.discover import discover_builtin_tools  # noqa: E402
from abstract.tools.registry import registry  # noqa: E402
from abstract.tools.toolsets_meta import register_builtin_toolset_descriptions  # noqa: E402
from system.context import RuntimeContext, set_runtime_context  # noqa: E402
from system.prompt import build_system_prompt, build_session_site_block, build_session_stage_block  # noqa: E402
from entity.constant import LLM_PROFILES_ES_KEY, LLM_PROFILES_ES_FILENAME  # noqa: E402


DEFAULT_MESSAGE = "你好，请简要说明你当前可以做什么。"
DEFAULT_SESSION_ID = "__prompt_smoke__"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Estimate one Evolve Agent first-turn prompt")
    parser.add_argument("--profile", default="mimo", help="LLM Profile name; default: mimo")
    parser.add_argument("--message", default=DEFAULT_MESSAGE, help="Synthetic first user message")
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID)
    parser.add_argument("--json", action="store_true", dest="as_json", help="Print machine-readable JSON")
    parser.add_argument(
        "--no-tools",
        action="store_true",
        help="Skip tool discovery and tool definitions; useful for an ablation comparison",
    )
    parser.add_argument(
        "--no-session-blocks",
        action="store_true",
        help="Exclude Session Site and Session Stage prompt blocks",
    )
    return parser.parse_args()


def load_profile(name: str) -> LLMProfile:
    path = AGENTSPACE_DIR / LLM_PROFILES_ES_FILENAME
    if not contains(LLM_PROFILES_ES_KEY, make_config(path)):
        raise FileNotFoundError(f"Profile storage not found or missing v2 key: {path}")
    root = load(LLM_PROFILES_ES_KEY, make_config(path), ignore_missing_fields=True)
    for profile in root.profiles:
        if isinstance(profile, LLMProfile) and profile.name == name:
            return profile
    available = [p.name for p in getattr(root, "profiles", []) if isinstance(p, LLMProfile)]
    raise LookupError(f"Profile {name!r} not found. Available profiles: {', '.join(available)}")


def build_runtime_context() -> RuntimeContext:
    return RuntimeContext(
        workspace=ROOT / "workspace",
        agentspace=AGENTSPACE_DIR,
        fork_path=ROOT / "workspace" / "slow_agent_space",
        log_path=ROOT / "workspace" / "logs" / "prompt_smoke.log",
        mode="fast",
        console_log=False,
        gateway_host="127.0.0.1",
        gateway_port=8765,
        git_remotes="",
        mcp_config_path=str(AGENTSPACE_DIR / "mcp_config.json"),
    )


def discover_tools() -> None:
    """Register the same source directories used by the running Agent."""
    # filesystem is imported explicitly by the runtime before AST discovery.
    import importlib
    importlib.import_module("component.tools.filesystem")

    discover_builtin_tools(str(AGENT_DIR / "component" / "tools"), "component.tools")
    discover_builtin_tools(str(AGENT_DIR / "component" / "extools"), "component.extools")
    discover_builtin_tools(str(AGENT_DIR / "component" / "multiagenttools"), "component.multiagenttools")
    discover_builtin_tools(str(AGENT_DIR / "component" / "automation"), "component.automation")
    discover_builtin_tools(str(AGENT_DIR / "component" / "browser"), "component.browser")

    custom_tools = ROOT / "custom_tools"
    if custom_tools.exists():
        discover_builtin_tools(str(custom_tools), "custom_tools")
    register_builtin_toolset_descriptions()


def estimate_tokens(text: str) -> tuple[int, str]:
    """Return (estimate, method), preferring an installed tokenizer."""
    try:
        import tiktoken  # type: ignore

        # mimo is accessed through an OpenAI-compatible endpoint, but its
        # private tokenizer is not necessarily available locally. cl100k_base
        # is therefore explicitly labelled an approximation.
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text)), "tiktoken:cl100k_base (approximation)"
    except Exception:
        # A deliberately conservative fallback for mixed Chinese/English/
        # JSON/schema text. It is not presented as provider-accurate.
        return max(1, (len(text) + 2) // 3), "character heuristic: ceil(chars / 3)"


def safe_profile_fields(profile: LLMProfile) -> dict[str, Any]:
    """Return non-secret profile metadata for the report."""
    return {
        "name": profile.name,
        "client": profile.llm_client_name,
        "model": profile.model,
        "base_url": profile.base_url,
        "soul_file": profile.soul_file,
        "max_context_tokens": profile.max_context_tokens,
    }


def main() -> int:
    args = parse_args()
    profile = load_profile(args.profile)
    ctx = build_runtime_context()
    set_runtime_context(ctx)

    loaded_toolsets = set() if args.no_tools else {"core"}
    if not args.no_tools:
        discover_tools()

    system_blocks = build_system_prompt(
        mode="fast",
        extra_blocks=[],
        workspace=ctx.workspace,
        agentspace=str(ctx.agentspace),
        fork_path=str(ctx.fork_path),
        fix_fork_path="",
        fix_log_path="",
        tool_availability_scope=ToolAvailability.MAIN,
        runtime_ctx=ctx,
        profile=profile,
        session_id=args.session_id,
        loaded_toolsets=loaded_toolsets,
    )

    if not args.no_session_blocks:
        site = build_session_site_block(args.session_id, owner="self")
        stage = build_session_stage_block(args.session_id, owner="self")
        if site:
            system_blocks.append(site)
        if stage:
            system_blocks.append(stage)

    messages: list[BaseMessage] = [
        CharacterSystemMessage(
            role=Role.SYSTEM,
            character_name="main-agent",
            content=block,
        )
        for block in system_blocks
    ]
    messages.append(BaseMessage(role=Role.USER, content=args.message))

    tools: list[dict[str, Any]] = []
    if not args.no_tools:
        tools = registry.get_definitions_for_loaded_toolsets(
            ToolAvailability.MAIN,
            loaded_toolsets,
            quiet=True,
        )

    wire_messages = messages_to_openai_list(messages, current_character_agent="main-agent")
    payload_for_estimate = json.dumps(
        {"messages": wire_messages, "tools": tools},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    payload_tokens, token_method = estimate_tokens(payload_for_estimate)

    system_rows = [
        {
            "index": index,
            "chars": len(block),
            "estimated_tokens": estimate_tokens(block)[0],
        }
        for index, block in enumerate(system_blocks, start=1)
    ]
    system_chars = sum(row["chars"] for row in system_rows)
    tool_chars = len(json.dumps(tools, ensure_ascii=False, separators=(",", ":")))
    history_chars = len(args.message)

    result = {
        "profile": safe_profile_fields(profile),
        "mode": "fast",
        "loaded_toolsets": sorted(loaded_toolsets),
        "message": args.message,
        "system_block_count": len(system_blocks),
        "system_chars": system_chars,
        "system_estimated_tokens": estimate_tokens("\n".join(system_blocks))[0],
        "system_blocks": system_rows,
        "tool_count": len(tools),
        "tool_schema_chars": tool_chars,
        "user_message_chars": history_chars,
        "wire_message_count": len(wire_messages),
        "serialized_payload_chars": len(payload_for_estimate),
        "serialized_payload_estimated_tokens": payload_tokens,
        "token_estimate_method": token_method,
        "excluded_from_this_local_estimate": [
            "provider-side hidden protocol overhead",
            "real provider prompt_tokens and cached token details",
            "dynamic custom_hooks output (some hooks require a live Application/session)",
            "existing conversation history beyond the synthetic user message",
        ],
    }

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print("Evolve Agent 首轮 Prompt 冒烟估算（本地、只读、不发送请求）")
    print(f"Profile: {profile.name} | model: {profile.model} | client: {profile.llm_client_name}")
    print(f"工具集: {', '.join(sorted(loaded_toolsets)) or '(none)'}")
    print(f"System prompt blocks: {len(system_blocks)}")
    print(f"System prompt: {system_chars:,} chars, about {result['system_estimated_tokens']:,} tokens")
    print(f"Tool definitions: {len(tools)} tools, {tool_chars:,} chars")
    print(f"Synthetic user message: {history_chars:,} chars")
    print(f"Serialized OpenAI-style payload: {len(payload_for_estimate):,} chars, about {payload_tokens:,} tokens")
    print(f"Tokenizer: {token_method}")
    print("\nSystem blocks:")
    for row in system_rows:
        print(f"  {row['index']:>2}: {row['chars']:>7,} chars, about {row['estimated_tokens']:>6,} tokens")
    print("\n说明：这里的 token 数是本地估算；真实请求应以 provider 返回的 prompt_tokens 为准。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
