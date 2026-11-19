---
name: context-saver
description: Activate Context Saver, open its viewer, or explicitly refresh saved project topics.
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
   uv run --no-project --python 3.12 --with fastembed==0.9.1 --with usearch==2.26.6 --with umap-learn==0.5.12 --with hdbscan==0.8.44 python -X utf8 scripts/thread_tree.py serve --host 127.0.0.1 --port 8765 --open
   ```

4. The command prints the actual URL, including the port when one was
   assigned. Check that URL's `/api/health` for the same Context Saver
   identity and share the verified link. If the environment cannot open a
   browser automatically, the user can open the link directly. If launch
   fails, explain the error and give the user the command with the verified
   package path for a local terminal.

## Refresh existing topics

When the user asks to **Refresh Context Saver topics**, perform the preparation
above, then refresh the requested project's existing topic hierarchy. This is
an explicit maintenance action; opening the viewer or installing an upgrade
does not authorize a refresh.

1. Locate the installed package from this skill's actual path and verify
   `scripts/thread_tree.py` and `server/requirements.txt` exist, as described
   above. Resolve the requested project path; use the current project when
   the user has not named another project.
2. Run this command from the verified package root, replacing the example
   project path with the resolved path:

   ```sh
   uv run --no-project --python 3.12 --with-requirements server/requirements.txt python -X utf8 scripts/thread_tree.py refresh-topics --project '/absolute/project/path' --json
   ```

   The requirements pin the same local embedding, UMAP, and HDBSCAN runtime
   as the server. To retry the same operation, pass the returned
   `--operation-id`; omit it for a fresh refresh.
3. Report the returned fit state and topic/message counts. The command changes
   derived topics while preserving saved messages, vectors, and chat consent.
   If it reports paused, unselected, or pending connections, explain the
   reported condition without changing connection settings automatically.
   Refresh only the requested project; do not refresh every indexed project
   during an upgrade.
