---
name: context-saver
description: Turn Context Saver off or on for this chat, check its connection, open its viewer, or explicitly refresh saved project topics.
---

# Context Saver invocation

## Handle off, on and status before preparation

When the user directs Context Saver to turn **off**, turn **on**, or report its
**status**, call `control_current_chat` with that action **before** any
preparation or history lookup. This includes a standalone `off`, `on` or
`status` argument to this skill and requests such as “Context Saver off.”
Ordinary occurrences of these words in quoted text or another task are not
control requests.

- **off** disconnects only this chat, preserves saved context and prevents new
  capture and history lookup here until an explicit **on**.
- **on** explicitly reconnects this chat and resumes from now. It does not
  import messages exchanged while off. The control tool handles preparation;
  do not prepare a second time.
- **status** reports the connection without activating the chat.

Use the current canonical project and exact current host chat identity. Codex
normally supplies `CODEX_THREAD_ID` or `CODEX_SESSION_ID` to the tool. Claude
Code supplies this skill's session identifier as `${CLAUDE_SESSION_ID}`; pass it
as `thread_id` only when the host has expanded it to a real identifier. Never
pass an unexpanded placeholder, invent an ID, or choose another recently
active chat. If the tool cannot identify the current chat, explain that no
connection change was confirmed and follow its actionable message.

If an already-open host session has not loaded `control_current_chat` yet,
use the installed package's command rather than asking the user to edit
settings. Locate the package from this skill's actual file path (or a verified
`CLAUDE_PLUGIN_ROOT`) and confirm `scripts/thread_tree.py` and
`server/requirements.txt` exist. Run from that package root, substituting the
requested action, current canonical project and exact trusted host chat ID:

```sh
uv run --no-project --python 3.12 --with-requirements server/requirements.txt python -X utf8 scripts/thread_tree.py off --project '/absolute/project/path' --thread-id 'exact-current-chat-id' --json
```

Replace `off` with `on` or `status` for the other controls. Parse the returned JSON and use
its result exactly as the MCP result. Pass the actual user project explicitly,
since the package working directory is different. If the exact current chat ID
is unavailable, explain that the connection could not be changed and ask the
user to reopen the chat with Context Saver attached so the host can identify
it. Never fall back to another chat or report an unverified change.

Report the tool's returned `message`. A successful off response must clearly
say **“Context Saver is OFF for this chat.”** Do not claim success when `ok`
is false or the state is unavailable. After **off** or **status**, do not call
`prepare_current_chat` or `search_project_history`. If the user also requested
other work, continue that work while respecting the returned connection state.
An off command does not uninstall the plugin or erase text already in the
coding agent's active conversation.

## Ordinary invocation

For other explicit attachments or invocations, call `prepare_current_chat`
before handling the user's message. Context Saver checks its own persisted
attached-chat list and performs the full-history backfill only when that chat
is absent. Preparation respects an explicit off state: it cannot reconnect
that chat. If the tool reports off or paused, continue the user's request
without a history lookup and explain how to reconnect when relevant.

After preparation, continue with the user's original request. Do not replace
the requested answer with an initialization report. When an explicit
attachment or activation returns `ready`, briefly confirm **“Context Saver is
ON for this chat.”** Then continue the requested work. Confirm ON only after
the tool succeeds; an attached plugin alone is not evidence of connection.
Mention a preparation failure only when it affects the requested result.

If the request needs historical project evidence, use
`search_project_history` after preparation. Otherwise, answer or perform the
request normally without forcing an unnecessary history search.
For lookup, pass the exact current `thread_id` when the MCP process lacks a host
identity; Claude Code provides the expanded `${CLAUDE_SESSION_ID}`. Never
bypass an off or identity-unavailable response with an anonymous retry.

## Open the viewer

When the user asks to **Open Context Saver** or browse saved chats in the
viewer, follow the ordinary-invocation check above and open the local viewer.
An off chat may open the viewer without reconnecting; never issue an implicit
**on** command to open it.

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
