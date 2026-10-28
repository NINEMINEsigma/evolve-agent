# Shell Sessions and Python Packages

Use the `shell` toolset when a task genuinely needs a command interpreter, package installation, or an interactive CLI. Prefer dedicated file tools for file operations.

## Start and reuse

Reuse an existing Shell when possible; otherwise call `StartShell`. Keep its `shell_id` and `output.next_offset` across tool calls and response turns.

- `ReadShell` reads further output using the returned offset.
- `WriteShell` sends another line to an existing Shell.
- `InterruptShell` sends Ctrl-C without destroying the Shell.
- `StopShell` terminates the entire Shell and its process tree.

A wait timeout does not mean a command failed and does not stop the Shell. Continue reading instead of starting a duplicate command. A command or response ending is not itself a reason to call `StopShell`. Retain the Shell while work remains or it can be reused.

Explicit stop results may report resource cleanup still pending. Do not claim the Shell was physically released unless the result confirms it.

## Paths and interpreter

`StartShell` supplies syntax-specific `namespace_env` references and an `EVOLVE_PYTHON` reference. Logical prefixes such as `ws:` are not automatically resolved inside command text; use the matching returned environment reference for physical paths.

Run pip through `EVOLVE_PYTHON` to install into the Agent's current Python interpreter rather than whichever executable happens to be on PATH. Use the syntax returned for the selected Shell, and reuse the same Shell for installer output, prompts, and subsequent commands.

Use `Write` or `PatchEdit` for text-file changes instead of Shell or Python scripts. If Python must generate binary or media artifacts, use the physical path supplied by the namespace environment. Present the resulting file with the browser URL conventions in FileDisplay mod.

## Ownership and lifecycle

Shell resources belong to the main session and creating character. Do not assume a different Agent can operate another character's Shell.

WebSocket disconnection does not stop Shells. Automatic session rotation migrates their ownership; manual termination, permanent session deletion, evolution, and application shutdown stop associated Shells.

The Gateway already occupies port `{{gateway_port}}`; do not start another server there. Temporary servers need a different free port. If an unknown program occupies a port, report it rather than killing that program without authorization.
