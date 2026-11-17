---
name: context-saver
description: Initialize Context Saver when the user explicitly attaches, invokes, or names the plugin, then continue handling the same request normally.
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
