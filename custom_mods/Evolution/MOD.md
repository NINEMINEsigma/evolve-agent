# Runtime Code Evolution

Use this guidance for an authorized request to evolve the Evolve Agent runtime, not for ordinary user file work or merely to customize a session's presentation.

## Repository roles

The origin repository is the persistent source from which runtime copies are initialized. The fast repository is the current running copy. The slow repository is the evolution target available through `fork:` in fast mode. The fallback repository retains a previous runtime for recovery.

There is no `self:` namespace. Use `fork:` for evolution changes, not the currently executing fast repository. Read-only namespaces such as `third:`, `custom_hooks:`, `custom_llm_client:`, and `custom_tools:` can be inspected within their permissions, but loading this guidance does not make them writable.

## Workflow

1. Confirm the requested behavior and inspect relevant code and development documents through the allowed namespaces.
2. Make complete, targeted changes in `fork:` using file tools.
3. Use the available `ValidateCode` and, when applicable, `ValidateFrontend` tools to inspect the proposed code through the supported workflow.
4. Resolve reported failures and call `EvolveCode` only when the requested change is ready for activation and the user has authorized that action.

Use the current tool definitions and load their toolsets first. These are capabilities of the runtime Agent, not instructions to bypass any user restriction on validation, execution, or startup.

Successful `EvolveCode` processing submits its tool result before requesting the coordinated evolution shutdown. Do not simulate success by killing a process, manually exiting with a success code, or copying runtime repositories yourself.

## Activation and recovery

The launch entry interprets exit code `-1` as evolution: it backs up fast to fallback, promotes slow to fast, and restarts. Backup and promotion use merge-copy behavior, so target-only files are not automatically removed. A normal stop uses code `0`; other failures can invoke fallback repair when enabled.

Do not claim changes are active merely because files were written to slow. Inspect the supported validation and evolution results and distinguish preparation, activation request, and actual restart.

For a fallback-mode repair assignment, see FallbackRepair mod. For session webpages, visual layers, or styles that do not require runtime evolution, see SessionSite, SessionStage, and SessionChatStyle mods.
