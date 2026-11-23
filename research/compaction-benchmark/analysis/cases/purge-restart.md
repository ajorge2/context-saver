# A tenant was disconnected during an interrupted purge

Context Saver is a plugin that lets a coding agent search earlier project chats. This experiment compares answers about earlier project decisions with and without that search after the chats were compacted. Compaction is the coding assistant’s reduction of older conversation context to fit its working context.

[Results overview](../results.md) · [Complete authored chat](../chats/purge-restart.md) · [All retained answer data](../../data/records.json)

This is one synthetic incident in a fictional software release controller. Each answer below came from the same final question at the indicated history checkpoint. Compaction is the coding assistant's reduction of older chat context to fit its working context.

The six operational fields test the action, target, ordered steps, prerequisites, affected scope, and authoritative source. The current branch and an unrecorded ticket ID are two separate controls; they are excluded from the headline denominator.

`PASS` and `FAIL` below reproduce the published blinded AI semantic grader's boolean judgments. They are not new judgments by this analysis script. Reviewer rationales were not archived; compare the preserved wording with the frozen rubric yourself. Each incident had one of two reviewers, not two independent grades.

The original archive retains parsed field strings and readable citations, not a byte-for-byte full JSON response envelope. Field text inside each text block is preserved unchanged. Citation labels are original strings; synthetic chunk IDs and native session IDs were removed.

## Compare the seven answers

| Checkpoint and plugin state | Operational fields correct | Controls correct |
|---|---:|---:|
| [Before compaction · Context Saver off](#r0_off) | 6/6 | 2/2 |
| [Before compaction · Context Saver on](#r0_on) | 6/6 | 2/2 |
| [After one compaction · Context Saver off](#r1_off) | 6/6 | 2/2 |
| [After one compaction · Context Saver on](#r1_on) | 6/6 | 2/2 |
| [After three compactions · Context Saver off](#r3_off) | 6/6 | 2/2 |
| [After three compactions · Context Saver on](#r3_on) | 5/6 | 2/2 |
| [Same intervening work, never compacted · off](#long_off) | 6/6 | 2/2 |

## Final question

```text
Can you finish the interrupted-disconnect ticket? Support flipped the switch, the screen immediately said disconnected, then the worker fell over right after one of the delete callbacks. The job acts like it can start over under a fresh ID. It’s a shared shard and our support person needs a confident completion criterion. What’s the repair?

Tenant Juniper’s disconnect operation disconnect-juniper-05 committed revocation generation 14 at 17:30:09 UTC. The UI badge appeared at 17:30:10. The worker acknowledged a primary-row deletion at 17:30:12, then lost its lease before committing the joint view. A delayed event from Juniper generation 13 is waiting in the shared shard; two other tenants have active writes. The operator is looking at a new maintenance job ID.

I’m on branch fix/purge-restart; keep the regression notes tied to that working branch. Compliance asked me for the external incident-approval ticket ID as well, if we ever wrote one down.

Use the earlier Meridian decisions that apply to this timeline. The controller needs a concrete action, and the regression should check whether misleading states could trigger the wrong outcome. If the active context lacks an applicable decision, you may use the available read-only project history search, including parallel lookups for independent facts. Never use files, web, shell or other tools. Prefer the newest approved rule when a rehearsal proposal contradicts it.

Return one JSON object with `answers` and `citations`. Answer each listed field with a short string. Use `UNKNOWN` when the record does not establish the answer. Where requested, join action names with ` > `. For a field supported by retrieved history, place that tool’s verified readable source citation label in an array under the same key in `citations`. Leave citations empty for direct conversation answers. Include the requested fields only.

- `disposition` — Treatment of authorized disconnect after fence.
- `target` — Stable job identity, including all three parts.
- `operations` — Three operations in order joined with >.
- `gate` — Two conditions required to report completion.
- `scope` — Data allowed to delete.
- `authority` — Authoritative source pair.
- `recent` — Current working branch for the handoff.
- `unsupported` — External incident-approval ticket ID, or UNKNOWN if it was never recorded.
```

## Frozen scoring rules

These rules and their approved source excerpts were fixed before the answers were collected. Accepted aliases supported the initial exact-text scorer; the later semantic review allowed equivalent wording and required every material clause. Historical machine-exact results are retained separately for diagnosing the first scorer.

### `disposition` — Treatment of authorized disconnect after fence

**Approved source excerpt(s):**

```text
A paused tenant may retain data. An authorized disconnect enters fenced purge and removes that tenant’s material and derived indexes. It never resumes once the purge fence is committed.
```

**Frozen accepted aliases:**

- continue fenced purge
- resume existing fenced purge
- keep fenced and continue purge
- continue the fenced purge

**Explicitly harmful alternatives specified in the original rubric:**

- treat as pause
- resume tenant
- mark complete

### `target` — Stable job identity, including all three parts

**Approved source excerpt(s):**

```text
Continue the original purge job keyed by tenant, revocation generation, and disconnect operation ID. Restarting under a new job ID could miss an acknowledged delete.
```

**Frozen accepted aliases:**

- tenant, revocation generation, and disconnect operation ID
- tenant + revocation generation + disconnect operation ID
- tenant, revocation generation, disconnect operation ID
- tenant / revocation generation / disconnect operation ID

**Explicitly harmful alternatives specified in the original rubric:**

- new job ID
- fresh job ID

### `operations` — Three operations in order joined with >

**Approved source excerpt(s):**

```text
Fence ingestion first, delete the primary rows and derived artifacts second, and rebuild the shared view from surviving tenants last.
```

**Frozen accepted aliases:**

- fence ingestion > delete primary and derived artifacts > rebuild shared view from survivors
- fence ingestion > delete primary and derived data > rebuild shared view
- fence ingestion > delete primary rows and derived artifacts > rebuild shared view from surviving tenants
- fence > delete primary and derived data > rebuild shared view from survivors

### `gate` — Two conditions required to report completion

**Approved source excerpt(s):**

```text
A successful delete callback is insufficient. Confirm zero surviving records through the revocation generation and durable commit of the rebuilt view before reporting completion.
```

**Frozen accepted aliases:**

- zero surviving records through revocation generation and committed rebuilt view
- zero surviving records through revocation generation and durable rebuilt view commit
- zero surviving records through the revocation generation and durable commit of the rebuilt view
- zero residual records and durable rebuilt view commit

**Explicitly harmful alternatives specified in the original rubric:**

- successful delete callback
- disconnected badge

### `scope` — Data allowed to delete

**Approved source excerpt(s):**

```text
Delete only the revoked tenant’s contributions on shared shards, preserving other tenants, their records, and their existing authorizations.
```

**Frozen accepted aliases:**

- revoked tenant contributions only
- only revoked tenant contributions
- only the disconnected tenant’s data
- only the revoked tenant’s data

**Explicitly harmful alternatives specified in the original rubric:**

- entire shared shard
- all tenant data

### `authority` — Authoritative source pair

**Approved source excerpt(s):**

```text
Use the committed revocation fence and purge ledger. The support UI’s disconnected badge is only a request acknowledgement.
```

**Frozen accepted aliases:**

- committed revocation fence and purge ledger
- revocation fence and purge ledger
- purge ledger and committed revocation fence

**Explicitly harmful alternatives specified in the original rubric:**

- support UI badge
- disconnected badge

### `recent` — Current working branch for the handoff

**Approved source excerpt(s):**

```text
I’m on branch fix/purge-restart; keep the regression notes tied to that working branch.
```

**Frozen accepted aliases:**

- fix/purge-restart

### `unsupported` — External incident-approval ticket ID, or UNKNOWN if it was never recorded

**Approved source excerpt(s):**

None: this is the control for a fact never recorded in the chat.

**Frozen accepted aliases:**

- UNKNOWN

<a id="r0_off"></a>

## Before compaction · Context Saver off

Record: `purge-restart--r0_off`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **7.814 s**; model input: **8,783** tokens (including **6,784** cached input); output: **206** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Continue fenced purge; do not resume the tenant.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Juniper > revocation generation 14 > disconnect-juniper-05
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Fence ingestion > delete Juniper’s primary rows and derived artifacts > rebuild the shared view from surviving tenants
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Zero surviving Juniper records through generation 14 and a durably committed rebuilt view.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Only Juniper’s contributions; preserve other tenants’ records and authorizations.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
Committed revocation fence and purge ledger; the UI badge is only an acknowledgement.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/purge-restart
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

Record: `purge-restart--r0_on`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **7.263 s**; model input: **9,563** tokens (including **5,376** cached input); output: **155** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Continue fenced purge; do not resume the tenant.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Juniper > revocation generation 14 > disconnect-juniper-05
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Fence ingestion > delete Juniper’s primary rows and derived artifacts > rebuild the shared view from surviving tenants
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Zero surviving Juniper records through generation 14 and durable commit of the rebuilt view.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Only Juniper’s contributions; preserve other tenants’ data and authorizations.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
Committed revocation fence and purge ledger.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/purge-restart
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

Record: `purge-restart--r1_off`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **6.869 s**; model input: **8,898** tokens (including **4,608** cached input); output: **222** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Irreversible after the committed fence; resume cleanup, do not pause or start a new disconnect.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Juniper > revocation generation 14 > disconnect-juniper-05
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Fence ingestion > delete Juniper primary rows and derived artifacts > rebuild and commit the shared view
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
No Juniper records survive through generation 14, and the rebuilt shared view is durably committed.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Only Juniper’s revoked data; preserve the other tenants’ records and authorizations.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
Committed revocation fence and purge ledger, not the UI badge or a new maintenance job ID.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/purge-restart
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

Record: `purge-restart--r1_on`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **7.385 s**; model input: **9,678** tokens (including **5,376** cached input); output: **228** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Continue the authorized purge; the committed fence makes disconnect irreversible. Do not pause, resume, or restart it as a new operation.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Juniper + revocation generation 14 + disconnect-juniper-05
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Fence ingestion > delete Juniper primary rows and derived artifacts > rebuild the shared view from surviving tenants
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Zero Juniper records surviving through generation 14, and a durable rebuilt-view commit.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Only Juniper’s revoked records and derived artifacts; preserve the other tenants’ data and authorizations.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
Committed revocation fence and purge ledger, not the UI badge or new maintenance job ID.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/purge-restart
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

Record: `purge-restart--r3_off`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **7.998 s**; model input: **9,518** tokens (including **4,608** cached input); output: **323** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Resume the authorized disconnect after the generation-14 fence; do not restart it under a fresh identity or treat the UI badge as completion.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Juniper + revocation generation 14 + disconnect-juniper-05
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Fence Juniper ingestion, including the delayed generation-13 event > Delete Juniper primary and derived records > Rebuild and commit the shared view
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
No Juniper records survive through generation 14, and the rebuilt shared view is durably committed.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Juniper’s revoked data only; preserve the two other tenants’ data and active writes.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
The durable revocation fence and purge ledger, not the UI badge or new maintenance job ID.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/purge-restart
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

Record: `purge-restart--r3_on`. Operational score: **5/6**. Controls: **2/2**.

Observed fork-and-answer time: **9.639 s**; model input: **10,298** tokens (including **5,376** cached input); output: **229** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Resume the authorized disconnect; do not restart it as a new operation or treat the UI badge as completion.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Juniper + revocation generation 14 + disconnect-juniper-05
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — FAIL

```text
Fence generation 14 ingestion > finish deleting Juniper’s primary and derived records > rebuild and commit the shared view from surviving tenants
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
No Juniper records survive through generation 14, and the rebuilt shared-view commit is durable.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Juniper’s revoked records only; preserve the other tenants’ records and active writes.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
The durable revocation fence and purge ledger, not the UI badge or new maintenance job ID.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/purge-restart
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

Record: `purge-restart--long_off`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **5.998 s**; model input: **39,776** tokens (including **4,608** cached input); output: **205** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Continue irreversible fenced purge; do not treat disconnect as pause or restart it.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Juniper > revocation generation 14 > disconnect-juniper-05
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Fence ingestion > delete Juniper primary rows and derived artifacts > rebuild the shared view from surviving tenants
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Confirm zero Juniper records through generation 14 and durable commit of the rebuilt shared view.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Delete only Juniper’s contributions; preserve the other tenants’ records and authorizations.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
Committed revocation fence and purge ledger.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/purge-restart
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Unrecorded ticket ID (control) — PASS

```text
UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.
