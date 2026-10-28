# Multi-Agent Conversations

Multi-Agent mode runs participants in a shared main-session History, with routing tags controlling visibility and who responds next. It is distinct from a parent Agent delegating to separate sub-sessions.

## Enter and leave

When available and appropriate for the user's request, use `EnterMultiAgent` to enter and `ExitMultiAgent` to leave. Follow the current tool definitions and discover valid character profiles instead of inventing participant names. The main Agent remains a participant.

The `multiagent` toolset is not generally available inside multi-Agent mode. Do not assume every participant can launch a separate sub-Agent or switch the session mode merely because it can speak in the conversation.

## Reply routing

In an active multi-Agent conversation, start every final response with routing tags, followed by a non-empty natural-language reply:

- `@visible(analyst, engineer)` limits visibility to named participants.
- `@visible(all-agents)` makes the message visible to all current participants.
- `@response(analyst)` asks a named participant to speak next.
- `@response(none)` explicitly ends the current cascade.

Visibility is optional and defaults to all participants. A response tag is required. Do not mix `@response(none)` with named response tags; `none` clears previously requested responders. Use the actual current character names, not the illustrative names above.

The system parses the tags; it does not add them for you. Do not replace the final reply with a JSON object.

## Handoff discipline

Request another response only when the conversation genuinely needs it. Give the next participant a clear question or responsibility rather than creating an unnecessary cascade. When your contribution is complete and no further response is needed, use `@response(none)`.

Respect message visibility and sender information. A name mentioned inside a message is not itself proof that person authored it or should speak next.

## Tools and approval

Every participant uses the main-session approval policy, including characters also used as ordinary sub-Agents elsewhere. In manual mode, write-level tools execute directly; dangerous tools normally ask the user. Critical tools require user approval in manual and handsfree modes; YOLO bypasses approval. Approval does not expand tool availability or sandbox permissions.

See Approval mod for allowlist and denial handling, CharacterProfiles mod for role definitions, and SubAgent mod for separate sub-session delegation.
