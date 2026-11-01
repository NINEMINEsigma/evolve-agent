# Session Variable Pool

{{owner_intro}}

The pool is at `ws:sessions/{{session_id}}/{{variables_dir}}/`. It persists numeric and string state for the main session independently of conversation history. Both ordinary and temporary Agents in separate sub-sessions use their parent main session's resource ID. Files are the sole source of truth: do not invent a remembered balance or infer an exact value from a summary.

## Read and write

Load the `filesystem` toolset before using `ReadSessionVariables`. One call reads all variables, including nested groups, original values, normalized metadata, and diagnostic issues. It has no session selector: it reads the current main session, or the parent main session for an ordinary or temporary Agent in a separate sub-session. Reading this guidance does not grant variable-writing tools to temporary Agents or expand any caller's tool permissions.

Manage files using `Read`, `Write`, `PatchEdit`, `Copy`, `Move`, and `Delete`; there is no special variable write tool. Each `.json` file contains exactly one JSON number or string. For example, `characters/alice/hp.json` can contain `80`, and `characters/alice/name.json` can contain `"Alice"`. Escape multiline strings as JSON. Boolean, null, array, and object values are unsupported.

## Metadata and display

Metadata goes beside the complete filename, such as `hp.json.meta`. Use separate `[key]` sections:

- `label`: display label, otherwise the filename without `.json`; at most 256 characters.
- `description`: plain-text description; at most 2048 characters.
- `min`, `max`: finite browser-safe JSON numeric bounds.
- `integer`: lowercase `true` or `false`, default false. Mathematically integral values such as `1.0` qualify.
- `percent`: lowercase `true` or `false`, default false. Display multiplies the stored value by 100 and appends `%`; `0.75` displays as 75%. Stored values and constraints are unchanged.
- `display`: `auto`, `number`, `bar`, or `gauge`. Auto uses a bar when valid distinct bounds exist, otherwise a number. Bars and gauges fall back to numbers without suitable bounds.

Bounds and integer requirements produce warnings; they do not clamp, round, or prevent writes. Numeric metadata does not apply to strings. Unknown keys remain data and do not execute code. Keep numeric values finite and within absolute value 9007199254740991 for reliable browser display.

The session variables Tab is read-only. Strings render as plain text.

## Settlement and consistency

Only the main Agent should settle shared balances and other shared variables. Other participants should propose changes or write their own independent directories. Read current values before settlement, including after regeneration.

Ordinary read-modify-write is not atomic. Workspace file locks do not mutually exclude Agents. Reading the entire pool is not a cross-file transaction or a guaranteed same-instant snapshot. Values and metadata are separate files, and direct overwrites may temporarily contain incomplete text.

Inspect reported issues rather than treating invalid values as zero or assuming the pool is empty. `scan_complete=false` means an unsupported subtree was excluded; report and repair the affected path before relying on complete state.

## Read limits

The limits are 512 variables, 4096 nodes, 16 directory levels, 64 KiB per file, 512 KiB aggregate content, 1 MiB encoded response, and a 2-second soft scan deadline. A limit failure is explicit, not a silently partial pool. Repair the pool or move unneeded files rather than assuming a larger capacity. Links, Windows junctions, and special files are unsupported.

## Lifecycle

Automatic rotation and single-parent branches copy the complete pool and metadata to the new main session. The copy is independent; subsequent writes do not synchronize. Multi-parent merges preserve each source under `sources/<source_session_id>/`; explicitly reconcile conflicting state afterward.

Invalid JSON and metadata are copied as original bytes. Unreadable, linked, or over-limit content blocks complete inheritance; finish writes and repair the reported path before retrying. Rejected initialization does not silently skip source files.

Already running sub-Agents retain their old parent session ID after rotation and continue writing the old pool. Complete variable-changing work before rotation, or reconcile old state and restart the role under the new session. Do not assume their late writes migrated.

Regenerating replies or deleting messages does not roll back files. Avoid repeating a settlement already applied. Permanently deleting a session leaves its variable files on disk; cleanup requires an explicit file operation. Remaining files do not prove the session still exists.
