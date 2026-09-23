---
title: Claude Platform release notes
url: https://platform.claude.com/docs/en/release-notes/overview
description: Updates to the Claude Platform, including the Claude API, client SDKs, and the Claude Console.
---

The Claude Platform release notes list changes to the Claude API, the client SDKs, and the Claude Console, newest first.

<Tip>
  For release notes on Claude Apps, see the [Release notes for Claude Apps in the Claude Help Center](https://support.claude.com/en/articles/12138966-release-notes).

  For updates to Claude Code, see the [complete CHANGELOG.md](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md) in the `claude-code` repository.
</Tip>

### September 22, 2026

* We've launched **Claude Opus 5.5** (`claude-opus-5-5`), a model for long-running agentic coding and knowledge work. It has a [1M token context window](https://platform.claude.com/docs/en/build-with-claude/context-windows) by default, 128k max output tokens, and always-on [adaptive thinking](https://platform.claude.com/docs/en/build-with-claude/thinking), at $4 / $20 USD per MTok (Claude Opus 5 is $5 / $25). Claude Opus 5.5 is available on the Claude API, [Claude in Amazon Bedrock](https://platform.claude.com/docs/en/build-with-claude/claude-in-amazon-bedrock), [Claude Platform on AWS](https://platform.claude.com/docs/en/build-with-claude/claude-platform-on-aws), [Claude on Google Cloud](https://platform.claude.com/docs/en/build-with-claude/claude-on-vertex-ai), and [Claude in Microsoft Foundry](https://platform.claude.com/docs/en/build-with-claude/claude-in-microsoft-foundry). See [What's new in Claude Opus 5.5](https://platform.claude.com/docs/en/models/opus-5-5/whats-new-opus-5-5) for capabilities, API changes, and migration guidance.
* On Claude Opus 5.5, thinking can't be disabled: `thinking: {"type": "disabled"}` and `thinking: {"type": "enabled", ...}` return a 400 error. Omit the `thinking` field and control thinking depth with the [effort parameter](https://platform.claude.com/docs/en/build-with-claude/effort). `tool_choice` types `any` and `tool` also return a 400 error, as on Claude Fable 5.1; use `auto` with [strict tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use). On the Claude API and Google Cloud, [computer use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool) on this model requires the `computer_toolset_20260801` toolset and the earlier `computer_20251124` tool returns a 400 error; on Amazon Bedrock, `computer_20251124` keeps working. See the [migration guide](https://platform.claude.com/docs/en/models/opus-5-5/migration-guide#migrating-from-claude-opus-5).

- [Fast mode](https://platform.claude.com/docs/en/build-with-claude/fast-mode) (research preview) is available for Claude Opus 5.5 on the Claude API.

* Tools can now be defined inside a [mid-conversation system message](https://platform.claude.com/docs/en/build-with-claude/mid-conversation-system-messages#define-tools-in-a-message-beta), in beta on the Claude API with the `inline-tools-2026-09-15` beta header. A `tool_addition` block can carry the tool's full definition (`tool: {"type": "tool_definition", "definition": {...}}`), so you can add a tool, change its schema, or move a server tool to a newer version without editing `tools` or invalidating the prompt cache. The same header covers adding and removing tools by reference. With the MCP connector's `mcp-client-2026-09-15` beta header as well, the definition can be an MCP toolset, and a response records each server's fetched tool list in an `mcp_tool_listing` block, which pins that list when you send it back.

### September 18, 2026

* The [Compliance API](https://platform.claude.com/docs/en/manage-claude/compliance-api) local session endpoints now also return transcripts of Claude in Chrome sessions (`product_surface` value `claude_in_chrome`), in beta for Claude Enterprise organizations, with your existing Compliance Access Key and the `read:compliance_user_data` scope. See [Sessions on users' machines](https://platform.claude.com/docs/en/manage-claude/compliance-sessions#retrieve-local-sessions).

### September 14, 2026

* The Messages API can now [compact a conversation on demand](https://platform.claude.com/docs/en/build-with-claude/compaction-on-demand) on the Claude API, in beta with the `compact-2026-09-04` beta header. Send the top-level `compaction` parameter, and the API returns a signed `compaction` block that summarizes the messages you sent. On later requests, send that block first, in place of those messages. You choose when to compact, the request can run in the background, and you can keep recent turns word for word after the summary. On models with preserved thinking, the thinking in those kept turns can stay valid.
* With the `thinking-binding-controls-2026-08-01` beta header, the `input_transformations` response field gains a second entry type, `thinking_mismatch_allowed`. It names a thinking block that failed the prefix check on a request where the API doesn't enforce that check: on Claude Fable 5.1, for example, a request from an account created before August 31, 2026, with `prefix_mismatch_behavior` unset. The block still reaches the model unchanged. Log these entries to find history edits in production traffic before you opt into enforcement. See [Set the mismatch behavior and read `input_transformations`](https://platform.claude.com/docs/en/build-with-claude/preserved-thinking#preserved-thinking-controls).
