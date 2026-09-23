# Codex CLI

<ConfigTable client:load options={globalFlagOptions} />

<ConfigTable
  client:load
  options={commandOverview}
  secondColumnTitle="Maturity"
  secondColumnVariant="maturity"
/>

<ConfigTable client:load options={appServerOptions} />

<ConfigTable client:load options={appOptions} />

<ConfigTable client:load options={debugAppServerSendMessageV2Options} />

<ConfigTable client:load options={debugModelsOptions} />

<ConfigTable client:load options={debugPromptInputOptions} />

<ConfigTable client:load options={applyOptions} />

<ConfigTable client:load options={reviewOptions} />

<ConfigTable client:load options={archiveOptions} />

<ConfigTable client:load options={deleteOptions} />

<ConfigTable client:load options={cloudExecOptions} />

<ConfigTable client:load options={cloudListOptions} />

<ConfigTable client:load options={completionOptions} />

<ConfigTable client:load options={doctorOptions} />

<ConfigTable client:load options={featuresOptions} />

<ConfigTable client:load options={execOptions} />

<ConfigTable client:load options={execResumeOptions} />

<ConfigTable client:load options={execpolicyOptions} />

<ConfigTable client:load options={loginOptions} />

<ConfigTable client:load options={mcpCommands} />

<ConfigTable client:load options={mcpAddOptions} />

<ConfigTable client:load options={pluginCommands} />

<ConfigTable client:load options={marketplaceCommands} />

<ConfigTable client:load options={resumeOptions} />

<ConfigTable client:load options={forkOptions} />

<ConfigTable client:load options={sandboxMacOptions} />

<ConfigTable client:load options={sandboxLinuxOptions} />

<ConfigTable client:load options={sandboxWindowsOptions} />

## Interactive shortcuts

- Type `@` to search for a file in the workspace and add its path to the prompt.
- Press <kbd>Up</kbd> or <kbd>Down</kbd> to restore draft history.
- Press <kbd>Ctrl</kbd>+<kbd>R</kbd> to search prompt history, then press <kbd>Enter</kbd> to use a match or <kbd>Esc</kbd> to cancel.
- Press <kbd>Ctrl</kbd>+<kbd>O</kbd> or run `/copy` to copy the latest completed Codex output.
- Prefix a line with `!` to run a local shell command under the current approval and sandbox settings.
- Press <kbd>Tab</kbd> while Codex is working to queue a follow-up prompt, slash command, or shell command for the next turn.
- Press <kbd>Enter</kbd> while Codex is working to inject new instructions into the current turn.
- Press <kbd>Esc</kbd> twice with an empty composer to edit the previous user message and fork the chat from that point.
- Press <kbd>Ctrl</kbd>+<kbd>C</kbd> or run `/exit` to close the session.

