# Hooks reference

## Hook events

Each event corresponds to a point.

### SessionStart

Runs when Claude Code starts a new session or resumes an existing session. Useful for loading development context like existing issues or recent changes to your codebase, or setting up environment variables. For static context that doesn't require a script, use [CLAUDE.md](/docs/en/memory) instead.

SessionStart runs on every session, so keep these hooks fast. Only `type: "command"` and `type: "mcp_tool"` hooks are supported. See [MCP tool hook fields](#mcp-tool-hook-fields) for when `mcp_tool` hooks run.

The matcher value corresponds to how the session was initiated:

| Matcher   | When it fires                                                                                                                          |
| :-------- | :------------------------------------------------------------------------------------------------------------------------------------- |
| `startup` | New session                                                                                                                            |
| `resume`  | `--resume`, `--continue`, or `/resume`                                                                                                 |
| `clear`   | `/clear`                                                                                                                               |
| `compact` | Auto or manual compaction                                                                                                              |
| `fork`    | A new session forked from an existing one: `--fork-session` with `--resume` or `--continue`, the `/fork` background copy, or `/branch` |

Before v2.1.214, forked sessions reported source `"resume"`.

When you start an interactive session, resume a conversation at launch with `--continue` or `--resume`, or run `/clear`, SessionStart hooks run in the background. You can type right away, and a conversation you resumed appears without waiting for the hooks. Claude's first response still waits for the hooks to finish, so their context reaches Claude.

When you switch conversations with `/resume` inside a session, the switch waits for the hooks to finish instead. If you run `/clear` or switch to another conversation while background hooks are still running, nothing they return applies to the session.

The same wait applies at launch, including a resumed session: a prompt you send while SessionStart hooks are still running doesn't reach Claude until they finish.

During either wait, press `Esc` to take the prompt back into the input without sending it. The hooks keep running.

#### SessionStart input

In addition to the [common input fields](#common-input-fields), SessionStart hooks receive `source` and optionally `model`, `agent_type`, and `session_title`:

| Field           | Description                                                                                                                                                                                                   |
| :-------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `source`        | How the session started: `"startup"` for new sessions, `"resume"` for resumed sessions, `"clear"` after `/clear`, `"compact"` after compaction, or `"fork"` for a new session forked from an existing one     |
| `model`         | The active model identifier. It can be omitted, for example after `/clear` or when a session is restored through conversation recovery, so check for the field before reading it                              |
| `agent_type`    | The agent name, present when you start Claude Code with `claude --agent <name>`                                                                                                                               |
| `session_title` | The current session title if one is already set, for example via `--name` or `/rename`. A hook that emits `sessionTitle` can check `session_title` first to avoid overwriting a title the user set explicitly |

When `source` is `"resume"` or `"fork"` and the transcript contains at least one response from Claude, SessionStart hooks also receive the four fields below. Your hook can use them to report what resuming a stale conversation costs before the first request, for example in a [`systemMessage`](#json-output). These fields require Claude Code v2.1.251 or later.

| Field                         | Description                                                                                                                                                                 |

### Setup

Fires only when you launch Claude Code with `--init-only`, or with `--init` or `--maintenance` in [non-interactive mode](/docs/en/headless) with the `-p` flag. It doesn't fire on normal startup. Use it for one-time dependency installation or scheduled cleanup that you trigger explicitly from CI or scripts, separate from normal session startup. For per-session initialization, use [SessionStart](#sessionstart) instead.

The matcher value corresponds to the CLI flag that triggered the hook:

| Matcher       | When it fires                              |
| :------------ | :----------------------------------------- |
| `init`        | `claude --init-only` or `claude -p --init` |
| `maintenance` | `claude -p --maintenance`                  |

When you run `claude --init-only`, Claude Code runs Setup hooks and `SessionStart` hooks with the `startup` matcher, then exits without starting a conversation.

When you start or continue a conversation with `-p`, you also need to supply a prompt, as an argument or piped on stdin. You can skip the prompt when a `SessionStart` hook supplies [`initialUserMessage`](#sessionstart-decision-control) or when you resume a session with a [deferred tool call](#defer-a-tool-call-for-later).

On success, `--init-only` prints nothing to the terminal. To confirm the hooks ran, start with `claude --debug-file <path> --init-only`, replacing `<path>` with a log file location, and check the log for the Setup and SessionStart hook entries.

Because Setup doesn't fire on every launch, a plugin that needs a dependency installed can't rely on Setup alone. The practical pattern is to check for the dependency on first use and install on miss, for example a hook or skill that tests for `${CLAUDE_PLUGIN_DATA}/node_modules` and runs `npm install` if absent. See the [persistent data directory](/docs/en/plugins-reference#persistent-data-directory) for where to store installed dependencies. If you distribute your plugin through a marketplace, you may not need this pattern: Claude Code [installs eligible Node.js package dependencies automatically](/docs/en/plugins-reference#node-js-package-dependencies) when it caches the plugin.

#### Setup input

In addition to the [common input fields](#common-input-fields), Setup hooks receive a `trigger` field set to either `"init"` or `"maintenance"`:

```json theme={null}
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../00893aaf-19fa-41d2-8238-13269b9b3ca0.jsonl",
  "cwd": "/Users/...",
  "hook_event_name": "Setup",
  "trigger": "init"
}
```

#### Setup decision control

Setup hooks can't block; execution continues on any exit code. On every exit code, Claude Code discards a Setup hook's [JSON output fields](#json-output), such as `systemMessage`, `continue`, and `hookSpecificOutput.additionalContext`. With `-p`, a Setup hook's stdout, stderr, and exit code appear in the run's output only as [`hook_response` events](/docs/en/headless#read-session-metadata) when you launch with `--output-format stream-json --verbose`.

Setup hooks have access to `CLAUDE_ENV_FILE`. Variables written to that file persist into subsequent Bash commands for the session, just as in [SessionStart hooks](#persist-environment-variables). Only `type: "command"` hooks run on `Setup`. A `type: "mcp_tool"` hook on `Setup` is always skipped, as described under [MCP tool hook fields](#mcp-tool-hook-fields).


## Prompt-based hooks

fin
