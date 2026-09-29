# Model Context Protocol

> For the complete documentation index, see [llms.txt](https://learn.chatgpt.com/llms.txt). Markdown versions of documentation pages are available by appending `.md` to the page URL.
## Connect Codex to an MCP server

Codex stores MCP configuration in `config.toml` alongside other Codex configuration settings. By default this is `~/.codex/config.toml`, but you can also scope MCP servers to a project with `.codex/config.toml` (trusted projects only).

The ChatGPT desktop app, Codex CLI, and IDE extension share this configuration.
Once you configure your MCP servers, you can switch among those clients without
redoing setup.

</ContentModeSwitch>

<ContentModeSwitch group="codex-surface" id="app">

### Configure in the ChatGPT desktop app

1. Open **Settings**, then select **MCP servers**.
2. Select **Add server**.
3. Enter a name, choose **STDIO** or **Streamable HTTP**, and provide the
   server's command or URL.
4. Save the server, then select **Restart**.

The server list shows which servers are enabled and which require OAuth. Select
**Authenticate** when an OAuth server requires sign-in. In the composer, type `/mcp`
to view connected servers.

</ContentModeSwitch>

<ContentModeSwitch group="codex-surface" id="web">

## Use MCP-backed tools in ChatGPT web

In a hosted ChatGPT Work chat, install a [plugin](https://learn.chatgpt.com/docs/plugins) to use its
bundled connectors and remote MCP tools. After installation, Chat and Work can
use those tools. Workspace administrators can control which plugins and tools
are available.

ChatGPT web doesn't read local Codex configuration files or expose the local
Codex command menu. Open the **Plugins** tab to browse and manage available
tools.

</ContentModeSwitch>

<ContentModeSwitch group="codex-surface" id="cli">

### Configure with the CLI

#### Add an MCP server

```bash
codex mcp add <server-name> --env VAR1=VALUE1 --env VAR2=VALUE2 -- <stdio server-command>
```

For example, to add Context7 (a free MCP server for developer documentation), you can run the following command:

```bash
codex mcp add context7 -- npx -y @upstash/context7-mcp
```

#### Other CLI commands

Run `codex mcp list` to see configured servers. To see all available MCP
commands, run `codex mcp --help`. For a server that supports OAuth, run
`codex mcp login <server-name>`.

#### Terminal UI (TUI)

In the `codex` TUI, use `/mcp` to see your active MCP servers.

</ContentModeSwitch>

<ContentModeSwitch group="codex-surface" id="ide">

### Configure in the IDE extension

1. Open the gear menu, then select **MCP servers**.
2. Select **Add server**.
3. Enter a name, choose **STDIO** or **Streamable HTTP**, and provide the
   server's command or URL.
4. Save the server, then select **Restart extension**.

The MCP server list shows which servers are enabled and which require OAuth.
Select **Authenticate** when an OAuth server requires sign-in.

</ContentModeSwitch>

<ContentModeSwitch group="codex-surface" ids="app,cli,ide">

### Configure with config.toml

For more fine-grained control, edit `~/.codex/config.toml` or a project-scoped
`.codex/config.toml`. See the [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
for a searchable list of every supported MCP option.

Configure each MCP server with a `[mcp_servers.<server-name>]` table in the configuration file.

</ContentModeSwitch>

<a id="stdio-servers"></a>

<ContentModeSwitch group="codex-surface" ids="app,cli,ide">

#### STDIO servers

- `command` (required): The command that starts the server.
- `args` (optional): Arguments to pass to the server.
- `env` (optional): Environment variables to set for the server.
- `env_vars` (optional): Environment variables to allow and forward.
- `cwd` (optional): Working directory to start the server from.
- `experimental_environment` (optional): Set to `remote` to start the stdio
  server through a remote executor environment when one is available.

`env_vars` can contain plain variable names or objects with a source:

```toml
env_vars = ["LOCAL_TOKEN", { name = "REMOTE_TOKEN", source = "remote" }]
```
