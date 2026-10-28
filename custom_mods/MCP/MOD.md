# MCP Servers

MCP (Model Context Protocol) connects external servers that provide tools and related capabilities. The current configuration file is `{{mcp_config_path}}`. Read it before making a requested change and preserve unrelated server entries.

## Configuration document

Use a UTF-8 JSON object whose top-level keys are server names. Each value is that server's configuration object. Use valid JSON with double quotes, no comments, and no trailing commas.

This runtime does not unwrap `mcpServers`, `mcp_servers`, or `servers`. When adapting configuration from another client, extract that client's server entries and merge them directly into this document. Do not copy a YAML example or an entire foreign configuration wrapper unchanged.

The examples below are independent configuration documents. Merge the selected server entry into the existing document instead of replacing all servers. Package names, endpoints, and credentials are illustrative; obtain the real values from the server's documentation and the user's authorized configuration.

## Choose a transport and authentication method

| Server requirement | Configuration |
|---|---|
| Local process speaking MCP over standard input/output | `command`, `args`, and optionally `env` |
| Remote Streamable HTTP endpoint | `url`, optionally `transport: "http"`, and `headers` when required |
| Legacy SSE endpoint | `url`, `transport: "sse"`, and `headers` when required |
| Browser-based OAuth authorization | HTTP or SSE entry with `auth: "oauth"` and optional `oauth` settings |

If `url` is present, the runtime selects remote transport rather than starting `command`. Configure one transport per entry. For stdio, omit `url`; a `transport: "stdio"` field is not required.

## Stdio configuration and env

For a locally launched MCP server, put the executable in `command` and each argument in its own `args` array element. Do not put a whole shell command line into `command`.

```json
{
  "local-service": {
    "command": "node",
    "args": ["C:/mcp-servers/service/server.js"],
    "env": {
      "SERVICE_API_KEY": "REPLACE_WITH_AUTHORIZED_API_KEY",
      "SERVICE_BASE_URL": "https://api.example.com",
      "SERVICE_TENANT": "example-tenant"
    },
    "connect_timeout": 60,
    "timeout": 120
  }
}
```

`env` must be an object mapping variable names to string values. Use the exact names expected by that server; `SERVICE_API_KEY` is not a universal MCP field. Even a numeric environment value must be a JSON string, such as `"SERVICE_PORT": "9000"`.

The runtime filters inherited process environment and then adds explicitly configured variables. Do not assume an API key present in the host environment is automatically inherited by the MCP subprocess. `env` supplies variables to that child process only; it does not set application-wide environment variables or configure HTTP request headers.

For package-manager launchers, follow the server's documented executable and arguments. On Windows, use a resolvable executable or the appropriate `.cmd` launcher, such as `npx.cmd`, when needed. Physical executable and script paths are process configuration, not sandbox file-tool paths. Use forward slashes or JSON-escaped backslashes in Windows paths; do not pass `ws:` as if the subprocess resolves that prefix.

Do not invent a `cwd` setting: the current stdio construction does not pass a configured working directory to the server process. Prefer explicit script and resource paths when necessary.

## HTTP configuration and headers

For a remote server, use its actual MCP endpoint, not merely its homepage or an ordinary REST API URL. The URL must use HTTP or HTTPS and include a host. Prefer HTTPS for credentials.

### Bearer token

```json
{
  "remote-service": {
    "url": "https://mcp.example.com/mcp",
    "transport": "http",
    "headers": {
      "Authorization": "Bearer REPLACE_WITH_AUTHORIZED_ACCESS_TOKEN"
    },
    "connect_timeout": 60,
    "timeout": 120
  }
}
```

The field name is `headers`, plural, and its value must map header names to strings. Include the `Bearer ` prefix and space only when the provider specifies Bearer authentication. A static token in a header does not require `auth: "oauth"`.

### API key or additional provider headers

```json
{
  "key-service": {
    "url": "https://mcp.example.com/mcp",
    "headers": {
      "X-API-Key": "REPLACE_WITH_AUTHORIZED_API_KEY",
      "X-Tenant-ID": "example-tenant"
    }
  }
}
```

Use the provider's documented header names and formats. A provider may require a different API-key header, an authorization scheme, or several headers together. Do not assume `X-API-Key`, tenant headers, cookies, or organization fields are universal requirements. Do not add unrelated credentials or conflicting authentication methods.

Headers are sent by the remote transport. Placing a token in an HTTP entry's `env` does not turn it into an authorization header. Conversely, a stdio entry's `headers` are not automatically converted into the local server's environment variables.

### Legacy SSE

For a server explicitly documented as using SSE, use its actual SSE endpoint:

```json
{
  "legacy-service": {
    "url": "https://mcp.example.com/sse",
    "transport": "sse",
    "headers": {
      "Authorization": "Bearer REPLACE_WITH_AUTHORIZED_ACCESS_TOKEN"
    }
  }
}
```

Omitting `transport` selects Streamable HTTP. Merely ending a URL with `/sse` does not select the SSE transport. The accepted Streamable HTTP transport names are `http`, `streamable_http`, and `streamable-http`; use the explicit lowercase value `sse` for SSE.

## Environment references and secrets

The current configuration load and connection paths do not apply environment-variable interpolation. Treat `${TOKEN}`, `$TOKEN`, `%TOKEN%`, and `${env:TOKEN}` in configuration values as literal strings, not working secret references. A helper for `${VAR}` exists in source but is not called by this loading path; its presence is not support for interpolation.

Do not write `"Authorization": "Bearer ${TOKEN}"` and claim the token will be resolved. Likewise, `"env": {"TOKEN": "${TOKEN}"}` currently supplies literal placeholder text. Entries in `env` do not define variables for use by other configuration fields.

The replacement markers in these examples are instructional placeholders, not runnable credentials. Obtain real credentials only through a user-authorized method and write them only to the intended local configuration when authorized. Do not echo them in responses, expose entire configuration contents unnecessarily, place them in command arguments or URLs when an environment variable or header is appropriate, or send them to unrelated services.

A locally stored JSON configuration containing actual keys is sensitive. Do not commit, publish, or treat it as encrypted storage. If the user requires environment-backed references without plaintext values in this file, explain the current limitation rather than inventing a supported syntax.

## OAuth authorization

Use OAuth only for a server that supports the MCP OAuth flow. Static API keys and Bearer headers are separate authentication mechanisms; `auth` is not a place to write `bearer`, `api_key`, or a token string. Its supported values are an empty string or `oauth`.

```json
{
  "oauth-service": {
    "url": "https://mcp.example.com/mcp",
    "auth": "oauth",
    "oauth": {
      "client_name": "Evolve-Agent",
      "redirect_port": 0,
      "timeout": 300
    }
  }
}
```

The runtime uses the MCP SDK's OAuth authorization-code flow with PKCE, discovery, client registration where supported, token exchange, and refresh. Browser consent is a user action; do not claim it is completed just because the configuration was saved.

Optional `oauth` fields are:

| Field | Meaning |
|---|---|
| `client_name` | Client display name; default `Evolve-Agent` |
| `client_id` | A pre-registered client ID when the provider requires or supplies one |
| `client_secret` | Secret for a confidential client when required; not a Bearer token |
| `scope` | Provider-defined space-separated scope string |
| `redirect_port` | Integer from 0 to 65535; 0 chooses an available local port |
| `timeout` | Positive authorization/callback waiting budget in seconds; default 300 |

For a pre-registered client, add the supplied `client_id` and, only when required, `client_secret` to the `oauth` object. The current confidential-client setup uses `client_secret_post`; do not promise arbitrary token endpoint authentication methods or client-credentials grants.

The callback URI is `http://127.0.0.1:<resolved-port>/callback`. If the provider requires a pre-registered fixed redirect URI, choose a matching nonzero `redirect_port` and arrange that exact URI with the provider. The runtime does not consume a configurable `redirect_uri` field. Do not kill an unrelated program to free a callback port.

First-time authorization requires the user to complete the browser flow. A non-interactive process without cached tokens may need an interactive authorization attempt; a web chat connection does not itself guarantee an interactive terminal. With remote deployment, the browser must be able to reach the callback listener on the machine running the Agent; the browser's own localhost may be a different machine. Report that deployment constraint rather than promising automatic remote login.

OAuth tokens and client metadata are managed under `ws:mcp-tokens`. Do not print, fabricate, or manually delete that state merely to retry a failure. If an entry uses OAuth, normally omit a static `Authorization` header and let the OAuth provider supply it. Include additional headers only when explicitly required by the service.

## Other supported connection fields

- `enabled`: boolean, default true. Set false to disable an entry without deleting it.
- `connect_timeout`: positive number of seconds for connection setup.
- `timeout`: positive number of seconds for tool calls; distinct from `oauth.timeout`.
- `supports_parallel_tool_calls`: boolean opt-in for concurrent calls to that server; leave disabled unless the server can handle it safely.
- `ssl_verify`: boolean used by the Streamable HTTP client, default true. The current SSE branch does not pass this setting through. Certificate errors are not authorization errors; do not disable verification to solve an authentication failure.

Keep connection and tool-call timeout values as JSON numbers, and booleans as JSON booleans. Increasing a timeout does not fix an invalid token, incorrect scope, or wrong endpoint.

## Save, apply, and load tools

1. Read `{{mcp_config_path}}` and determine the documented transport and authentication requirements.
2. Add or edit only the intended server object with file tools. Preserve unrelated entries and use the correct JSON types.
3. Load the `mcp` toolset when available and call `MCPRefresh` using its actual schema.
4. Inspect per-server `status`, `failed`, and `errors`. A top-level `refreshed: true` does not mean every server connected. Treat `cleanup_pending`, when present, as unfinished cleanup rather than confirmed release.
5. Use the current catalog and `LoadToolset` to load the connected server's `mcp-<server>` toolset. Only call tools present in the current request's definitions.

### Changes to an already connected server

The current refresh path rereads the file, removes missing or disabled servers, and starts newly enabled ones. It keeps an existing same-name server instance without comparing and reapplying changed configuration. Therefore, saving a new URL, header, environment value, or OAuth setting and calling `MCPRefresh` once is not proof that the existing connection uses it.

For an authorized live replacement, set that entry's `enabled` to false, save, and refresh to remove the old instance. Confirm removal and resolve any pending cleanup before restoring `enabled` to true, saving, and refreshing again. Explain that this temporarily interrupts that server's tools. A user-controlled application restart is another way to rebuild connections; do not start or restart the application without authorization.

If OAuth settings changed, rebuilding the server connection alone is not proof that cached OAuth client/provider state was replaced. Report persistent authorization issues and use an explicitly supported user-authorized reauthentication procedure rather than deleting token files or repeatedly cycling the server.

## Authentication failures

- For 401 or an explicit authentication error, check the required mechanism, header spelling, scheme, credential validity, and whether the changed configuration was actually applied. For OAuth, determine whether user authorization is still needed.
- For 403, check the provider's stated scopes, permissions, tenant, or policy restrictions. Do not assume every 403 is solved by obtaining a different token.
- For unavailable subprocesses, check executable resolution, arguments, and the exact `env` names required by the server. Do not mistake startup failure for a rejected remote token.
- For malformed JSON or server-entry type errors, repair the document before treating missing tools as an authentication problem.

One failed server can be skipped while others remain available. Report the actual failure without exposing credentials; do not invent tool availability, repeatedly retry unchanged credentials, or modify read-only custom source directories as a workaround.

Remote tool access remains subject to normal scope, approval, validation, and interruption rules. See Toolsets mod for progressive loading and Approval mod for approval behavior.
