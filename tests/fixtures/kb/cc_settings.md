# All settings

## Model and responses

### `advisorModel`

Pick which model answers when Claude calls the server-side [advisor tool](/docs/en/advisor). Unset it to turn the advisor off. The advisor must be at least as capable as your main model. See [Choose an advisor model](/docs/en/advisor#choose-an-advisor-model) for the accepted pairings and what happens when you pick one that isn't accepted.

You don't usually edit this key by hand. Run `/advisor` to open a picker that shows the current choice, the models that can advise, and **No advisor**. Claude Code saves your pick to this key in `~/.claude/settings.json`. If you pick from a [Remote Control](/docs/en/remote-control) client or in a session attached to a remote worker, the pick applies to that session only and doesn't change this key.

If your account requires the [usage-credits consent](/docs/en/advisor#fable-advisor-and-usage-credits), accept it first by running `/model fable`. Until you do, picking Fable in `/advisor` saves nothing and Claude Code tells you to run `/model fable` first.

* **Scope**: [`Any file`](#scopes)
* **Type**: string, one of the aliases `"fable"`, `"opus"`, or `"sonnet"`, which resolve to Claude Code's current default version of that model family, or a full model ID such as `"claude-opus-5-5"`
* **Default**: unset, so the advisor is off
* **Per-session overrides**: `--advisor` takes precedence over this key for one session. [`CLAUDE_CODE_DISABLE_ADVISOR_TOOL`](/docs/en/env-vars) turns the advisor off, and this key can't turn it back on

```json settings.json theme={null}
{
  "advisorModel": "opus"
}
```

The key has no effect on providers where the advisor [isn't available](/docs/en/advisor#requirements), such as Amazon Bedrock and Claude Platform on AWS. `"fable"` requires [Fable access](/docs/en/advisor#choose-an-advisor-model).


### `alwaysThinkingEnabled`

Turn [extended thinking](/docs/en/model-config#extended-thinking) off for every session by setting this to `false`. Thinking is on by default, so `true` changes nothing. Most people set this through `/config` rather than by editing the file.

On models that always think, such as Opus 5.5 and the Fable models, `false` has no effect. On [third-party providers](/docs/en/third-party-integrations) Claude Code omits the `thinking` parameter instead of turning thinking off, so adaptive-reasoning models may still think. With thinking turned off on the Anthropic API, Claude Code sends effort `high` instead of a higher level to models it knows [don't accept that combination](/docs/en/errors#effort-isnt-available-with-thinking-turned-off), such as Opus 5.

* **Scope**: [`Any file`](#scopes)
* **Type**: Boolean
  * `true`: no effect; thinking is already on
  * `false`: Claude Code turns extended thinking off for every session
* **Default**: unset, so thinking is on for models that support it
* **Per-session overrides**: [`MAX_THINKING_TOKENS`](/docs/en/env-vars) takes precedence over this key for one session: `0` turns thinking off, under the same model and provider limits as `false`, and a positive value turns thinking on even when this key is `false`. On adaptive-reasoning models the number itself is ignored

```json settings.json theme={null}
{
  "alwaysThinkingEnabled": false
}
```


## Enterprise and managed settings

### `disableSideloadFlags`

Reject the `--plugin-dir`, `--plugin-url`, `--agents`, and `--mcp-config` CLI flags at startup, which users could otherwise pass to bypass [`strictKnownMarketplaces`](#strictknownmarketplaces) for a single run. Claude Code exits with an error naming the rejected flags, and applies the same check to surfaces that start the CLI with these flags internally, currently [Cowork](/docs/en/desktop) local sessions in the desktop app. In [cloud sessions](/docs/en/claude-code-on-the-web), Claude Code drops the MCP servers the server delivered through `--mcp-config`, other than in-process `type: "sdk"` entries, and starts the session. Requires Claude Code v2.1.193 or later.

* **Scope**: [`Managed`](#scopes)
* **Type**: Boolean
  * `true`: Claude Code rejects `--plugin-dir`, `--plugin-url`, `--agents`, and `--mcp-config` at startup and exits with an error naming them, except that in cloud sessions it drops the MCP servers the server delivered through `--mcp-config`, other than in-process `type: "sdk"` entries, and starts the session
  * `false`: Claude Code accepts those flags
* **Default**: `false`

```json managed-settings.json theme={null}
{
  "disableSideloadFlags": true
}
```

Claude Code still accepts a `--mcp-config` whose servers are all in-process `type: "sdk"` entries, so the Agent SDK and VS Code extension keep working. Users can still add servers with `claude mcp add` or a `.mcp.json` file; for per-server control, set [`allowedMcpServers`](/docs/en/managed-mcp) as well. Requires Claude Code v2.1.193 or later.

In cloud sessions, Claude Code also ignores server-delivered mid-session MCP updates, the path behind cloud session configuration and SDK `setMcpServers()` calls that reach those sessions. In-process `type: "sdk"` entries stay exempt there too. Before v2.1.239, a server-delivered `--mcp-config` blocked a cloud session from starting.

