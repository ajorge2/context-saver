#!/usr/bin/env python3
"""Local stdio MCP server for the Thread Tree plugin."""

from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as error:  # pragma: no cover - exercised by clean-install checks
    raise SystemExit(
        "Context Saver's MCP server requires mcp==1.26.0. "
        "Install server/requirements.txt in the plugin runtime."
    ) from error

from thread_tree_tools import prepare_current_chat as prepare_chat
from thread_tree_tools import search_project_history as search_history


server = FastMCP(
    "thread-tree",
    instructions=(
        "When Context Saver is explicitly attached or invoked, call "
        "prepare_current_chat once before handling the user's request. The tool "
        "checks Context Saver's own attached-chat list and backfills only on the "
        "first invocation. Always continue with the original user request after "
        "preparation. "
        "Search project conversation history only when needed information is not "
        "explicitly stated in the active context. A familiar topic, vague summary, "
        "or confident inference is not answer-bearing evidence. Use one self-contained query per "
        "independent information need. The model—not this tool—judges whether returned "
        "chunks answer that need and makes a bounded follow-up with inspected chunk IDs "
        "excluded when they do not. Cite claims derived from returned chunks in plain "
        "text with each chunk's chat title and timestamp."
    ),
)


@server.tool()
def prepare_current_chat(
    project_root: str | None = None,
    thread_id: str | None = None,
) -> dict:
    """Prepare the chat when Context Saver is explicitly invoked.

    Call this once at the start of every explicit Context Saver invocation. The
    tool—not the model—checks whether the current chat already appears in
    Context Saver's persisted attached-chat list. On the first invocation it
    activates only this chat and synchronously indexes all completed earlier
    turns. Later calls return immediately. Regardless of status, continue with
    the user's original attached message after this call.

    Args:
        project_root: Optional current project root; normally inferred from the prompt hook.
        thread_id: Optional host session ID for adapters or tests that can provide it.
    """

    return prepare_chat(project_root=project_root, thread_id=thread_id)


@server.tool()
def search_project_history(
    query: str,
    evidence_needed: str | None = None,
    project_root: str | None = None,
    exclude_chunk_ids: list[str] | None = None,
    max_results: int = 8,
) -> dict:
    """Search earlier chats in the current project.

    Use this when completing the user's request requires a decision, fact,
    constraint, implementation detail, or discussion from earlier project
    conversations that is not explicitly answerable from the active context. The
    query must be a self-contained description of the missing information.
    Do not call this when explicit answer-bearing evidence is already present.
    Preserve the returned chunk IDs for any evidence you rely on. For each
    answer claim grounded in a returned chunk, append the plain-text
    compact `source.citation_label`, which contains a shortened chat title and
    timestamp. Do not hyperlink it, prefix it with `Source:`, or repeat it on
    adjacent claims from the same chunk. Include raw chunk IDs whenever the
    response requests provenance or evidence identifiers.

    Args:
        query: Self-contained description of the historical information needed.
        evidence_needed: Optional model-facing description of answer-bearing evidence.
        project_root: Current canonical project root. Required when multiple trees exist.
        exclude_chunk_ids: Evidence chunks the model already inspected in this reasoning path.
        max_results: Maximum evidence chunks to return, from 1 through 20.
    """

    return search_history(
        query,
        evidence_needed=evidence_needed,
        project_root=project_root,
        exclude_chunk_ids=exclude_chunk_ids or [],
        max_results=max_results,
    )


if __name__ == "__main__":
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    if transport == "--check":
        print("thread-tree MCP server ready")
        raise SystemExit(0)
    server.run(transport=transport)
