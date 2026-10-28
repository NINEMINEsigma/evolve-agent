# Ordinary Sub-Agents

Use an ordinary sub-Agent for a role with its own LLM context and conversation that may continue across multiple exchanges. This is distinct from a one-shot temporary Agent and from participants sharing a multi-Agent main session.

## Discover and launch

Load the `multiagent` toolset when available. Use `ListSubAgents` to discover current character names, types, descriptions, configuration errors, and running states. A name in an earlier prompt may no longer be runnable; use current discovery results.

Launch with `RunSubAgent`. Put the task, relevant facts, constraints, expected output, and all initial context into `initial_prompt`. Do not launch and then use a separate chat call merely to supply the initial assignment.

Within one parent session, the same character name cannot have more than one active instance. Stop the existing instance before restarting that role. There is no general active-count limit or waiting queue to infer from an old description.

See CharacterProfiles mod to prepare or repair a role definition.

## Communication

After launch, wait for the `[subagent-result]` feedback before another conversational exchange with that sub-Agent. Do not poll with `ChatSubAgent`, ask whether it is alive, or urge it to respond faster.

Use `ChatSubAgent` after receiving the latest response to answer questions, provide missing context, or correct direction. Supply enough information for its separate context; it does not automatically possess everything in the main conversation.

## When you are the sub-Agent

Your default conversation partner is the parent Agent, and ordinary replies are delivered back to it. The human end user is the same person operating the main session, not an unrelated visitor.

Use the message header to identify the speaker and delivery route:

- `[your direct conversation partner in this turn: <name>]`: respond to the named partner; the reply returns to the parent Agent.
- `[The speaker of this message in this turn: <name>]`: an overheard message; do not assume a reply is required unless its content asks something of you.
- `[Direct message from the end user: <name>]`: respond directly to the human; this reply is shown in the sub-session and is not delivered to the parent inbox.

The header, not a name mentioned inside the body, determines the current speaker. Use only tools available to the sub-session and do not attempt to spawn further sub-Agents. On completion, state the conclusion clearly; the parent Agent manages stopping the role.

## Approval

An ordinary sub-session follows the parent main session's server-side mode. Safe tools run directly. In manual mode, calls needing approval wait for the parent Agent's decision through `ApprovalSubAgent`; this is not a frontend user approval dialog. In handsfree mode, such calls use the approval model. Allowlist matches and YOLO can bypass approval without expanding tool permissions.

Handle pending approval feedback rather than assuming the sub-Agent is unresponsive. Built-in critical tools are not exposed to ordinary sub-Agents. See Approval mod for the complete distinction between main-session and sub-session routing.

## Stop and history

Use `StopSubAgent` when the role's work is done or it must be restarted. Ordinary sub-Agent History is saved on stop to `ws:tmp/<session_id>.es`. To resume a saved history on a later launch, explicitly pass its logical `history_path`; there is no automatic history lookup by character name. An invalid explicit history rejects launch rather than silently starting fresh.

Session visual files and variables belong to the parent main session, not the sub-session. See SessionSite, SessionStage, SessionChatStyle, and SessionVariables mods before assigning work on them. Running sub-Agents retain their old parent ID after main-session rotation; do not assume all file-based state migrated.

For one-shot safe work without persistent History, see TaskAgent mod. For shared-history conversation and routing tags, see MultiAgent mod.
