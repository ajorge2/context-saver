# Project defaults and messages-only navigation

The viewer opens with useful context already selected. It follows the project's last accepted Context Saver tool use, while keeping a person's current browsing choice stable during a connection refresh.

## Choose a project automatically

- A fresh viewer load selects the most recently invoked available project. An accepted `prepare_current_chat` or `search_project_history` call records the project's invocation time. Transcript ingestion, fitting, UI searches and manual project selection do not promote it.
- Invocation time is captured when the tool call starts and merged monotonically, so an older backfill finishing later cannot outrank a newer invocation. Existing activation timestamps contribute to the effective order; projects without a usage timestamp have a stable ID tie-break.
- Exactly one project is selected whenever the available list is nonempty. Clicking the selected option keeps it selected; the project selector has no clear-to-empty action.
- A list refresh retains the current selection while it remains available. If it disappears, selection falls back to the first remaining project in the recency order, then the next as necessary. This uses the scoped available-project list; it does not reconnect sources or delete retained history.
- An empty list displays **No connected projects**. A failed or malformed project response displays **Projects unavailable**, rather than presenting a network failure as an empty history. Superseded list responses cannot restore an outdated selection.

The usage stamp is project metadata, not a new saved message or a record of the search phrase. [Backend recency regressions](../tests/test_project_recency.py) · [Project-selection browser scenarios](../tests/browser/viewer-project-default.spec.js)

## Switch between five slides and two

Normal context mode has five slides:

`Welcome / search → Subjects → Broad Topics → Specific Topics → Specific Messages`

Selecting the **M** messages-only toggle leaves exactly two:

`Welcome / search ↔ Specific Messages`

The three semantic slides and their navigation dots become hidden and inert. The search slide's down arrow goes directly to Specific Messages, and that slide's up arrow returns directly to search. Hidden slides cannot remain an arrow or programmatic navigation target. Track height, progress and active navigation follow the visible sequence. A mode change cancels an in-flight smooth scroll before its old target can become hidden or move. It also reconciles alignment on the next visual frame: a native compositor can deliver one last scroll delta after the immediate layout change. A navigation epoch prevents that deferred correction from overriding a newer button action.

Entering messages-only mode clears Subject, Broad Topic and Specific Topic filters so invisible constraints cannot silently restrict the messages. The submitted query, an unsent draft and any selected message remain intact. Browse mode refreshes its message page if clearing a topic filter broadens the branch. Switching back restores the five-slide sequence with those topic filters still cleared.

The toggle does not submit a draft. Hover previews its placeholder only; activation changes the route. Search still uses the same transient canonical-message retrieval and does not store the query in the index. Messages retain their card selection, pagination and source-detail controls.

## Keep navigation predictable

Pending search keeps its loader and navigation guards when the mode changes. Manual page scrolling stays blocked outside internal scrollable controls; keyboard-activated buttons remain usable. Normal transitions use the existing fade and scroll animation, while reduced-motion transitions are immediate. Reload returns to Welcome and the normal five-slide context mode, then selects the most recently used available project.

[Messages-only browser scenarios](../tests/browser/viewer-messages-mode.spec.js) cover both route sequences, hidden focus/target rejection, filter clearing, draft/query/message preservation, loading, reload and interrupted smooth scrolling. These targeted scenarios describe the new contracts; the release validation record separately reports completed full-suite and native-platform runs.

## Completed validation

The final application passed 264 Python methods, five Node checks and 49 Chromium scenarios per platform on macOS, Linux and Windows. Linux and macOS skip two Windows-only methods. Installed-host and trust checks also passed, with a diagnostic-only Windows follow-up completing the previously cancelled startup probe. [Exact runs and scopes](platform-validation.md#version-0122--project-defaults-and-messages-only-navigation)

The final local combined run also passed 267 Python methods (two Windows-only skips), including the added failure-diagnostic cases.
