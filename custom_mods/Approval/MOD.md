# Tool Approval

Tool approval depends on registered danger level, the main session's server-side mode, and whether the call is in a main session or a separate sub-session. Use `ShowTool` to inspect a level instead of guessing from the name or arguments.

## Main-session policy

The following applies to ordinary main sessions, Colloquy, and all multi-Agent main-session participants, before an allowlist match:

| Danger level | Manual mode | Handsfree mode | YOLO mode |
|---|---|---|---|
| safe | Direct execution | Direct execution | Direct execution |
| write | Direct execution | Approval model | Direct execution |
| dangerous | User approval | Approval model | Direct execution |
| critical | User approval | User approval | Direct execution |

Manual mode does not mean every write asks the user. In particular, write-level `Write` and `PatchEdit` calls in a main session do not open an approval dialog.

Outside YOLO, a matching allowlist entry can bypass approval for non-critical calls. Critical calls skip the allowlist and require user approval in both manual and handsfree modes. Matching includes the tool name and normalized arguments, excluding `reason` and internal approval/session fields. Always-allow is not blanket permission for all argument combinations.

Approval allows execution to continue; it does not guarantee success or bypass scope, sandbox permissions, validation, or interruption. An unavailable approval model can deny a call without changing a persisted handsfree session back to manual mode.

## Separate sub-sessions

Ordinary sub-Agents use the parent main session's mode:

- Safe tools execute directly.
- In manual mode, calls needing approval wait for the parent Agent through `ApprovalSubAgent`, not a frontend user dialog.
- In handsfree mode, calls needing approval use the approval model.
- Allowlist matches and YOLO bypass this sub-session approval.

Built-in critical tools are not exposed to ordinary sub-Agents. If an authorized custom critical tool is exposed, the generic sub-session route is parent-Agent approval in manual mode or model approval in handsfree mode, without the main-session critical-specific allowlist exception.

Temporary Agents only receive authorized safe tools and do not enter approval. YOLO does not expand their permissions. Multi-Agent main-session participants use the main-session policy, not the separate sub-session policy.

## Reasons and denials

Provide an honest, accurate `reason` when the tool schema supports it and context is needed. It supplements the actual arguments; it is not a way to disguise an operation or manipulate approval.

- `[user denied]` or `[parent Agent denied]`: adjust the approach or ask the appropriate conversation partner for clarification.
- `[approval model denied]`: consider the reason and adjust. Report abnormal repeated denials, nonsensical reasons, or internal errors to the user, or to the parent Agent in a sub-session.
- `[system denied]`: stop tool calls for the turn and report the approval failure. Ask the user for intervention, such as disabling handsfree mode; do not attempt to repair the approval system. A sub-Agent should ask its parent to relay the issue.

If approval fails because the WebSocket is disconnected, do not repeatedly retry or diagnose the application. Wait for reconnection or continue only with appropriate alternatives that do not depend on the blocked approval route.

## Disgust signal

When a tool rejection contains `"_disgusted": true`, stop calling tools immediately and address the user's concerns in text. This signal blocks tools but does not stop response generation. It clears when the user sends the next message.

The user controls manual, handsfree, and YOLO selection through the input bar's approval-mode entry. See SubAgent and TaskAgent mods for delegation-specific guidance.
