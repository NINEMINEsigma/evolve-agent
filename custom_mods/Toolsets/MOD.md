# Progressive Toolset Loading

Tools are grouped into toolsets and exposed progressively. A mod provides guidance; it does not by itself load a toolset or grant permission to call a tool.

## Discover and load

Use the current toolset catalog to find a relevant toolset. Entries include a name, loaded or not-loaded state, member tool names, and a short description.

Call `LoadToolset` before using tools from a toolset that is not loaded. Follow its current parameter schema. After loading succeeds, use the tools included in the next request's definitions rather than assuming a remembered definition is still valid.

New sessions normally begin with `core`. An unavailable tool must not be called just because its name appears in an old message or another Agent's context.

## Scope and permissions

The effective tool set depends on loaded toolsets, the current Agent's availability scope, and runtime availability checks. Loading does not bypass sandbox permissions, argument validation, approval, or interruption.

Temporary Agents additionally require `TASKAGENT` availability and `safe` danger level for every tool. Ordinary sub-Agents have their own toolset state; loading a toolset in the main session does not automatically load it in a separate sub-session.

Multi-Agent participants share the main session's loading state, but participant-specific permissions can still restrict tools.

## Persistence

Main-session loading intent is persisted. Ordinary and temporary sub-session loading is local to that instance and starts from the default again on a new launch. Do not confuse a persisted name with proof that all its former tools remain available.

Use `ShowTool` when you need current registered details such as danger level, subject to its own visibility rules. See Approval mod for approval behavior and Skills mod for loading reusable knowledge rather than tool definitions.
