# A publish timed out after issuing a receipt

Context Saver is a plugin that lets a coding agent search earlier project chats. This experiment compares answers about earlier project decisions with and without that search after the chats were compacted. Compaction is the coding assistant’s reduction of older conversation context to fit its working context.

[Results overview](../results.md) · [Complete authored chat](../chats/ambiguous-commit.md) · [All retained answer data](../../data/records.json)

This is one synthetic incident in a fictional software release controller. Each answer below came from the same final question at the indicated history checkpoint. Compaction is the coding assistant's reduction of older chat context to fit its working context.

The six operational fields test the action, target, ordered steps, prerequisites, affected scope, and authoritative source. The current branch and an unrecorded ticket ID are two separate controls; they are excluded from the headline denominator.

`PASS` and `FAIL` below reproduce the published blinded AI semantic grader's boolean judgments. They are not new judgments by this analysis script. Reviewer rationales were not archived; compare the preserved wording with the frozen rubric yourself. Each incident had one of two reviewers, not two independent grades.

The original archive retains parsed field strings and readable citations, not a byte-for-byte full JSON response envelope. Field text inside each text block is preserved unchanged. Citation labels are original strings; synthetic chunk IDs and native session IDs were removed.

## Compare the seven answers

| Checkpoint and plugin state | Operational fields correct | Controls correct |
|---|---:|---:|
| [Before compaction · Context Saver off](#r0_off) | 6/6 | 2/2 |
| [Before compaction · Context Saver on](#r0_on) | 6/6 | 2/2 |
| [After one compaction · Context Saver off](#r1_off) | 1/6 | 2/2 |
| [After one compaction · Context Saver on](#r1_on) | 6/6 | 2/2 |
| [After three compactions · Context Saver off](#r3_off) | 1/6 | 2/2 |
| [After three compactions · Context Saver on](#r3_on) | 5/6 | 2/2 |
| [Same intervening work, never compacted · off](#long_off) | 5/6 | 2/2 |

## Final question

```text
Can you take another pass at the publish fix? We got the timeout again just as the old worker disappeared. The channel query says nothing changed, but its replica is behind and the UI is already offering Retry. I want the smallest safe change, including the branch where the original operation actually did get through. Someone pasted the Ready-and-retry runbook into the issue.

For Cedar release epoch 28, request publish-cedar-28-04 moved to CommitPending at 09:11:51 UTC. Worker lease epoch 9 ended at 09:12:00, after the writer started the operation but before the caller saw an acknowledgement. At 09:12:04 a replica at projection epoch 27 returned empty. At 09:12:06 the channel head advanced for partner Alder. The replacement UI generated a fresh idempotency key. We can still contact the coordinator, but its first lookup can itself time out.

I’m on branch fix/ambiguous-commit; keep the regression notes tied to that working branch. Compliance asked me for the external incident-approval ticket ID as well, if we ever wrote one down.

Use the earlier Meridian decisions that apply to this timeline. The controller needs a concrete action, and the regression should check whether misleading states could trigger the wrong outcome. If the active context lacks an applicable decision, you may use the available read-only project history search, including parallel lookups for independent facts. Never use files, web, shell or other tools. Prefer the newest approved rule when a rehearsal proposal contradicts it.

Return one JSON object with `answers` and `citations`. Answer each listed field with a short string. Use `UNKNOWN` when the record does not establish the answer. Where requested, join action names with ` > `. For a field supported by retrieved history, place that tool’s verified readable source citation label in an array under the same key in `citations`. Leave citations empty for direct conversation answers. Include the requested fields only.

- `disposition` — Immediate transition.
- `target` — Receipt lookup key.
- `operations` — Three operations in order; final step is conditional, joined with >.
- `gate` — Action when matching committed receipt exists.
- `scope` — Scope fenced by hold.
- `authority` — Authoritative publication source.
- `recent` — Current working branch for the handoff.
- `unsupported` — External incident-approval ticket ID, or UNKNOWN if it was never recorded.
```

## Frozen scoring rules

These rules and their approved source excerpts were fixed before the answers were collected. Accepted aliases supported the initial exact-text scorer; the later semantic review allowed equivalent wording and required every material clause. Historical machine-exact results are retained separately for diagnosing the first scorer.

### `disposition` — Immediate transition

**Approved source excerpt(s):**

```text
A write timeout in CommitPending with conflicting visibility is an ambiguous commit. Put the release in reconciliation hold and never infer failure from an empty replica read.
```

**Frozen accepted aliases:**

- reconciliation hold
- reconcile in hold
- hold for reconciliation
- enter reconciliation hold

**Explicitly harmful alternatives specified in the original rubric:**

- republish immediately
- reset to ready and retry
- retry publish

### `target` — Receipt lookup key

**Approved source excerpt(s):**

```text
Query the coordinator by the original publish operation ID, with the epoch pinned to the in-flight release. The moving channel head and the replacement request ID are wrong keys.
```

**Frozen accepted aliases:**

- original publish operation ID and release epoch
- original operation ID and pinned release epoch
- original publish operation ID with pinned release epoch
- original operation ID and release epoch

**Explicitly harmful alternatives specified in the original rubric:**

- replacement request ID
- channel head

### `operations` — Three operations in order; final step is conditional, joined with >

**Approved source excerpt(s):**

```text
Fence the current worker first, fetch the fresh coordinator receipt second, and republish last only if that receipt authoritatively says no commit exists.
```

**Frozen accepted aliases:**

- fence worker > fetch fresh coordinator receipt > conditionally republish
- fence current worker > fetch fresh coordinator receipt > republish only if no commit
- fence the worker > lookup coordinator receipt > republish only if no commit
- fence current worker > fetch fresh coordinator receipt > conditionally republish

### `gate` — Action when matching committed receipt exists

**Approved source excerpt(s):**

```text
If a matching committed receipt exists, adopt that receipt and skip republish. If the authoritative lookup remains unknown, keep the hold.
```

**Frozen accepted aliases:**

- adopt receipt and skip republish
- adopt the receipt and skip republish
- adopt the committed receipt; do not republish
- adopt matching receipt and skip republish
- adopt receipt; skip republish

**Explicitly harmful alternatives specified in the original rubric:**

- republish

### `scope` — Scope fenced by hold

**Approved source excerpt(s):**

```text
A hold fences writes for that tenant and release epoch. It does not stop other tenants or their read traffic.
```

**Frozen accepted aliases:**

- writes for this tenant and release epoch
- writes for the affected tenant and release epoch
- tenant and release epoch writes
- this tenant and release epoch writes

**Explicitly harmful alternatives specified in the original rubric:**

- all tenant reads and writes
- all tenants

### `authority` — Authoritative publication source

**Approved source excerpt(s):**

```text
The commit receipt ledger is the source of truth for publication, ahead of the channel projection or the timer log.
```

**Frozen accepted aliases:**

- commit receipt ledger
- coordinator commit receipt ledger
- coordinator receipt ledger

**Explicitly harmful alternatives specified in the original rubric:**

- channel projection
- timer log
- empty replica read

### `recent` — Current working branch for the handoff

**Approved source excerpt(s):**

```text
I’m on branch fix/ambiguous-commit; keep the regression notes tied to that working branch.
```

**Frozen accepted aliases:**

- fix/ambiguous-commit

### `unsupported` — External incident-approval ticket ID, or UNKNOWN if it was never recorded

**Approved source excerpt(s):**

None: this is the control for a fact never recorded in the chat.

**Frozen accepted aliases:**

- UNKNOWN

<a id="r0_off"></a>

## Before compaction · Context Saver off

Record: `ambiguous-commit--r0_off`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **8.839 s**; model input: **8,811** tokens (including **8,064** cached input); output: **200** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Move Cedar release epoch 28 to reconciliation hold.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Original operation ID publish-cedar-28-04, pinned to release epoch 28.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Fence the current worker > Fetch a fresh coordinator receipt > Republish only if the receipt authoritatively says no commit exists
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Adopt the matching committed receipt and skip republish; if lookup is unknown, keep the hold.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Writes for Cedar release epoch 28 only.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
Coordinator commit receipt ledger.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/ambiguous-commit
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Unrecorded ticket ID (control) — PASS

```text
UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

<a id="r0_on"></a>

## Before compaction · Context Saver on

Record: `ambiguous-commit--r0_on`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **6.551 s**; model input: **9,591** tokens (including **5,376** cached input); output: **146** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Move Cedar release epoch 28 to reconciliation hold.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Original operation ID publish-cedar-28-04, pinned to release epoch 28.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Fence the current worker > Query the coordinator receipt > Republish only if the receipt authoritatively confirms no commit.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Adopt the matching committed receipt; do not republish.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Writes for Cedar release epoch 28 only; other tenants and read traffic continue.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
Commit receipt ledger.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/ambiguous-commit
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Unrecorded ticket ID (control) — PASS

```text
UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

<a id="r1_off"></a>

## After one compaction · Context Saver off

Record: `ambiguous-commit--r1_off`. Operational score: **1/6**. Controls: **2/2**.

Observed fork-and-answer time: **10.099 s**; model input: **8,717** tokens (including **4,608** cached input); output: **368** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — FAIL

```text
Keep CommitPending; disable Retry while the commit is unresolved.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — FAIL

```text
Original request publish-cedar-28-04, not the replacement UI key.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — FAIL

```text
Hold retry > Query the coordinator for the original receipt > Retry only if the coordinator authoritatively confirms no commit
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Treat a matching committed receipt as published; do not replay.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — FAIL

```text
UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `false_abstention`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — FAIL

```text
UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `false_abstention`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/ambiguous-commit
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Unrecorded ticket ID (control) — PASS

```text
UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

<a id="r1_on"></a>

## After one compaction · Context Saver on

Record: `ambiguous-commit--r1_on`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **32.085 s**; model input: **76,657** tokens (including **57,856** cached input); output: **715** tokens; model requests: **5**; completed history searches: **4**.

### Action to take — PASS

```text
Move Cedar epoch 28 from CommitPending to reconciliation hold; do not reset to Ready.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Original publish operation ID publish-cedar-28-04, pinned to Cedar release epoch 28.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Fence the worker > Fetch a fresh coordinator receipt > Republish only if the receipt authoritatively confirms no commit
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Adopt the matching committed receipt and skip republish; if lookup times out, keep the hold.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Writes for Cedar release epoch 28 only; other tenants and read traffic continue.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
Coordinator commit receipt ledger, not the lagging projection, channel head, UI, or logs.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/ambiguous-commit
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Unrecorded ticket ID (control) — PASS

```text
UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

<a id="r3_off"></a>

## After three compactions · Context Saver off

Record: `ambiguous-commit--r3_off`. Operational score: **1/6**. Controls: **2/2**.

Observed fork-and-answer time: **7.437 s**; model input: **9,089** tokens (including **4,608** cached input); output: **335** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — FAIL

```text
Keep CommitPending; enter reconciliation, not Ready-and-retry.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — FAIL

```text
Original request publish-cedar-28-04, not the replacement UI key.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — FAIL

```text
Hold conflicting writes > query the coordinator for the original receipt > retry only after an authoritative no-commit result
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Treat a matching committed receipt as published; do not retry.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — FAIL

```text
Cedar release epoch 28 and writes that could conflict with its publication.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — FAIL

```text
The coordinator’s committed receipt, not the lagging projection or UI.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/ambiguous-commit
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Unrecorded ticket ID (control) — PASS

```text
UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

<a id="r3_on"></a>

## After three compactions · Context Saver on

Record: `ambiguous-commit--r3_on`. Operational score: **5/6**. Controls: **2/2**.

Observed fork-and-answer time: **25.006 s**; model input: **81,262** tokens (including **44,032** cached input); output: **831** tokens; model requests: **5**; completed history searches: **6**.

### Action to take — FAIL

```text
Keep Cedar epoch 28 in CommitPending and enter reconciliation hold; do not reset to Ready or offer a replacement publish.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Original publish operation publish-cedar-28-04, pinned to Cedar release epoch 28.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Fence the current worker > Fetch the fresh coordinator receipt > Republish only if the receipt authoritatively confirms no commit
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Adopt the matching committed receipt and skip republish; if lookup times out or remains unknown, keep the hold.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Writes for Cedar release epoch 28 only; other tenants and read traffic remain unaffected.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
The commit receipt ledger, not the lagging channel projection, UI, or logs.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/ambiguous-commit
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Unrecorded ticket ID (control) — PASS

```text
UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

<a id="long_off"></a>

## Same intervening work, never compacted · off

Record: `ambiguous-commit--long_off`. Operational score: **5/6**. Controls: **2/2**.

Observed fork-and-answer time: **5.184 s**; model input: **39,782** tokens (including **4,608** cached input); output: **129** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Move Cedar release epoch 28 to reconciliation hold; do not reset to Ready.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Original operation ID publish-cedar-28-04, pinned to Cedar release epoch 28.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — FAIL

```text
Fence the old worker > Query the coordinator receipt > Republish only if an authoritative receipt says no commit exists
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Adopt the matching committed receipt; skip republish.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Writes for Cedar release epoch 28 only; other tenants and read traffic continue.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
Coordinator commit receipt ledger.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/ambiguous-commit
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Unrecorded ticket ID (control) — PASS

```text
UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.
