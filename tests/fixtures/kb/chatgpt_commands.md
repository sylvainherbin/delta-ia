# ChatGPT desktop app commands

## Keyboard shortcuts

### Linux



| General | Shortcut |
| --- | --- |
| Open command menu | **Ctrl+Shift+P** or **Ctrl+K** |
| Open settings | **Ctrl+,** |
| Open keyboard shortcuts | **Ctrl+/** |

| Chats | Shortcut |
| --- | --- |
| New chat | **Ctrl+N** or **Ctrl+Shift+O** |
| New standalone chat (Codex only) | **Ctrl+Alt+O** |
| Quick chat (ChatGPT only) | **Ctrl+Alt+N** |

| Input and modes | Shortcut |
| --- | --- |
| Open model picker | **Ctrl+Shift+M** |
| Open project picker | **Ctrl+Alt+Shift+O** |
| Start voice chat (When voice chat is available) | **Ctrl+Shift+V** |

| Workspace and browser | Shortcut |
| --- | --- |
| Run environment action 1 (When the environment defines a primary action) | **Super+Shift+D** |
| Search files (Codex only) | **Ctrl+P** |
| Toggle file tree (Codex only) | **Ctrl+Shift+E** |
Shortcuts**.

You can search by command name or switch the search field into keystroke mode
and press the shortcut you want to find. Appshots use a separate global shortcut
under **Settings > Appshots**.

On Linux, experimental native Wayland can affect shortcut support. See the
[Linux desktop app guide](https://learn.chatgpt.com/docs/linux/linux-app#wayland-support).

<a id="search-past-tasks-and-find-in-a-task"></a>

## Deep links

### Supported links

Use these canonical forms when you create links. The sections below list the full reference by link type.

| Deep link                                                                   | Opens                                                   |
| --------------------------------------------------------------------------- | ------------------------------------------------------- |
| `codex://threads/new`                                                       | A new local chat.                                       |
| `codex://new?<query>`                                                       | A new local chat with at least one query parameter.     |
| `codex://threads/<thread-id>`                                               | A local chat. `<thread-id>` is its technical thread ID. |
| `codex://settings`                                                          | Settings.                                               |

<a id="tasks"></a>
