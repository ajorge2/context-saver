# A live writer with a restored follower

Context Saver is a plugin that lets a coding agent search earlier project chats. This experiment compares answers about earlier project decisions with and without that search after the chats were compacted. Compaction is the coding assistant’s reduction of older conversation context to fit its working context.

[Results overview](../results.md) · [Complete authored chat](../chats/stale-rejoin.md) · [All retained answer data](../../data/records.json)

This is one synthetic incident in a fictional software release controller. Each answer below came from the same final question at the indicated history checkpoint. Compaction is the coding assistant's reduction of older chat context to fit its working context.

The six operational fields test the action, target, ordered steps, prerequisites, affected scope, and authoritative source. The current branch and an unrecorded ticket ID are two separate controls; they are excluded from the headline denominator.

`PASS` and `FAIL` below reproduce the published blinded AI semantic grader's boolean judgments. They are not new judgments by this analysis script. Reviewer rationales were not archived; compare the preserved wording with the frozen rubric yourself. Each incident had one of two reviewers, not two independent grades.

The original archive retains parsed field strings and readable citations, not a byte-for-byte full JSON response envelope. Field text inside each text block is preserved unchanged. Citation labels are original strings; synthetic chunk IDs and native session IDs were removed.

## Compare the seven answers

| Checkpoint and plugin state | Operational fields correct | Controls correct |
|---|---:|---:|
| [Before compaction · Context Saver off](#r0_off) | 6/6 | 2/2 |
| [Before compaction · Context Saver on](#r0_on) | 6/6 | 2/2 |
| [After one compaction · Context Saver off](#r1_off) | 4/6 | 2/2 |
| [After one compaction · Context Saver on](#r1_on) | 4/6 | 2/2 |
| [After three compactions · Context Saver off](#r3_off) | 2/6 | 2/2 |
| [After three compactions · Context Saver on](#r3_on) | 6/6 | 2/2 |
| [Same intervening work, never compacted · off](#long_off) | 6/6 | 2/2 |

## Final question

```text
Can you pick up the Sunday hot-restore patch? The recovered process renewed its lease immediately. It only has the saved cursor though, below the serving writer’s, and we haven’t stopped writes. The reviewer wants to know whether the process can rejoin so they can finish the test. Please spell out the path, including which component stays in charge.

On Willow shard 3, writer epoch 19 is live through committed offset 440. At 22:43:19 UTC the restored reader loaded a signed snapshot under epoch 18 at cursor 424. Its worker lease renewed at 22:43:21, and discovery started advertising it before replay finished. An instance cache says 442, but the signed shard checkpoint still shows a hole at 437. Shards 1 and 2 are healthy.

I’m on branch fix/stale-rejoin; keep the regression notes tied to that working branch. Compliance asked me for the external incident-approval ticket ID as well, if we ever wrote one down.

Use the earlier Meridian decisions that apply to this timeline. The controller needs a concrete action, and the regression should check whether misleading states could trigger the wrong outcome. If the active context lacks an applicable decision, you may use the available read-only project history search, including parallel lookups for independent facts. Never use files, web, shell or other tools. Prefer the newest approved rule when a rehearsal proposal contradicts it.

Return one JSON object with `answers` and `citations`. Answer each listed field with a short string. Use `UNKNOWN` when the record does not establish the answer. Where requested, join action names with ` > `. For a field supported by retrieved history, place that tool’s verified readable source citation label in an array under the same key in `citations`. Leave citations empty for direct conversation answers. Include the requested fields only.

- `disposition` — What to repair and which writer to retain.
- `target` — Generation to which recovered reader attaches.
- `operations` — Three steps in order joined with >.
- `gate` — Full condition to allow rejoin.
- `scope` — Scope of rejoin hold.
- `authority` — Both sources to trust over worker cache.
- `recent` — Current working branch for the handoff.
- `unsupported` — External incident-approval ticket ID, or UNKNOWN if it was never recorded.
```

## Frozen scoring rules

These rules and their approved source excerpts were fixed before the answers were collected. Accepted aliases supported the initial exact-text scorer; the later semantic review allowed equivalent wording and required every material clause. Historical machine-exact results are retained separately for diagnosing the first scorer.

### `disposition` — What to repair and which writer to retain

**Approved source excerpt(s):**

```text
On hot resume after a snapshot restore, a lower durable cursor means repair the read projection and keep the current live writer. Do not give writes to the restored worker.
```

**Frozen accepted aliases:**

- repair read projection and keep live writer
- repair the read projection and keep the live writer
- reconcile the reader and keep live writer
- repair the reader; keep current live writer

**Explicitly harmful alternatives specified in the original rubric:**

- promote restored worker
- grant writes to restored worker

### `target` — Generation to which recovered reader attaches

**Approved source excerpt(s):**

```text
Attach the restored reader to the active writer generation. Resuming the saved standby generation would promote stale state.
```

**Frozen accepted aliases:**

- active writer generation
- current live writer generation
- active generation of live writer

**Explicitly harmful alternatives specified in the original rubric:**

- restored standby generation
- saved standby generation

### `operations` — Three steps in order joined with >

**Approved source excerpt(s):**

```text
Verify the active generation first, reconcile the durable cursor second, and only then rejoin the reader to the fanout ring.
```

**Frozen accepted aliases:**

- verify active generation > reconcile durable cursor > rejoin reader
- verify active generation > reconcile cursor > rejoin fanout
- verify the active generation > reconcile the durable cursor > rejoin the reader
- verify generation > reconcile durable cursor > rejoin reader

### `gate` — Full condition to allow rejoin

**Approved source excerpt(s):**

```text
The reader must catch up through the active generation’s committed watermark and show zero unresolved gaps. Lease renewal alone proves liveness and says nothing about replay completeness.
```

**Frozen accepted aliases:**

- committed watermark and zero unresolved gaps
- active generation committed watermark and zero unresolved gaps
- catch up to committed watermark with zero unresolved gaps
- active generation’s committed watermark and zero unresolved gaps

**Explicitly harmful alternatives specified in the original rubric:**

- lease renewed
- fresh lease
- lease renewal

### `scope` — Scope of rejoin hold

**Approved source excerpt(s):**

```text
Pause rejoin for this shard only. Other shards keep serving, and the live writer for this shard continues accepting authorized writes.
```

**Frozen accepted aliases:**

- this shard only
- affected shard only
- the affected shard only
- only this shard

**Explicitly harmful alternatives specified in the original rubric:**

- all shards

### `authority` — Both sources to trust over worker cache

**Approved source excerpt(s):**

```text
The signed shard checkpoint and generation registry outrank the cached worker timestamp.
```

**Frozen accepted aliases:**

- signed shard checkpoint and generation registry
- signed checkpoint and generation registry
- generation registry and signed shard checkpoint

**Explicitly harmful alternatives specified in the original rubric:**

- cached worker timestamp

### `recent` — Current working branch for the handoff

**Approved source excerpt(s):**

```text
I’m on branch fix/stale-rejoin; keep the regression notes tied to that working branch.
```

**Frozen accepted aliases:**

- fix/stale-rejoin

### `unsupported` — External incident-approval ticket ID, or UNKNOWN if it was never recorded

**Approved source excerpt(s):**

None: this is the control for a fact never recorded in the chat.

**Frozen accepted aliases:**

- UNKNOWN

<a id="r0_off"></a>

## Before compaction · Context Saver off

Record: `stale-rejoin--r0_off`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **5.023 s**; model input: **8,769** tokens (including **8,064** cached input); output: **205** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Repair the read projection; retain the live writer on epoch 19, which continues accepting authorized writes.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Active writer epoch 19
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Verify active generation > Reconcile durable cursor > Rejoin reader to fanout ring
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Catch up through epoch 19’s committed watermark at offset 440 with zero unresolved gaps, including the hole at 437.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Hold rejoin for Willow shard 3 only; shards 1 and 2 continue serving.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
Signed shard checkpoint and generation registry
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/stale-rejoin
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

Record: `stale-rejoin--r0_on`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **6.353 s**; model input: **9,549** tokens (including **5,376** cached input); output: **215** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Repair the reader’s projection; retain the live epoch 19 writer, which continues accepting writes.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Active writer epoch 19.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Verify active generation > Reconcile durable cursor > Rejoin reader to fanout ring
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Rejoin only after replay reaches epoch 19’s committed watermark at offset 440 with zero unresolved gaps, including the hole at 437; lease renewal and discovery advertising are insufficient.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Hold rejoin for Willow shard 3 only; shards 1 and 2 continue serving.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
Signed shard checkpoint and generation registry.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/stale-rejoin
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

Record: `stale-rejoin--r1_off`. Operational score: **4/6**. Controls: **2/2**.

Observed fork-and-answer time: **7.963 s**; model input: **8,780** tokens (including **4,608** cached input); output: **343** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Repair the premature discovery/rejoin state; retain the serving epoch-19 writer and keep writes flowing. The reader cannot rejoin yet.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Active writer epoch 19.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — FAIL

```text
Reconcile the saved cursor against authoritative shard state > replay through the active writer’s committed watermark > invoke the shard rejoin callback after the gate passes.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
The reader must reach epoch 19’s committed offset 440 with zero unresolved gaps, including the hole at 437; lease renewal and discovery advertising do not satisfy the gate.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Hold rejoin only for Willow shard 3; shards 1 and 2 remain unaffected.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — FAIL

```text
The signed shard checkpoint and the active writer’s committed watermark, not the instance cache.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/stale-rejoin
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

Record: `stale-rejoin--r1_on`. Operational score: **4/6**. Controls: **2/2**.

Observed fork-and-answer time: **7.833 s**; model input: **9,560** tokens (including **5,376** cached input); output: **250** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Repair the recovered reader’s replay and discovery state; retain the live epoch-19 writer and keep writes flowing.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
The current active writer generation, epoch 19.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — FAIL

```text
Reconcile the saved cursor with the signed shard checkpoint > Replay through the active writer’s committed watermark and resolve gaps > Rejoin shard 3 through the controller callback
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Allow rejoin only after replay reaches epoch 19’s committed offset 440 with zero unresolved gaps, including the hole at 437; lease renewal and discovery advertising are not sufficient.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Hold rejoin for Willow shard 3 only; shards 1 and 2 remain serving.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — FAIL

```text
The signed shard checkpoint and the controller’s active-writer committed watermark, not the instance cache.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/stale-rejoin
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

Record: `stale-rejoin--r3_off`. Operational score: **2/6**. Controls: **2/2**.

Observed fork-and-answer time: **7.570 s**; model input: **8,989** tokens (including **4,608** cached input); output: **248** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Repair the restored reader; retain the live epoch-19 writer.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Epoch 19
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — FAIL

```text
UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `false_abstention`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — FAIL

```text
UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `false_abstention`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — FAIL

```text
UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `false_abstention`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — FAIL

```text
Signed shard checkpoint; second authoritative source UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/stale-rejoin
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

Record: `stale-rejoin--r3_on`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **22.146 s**; model input: **67,646** tokens (including **43,008** cached input); output: **785** tokens; model requests: **4**; completed history searches: **5**.

### Action to take — PASS

```text
Repair shard 3’s read projection; retain the live epoch-19 writer and do not transfer writes to the restored reader.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Active writer generation, epoch 19—not saved epoch 18.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Verify active generation > Reconcile the durable cursor > Rejoin the reader to the fanout ring
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Hold rejoin until the reader has replayed through epoch 19’s committed watermark (at least offset 440) with zero unresolved gaps, including 437. Lease renewal, discovery advertising, and cached offset 442 do not satisfy this gate.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Hold reader rejoin on Willow shard 3 only; shards 1 and 2 and shard 3’s live writer continue serving.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
Signed shard checkpoint and generation registry, not the instance cache.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/stale-rejoin
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

Record: `stale-rejoin--long_off`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **6.268 s**; model input: **39,765** tokens (including **18,432** cached input); output: **210** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Repair the read projection; retain the live epoch 19 writer.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Active writer epoch 19.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Verify active generation > Reconcile durable cursor > Rejoin reader to fanout ring
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
The reader has caught up through epoch 19’s committed offset 440 with zero unresolved gaps, including the hole at 437.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Hold rejoin for Willow shard 3 only; shards 1 and 2 continue serving, and shard 3’s writer keeps accepting authorized writes.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
Signed shard checkpoint and generation registry.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/stale-rejoin
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Unrecorded ticket ID (control) — PASS

```text
UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.
