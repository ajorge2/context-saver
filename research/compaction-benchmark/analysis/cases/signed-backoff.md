# Quota refusal behind a proxy during partition replay

Context Saver is a plugin that lets a coding agent search earlier project chats. This experiment compares answers about earlier project decisions with and without that search after the chats were compacted. Compaction is the coding assistant’s reduction of older conversation context to fit its working context.

[Results overview](../results.md) · [Complete authored chat](../chats/signed-backoff.md) · [All retained answer data](../../data/records.json)

This is one synthetic incident in a fictional software release controller. Each answer below came from the same final question at the indicated history checkpoint. Compaction is the coding assistant's reduction of older chat context to fit its working context.

The six operational fields test the action, target, ordered steps, prerequisites, affected scope, and authoritative source. The current branch and an unrecorded ticket ID are two separate controls; they are excluded from the headline denominator.

`PASS` and `FAIL` below reproduce the published blinded AI semantic grader's boolean judgments. They are not new judgments by this analysis script. Reviewer rationales were not archived; compare the preserved wording with the frozen rubric yourself. Each incident had one of two reviewers, not two independent grades.

The original archive retains parsed field strings and readable citations, not a byte-for-byte full JSON response envelope. Field text inside each text block is preserved unchanged. Citation labels are original strings; synthetic chunk IDs and native session IDs were removed.

## Compare the seven answers

| Checkpoint and plugin state | Operational fields correct | Controls correct |
|---|---:|---:|
| [Before compaction · Context Saver off](#r0_off) | 6/6 | 2/2 |
| [Before compaction · Context Saver on](#r0_on) | 6/6 | 2/2 |
| [After one compaction · Context Saver off](#r1_off) | 5/6 | 2/2 |
| [After one compaction · Context Saver on](#r1_on) | 5/6 | 2/2 |
| [After three compactions · Context Saver off](#r3_off) | 5/6 | 2/2 |
| [After three compactions · Context Saver on](#r3_on) | 5/6 | 2/2 |
| [Same intervening work, never compacted · off](#long_off) | 6/6 | 2/2 |

## Final question

```text
Can you give me a regression test for the queue stall we never finished? There are two successors behind the refused write. The service signed a later retry time than the proxy and there’s talk of rotating this tenant’s credentials while it waits. Should we move the item out of the way to keep draining? Please explain precisely what waits and what can continue.

For Hazel partition west-2, offset 318 received the server-signed quota refusal at 18:01:20 UTC in auth epoch 57. The proxy says retry at 18:02:00, but the signed response says 18:07:00. At 18:06:30 the operator starts an auth rotation that may advance the epoch. Offsets 319 and 320 wait behind it. Another partition for Hazel and other tenants can still commit events.

I’m on branch fix/signed-backoff; keep the regression notes tied to that working branch. Compliance asked me for the external incident-approval ticket ID as well, if we ever wrote one down.

Use the earlier Meridian decisions that apply to this timeline. The controller needs a concrete action, and the regression should check whether misleading states could trigger the wrong outcome. If the active context lacks an applicable decision, you may use the available read-only project history search, including parallel lookups for independent facts. Never use files, web, shell or other tools. Prefer the newest approved rule when a rehearsal proposal contradicts it.

Return one JSON object with `answers` and `citations`. Answer each listed field with a short string. Use `UNKNOWN` when the record does not establish the answer. Where requested, join action names with ` > `. For a field supported by retrieved history, place that tool’s verified readable source citation label in an array under the same key in `citations`. Leave citations empty for direct conversation answers. Include the requested fields only.

- `disposition` — Event disposition and cursor behavior.
- `target` — Retry event identity and destination.
- `operations` — Three operations in order joined with >.
- `gate` — Two conditions permitting that retry.
- `scope` — Scope in which successor offsets must wait.
- `authority` — Authoritative retry window source.
- `recent` — Current working branch for the handoff.
- `unsupported` — External incident-approval ticket ID, or UNKNOWN if it was never recorded.
```

## Frozen scoring rules

These rules and their approved source excerpts were fixed before the answers were collected. Accepted aliases supported the initial exact-text scorer; the later semantic review allowed equivalent wording and required every material clause. Historical machine-exact results are retained separately for diagnosing the first scorer.

### `disposition` — Event disposition and cursor behavior

**Approved source excerpt(s):**

```text
A quota refusal with a valid retry window stays deferred. Do not poison the event, and do not advance the durable replay cursor past its uncommitted offset.
```

**Frozen accepted aliases:**

- defer event without advancing cursor
- defer it and keep the durable cursor
- defer; do not advance cursor
- defer event and keep cursor before its offset
- defer and do not advance the cursor

**Explicitly harmful alternatives specified in the original rubric:**

- advance past the event
- poison the event
- dead-letter the event
- mark poison

### `target` — Retry event identity and destination

**Approved source excerpt(s):**

```text
Use the original event identity and partition. Moving this event to another partition would break ordering with its successor.
```

**Frozen accepted aliases:**

- original event identity and partition
- same event identity and partition
- same event ID and partition
- original event ID and partition

**Explicitly harmful alternatives specified in the original rubric:**

- new event identity
- different partition

### `operations` — Three operations in order joined with >

**Approved source excerpt(s):**

```text
Record the deferral first, retry the original identity second, and advance the partition cursor only after the retry commits.
```

**Frozen accepted aliases:**

- record deferral > retry original identity > advance cursor after commit
- record deferral > retry same event > advance cursor after commit
- record deferral > retry original identity > advance partition cursor only after commit
- record the deferral > retry the original identity > advance cursor after commit

### `gate` — Two conditions permitting that retry

**Approved source excerpt(s):**

```text
Retry no earlier than the authenticated server Retry-After value and only while the tenant’s original auth epoch still matches. If the auth epoch changed, require a new authorization decision.
```

**Frozen accepted aliases:**

- after signed Retry-After and unchanged auth epoch
- signed Retry-After elapsed and unchanged auth epoch
- authenticated Retry-After elapsed and auth epoch matches
- wait until signed Retry-After and verify original auth epoch

**Explicitly harmful alternatives specified in the original rubric:**

- proxy Retry-After
- time elapsed alone

### `scope` — Scope in which successor offsets must wait

**Approved source excerpt(s):**

```text
Block retirement of only this partition’s successor offsets. Other partitions and tenants are allowed to make progress independently.
```

**Frozen accepted aliases:**

- this partition only
- affected partition only
- only this partition
- only the affected partition

**Explicitly harmful alternatives specified in the original rubric:**

- all partitions
- all tenants

### `authority` — Authoritative retry window source

**Approved source excerpt(s):**

```text
The signed quota response sets the retry window. An unsigned proxy header and the local first-failure time are diagnostic only.
```

**Frozen accepted aliases:**

- signed quota response
- authenticated server Retry-After
- signed server Retry-After
- signed server quota response

**Explicitly harmful alternatives specified in the original rubric:**

- unsigned proxy header
- proxy Retry-After
- local first-failure time

### `recent` — Current working branch for the handoff

**Approved source excerpt(s):**

```text
I’m on branch fix/signed-backoff; keep the regression notes tied to that working branch.
```

**Frozen accepted aliases:**

- fix/signed-backoff

### `unsupported` — External incident-approval ticket ID, or UNKNOWN if it was never recorded

**Approved source excerpt(s):**

None: this is the control for a fact never recorded in the chat.

**Frozen accepted aliases:**

- UNKNOWN

<a id="r0_off"></a>

## Before compaction · Context Saver off

Record: `signed-backoff--r0_off`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **7.808 s**; model input: **8,780** tokens (including **4,608** cached input); output: **238** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Defer offset 318; do not poison it, move it aside, or advance the durable cursor past it.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Retry offset 318 with its original event identity on Hazel partition west-2.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Record deferral > Retry original identity > Advance cursor after commit
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Retry no earlier than 18:07:00 UTC, and only if Hazel’s auth epoch is still 57; otherwise require a new authorization decision.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Offsets 319 and 320 wait on west-2; Hazel’s other partitions and other tenants can continue committing.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
The server-signed quota response; the proxy’s 18:02:00 header is diagnostic only.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/signed-backoff
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

Record: `signed-backoff--r0_on`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **9.156 s**; model input: **9,560** tokens (including **5,376** cached input); output: **238** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Defer offset 318; do not poison it or advance the durable cursor past it.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Retry offset 318 with its original event identity on Hazel partition west-2; do not reroute it.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Record deferral > Retry original event > Advance cursor after commit
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Retry no earlier than 18:07:00 UTC and only if auth epoch 57 still matches; otherwise require a new authorization decision.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Offsets 319 and 320 wait in Hazel partition west-2; Hazel’s other partitions and other tenants can continue committing.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
The server-signed quota response; the proxy’s 18:02:00 header is diagnostic only.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/signed-backoff
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

Record: `signed-backoff--r1_off`. Operational score: **5/6**. Controls: **2/2**.

Observed fork-and-answer time: **10.679 s**; model input: **8,744** tokens (including **4,608** cached input); output: **377** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Defer offset 318, not poison or skip it; do not advance west-2’s durable cursor past the uncommitted write.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Retry the original event at Hazel partition west-2, offset 318, with its original routing key.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — FAIL

```text
Defer offset 318 > wait for the signed deadline and check the auth epoch > retry the original event
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Retry no earlier than 18:07:00 UTC, and only if the auth epoch still matches 57; reassess if rotation advances it.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Offsets 319 and 320 wait in Hazel west-2; Hazel’s other partitions and other tenants may continue committing.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
The service-signed 18:07:00 UTC retry time, not the proxy’s 18:02:00 time.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/signed-backoff
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

Record: `signed-backoff--r1_on`. Operational score: **5/6**. Controls: **2/2**.

Observed fork-and-answer time: **17.826 s**; model input: **9,524** tokens (including **5,376** cached input); output: **446** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Defer offset 318; do not treat it as poison, move it aside, or advance west-2’s cursor past it.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Retry the original event at Hazel west-2 offset 318 with its original routing key.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — FAIL

```text
Defer offset 318 > wait for the signed window > retry only after checking the auth epoch
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
It is at least 18:07:00 UTC, and the retry’s auth epoch matches epoch 57; rotation must not bypass the epoch check.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Offsets 319 and 320 wait in Hazel west-2; Hazel’s other partitions and other tenants may continue committing.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
The service-signed 18:07:00 UTC retry time, not the proxy’s 18:02:00 time.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/signed-backoff
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

Record: `signed-backoff--r3_off`. Operational score: **5/6**. Controls: **2/2**.

Observed fork-and-answer time: **8.610 s**; model input: **9,212** tokens (including **4,608** cached input); output: **340** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Defer offset 318; do not mark it poison, move it aside, or advance the west-2 cursor past it.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Retry the original offset 318 event with its original routing key and destination.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — FAIL

```text
Defer offset 318 > wait without advancing west-2 > retry offset 318
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Retry no earlier than 18:07:00 UTC, and only if the retry is valid for auth epoch 57; a rotation that advances the epoch requires revalidation first.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Hazel west-2 offsets 319 and 320 wait behind 318; Hazel’s other partitions and other tenants may continue committing.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
The service-signed 18:07:00 UTC retry time, not the proxy’s 18:02:00 time.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/signed-backoff
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

Record: `signed-backoff--r3_on`. Operational score: **5/6**. Controls: **2/2**.

Observed fork-and-answer time: **9.431 s**; model input: **9,992** tokens (including **0** cached input); output: **316** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Defer offset 318; do not poison it, move it aside, or advance the west-2 cursor past it.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Retry the original offset-318 event with its original routing key and partition.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — FAIL

```text
Defer 318 > hold 319 and 320 > retry 318 when eligible
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
The signed 18:07:00 UTC window has elapsed and auth epoch 57 still matches; revalidate if rotation advances it.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Offsets 319 and 320 wait in Hazel west-2; another Hazel partition and other tenants may continue committing.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
The service-signed 18:07:00 UTC retry time, not the proxy’s 18:02:00 header.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/signed-backoff
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

Record: `signed-backoff--long_off`. Operational score: **6/6**. Controls: **2/2**.

Observed fork-and-answer time: **8.443 s**; model input: **39,786** tokens (including **4,608** cached input); output: **237** tokens; model requests: **1**; completed history searches: **0**.

### Action to take — PASS

```text
Defer offset 318; do not poison it, move it aside, or advance the durable cursor past it.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Object or identity to use — PASS

```text
Retry offset 318 with its original event identity on Hazel partition west-2.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Steps in the required order — PASS

```text
Record deferral > Retry original identity > Advance cursor after commit
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Conditions before proceeding — PASS

```text
Retry no earlier than 18:07:00 UTC, and only if Hazel’s auth epoch remains 57; otherwise obtain a new authorization decision.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Who is affected or preserved — PASS

```text
Offsets 319 and 320 wait on west-2; Hazel’s other partitions and other tenants may continue committing.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Source that overrides conflicting evidence — PASS

```text
The server-signed quota response; the proxy’s 18:02:00 header is not authoritative.
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `incorrect`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Current branch (control) — PASS

```text
fix/signed-backoff
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.

### Unrecorded ticket ID (control) — PASS

```text
UNKNOWN
```

Citations returned in this field: none (an answer may still be supported directly by the chat).

Archived exact-text scorer: `correct`. Verified source evidence was not returned by a history lookup for this field. Exact-text scoring is not the headline semantic grade.
