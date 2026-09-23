# Discover plugins

## Official Anthropic marketplace

Claude Code adds the official Anthropic marketplace (`claude-plugins-official`) automatically the first time you start it interactively. If Claude Code can't add it, for example because your network blocks the download or a [marketplace policy](/docs/en/plugin-marketplaces#managed-marketplace-restrictions) blocked an earlier attempt, add it yourself with `/plugin marketplace add anthropics/claude-plugins-official`.

To browse what's available, run `/plugin` and go to the **Discover** tab, or view the catalog at [claude.com/plugins](https://claude.com/plugins).

To install a plugin from the official marketplace, use `/plugin install <name>@claude-plugins-official`. For example, to install the GitHub integration:

```shell theme={null}
/plugin install github@claude-plugins-official
```

`/plugin` opens an interactive panel in the terminal CLI. If Claude replies that `/plugin` isn't available in this environment, install the plugin another way:

* **Claude desktop app**: use the [plugin browser](/docs/en/desktop#install-plugins).
* **VS Code extension**: install from the [**Manage plugins** dialog](/docs/en/vs-code#manage-plugins).
* **Cloud sessions**: enable the plugin for your claude.ai account so Claude Code loads it as a [synced plugin](/docs/en/plugins-reference#synced-plugins).

If the install fails, match the message Claude Code reports:

* `Marketplace "claude-plugins-official" not found`: add the marketplace with `/plugin marketplace add anthropics/claude-plugins-official`, then retry the install.
* The plugin is [not found in the marketplace](#install-plugins): check the plugin name.

<Note>
  The official marketplace is curated by Anthropic, and inclusion is at Anthropic's discretion. The in-app submission forms add plugins to the [community marketplace](#community-marketplace), not the official one. To distribute plugins independently, [create your own marketplace](/docs/en/plugin-marketplaces) and share it with users.
</Note>

The official marketplace includes several categories of plugins:

### Code intelligence

Code intelligence plugins enable Claude Code's built-in LSP tool, giving Claude the ability to jump to definitions, find references, and see type errors immediately after edits. These plugins configure [Language Server Protocol](https://microsoft.github.io/language-server-protocol/) connections, the same technology that powers VS Code's code intelligence. In [cloud sessions](/docs/en/claude-code-on-the-web), Claude Code doesn't start plugin language servers, so Claude doesn't get the LSP tool there.

Install the language server binary from the table below before using these plugins; the plugin doesn't install it for you. If you already have a language server installed, Claude may prompt you to install the corresponding plugin when you open a project.

| Language   | Plugin              | Binary required              |
| :--------- | :------------------ | :--------------------------- |
| C/C++      | `clangd-lsp`        | `clangd`                     |
| C#         | `csharp-lsp`        | `csharp-ls`                  |
| Go         | `gopls-lsp`         | `gopls`                      |

You can also [create your own LSP plugin](/docs/en/plugins-reference#lsp-servers) for other languages.

<Note>
  If you see `Executable not found in $PATH` in the `/plugin` Errors tab after installing a plugin, install the binary the [code intelligence](#code-intelligence) table lists for that plugin.
</Note>

#### What Claude gains from code intelligence plugins

Once a code intelligence plugin is installed and its language server binary is available, Claude gains two capabilities:

* **Automatic diagnostics**: after every file edit Claude makes, the language server reports errors and warnings back, so Claude sees type errors, missing imports, and syntax issues without running a compiler or linter. If Claude introduces an error, it notices and fixes it in the same turn.
* **Code navigation**: Claude can use the language server to jump to definitions, find references, get type info on hover, list symbols, find implementations, and trace call hierarchies. These operations give Claude more precise navigation than grep-based search, though availability may vary by language and environment.

You don't need to configure diagnostics beyond installing the plugin. To read them yourself, press **Ctrl+O** when Claude Code shows an indicator such as **Found 3 new diagnostic issues in 2 files**.

If you run into issues, see [Code intelligence troubleshooting](#code-intelligence-issues).

### External integrations

These plugins bundle pre-configured [MCP servers](/docs/en/mcp) so you can connect Claude to external services without manual setup:

* **Source control**: `github`, `gitlab`
* **Project management**: `atlassian` (Jira/Confluence), `asana`, `linear`, `notion`
* **Design**: `figma`
* **Infrastructure**: `vercel`, `firebase`, `supabase`
* **Communication**: `slack`
* **Monitoring**: `sentry`

### Automatic security review

The `security-guidance` plugin reviews each change Claude makes for common vulnerabilities and instructs Claude to fix what it finds in the same session. See [Catch security issues as Claude writes code](/docs/en/security-guidance) for what it checks and how to add project-specific rules.

### Development workflows

Plugins that add skills and agents for common development tasks:

* **commit-commands**: Git commit workflows including commit, push, and PR creation
* **pr-review-toolkit**: specialized agents for reviewing pull requests
* **agent-sdk-dev**: tools for building with the Claude Agent SDK
* **plugin-dev**: toolkit for creating your own plugins

### Output styles

Customize how Claude responds:

* **explanatory-output-style**: educational insights about implementation choices
* **learning-output-style**: interactive learning mode for skill building

## Community marketplace

fin
