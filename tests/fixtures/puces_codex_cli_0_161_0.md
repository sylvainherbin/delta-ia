
## New Features

- GPT-6.1 Sol is now the default model in the bundled and Amazon Bedrock catalogs. (#49318, #49339)
- Amazon Bedrock supports multi-agent V2 and Ultra reasoning on compatible models; Bedrock Mantle also accepts AWS GovCloud regions. (#49345, #49813)
- Sign in to MCP servers from an active terminal session with `/mcp login <name>`. (#49290)

## Bug Fixes

- Approved filesystem escalation can now grant broader write access while preserving denied reads and network restrictions. Background tasks retain their originating turn’s permissions. (#49353, #49880)
- Explicit launch permissions survive terminal reconnects and new sessions, while implicit client settings no longer overwrite server or saved-thread web-search settings. (#49809, #49799)
- Elevated Windows terminal sessions can start using an embedded server, and sandboxed PowerShell preserves relative paths beneath protected user profiles. (#49855, #49690)

## Documentation

- Authentication guidance now accounts for keyring storage instead of implying credentials always reside in `auth.json`. (#49361)

## Chores

- Publishing an older alpha or hotfix no longer moves npm alpha tags backward. (#49704)

## Changelog

- #49246 Use executable fixture copying in the bundled bwrap test @felixxia-oai
- #49290 Add `/mcp login <name>` to the TUI @nicksteele-oai
- #49395 Remove randomized greetings from TUI session headers @etraut-openai
