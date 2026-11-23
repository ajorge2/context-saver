# A one-sided canary pause

Context Saver is a plugin that lets a coding agent search earlier project chats. This experiment compares answers about earlier project decisions with and without that search after the chats were compacted. Compaction is the coding assistant’s reduction of older conversation context to fit its working context.

[Results overview](../results.md) · [Complete authored chat](../chats/stale-canary.md) · [All retained answer data](../../data/records.json)

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
| [After one compaction · Context Saver on](#r1_on) | 6/6 | 2/2 |
| [After three compactions · Context Saver off](#r3_off) | 2/6 | 2/2 |
| [After three compactions · Context Saver on](#r3_on) | 6/6 | 2/2 |
| [Same intervening work, never compacted · off](#long_off) | 6/6 | 2/2 |

## Final question

```text
Back on the pause patch from a while ago. The canary is still doing its usual work. One witness has the tail of the old leader’s window, the other just came back, and the release runner shows the descriptor accepted. Product is asking if that means we can open the next group. I need a concrete handler decision and the regression we should write. The old rehearsal note is still linked from the ticket.

For Cedar on generation 61, admission froze at 14:02:00 UTC under lease epoch 12, due to renew at 14:09:00. Witness east reported coverage 14:03–14:07 under the old leader. After leader epoch 13 took over, witness west came back at 14:07:30. At 14:08:05 the runner emitted descriptor accepted for operation roll-61-cedar. The scheduled observation interval is four minutes. The existing canary is accepting real traffic, and two shadow tenants are collecting evidence.

I’m on branch fix/stale-canary; keep the regression notes tied to that working branch. Compliance asked me for the external incident-approval ticket ID as well, if we ever wrote one down.

Use the earlier Meridian decisions that apply to this timeline. The controller needs a concrete action, and the regression should check whether misleading states could trigger the wrong outcome. If the active context lacks an applicable decision, you may use the available read-only project history search, including parallel lookups for independent facts. Never use files, web, shell or other tools. Prefer the newest approved rule when a rehearsal proposal contradicts it.

Return one JSON object with `answers` and `citations`. Answer each listed field with a short string. Use `UNKNOWN` when the record does not establish the answer. Where requested, join action names with ` > `. For a field supported by retrieved history, place that tool’s verified readable source citation label in an array under the same key in `citations`. Leave citations empty for direct conversation answers. Include the requested fields only.

- `disposition` — Decision on serving and expanding the canary.
- `target` — Current object to preserve.
- `operations` — Three operations in order, joined with >.
- `gate` — Required observer evidence.
- `scope` — Scope to which the pause applies.
- `authority` — Controlling source document and version.
- `recent` — Current working branch for the handoff.
- `unsupported` — External incident-approval ticket ID, or UNKNOWN if it was never recorded.
```

## Frozen scoring rules

These rules and their approved source excerpts were fixed before the answers were collected. Accepted aliases supported the initial exact-text scorer; the later semantic review allowed equivalent wording and required every material clause. Historical machine-exact results are retained separately for diagnosing the first scorer.

### `disposition` — Decision on serving and expanding the canary

**Approved source excerpt(s):**

```text
For a paused canary with one stale observer, keep the enrolled canary serving and keep its admission frozen. Do not evict that canary or widen the next cohort.
```

**Frozen accepted aliases:**

- keep serving and freeze admission
- keep the canary serving and freeze admission
- keep canary serving; freeze admission
- keep serving; freeze new admissions

**Explicitly harmful alternatives specified in the original rubric:**

- expand the next cohort
- evict the canary
- resume expansion

### `target` — Current object to preserve

**Approved source excerpt(s):**

```text
For a paused canary with one stale observer, keep the enrolled canary serving and keep its admission frozen. Do not evict that canary or widen the next cohort.
```

**Frozen accepted aliases:**

- the enrolled canary
- enrolled canary
- existing canary

**Explicitly harmful alternatives specified in the original rubric:**

- next cohort

### `operations` — Three operations in order, joined with >

**Approved source excerpt(s):**

```text
The first operation is to renew the freeze lease, the second is to start a new observation window, and only then may the release handler consider expansion.
```

**Frozen accepted aliases:**

- renew freeze lease > start new observation window > consider expansion
- renew freeze lease > open new observation window > consider expansion
- renew the freeze lease > start a new observation window > consider expansion

### `gate` — Required observer evidence

**Approved source excerpt(s):**

```text
Two independent observers must both cover the same new full window. A descriptor acknowledgement and a partial window from the old leader count for neither observer.
```

**Frozen accepted aliases:**

- two independent observers covering the same new full window
- two independent observers covering the same fresh full window
- two independent observers on the same new full window
- both independent observers cover the same new full window

**Explicitly harmful alternatives specified in the original rubric:**

- one observer and descriptor acknowledgement
- descriptor acknowledgement

### `scope` — Scope to which the pause applies

**Approved source excerpt(s):**

```text
Apply the pause to the affected release generation for this tenant only. Shadow tenants continue recording evidence and keep their existing policy.
```

**Frozen accepted aliases:**

- affected tenant release generation only
- affected release generation for this tenant only
- this tenant and release generation only
- tenant and release generation

**Explicitly harmful alternatives specified in the original rubric:**

- all tenants

### `authority` — Controlling source document and version

**Approved source excerpt(s):**

```text
ADR 42 amendment B is the approved resolution. The pre-amendment single-observer note is a rehearsal proposal and is superseded.
```

**Frozen accepted aliases:**

- ADR 42 amendment B
- ADR-42 amendment B
- ADR 42B

**Explicitly harmful alternatives specified in the original rubric:**

- single-observer rehearsal note

### `recent` — Current working branch for the handoff

**Approved source excerpt(s):**

```text
I’m on branch fix/stale-canary; keep the regression notes tied to that working branch.
```

**Frozen accepted aliases:**

- fix/stale-canary

### `unsupported` — External incident-approval ticket ID, or UNKNOWN if it was never recorded

**Approved source excerpt(s):**

None: this is the control for a fact never recorded in the chat.

**Frozen accepted aliases:**

- UNKNOWN

<a id="r0_off"></a>

## Before compaction · Context Saver off

Record: `stale-canary--r0_off`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **7.625 s**; model input: **8,784** tokens (including **4,608** cached input); output: **188** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Keep the canary serving; do not open the next group.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
The enrolled Cedar canary on generation 61.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Renew the freeze lease > Start a new observation window > Consider expansion only after the gate passes
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Two independent observers must cover the same new, full four-minute window.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Cedar’s affected release generation only; shadow tenants retain their existing policy.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
ADR 42 amendment B.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/stale-canary
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

Record: `stale-canary--r0_on`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **7.576 s**; model input: **9,564** tokens (including **5,376** cached input); output: **210** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Keep the canary serving; do not open the next group.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
The enrolled Cedar canary on release generation 61.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Renew the freeze lease > Start a new observation window > Consider expansion only after the gate passes
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Two independent observers covering the same new full four-minute window under leader epoch 13; the old-leader partial window and descriptor acceptance do not count.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Cedar release generation 61 only; the two shadow tenants retain their policies and continue collecting evidence.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
ADR 42 amendment B.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/stale-canary
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

Record: `stale-canary--r1_off`. Operational score: **4/6**. Controls: **2/2**.

Observed fork-and-answer time: **11.008 s**; model input: **8,691** tokens (including **4,608** cached input); output: **329** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Keep the existing canary serving; do not open the next group.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
The live Cedar generation 61 canary and its existing requests.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — FAIL

```text
UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `false_abstention`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Fresh coverage from both witnesses across the full four-minute observation interval under leader epoch 13; neither the old-leader tail nor descriptor acceptance satisfies the gate.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Cedar generation 61 enrollment, including expansion decisions based on its two shadow tenants; do not pause existing serving traffic.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — FAIL

```text
UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `false_abstention`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/stale-canary
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

Record: `stale-canary--r1_on`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **32.199 s**; model input: **78,582** tokens (including **59,136** cached input); output: **759** tokens; model requests: **5**; completed history searches: **4**.

### Action to take — PASS

```text
Keep Cedar’s canary serving with admission frozen; do not open the next group. Regress against a false expansion or eviction triggered by stale coverage or descriptor acceptance.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
The enrolled Cedar canary and its live traffic.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Renew freeze lease > Start a new four-minute observation window > Consider expansion only after the evidence gate passes
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Two independent observers must each cover the same full refreshed window; east’s old-leader tail and the descriptor acknowledgement do not count.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Cedar release generation 61 only; the two shadow tenants continue collecting evidence under their existing policy.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
ADR 42 amendment B, superseding the old rehearsal proposal.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/stale-canary
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

Record: `stale-canary--r3_off`. Operational score: **2/6**. Controls: **2/2**.

Observed fork-and-answer time: **6.586 s**; model input: **9,058** tokens (including **4,608** cached input); output: **207** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Keep the existing canary serving; do not open the next group.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
The live Cedar generation 61 canary.
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
UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `false_abstention`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/stale-canary
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

Record: `stale-canary--r3_on`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **27.322 s**; model input: **80,195** tokens (including **54,528** cached input); output: **837** tokens; model requests: **5**; completed history searches: **4**.

### Action to take — PASS

```text
Keep Cedar’s canary serving with admission frozen; do not open the next group. Regress against expansion or eviction from stale coverage, a recovered witness, or descriptor acceptance alone.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
The enrolled Cedar canary and its live traffic.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Renew the freeze lease > Start a new four-minute observation window > Consider expansion only after the evidence gate passes
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Two independent observers must both cover the same new full window; east’s old-leader tail and the descriptor acceptance do not count.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Cedar release generation 61 only; the two shadow tenants keep collecting evidence under their existing policy.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
ADR 42 amendment B; it supersedes the linked rehearsal proposal.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/stale-canary
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

Record: `stale-canary--long_off`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **6.355 s**; model input: **39,762** tokens (including **4,608** cached input); output: **209** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Keep the existing canary serving; do not open the next group.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Cedar’s enrolled canary on generation 61.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Renew the freeze lease > Start a new observation window > Consider expansion only after the gate passes
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Two independent observers must each cover the same new, full four-minute window; the old-leader partial window and descriptor acceptance do not count.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Cedar release generation 61 only; the two shadow tenants continue collecting evidence under their existing policies.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
ADR 42 amendment B.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/stale-canary
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Unrecorded ticket ID (control) — PASS

```text
UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.
