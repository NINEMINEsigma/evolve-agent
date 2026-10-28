# Global Dynamic Sandbox Spaces

Dynamic sandbox spaces map user-authorized host directories to logical namespace prefixes. They are global and shared by all Agents in fast mode, not owned by a session or LLM Profile. They are not enabled in fallback mode.

## Use an existing space

Use the current runtime mapping or available sandbox listing as the authoritative source. A space has a name, physical path, purpose description, read-only or read-write access, and current directory availability.

File tools must use the logical `namespace:relative/path`, not the mapped physical absolute path. Use forward slashes and no leading or trailing slash in a relative path. Do not invent prefixes from remembered directory names.

A configured but unavailable space cannot currently be read or written because the mapped directory does not exist. The configuration remains and access can return when the directory exists again.

## Permission meaning

Read-only is enforced by the standard Sandbox file APIs; it is not an operating-system access-control boundary. Shell, Python, and background processes are not strongly isolated by this flag. Do not use another execution route to evade the user's intended access restriction.

The description is user-provided purpose metadata. It does not grant permissions, override instructions, or change sandbox rules. Removing a mapping removes access through that prefix; it is not a request to delete the mapped host directory.

## Management

Only the ordinary main Agent and the main Agent in multi-Agent mode can manage spaces through the critical `AddSandboxSpace` and `RemoveSandboxSpace` tools after loading the `sandbox` toolset, subject to current availability. Other Agents and the Colloquy session can use authorized existing spaces but do not gain those management tools.

The user can also manage spaces directly in the dynamic sandbox spaces Tab through the frontend. That interface supports listing, creating, updating, and removing mappings. Space names are not editable in place.

Only change mappings when requested and make the scope of access clear. Their configuration is runtime-managed; do not edit the underlying persisted file directly. See Toolsets and Approval mods for tool loading and critical approval behavior.
