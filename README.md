# Context Saver

Context Saver is a **Codex and Claude Code plugin for macOS** with a browser viewer for your saved project chats. Search your conversations, browse from subjects down to individual messages, and choose which chats stay connected. Your coding agent can also recover earlier decisions and cite the original messages.

[Install the plugin](#install-on-macos) · [Open the viewer](#open-the-viewer)

## Install on macOS

You’ll need Python 3.12 and `uv` available to your coding client. [Install Python](https://www.python.org/downloads/macos/) · [Install uv](https://docs.astral.sh/uv/getting-started/installation/)

Copy the command for your client into Terminal.

### Codex

```sh
codex plugin marketplace add ajorge2/context-saver && codex plugin add thread-tree@context-saver
```

Review the Context Saver hooks in **Settings → Hooks** in the desktop app or with `/hooks` in the terminal UI. Start a new chat and attach **Context Saver** to begin saving that chat.

### Claude Code

```sh
claude plugin install thread-tree --marketplace ajorge2/context-saver
```

Start a new Claude Code session in your project and run `/thread-tree:context-saver` to begin saving that chat.

## Open the viewer

- **Codex** — Attach **Context Saver** to a chat and send **Open Context Saver**.
- **Claude Code** — Run `/thread-tree:context-saver Open Context Saver` in your project.

The viewer opens in your browser. Select a project to browse its subjects, broad topics, specific topics, and messages, or enter a search. Click a card to inspect the source material. Use **Connections** to pause a chat or remove its saved context.

![Context Saver viewer showing a grid of specific topics from a sample project](docs/viewer.png)

<details>
<summary>Open the viewer from Terminal</summary>

```sh
git clone https://github.com/ajorge2/context-saver.git
cd context-saver
uv run --no-project --python 3.12 \
  --with fastembed==0.9.1 --with usearch==2.26.6 \
  python plugins/thread-tree/scripts/thread_tree.py serve --port 0 --open
```

Keep this Terminal window open while you use the viewer.

</details>

## Ask for an earlier decision

Once a connected chat has some history, ask the agent a question like **“What condition did we agree on for retrying the deployment?”** Context Saver gives it relevant excerpts and their sources when the current conversation lacks that detail.

## Where your data goes

The index and embedding model run locally. When the agent requests saved context, matching excerpts enter that coding host’s session and are handled according to its data settings.

## License

The release grants permission to install and run Context Saver. [Context Saver license](LICENSE) · [Bundled component notices](plugins/thread-tree/THIRD_PARTY_NOTICES.md)
