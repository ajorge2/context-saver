# Browsing and topic refresh

This follow-up makes older saved evidence reachable through message paging and preserves its topic ancestry across ingestion and later fits. Existing topic trees can be refreshed explicitly with the current local clustering runtime.

## Browse the selected history

Blank-query browsing now pages through all eligible indexed chunks. The server returns 36 by default, accepts up to 100 per request, and reports the total and whether another page exists. Topic filters intersect, and an older selected message stays available only while it remains in scope. The full topic hierarchy stays available while message pages change. Search keeps its existing 80-result default.

Each request counts eligible evidence and fetches its page within one SQLite snapshot. Excluded, disconnected, and evicted evidence stays excluded; staged prompts are not browse results. Browsing and search do not write queries or trigger a topic rebuild. [Pagination regressions](../tests/test_explorer_pagination.py)

Message cards represent indexed chunks, so one long source message can produce several cards. Separate page requests are not a frozen export: concurrent additions or deletions can change offsets. A stale offset is clamped to available evidence.

## Preserve the hierarchy

Fits execute from spans to specific topics to broad topics, including retries of older queued work. Upper fits combine retained live children with current replacements. An accepted assignment to an existing span writes membership through its valid primary ancestors in the ingestion transaction.

Publication preserves newer accepted assignments across an older fit watermark and follows replacement child identities when a span splits. A writer lock protects that publication boundary. If a prototype disappears or becomes invalid, its newer evidence remains searchable and returns to the unclustered frontier with fit debt.

Structural singleton parents keep valid children connected when an upper merge is unsupported or below its fit threshold. They remain unlocked and carry zero clustering persistence. Explicit full refreshes replace old upper nodes even when density produces no groups; unsupported old ancestry cannot survive solely through raw chunk overlap. [Hierarchy regressions](../tests/test_hierarchy_coverage.py)

## Local clustering

Embedded evidence uses UMAP followed by HDBSCAN directly, reusing the stored local vectors. BERTopic is no longer required. USearch provides retrieval indexing rather than topic grouping. The pinned runtime is Python 3.12, FastEmbed 0.9.1, USearch 2.26.6, umap-learn 0.5.12, and hdbscan 0.8.44. [Requirements](../plugins/thread-tree/server/requirements.txt)

The `density-sqrt-v1` policy scales minimum support with the square root of the current layer's input size. It does not require a target topic count. Exact directional duplicates and two-direction geometry have explicit handling; insufficient evidence can remain noise. Entirely unembedded input retains a bounded lexical mode. Incomplete embeddings and semantic-runtime failures surface as errors while the previously published tree stays intact.

The [recorded synthetic experiments](density-clustering-experiments.json) reuse one production UMAP projection per fixture when comparing policies. The selected policy recovered the authored equal and unequal families in those fixtures. Its limitations remain visible: one outlier can fragment a cohesive family, diffuse vectors can still form density groups, and smaller minority families can be omitted or merged. Density, persistence, membership strength, and readable labels do not prove semantic correctness or establish quality on a private corpus.

## Readable names without another model

Names use short phrases supported across the whole cluster, discounted against the other evidence in the same fit layer. This favors a shared subject over the first message or a repeated instruction. Role markers, code fences, generic conversational wording, overlapping fragments, and incomplete trailing verbs are excluded. The fit extracts each row once for its shared background and once for its group; naming does not make model calls or generate new embeddings.

A prohibition cannot become an affirmative action label. Negated clauses are excluded while independent topic statements remain available. If no sufficiently specific phrase survives, the label stays neutral. A structural parent containing one child preserves its useful name. These are deterministic phrase heuristics, not generated semantic summaries; exact source messages remain available in the metadata dialog. [Naming regressions](../tests/test_cluster_labels.py)

When a connection permits only selected chats, a stored topic name can contain words from an excluded chat. The presentation layer instead names each topic from all permitted member previews, sharing one lazy background and deduplicating identical member sets across layers. A bounded 256-entry cache stores only titles and fingerprint keys; scope, preview or membership changes invalidate reuse. Later message pages do not repeat phrase extraction. The scoped API regressions check cards, metadata relations and tree responses, hidden-name sentinels, invalidation, bounded cache size and extraction counts over 10,000 synthetic rows. [Scoped-name regressions](../tests/test_visible_cluster_labels.py)

## Refresh one existing project

Attach Context Saver and ask **Refresh Context Saver topics**. Preparation runs first, then the verified installed package refreshes the requested project. For a repository checkout, run from its root:

```sh
uv run --no-project --python 3.12 --with-requirements plugins/thread-tree/server/requirements.txt python -X utf8 plugins/thread-tree/scripts/thread_tree.py refresh-topics --project '<project-folder>' --json
```

This rebuild changes derived topic organization while preserving canonical messages, stored vectors, the retrieval index, and chat consent. It refuses missing, unselected, paused, or pending connections and retained live chats outside the selected scope. Consent checks are brief and repeat before counts are reported. JSON contains project metadata, fit state, operation identity, and counts without message text.

Pass the returned `--operation-id` to retry the same refresh; omit it for a fresh operation. An upgrade or viewer request does not eagerly rebuild every project. Normal ingestion still schedules fits as debt reaches its thresholds. A refresh can change labels, counts, and grouping, and can leave evidence unclustered. [Refresh-command regressions](../tests/test_topic_refresh.py)

## Verification scope

Focused local runs passed the pagination, hierarchy, refresh-command, state, pipeline, and crash-recovery regressions. Their fixtures use disposable synthetic indexes. They cover more than 100 eligible rows, full paging reachability, scope exclusions, atomic rollback, ingestion replay, concurrent publication, split ancestry, and preservation of messages and vectors. Browser regressions cover paging, filters, selected anchors, late responses, retries, and deletion clamps. [Browser scenarios](../tests/browser/viewer-real-server.spec.js) · [Race scenarios](../tests/browser/viewer-resilience.spec.js)

The density experiment report records synthetic policy evidence and its runtime; its machine-specific timing observations are not general performance claims. The [native-platform validation page](platform-validation.md) records the earlier release matrix. These focused checks do not replace a new installed-host and platform run for the updated runtime, or a review of refreshed topic quality.
