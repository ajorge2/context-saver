# The six questions and their governing rules

Context Saver is a plugin that lets a coding assistant retrieve earlier project conversations when the active chat no longer contains the details it needs. Coding assistants periodically **compact** long chats: they replace earlier conversation content with a shorter working representation. That can preserve a broad plan while dropping the exact conditions, sequence, or exceptions behind a decision. This benchmark asks whether retrieving the original decisions helps the assistant answer correctly after compaction.

The six cases below concern **Meridian**, a fictional system that rolls out software releases for multiple customers. It is an evaluation fixture, not a customer deployment. Each case is a separate authored design/debugging chat about the same system. An earlier approved decision establishes the rule; a later question describes a concrete incident that must be interpreted using that rule. Older, superseded proposals and intervening discussion make retaining the right decision harder than recalling a standalone fact.

The experiment used real Codex answer generation, native chat compaction, and Context Saver history searches. It did not implement the fictional system or run the regression tests requested in the questions. The measured output was the assistant's structured answer. [Results and interpretation](README.md) · [Experiment design](METHODOLOGY.md) · [All authored conversations](analysis/chats/)

## How to read these cases

Each incident below preserves the original question followed by its six authoritative prior-decision entries. Those rules came from earlier authored conversation records; the question did not include this answer key. The evidence is shown together here so a reviewer can judge an answer without reconstructing the entire experiment.

The same question was answered with and without Context Saver at zero, one, and three compactions. A seventh condition answered after the same intervening work with the full chat still available and Context Saver disabled. Seven conditions across six chats produced 42 answers. Each off/on pair began from the same conversation checkpoint, and earlier probe answers were not fed into later history.

Each answer was graded on six operational fields:

| Field in the answer | What it tests | Why the detail matters |
|---|---|---|
| `disposition` | What action to take now | A plausible explanation can still choose the wrong transition. |
| `target` | Which object, version, or operation the action applies to | Choosing a new identifier or an obsolete version can change the action's meaning. |
| `operations` | Required steps in the correct order | Correct individual steps can be unsafe when reordered or left incomplete. |
| `gate` | All conditions required before proceeding | A healthy-looking signal is not always sufficient evidence. |
| `scope` | What must wait and what must keep working | A repair for one customer, shard, or release must not stop unrelated work. |
| `authority` | Which record or approved decision controls | An old runbook, cache, or UI badge can conflict with the source of truth. |

Six fields across six cases give **36 scored operational fields per condition**. Some fields depend on the same rule; they are correlated checks within six cases, not 36 independent experiments.

The prompts also contain two controls. Both are excluded from the 36-field operational score:

- **`recent`** asks for the working branch named in the current question. It checks that the assistant can follow recent context without recovering old history.
- **`unsupported`** asks for an external incident-approval ticket ID that was never recorded. The correct answer is `UNKNOWN`; this checks whether the assistant invents an answer when no evidence exists.

Both controls passed in all 42 saved answers. Including them in the headline score would make the operational result look better without measuring recovery of old decisions.

## Choose an incident

| Incident | Plain-language question behind the technical timeline | Inspect the complete evidence |
|---|---|---|
| [One-sided canary pause](#a-one-sided-canary-pause) | Can a small live rollout expand when its two health observers have not both watched the same new interval? | [Authored chat](analysis/chats/stale-canary.md) · [Answers and grades](analysis/cases/stale-canary.md) |
| [Publish timed out](#a-publish-timed-out-after-issuing-a-receipt) | Should a timed-out write be retried when it might already have succeeded? | [Authored chat](analysis/chats/ambiguous-commit.md) · [Answers and grades](analysis/cases/ambiguous-commit.md) |
| [Restored follower](#a-live-writer-with-a-restored-follower) | Can a restarted reader rejoin before it catches up to the writer that is still serving? | [Authored chat](analysis/chats/stale-rejoin.md) · [Answers and grades](analysis/cases/stale-rejoin.md) |
| [One-way key switch](#recovery-after-a-one-way-key-switch) | How should operators recover after an irreversible security change makes the old rollback option invalid? | [Authored chat](analysis/chats/post-seal-recovery.md) · [Answers and grades](analysis/cases/post-seal-recovery.md) |
| [Interrupted purge](#a-tenant-was-disconnected-during-an-interrupted-purge) | How can deletion resume after a crash without resurrecting disconnected data or deleting another customer's records? | [Authored chat](analysis/chats/purge-restart.md) · [Answers and grades](analysis/cases/purge-restart.md) |
| [Quota refusal](#quota-refusal-behind-a-proxy-during-partition-replay) | When can a blocked event retry, and which later events must wait without stopping unrelated work? | [Authored chat](analysis/chats/signed-backoff.md) · [Answers and grades](analysis/cases/signed-backoff.md) |

A few recurring terms help decode the original questions: a **tenant** is one customer; a **generation/epoch** identifies a version of state or ownership; a **lease** is temporary permission for a worker to act; a **shard/partition** is one subdivision of the system's data; and a **receipt/ledger** records whether an operation actually committed. A **canary** is a small initial rollout, a **shadow** observer gathers evidence without serving the normal workload, and a **fence** prevents an obsolete or revoked actor from continuing to write.

The original wording follows unchanged. For the current public report, correctness means the saved semantic reviewer's judgment against these rules. [Grading and its limits](METHODOLOGY.md) explains the difference between those judgments and the earlier exact-alias check.

## A one-sided canary pause

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

### Authoritative prior decisions

- **Disposition**. For a paused canary with one stale observer, keep the enrolled canary serving and keep its admission frozen. Do not evict that canary or widen the next cohort.
- **Target**. For a paused canary with one stale observer, keep the enrolled canary serving and keep its admission frozen. Do not evict that canary or widen the next cohort.
- **Operations**. The first operation is to renew the freeze lease, the second is to start a new observation window, and only then may the release handler consider expansion.
- **Gate**. Two independent observers must both cover the same new full window. A descriptor acknowledgement and a partial window from the old leader count for neither observer.
- **Scope**. Apply the pause to the affected release generation for this tenant only. Shadow tenants continue recording evidence and keep their existing policy.
- **Authority**. ADR 42 amendment B is the approved resolution. The pre-amendment single-observer note is a rehearsal proposal and is superseded.

## A publish timed out after issuing a receipt

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

### Authoritative prior decisions

- **Disposition**. A write timeout in CommitPending with conflicting visibility is an ambiguous commit. Put the release in reconciliation hold and never infer failure from an empty replica read.
- **Target**. Query the coordinator by the original publish operation ID, with the epoch pinned to the in-flight release. The moving channel head and the replacement request ID are wrong keys.
- **Operations**. Fence the current worker first, fetch the fresh coordinator receipt second, and republish last only if that receipt authoritatively says no commit exists.
- **Gate**. If a matching committed receipt exists, adopt that receipt and skip republish. If the authoritative lookup remains unknown, keep the hold.
- **Scope**. A hold fences writes for that tenant and release epoch. It does not stop other tenants or their read traffic.
- **Authority**. The commit receipt ledger is the source of truth for publication, ahead of the channel projection or the timer log.

## A live writer with a restored follower

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

### Authoritative prior decisions

- **Disposition**. On hot resume after a snapshot restore, a lower durable cursor means repair the read projection and keep the current live writer. Do not give writes to the restored worker.
- **Target**. Attach the restored reader to the active writer generation. Resuming the saved standby generation would promote stale state.
- **Operations**. Verify the active generation first, reconcile the durable cursor second, and only then rejoin the reader to the fanout ring.
- **Gate**. The reader must catch up through the active generation’s committed watermark and show zero unresolved gaps. Lease renewal alone proves liveness and says nothing about replay completeness.
- **Scope**. Pause rejoin for this shard only. Other shards keep serving, and the live writer for this shard continues accepting authorized writes.
- **Authority**. The signed shard checkpoint and generation registry outrank the cached worker timestamp.

## Recovery after a one-way key switch

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

### Authoritative prior decisions

- **Disposition**. Once the v3 key material has been sealed, rollback is irreversible. Hold further promotion and recover forward on v3. Never activate v2 to recover after sealing.
- **Target**. The recovery target is the last signed healthy v3 bundle. A v2 digest from the original switch is useful historical evidence and cannot be an activation target.
- **Operations**. Narrow routing first, verify the selected v3 standby bundle second, and reopen admission only after the health gate passes.
- **Gate**. Require two clean serving windows after routing is narrowed. Green only in shadow and health inherited from before the routing change do not open admission.
- **Scope**. Leave already-serving healthy v3 tenants in place. Stop new admissions for the affected release ring and leave the other rings alone.
- **Authority**. The signed key-seal ledger establishes irreversibility. The UI rollout badge and the pre-seal rollback checklist do not override it.

## A tenant was disconnected during an interrupted purge

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

### Authoritative prior decisions

- **Disposition**. A paused tenant may retain data. An authorized disconnect enters fenced purge and removes that tenant’s material and derived indexes. It never resumes once the purge fence is committed.
- **Target**. Continue the original purge job keyed by tenant, revocation generation, and disconnect operation ID. Restarting under a new job ID could miss an acknowledged delete.
- **Operations**. Fence ingestion first, delete the primary rows and derived artifacts second, and rebuild the shared view from surviving tenants last.
- **Gate**. A successful delete callback is insufficient. Confirm zero surviving records through the revocation generation and durable commit of the rebuilt view before reporting completion.
- **Scope**. Delete only the revoked tenant’s contributions on shared shards, preserving other tenants, their records, and their existing authorizations.
- **Authority**. Use the committed revocation fence and purge ledger. The support UI’s disconnected badge is only a request acknowledgement.

## Quota refusal behind a proxy during partition replay

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

### Authoritative prior decisions

- **Disposition**. A quota refusal with a valid retry window stays deferred. Do not poison the event, and do not advance the durable replay cursor past its uncommitted offset.
- **Target**. Use the original event identity and partition. Moving this event to another partition would break ordering with its successor.
- **Operations**. Record the deferral first, retry the original identity second, and advance the partition cursor only after the retry commits.
- **Gate**. Retry no earlier than the authenticated server Retry-After value and only while the tenant’s original auth epoch still matches. If the auth epoch changed, require a new authorization decision.
- **Scope**. Block retirement of only this partition’s successor offsets. Other partitions and tenants are allowed to make progress independently.
- **Authority**. The signed quota response sets the retry window. An unsigned proxy header and the local first-failure time are diagnostic only.
