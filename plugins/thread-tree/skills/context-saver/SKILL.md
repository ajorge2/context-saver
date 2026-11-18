---
name: context-saver
description: Activate Context Saver for the current chat or open its local viewer to browse saved project context.
---

# Context Saver invocation

When Context Saver is explicitly attached or invoked, call
`prepare_current_chat` before handling the user's message. Call it on every
explicit invocation; Context Saver checks its own persisted attached-chat list
and performs the full-history backfill only when that chat is absent.

After preparation, continue with the user's original request. Do not replace
the requested answer with an initialization report. Mention a preparation
failure only when it affects the requested result.

If the request needs historical project evidence, use
`search_project_history` after preparation. Otherwise, answer or perform the
request normally without forcing an unnecessary history search.

## Open the viewer

When the user asks to **Open Context Saver** or browse saved chats in the
viewer, complete the activation above and open the local viewer.

1. Check `http://127.0.0.1:8765/api/health` with a short timeout. A response with
   `ok: true` and `service: "thread-tree"` identifies a running Context Saver.
   Open its root URL in the browser and give the user that link.
2. Otherwise locate the installed package. The loaded skill file is
   `<package-root>/skills/context-saver/SKILL.md`. Use its actual path to find
   the package root and verify `scripts/thread_tree.py` exists there. When the
   host provides `CLAUDE_PLUGIN_ROOT`, use it if it contains that bundled
   script. The current project's directory can differ from the package root.
3. Run the following command with its working directory set to the verified
   package root. If port `8765` is occupied by a different service, replace
   `--port 8765` with `--port 0` so the operating system assigns a free port.
   Use a persistent terminal session and leave the server running.

   ```sh
   uv run --no-project --python 3.12 --with fastembed==0.9.1 --with usearch==2.26.6 python -X utf8 scripts/thread_tree.py serve --host 127.0.0.1 --port 8765 --open
   ```

4. The command prints the actual URL, including the port when one was
   assigned. Check that URL's `/api/health` for the same Context Saver
   identity and share the verified link. If the environment cannot open a
   browser automatically, the user can open the link directly. If launch
   fails, explain the error and give the user the command with the verified
   package path for a local terminal.
