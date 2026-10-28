# Fallback Repair

This guidance applies only when the launch entry has started the Agent in fallback mode after the fast runtime failed. Loading it in a normal conversation is not a request to enter fallback or start a repair.

## Assigned target

Use the supplied runtime error log at `{{fix_log_path}}` and repair target at `{{fix_fork_path}}`. The `fix:` namespace resolves to the target configured for this fallback process. Do not assume its physical location from the name of the fallback repository or modify the currently executing repair runtime.

Fallback mode does not provide the fast-mode `fork:` evolution space or global dynamic sandbox spaces. Respect current namespace and tool availability.

## Repair workflow

1. Read the assigned error information through the provided supported access path.
2. Inspect the affected code in the assigned repair target.
3. Use file tools to make focused changes that address the failure without unrelated redesign.
4. Use available verification tools only as authorized by the repair assignment and current tool definitions.
5. Follow the supplied fallback completion protocol; do not trigger a fast-mode evolution to finish a repair.

The fallback task is a repair operation rather than an ordinary chat or feature-development session. Follow its output restrictions instead of adding unrelated explanations or questions.

## Completion

The launch entry treats successful fallback exit code `0` as permission to restart fast. A failed repair causes the launch entry to stop rather than claiming recovery.

Do not report a successful repair merely because a file edit completed, and do not manufacture an exit code or terminate unrelated processes. Use the runtime's supported completion path and the actual results of the assigned operation.

See Evolution mod for normal fast-mode evolution; it is a separate workflow.
