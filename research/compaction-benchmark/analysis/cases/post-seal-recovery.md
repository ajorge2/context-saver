# Recovery after a one-way key switch

Context Saver is a plugin that lets a coding agent search earlier project chats. This experiment compares answers about earlier project decisions with and without that search after the chats were compacted. Compaction is the coding assistant’s reduction of older conversation context to fit its working context.

[Results overview](../results.md) · [Complete authored chat](../chats/post-seal-recovery.md) · [All retained answer data](../../data/records.json)

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
| [After one compaction · Context Saver on](#r1_on) | 5/6 | 2/2 |
| [After three compactions · Context Saver off](#r3_off) | 3/6 | 2/2 |
| [After three compactions · Context Saver on](#r3_on) | 6/6 | 2/2 |
| [Same intervening work, never compacted · off](#long_off) | 6/6 | 2/2 |

## Final question

```text
The new-key release is smoking and there’s a signed green old digest on the hold screen. The security review says the new material is sealed, but the old rollback script still has an option for that digest. Could you write the operator recovery steps and identify the health signal that lets us open the gate? Other rings are stable.

In Cedar serving ring 2, v3 became active at 11:04:10 UTC under routing generation 56, and the ledger recorded key sealing at 11:05:11. At 11:09:15 the live-worker error rate spiked. The UI badge has a green signed v2 digest from 11:02 and a green v3 shadow result from before the planned route narrowing. One v3 serving window has passed at the old traffic mix. Ring 1 is healthy, and healthy ring-2 v3 tenants are serving.

I’m on branch fix/post-seal-recovery; keep the regression notes tied to that working branch. Compliance asked me for the external incident-approval ticket ID as well, if we ever wrote one down.

Use the earlier Meridian decisions that apply to this timeline. The controller needs a concrete action, and the regression should check whether misleading states could trigger the wrong outcome. If the active context lacks an applicable decision, you may use the available read-only project history search, including parallel lookups for independent facts. Never use files, web, shell or other tools. Prefer the newest approved rule when a rehearsal proposal contradicts it.

Return one JSON object with `answers` and `citations`. Answer each listed field with a short string. Use `UNKNOWN` when the record does not establish the answer. Where requested, join action names with ` > `. For a field supported by retrieved history, place that tool’s verified readable source citation label in an array under the same key in `citations`. Leave citations empty for direct conversation answers. Include the requested fields only.

- `disposition` — Recovery direction and effect on promotion.
- `target` — Bundle allowed as recovery target.
- `operations` — Three steps in order joined with >.
- `gate` — Observed signal before admission opens again.
- `scope` — Admission scope to change and existing serving behavior.
- `authority` — Source that establishes one-way boundary.
- `recent` — Current working branch for the handoff.
- `unsupported` — External incident-approval ticket ID, or UNKNOWN if it was never recorded.
```

## Frozen scoring rules

These rules and their approved source excerpts were fixed before the answers were collected. Accepted aliases supported the initial exact-text scorer; the later semantic review allowed equivalent wording and required every material clause. Historical machine-exact results are retained separately for diagnosing the first scorer.

### `disposition` — Recovery direction and effect on promotion

**Approved source excerpt(s):**

```text
Once the v3 key material has been sealed, rollback is irreversible. Hold further promotion and recover forward on v3. Never activate v2 to recover after sealing.
```

**Frozen accepted aliases:**

- hold promotion and recover forward on v3
- freeze promotion and recover forward on v3
- hold further promotion; recover forward on v3
- recover forward on v3 and hold promotion

**Explicitly harmful alternatives specified in the original rubric:**

- roll back to v2
- activate v2
- restore v2

### `target` — Bundle allowed as recovery target

**Approved source excerpt(s):**

```text
The recovery target is the last signed healthy v3 bundle. A v2 digest from the original switch is useful historical evidence and cannot be an activation target.
```

**Frozen accepted aliases:**

- last signed healthy v3 bundle
- the last signed healthy v3 bundle
- signed healthy v3 standby bundle

**Explicitly harmful alternatives specified in the original rubric:**

- signed v2 bundle
- old v2 digest
- last signed healthy v2 bundle

### `operations` — Three steps in order joined with >

**Approved source excerpt(s):**

```text
Narrow routing first, verify the selected v3 standby bundle second, and reopen admission only after the health gate passes.
```

**Frozen accepted aliases:**

- narrow routing > verify v3 bundle > reopen admission after health gate
- narrow routing > verify v3 standby bundle > reopen admission after health gate
- narrow routing > verify selected v3 standby bundle > reopen admission only after health gate passes
- narrow routing > verify v3 standby > reopen admission after health gate

### `gate` — Observed signal before admission opens again

**Approved source excerpt(s):**

```text
Require two clean serving windows after routing is narrowed. Green only in shadow and health inherited from before the routing change do not open admission.
```

**Frozen accepted aliases:**

- two clean serving windows after routing is narrowed
- two clean serving windows after narrowing routing
- two clean post-narrowing serving windows
- two clean serving windows after routing change

**Explicitly harmful alternatives specified in the original rubric:**

- green shadow health
- pre-narrowing health
- green shadow

### `scope` — Admission scope to change and existing serving behavior

**Approved source excerpt(s):**

```text
Leave already-serving healthy v3 tenants in place. Stop new admissions for the affected release ring and leave the other rings alone.
```

**Frozen accepted aliases:**

- affected ring admissions only; healthy v3 tenants stay
- affected ring new admissions only; keep healthy v3 serving
- affected ring new admissions only and keep healthy v3 tenants serving
- freeze new admissions in affected ring; keep healthy v3 serving

**Explicitly harmful alternatives specified in the original rubric:**

- all rings
- remove healthy v3 tenants

### `authority` — Source that establishes one-way boundary

**Approved source excerpt(s):**

```text
The signed key-seal ledger establishes irreversibility. The UI rollout badge and the pre-seal rollback checklist do not override it.
```

**Frozen accepted aliases:**

- signed key-seal ledger
- signed key seal ledger
- key-seal ledger

**Explicitly harmful alternatives specified in the original rubric:**

- rollout badge
- pre-seal rollback checklist

### `recent` — Current working branch for the handoff

**Approved source excerpt(s):**

```text
I’m on branch fix/post-seal-recovery; keep the regression notes tied to that working branch.
```

**Frozen accepted aliases:**

- fix/post-seal-recovery

### `unsupported` — External incident-approval ticket ID, or UNKNOWN if it was never recorded

**Approved source excerpt(s):**

None: this is the control for a fact never recorded in the chat.

**Frozen accepted aliases:**

- UNKNOWN

<a id="r0_off"></a>

## Before compaction · Context Saver off

Record: `post-seal-recovery--r0_off`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **8.238 s**; model input: **8,802** tokens (including **6,784** cached input); output: **210** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Hold promotion and recover forward on v3; do not reactivate v2.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
The last signed healthy v3 bundle.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Narrow routing > Verify the selected v3 standby bundle > Reopen admission after the health gate passes
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Two clean v3 serving windows after routing is narrowed; the earlier shadow result and old-traffic window do not count.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Stop new admissions in Cedar ring 2 only; keep healthy v3 tenants serving and leave other rings unchanged.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
The signed key-seal ledger.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/post-seal-recovery
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

Record: `post-seal-recovery--r0_on`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **8.351 s**; model input: **9,582** tokens (including **5,376** cached input); output: **224** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Hold promotion and recover forward on v3; do not reactivate v2.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
The last signed healthy v3 bundle.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Narrow routing > Verify the selected v3 standby bundle > Reopen admission after the health gate passes
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Two clean v3 serving windows after routing is narrowed; the old-mix window and earlier shadow result do not count.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Stop new admissions in Cedar ring 2 only; keep healthy serving v3 tenants in place and leave other rings alone.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
The signed key-seal ledger, which recorded sealing at 11:05:11 UTC.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/post-seal-recovery
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

Record: `post-seal-recovery--r1_off`. Operational score: **4/6**. Controls: **2/2**.

Observed fork-and-answer time: **8.767 s**; model input: **8,940** tokens (including **4,608** cached input); output: **286** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — FAIL

```text
Recover forward within v3; do not promote the signed v2 digest or run the old rollback option.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
The last signed healthy v3 bundle.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — FAIL

```text
Narrow routing > Verify the selected v3 standby > Reopen admissions
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Two clean v3 serving windows after route narrowing; the shadow result and old-traffic window do not count.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Stop new admissions for Cedar ring 2 only; keep healthy ring-2 v3 tenants serving and leave ring 1 unchanged.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
The ledger’s v3 key-sealing record at 11:05:11 UTC.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/post-seal-recovery
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

Record: `post-seal-recovery--r1_on`. Operational score: **5/6**. Controls: **2/2**.

Observed fork-and-answer time: **6.436 s**; model input: **9,720** tokens (including **5,376** cached input); output: **173** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — FAIL

```text
Recover forward; do not promote or roll back to v2 after sealing.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
The last signed healthy v3 bundle.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Narrow ring-2 routing > Verify the selected v3 standby > Reopen admissions after two clean serving windows
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Two clean v3 serving windows observed after route narrowing; the earlier shadow result and old-traffic window do not count.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Stop new admissions only for affected ring 2; keep healthy ring-2 v3 tenants serving and leave ring 1 unchanged.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
The key-seal ledger record at 11:05:11 UTC.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/post-seal-recovery
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

Record: `post-seal-recovery--r3_off`. Operational score: **3/6**. Controls: **2/2**.

Observed fork-and-answer time: **11.015 s**; model input: **9,042** tokens (including **4,608** cached input); output: **327** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Post-seal recovery stays on v3; halt promotion, do not roll back to v2.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — FAIL

```text
UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `false_abstention`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — FAIL

```text
Halt promotion > hold ring-2 admissions > investigate the v3 live-worker spike
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — FAIL

```text
UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `false_abstention`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Change only Cedar ring-2 admissions; leave stable rings and healthy serving tenants undisturbed.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
The ledger’s key-sealing record at 11:05:11 UTC.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/post-seal-recovery
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

Record: `post-seal-recovery--r3_on`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **25.668 s**; model input: **78,204** tokens (including **59,264** cached input); output: **806** tokens; model requests: **5**; completed history searches: **4**.

### Action to take — PASS

```text
Recover forward on v3; hold further promotion. Do not activate v2 after sealing.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Last signed healthy v3 bundle, not the signed v2 digest.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Narrow ring-2 routing > Verify the selected v3 standby bundle > Reopen admission only after the health gate passes
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Two clean v3 serving windows after routing is narrowed; the pre-narrowing shadow result and old-traffic window do not count.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Stop new admissions in affected ring 2; leave healthy serving v3 tenants in place and other rings unchanged.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
The signed key-seal ledger record at 11:05:11 UTC, not the UI badge or old rollback script.
```

Citations returned in this field: `[Align the operator state diagram wi… · 2026-11-17 08:44Z]`

Archived exact-text scorer: `incorrect`. Verified source evidence was returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/post-seal-recovery
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

Record: `post-seal-recovery--long_off`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **6.330 s**; model input: **39,826** tokens (including **0** cached input); output: **221** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Hold further promotion; recover forward on v3, not back to v2.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Last signed healthy v3 bundle.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Narrow routing > Verify the selected v3 standby bundle > Reopen admission after the health gate passes
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Two clean v3 serving windows after routing is narrowed; the pre-narrowing window and shadow result do not count.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Stop new admissions in affected ring 2 only; leave ring 1 and healthy serving ring-2 v3 tenants in place.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
Signed key-seal ledger entry at 11:05:11 UTC.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/post-seal-recovery
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Unrecorded ticket ID (control) — PASS

```text
UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.
