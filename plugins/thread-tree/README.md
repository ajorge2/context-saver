# Context Saver

Context Saver is a plugin for Codex and Claude Code on macOS, Linux, and Windows. Use the browser viewer to explore your saved chats, or ask your coding agent to recover an earlier decision with its source.

In Codex, attach **Context Saver** and send **Open Context Saver**. In Claude Code, run `/thread-tree:context-saver Open Context Saver`.

The index is stored on the device. Lookup excerpts enter the configured coding agent session.

Topics use the existing local embeddings with direct UMAP + HDBSCAN grouping. USearch serves nearest-neighbor retrieval. [Server requirements](server/requirements.txt) pin the dependencies for both the installed plugin and manual launch commands.

Ask **Refresh Context Saver topics** to reorganize the current project's saved topics while preserving messages, embeddings, and connection settings. Refresh requires an active, selected project and runs only when requested. [Repair notes and limitations](../../docs/browse-hierarchy-repair.md)

[Install Context Saver](https://github.com/ajorge2/context-saver#install-on-macos) · [Open the viewer](https://github.com/ajorge2/context-saver#open-the-viewer) · [Refresh existing topics](https://github.com/ajorge2/context-saver#refresh-existing-topics)
