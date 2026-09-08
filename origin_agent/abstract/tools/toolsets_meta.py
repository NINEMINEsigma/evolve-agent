"""内置工具集元数据注册。

在工具发现后由 main.py 调用，为每个内置工具集注册简短描述和详细使用说明。
未加载时系统提示词只显示 description（简述），加载后显示 usage_guide（详细说明）。
"""

from abstract.tools.registry import registry


def register_builtin_toolset_descriptions() -> None:
    """注册所有内置工具集的简短描述和详细使用说明。"""
    registry.register_toolset(
        name="core",
        description="Essential tools: ask questions, search sessions, compress history, show tool metadata, manage skills, load toolsets.",
        loaded_by_default=True,
    )
    registry.register_toolset(
        name="filesystem",
        description="Read, write, edit, delete, copy, move, and search files in logical namespaces.",
        usage_guide="""Filesystem tools operate on logical namespace prefixes (ws:, fork:, fix:, skills:, etc.).

Multimodal Read conventions:
- The Read tool can read image, audio, and video files. Multimodal capability is automatically probed on first access — no manual probe call needed.
- The system probes BOTH tool-message and user-message multimodal paths. Results are cached per model+provider, so probing happens only once per unique model+provider combination.
- If the model supports image (or audio or video) in tool messages, Read delivers the content directly in the tool result as a multimodal content block.
- If the model supports image (or audio or video) only in user messages, Read still reads the file — the content is delivered via a follow-up user message after the current tool round completes. The tool result text will explicitly advise you to stop calling tools and respond directly to receive the media content.
- If both tool and user message paths are unsupported but a reference profile is configured, the content is forwarded to the referenced profile's model for a text description, returned in the `description` field.
- If both paths are unsupported and no reference is configured, Read returns an error and does not read the file.
- In the user-message fallback path, do NOT call any more tools after receiving the result containing `_user_blocks` — respond directly so the follow-up user message with the media content is delivered to you in the next turn.""",
    )
    registry.register_toolset(
        name="shell",
        description="Execute shell commands in the sandbox with a 30-second timeout.",
        usage_guide="""Shell tools execute commands in the sandbox with a 30-second timeout.

Long-running task conventions:
- RunCommand has a fixed 30-second timeout.
- Decision tree for tasks that may exceed the timeout:
  1. Definitely under 30s → RunCommand.
  2. Might exceed 30s but has a bounded duration → RunPython with an increased `timeout` parameter.
  3. Unbounded or likely to exceed any timeout → StartBackgroundService (non-blocking, returns task_id + log_path), then poll the log via Read at reasonable intervals.
  4. Need real-time output monitoring with automatic callbacks → StartWatchingService + RegisterDynamicEndpoint.
- NEVER manually simulate a command's effects when it times out. A timeout is a signal to switch to background tools, not a reason to bypass the command entirely.
- After starting a background task, use WaitCron or ScheduleCron to periodically Read the log and check for completion, rather than blocking the conversation.""",
    )
    registry.register_toolset(
        name="python",
        description="Execute Python code using the agent's own interpreter.",
        usage_guide="""Python tools use the same Python interpreter as the agent process.

- RunPython has a configurable `timeout` parameter for tasks that may exceed 30 seconds.
- Never use RunPython to write files; always use Write or PatchEdit instead.
- In RunPython, `sys.executable` is the current Python path. Do NOT use bare "ws:" paths directly in matplotlib/Pillow/etc. — query the agentspace path via RunPython, use an absolute path, then write the file.""",
    )
    registry.register_toolset(
        name="code",
        description="Validate and evolve the agent's own source code.",
    )
    registry.register_toolset(
        name="frontend",
        description="Validate frontend builds by running package manager install and build.",
    )
    registry.register_toolset(
        name="lsp",
        description="Language server protocol diagnostics, references, definitions, and symbols.",
    )
    registry.register_toolset(
        name="progress",
        description="Create, update, and clear frontend progress bars for multi-step tasks.",
        usage_guide="""Progress bar conventions:
- When a task can be decomposed into 3 or more discrete steps, proactively call SetTaskProgress to create a progress bar before starting work.
- Use a stable task_id for the entire task lifecycle; reuse it on every update to overwrite the same bar rather than creating duplicates.
- Update the progress bar in real time after each step completes (increment current by 1), and set status to reflect the current phase.
- Set total to the number of planned steps and current to the number of completed steps.
- After all steps finish, set current equal to total and keep the progress bar visible — do NOT call ClearTaskProgress yet.
- The progress bar must remain visible until the user has reviewed and accepted the work. Only call ClearTaskProgress after user confirmation or explicit request to clean up.
- If the task is cancelled or aborted, call ClearTaskProgress to remove the stale bar.""",
    )
    registry.register_toolset(
        name="clipboard",
        description="Create and manage one-click copy areas in the frontend top panel.",
    )
    registry.register_toolset(
        name="multiagent",
        description="Register, run, chat with, stop, and manage sub-agents; enter and exit multi-agent mode.",
        usage_guide="""Sub-agent conventions:
- After launching a sub-agent with RunSubAgent, you MUST wait for the [subagent-result] message before interacting with it again.
- Do NOT call ChatSubAgent to check whether the sub-agent is alive, to ask "are you there", or to urge it to respond faster. The system will reject such calls while the sub-agent is still generating its current response.
- Use ChatSubAgent only to reply to the sub-agent's questions, add missing context, or correct its direction AFTER you have received its latest response.
- Do NOT call ChatSubAgent just to send the initial prompt; put all initial context into the initial_prompt parameter of RunSubAgent.
- Within the same parent session, only one instance of a given sub-agent name can be active or queued at a time. If you need to restart a sub-agent, stop it first with StopSubAgent.

Task-agent conventions:
- Use RunTaskAgent to launch a one-shot task agent with a single prompt. The task agent runs asynchronously with safe tools only.
- The result will be delivered as a [subagent-result] message when the task completes. Do not poll or chat with task agents.
- Use StopTaskAgent with the session_id if a task agent must be terminated early.
- Task agents are fire-and-forget: no history is saved, no persistent session.

Task agent dispatch conventions:
- When a task is stateless, does not require extensive context or memory, only needs read access, and returns a text result, prefer dispatching it to a task agent via RunTaskAgent rather than executing it in the main agent loop.
- Delegating such tasks frees the main agent's context window and avoids polluting conversation history with intermediate tool outputs.
- Put all necessary context into the prompt parameter — the task agent receives only that single message and has no access to the main agent's conversation history.
- Do not delegate tasks that require write access, multi-round interaction, or persistent memory — handle those in the main agent loop directly.""",
    )
    registry.register_toolset(
        name="extools",
        description="Web search and fetch, archive tools, diff tools.",
    )
    registry.register_toolset(
        name="cron",
        description="Schedule, list, cancel, trigger, and copy one-shot background cron tasks; wait reminders.",
        usage_guide="""Cron tool conventions:
- Scheduled tasks are background one-shot tasks, not a batch queue or an automatic loop mechanism.
- Periodic work, polling, or long-running observation must be expressed as recursive scheduling: wait for the task result, then schedule the next one-shot task.
- Raw scheduled-task output is internal Agent input and log content, not a user message; if the user needs the result, actively summarize it.""",
    )
    registry.register_toolset(
        name="background",
        description="Start, stop, and watch long-running background service processes.",
        usage_guide="""Background service conventions:
- StartBackgroundService starts a long-running service process in the background and returns immediately without waiting for completion.
- After starting a background task, use WaitCron or ScheduleCron to periodically Read the log and check for completion, rather than blocking the conversation.
- StartWatchingService starts a background process and watches its stdout/stderr, posting incremental output to a dynamic endpoint at adaptive intervals.""",
    )
    registry.register_toolset(
        name="dynamic",
        description="Register, unregister, and list dynamic HTTP POST endpoints for real-time callbacks.",
    )
    registry.register_toolset(
        name="archive",
        description="Compress and decompress files and directories into archives (zip, tar, 7z).",
    )
    registry.register_toolset(
        name="automation",
        description="Desktop automation: window management, mouse, keyboard, screen capture, template matching.",
    )
    registry.register_toolset(
        name="browser",
        description="Browser control via CDP: navigate, click, type, scroll, screenshot, query elements.",
    )
