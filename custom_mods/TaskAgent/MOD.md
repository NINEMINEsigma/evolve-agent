# Temporary Agents

Use `RunTaskAgent` for a one-shot task with a single prompt and a result delivered asynchronously. Load its toolset first if necessary.

## Prepare the assignment

The temporary Agent has no system prompt and no inherited conversation History. Include the task, relevant facts, exact logical paths, constraints, expected output, and completion criteria in its prompt. Do not assume it has read this mod or knows the main conversation.

It receives a non-persistent deep snapshot of the parent main session's active LLM Profile at launch. Later Profile changes do not alter an already running temporary Agent.

## Tool scope

A temporary Agent may use only tools that satisfy all of these conditions:

- Their toolset is loaded in that temporary sub-session.
- Their availability includes `TASKAGENT`.
- Their registered danger level is `safe`.

Loading another toolset does not authorize non-safe or otherwise unavailable tools. Temporary Agents do not enter parent-Agent or approval-model approval. YOLO does not expand this scope.

Do not assign work that requires writes, dangerous operations, or approval and then assume a mode change can make it executable.

## Results and cancellation

Wait for the `[subagent-result]` feedback. Do not poll or chat with a temporary Agent. It terminates after producing its plain-text result or reaching its execution limit, and does not save persistent History.

Use `StopTaskAgent` with the returned `session_id` if it must be stopped early. There is no persistent temporary conversation to resume afterward.

Use SubAgent mod when the task needs an ordinary role, multiple exchanges, or a separately saved History.
