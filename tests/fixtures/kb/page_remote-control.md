> ## Documentation Index
> Fetch the complete documentation index at: https://code.claude.com/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Continue local sessions from any device with Remote Control

> Continue a local Claude Code session from your phone, tablet, or any browser using Remote Control. Works with claude.ai/code and the Claude mobile app.

<Note>
  Remote Control is available on all plans. On Team and Enterprise, it is off by default until an Owner enables the Remote Control toggle in [Claude Code admin settings](https://claude.ai/admin-settings/claude-code).
</Note>

Remote Control connects [claude.ai/code](https://claude.ai/code) or the Claude app for [iOS](https://apps.apple.com/us/app/claude-by-anthropic/id6473753684) and [Android](https://play.google.com/store/apps/details?id=com.anthropic.claude) to a Claude Code session running on your machine. Start a task at your desk, then pick it up from your phone on the couch or a browser on another computer.

When you start a Remote Control session on your machine, Claude keeps running locally the entire time, so your code execution and filesystem access stay on your machine. With Remote Control you can:

* **Use your full local environment remotely**: your filesystem, [MCP servers](/docs/en/mcp), tools, and project configuration all stay available, and typing `@` autocompletes file paths from your local project.
* **Work from both surfaces at once**: the conversation and the progress of [subagents](/docs/en/sub-agents) and [dynamic workflows](/docs/en/workflows) stay in sync across all connected devices, so you can send messages from your terminal, browser, and phone interchangeably.
* **Send images and files from your phone or browser**: attach a photo or file in the Claude app or at claude.ai/code, with or without a caption. Claude sees attached photos directly as part of your message. Claude Code downloads other files to your machine and passes them to Claude as `@` file references.
* **Survive interruptions**: if your laptop sleeps or your network drops, Claude Code reconnects automatically when your machine comes back online. While the connection is rebuilding, Claude Code queues messages, permission prompts, and status updates from subagents and workflows, and delivers them once the connection recovers.

Unlike [cloud sessions](/docs/en/claude-code-on-the-web), which run on cloud infrastructure, Remote Control sessions run directly on your machine and interact with your local filesystem. The web and mobile interfaces are a window into that local session.

This page covers setup, how to start and connect to sessions, and how Remote Control compares to cloud sessions.

## Requirements

Before using Remote Control, confirm that your environment meets these conditions:

* **Subscription**: available on Pro, Max, Team, and Enterprise plans. API keys are not supported. On Team and Enterprise, an Owner must first enable the Remote Control toggle in [Claude Code admin settings](https://claude.ai/admin-settings/claude-code).
* **Authentication**: run `claude` and use `/login` to sign in through claude.ai if you haven't already. Without an eligible login, `claude remote-control` exits with an error, while `claude --remote-control` still starts an interactive session and shows a Remote Control failure notification shortly after launch.
* **API endpoint**: not available in any of these configurations:
  * You use Amazon Bedrock, Google Cloud's Agent Platform, or Microsoft Foundry.
  * You point [`ANTHROPIC_BASE_URL`](/docs/en/env-vars) at a host other than `api.anthropic.com`, such as an [LLM gateway](/docs/en/llm-gateway) or proxy. Unset the variable to use Remote Control. Before v2.1.196, Claude Code allowed Remote Control with a custom `ANTHROPIC_BASE_URL`.
  * You sign in through an enterprise [Claude apps gateway](/docs/en/claude-apps-gateway).
* **Feature-flag evaluation**: [`DISABLE_TELEMETRY`, `DO_NOT_TRACK`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`, and `DISABLE_GROWTHBOOK`](/docs/en/env-vars) each disable the feature-flag evaluation that Remote Control availability depends on. Unset the variable wherever it's set, in your shell environment or in the `env` block of a [`settings.json` file](/docs/en/settings-reference#all-settings), to use Remote Control.
* **Workspace trust**: run `claude` in your project directory at least once to accept the workspace trust dialog. The startup trust dialog never saves trust for your home directory, so start Remote Control from a project directory.

## Start a Remote Control session

You can start a Remote Control session from the CLI or the VS Code extension. The CLI offers three invocation modes; VS Code uses the `/remote-control` command.

<Tabs>
  <Tab title="Server mode">
    In your project directory, run:

    ```bash theme={null}
    claude remote-control
    ```

    Until you accept Remote Control's one-time confirmation, `claude remote-control` explains what it does and asks `Enable Remote Control? (y/n)` before starting the server. Answer `y` to accept and start the server. If you decline, Claude Code exits without starting the server and asks again the next time you run the command.

    The process stays running in your terminal in server mode, waiting for remote connections. It displays a session URL you can use to [connect from another device](#connect-from-another-device), and you can press spacebar to show a QR code for quick access from your phone. While a remote session is active, the terminal shows connection status and tool activity.

    Available flags:

    | Flag                                            | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
    | ----------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
    | `--name "My Project"`                           | Set a custom session title visible in the session list at claude.ai/code.                                                                                                                                                                                                                                                                                                                                                                                                          |
    | `--remote-control-session-name-prefix <prefix>` | Prefix for auto-generated session names when no explicit name is set. Defaults to your machine's hostname, producing names like `myhost-graceful-unicorn`. Set `CLAUDE_REMOTE_CONTROL_SESSION_NAME_PREFIX` for the same effect.                                                                                                                                                                                                                                                    |
