# Context Saver

Context Saver is a plugin for **Codex and Claude Code on macOS**. It helps your coding agent recover decisions from connected chats and cite the original messages.

## Install on macOS

You’ll need [Python 3.12](https://www.python.org/downloads/macos/) and [uv](https://docs.astral.sh/uv/getting-started/installation/) on your coding client’s PATH. Copy the command for your client into Terminal.

### Codex

```sh
codex plugin marketplace add ajorge2/context-saver && codex plugin add thread-tree@context-saver
```

Review the Context Saver hooks in **Settings → Hooks** in the desktop app or with `/hooks` in the terminal UI. Start a new chat and attach **Context Saver** to begin saving that chat.

### Claude Code

```sh
claude plugin marketplace add ajorge2/context-saver && claude plugin install thread-tree@context-saver
```

Start a new Claude Code session in your project and run `/thread-tree:context-saver` to begin saving that chat.

## Ask for an earlier decision

Once a connected chat has some history, ask the agent a question like **“What condition did we agree on for retrying the deployment?”** Context Saver gives it relevant excerpts and their sources when the current conversation lacks that detail.

## Browse your saved context

Clone this repository and run this from its root to open the viewer.

```sh
uv run --no-project --python 3.12 \
  --with fastembed==0.9.1 --with usearch==2.26.6 \
  python plugins/thread-tree/scripts/thread_tree.py serve --open
```

Select a project to browse its topics and messages. Use **Connections** to pause a chat or remove its saved context.

## Where your data goes

The index and embedding model run locally. When the agent requests saved context, matching excerpts enter that coding host’s session and are handled according to its data settings.

## License

The release grants permission to install and run Context Saver. [Context Saver license](LICENSE) · [Bundled component notices](plugins/thread-tree/THIRD_PARTY_NOTICES.md)
