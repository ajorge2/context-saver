# Context Saver

Context Saver is a plugin for Codex and Claude Code on macOS, Linux, and Windows. Use the browser viewer to explore your saved chats, or ask your coding agent to recover an earlier decision with its source.

Successful activation confirms **“Context Saver is ON for this chat.”** You can check or change that connection at any time with the controls below.

In Codex, attach **Context Saver** and send **Open Context Saver**. In Claude Code, run `/thread-tree:context-saver Open Context Saver`.

## Turn it off or on

**Context Saver has an off switch for each chat.** In Codex, attach **Context Saver** and send **off** or **Context Saver off**. In Codex CLI, select Context Saver from the `$` skill menu and append `off`. In Claude Code, run `/thread-tree:context-saver off`.

The confirmation says **“Context Saver is OFF for this chat.”** New messages are not saved, and the agent cannot look up saved history in that chat. Existing saved context stays intact. Other chats keep their own settings.

Use **on** to reconnect or **status** to check the connection through the same control. Off persists across reopening and ordinary plugin invocations. On resumes from now without importing messages exchanged while off. Opening the viewer keeps an off chat off. The viewer’s **Disconnect** action removes saved context; the off command preserves it. Text already present in the agent’s active conversation remains there.

[Commands and control behavior](https://github.com/ajorge2/context-saver#turn-it-off-or-on)

## Saved context

The index is stored on the device. Lookup excerpts enter the configured coding agent session.

Topics use the existing local embeddings with direct UMAP + HDBSCAN grouping. USearch serves nearest-neighbor retrieval. [Server requirements](server/requirements.txt) pin the dependencies for both the installed plugin and manual launch commands.

Ask **Refresh Context Saver topics** to reorganize the current project's saved topics while preserving messages, embeddings, and connection settings. Refresh requires an active, selected project and runs only when requested. [Repair notes and limitations](../../docs/browse-hierarchy-repair.md)

[Install Context Saver](https://github.com/ajorge2/context-saver#install-on-macos) · [Turn it off or on](https://github.com/ajorge2/context-saver#turn-it-off-or-on) · [Open the viewer](https://github.com/ajorge2/context-saver#open-the-viewer) · [Refresh existing topics](https://github.com/ajorge2/context-saver#refresh-existing-topics)
