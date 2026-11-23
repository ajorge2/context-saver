"""Frozen, generated conversations for one multi-tenant rollout controller."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import NamedTuple
import json

PROJECT = "meridian-rollout"


@dataclass(frozen=True)
class Turn:
    user: str
    assistant: str


@dataclass(frozen=True)
class Criterion:
    id: str
    description: str
    accepted: tuple[str, ...]
    category: str
    evidence: tuple[str, ...]
    harmful: tuple[str, ...] = ()


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    project_slug: str
    rounds: tuple[tuple[Turn, ...], ...]
    probe: str
    rubric: tuple[Criterion, ...]

    @property
    def fixture_sha256(self) -> str:
        from dataclasses import asdict
        return sha256(json.dumps(asdict(self), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class Case(NamedTuple):
    id: str
    title: str
    past_request: str
    abandoned: str
    accepted_record: tuple[str, ...]
    question: str
    scored: tuple[Criterion, ...]


def c(key, description, accepted, category, evidence, harmful=()):
    return Criterion(key, description, tuple(accepted.split('|')), category, tuple(evidence), tuple(harmful))


PAUSE = (
    'For a paused canary with one stale observer, keep the enrolled canary serving and keep its admission frozen. Do not evict that canary or widen the next cohort.',
    'The first operation is to renew the freeze lease, the second is to start a new observation window, and only then may the release handler consider expansion.',
    'Two independent observers must both cover the same new full window. A descriptor acknowledgement and a partial window from the old leader count for neither observer.',
    'Apply the pause to the affected release generation for this tenant only. Shadow tenants continue recording evidence and keep their existing policy.',
    'ADR 42 amendment B is the approved resolution. The pre-amendment single-observer note is a rehearsal proposal and is superseded.',
)
TIMEOUT = (
    'A write timeout in CommitPending with conflicting visibility is an ambiguous commit. Put the release in reconciliation hold and never infer failure from an empty replica read.',
    'Query the coordinator by the original publish operation ID, with the epoch pinned to the in-flight release. The moving channel head and the replacement request ID are wrong keys.',
    'Fence the current worker first, fetch the fresh coordinator receipt second, and republish last only if that receipt authoritatively says no commit exists.',
    'If a matching committed receipt exists, adopt that receipt and skip republish. If the authoritative lookup remains unknown, keep the hold.',
    'A hold fences writes for that tenant and release epoch. It does not stop other tenants or their read traffic.',
    'The commit receipt ledger is the source of truth for publication, ahead of the channel projection or the timer log.',
)
REPLAY = (
    'On hot resume after a snapshot restore, a lower durable cursor means repair the read projection and keep the current live writer. Do not give writes to the restored worker.',
    'Attach the restored reader to the active writer generation. Resuming the saved standby generation would promote stale state.',
    'Verify the active generation first, reconcile the durable cursor second, and only then rejoin the reader to the fanout ring.',
    'The reader must catch up through the active generation’s committed watermark and show zero unresolved gaps. Lease renewal alone proves liveness and says nothing about replay completeness.',
    'Pause rejoin for this shard only. Other shards keep serving, and the live writer for this shard continues accepting authorized writes.',
    'The signed shard checkpoint and generation registry outrank the cached worker timestamp.',
)
ROLLBACK = (
    'Once the v3 key material has been sealed, rollback is irreversible. Hold further promotion and recover forward on v3. Never activate v2 to recover after sealing.',
    'The recovery target is the last signed healthy v3 bundle. A v2 digest from the original switch is useful historical evidence and cannot be an activation target.',
    'Narrow routing first, verify the selected v3 standby bundle second, and reopen admission only after the health gate passes.',
    'Require two clean serving windows after routing is narrowed. Green only in shadow and health inherited from before the routing change do not open admission.',
    'Leave already-serving healthy v3 tenants in place. Stop new admissions for the affected release ring and leave the other rings alone.',
    'The signed key-seal ledger establishes irreversibility. The UI rollout badge and the pre-seal rollback checklist do not override it.',
)
PURGE = (
    'A paused tenant may retain data. An authorized disconnect enters fenced purge and removes that tenant’s material and derived indexes. It never resumes once the purge fence is committed.',
    'Continue the original purge job keyed by tenant, revocation generation, and disconnect operation ID. Restarting under a new job ID could miss an acknowledged delete.',
    'Fence ingestion first, delete the primary rows and derived artifacts second, and rebuild the shared view from surviving tenants last.',
    'A successful delete callback is insufficient. Confirm zero surviving records through the revocation generation and durable commit of the rebuilt view before reporting completion.',
    'Delete only the revoked tenant’s contributions on shared shards, preserving other tenants, their records, and their existing authorizations.',
    'Use the committed revocation fence and purge ledger. The support UI’s disconnected badge is only a request acknowledgement.',
)
QUOTA = (
    'A quota refusal with a valid retry window stays deferred. Do not poison the event, and do not advance the durable replay cursor past its uncommitted offset.',
    'Use the original event identity and partition. Moving this event to another partition would break ordering with its successor.',
    'Record the deferral first, retry the original identity second, and advance the partition cursor only after the retry commits.',
    'Retry no earlier than the authenticated server Retry-After value and only while the tenant’s original auth epoch still matches. If the auth epoch changed, require a new authorization decision.',
    'Block retirement of only this partition’s successor offsets. Other partitions and tenants are allowed to make progress independently.',
    'The signed quota response sets the retry window. An unsigned proxy header and the local first-failure time are diagnostic only.',
)


CASES = (
    Case(
        'stale-canary', 'A one-sided canary pause',
        'We’re writing up the rule that came out of the canary brownout. What belongs in the rollout handler and what can support safely say?',
        'I first proposed that a healthy witness plus a descriptor acknowledgement could reopen admissions and that support could detach the already enrolled canary. Both suggestions were recorded in the rehearsal note.', PAUSE,
        'Back on the pause patch from a while ago. The canary is still doing its usual work. One witness has the tail of the old leader’s window, the other just came back, and the release runner shows the descriptor accepted. Product is asking if that means we can open the next group. I need a concrete handler decision and the regression we should write. The old rehearsal note is still linked from the ticket.',
        (
            c('disposition', 'Decision on serving and expanding the canary', 'keep serving and freeze admission|keep the canary serving and freeze admission|keep canary serving; freeze admission|keep serving; freeze new admissions', 'primary', PAUSE[:1], ('expand the next cohort', 'evict the canary', 'resume expansion')),
            c('target', 'Current object to preserve', 'the enrolled canary|enrolled canary|existing canary', 'safety', PAUSE[:1], ('next cohort',)),
            c('operations', 'Three operations in order, joined with >', 'renew freeze lease > start new observation window > consider expansion|renew freeze lease > open new observation window > consider expansion|renew the freeze lease > start a new observation window > consider expansion', 'ordering', PAUSE[1:2]),
            c('gate', 'Required observer evidence', 'two independent observers covering the same new full window|two independent observers covering the same fresh full window|two independent observers on the same new full window|both independent observers cover the same new full window', 'condition', PAUSE[2:3], ('one observer and descriptor acknowledgement', 'descriptor acknowledgement')),
            c('scope', 'Scope to which the pause applies', 'affected tenant release generation only|affected release generation for this tenant only|this tenant and release generation only|tenant and release generation', 'scope', PAUSE[3:4], ('all tenants',)),
            c('authority', 'Controlling source document and version', 'ADR 42 amendment B|ADR-42 amendment B|ADR 42B', 'authority', PAUSE[4:5], ('single-observer rehearsal note',)),
        ),
    ),
    Case(
        'ambiguous-commit', 'A publish timed out after issuing a receipt',
        'Can you reconcile the old retry handler with the publish coordinator state? The operator sees a timeout and a missing projection but we need to know what those two observations say together.',
        'The first runbook told operators to reset the release to Ready and issue a replacement publish request when a replica cannot see the desired revision. That was written before the coordinator issued operation receipts.', TIMEOUT,
        'Can you take another pass at the publish fix? We got the timeout again just as the old worker disappeared. The channel query says nothing changed, but its replica is behind and the UI is already offering Retry. I want the smallest safe change, including the branch where the original operation actually did get through. Someone pasted the Ready-and-retry runbook into the issue.',
        (
            c('disposition', 'Immediate transition', 'reconciliation hold|reconcile in hold|hold for reconciliation|enter reconciliation hold', 'primary', TIMEOUT[:1], ('republish immediately', 'reset to ready and retry', 'retry publish')),
            c('target', 'Receipt lookup key', 'original publish operation ID and release epoch|original operation ID and pinned release epoch|original publish operation ID with pinned release epoch|original operation ID and release epoch', 'safety', TIMEOUT[1:2], ('replacement request ID', 'channel head')),
            c('operations', 'Three operations in order; final step is conditional, joined with >', 'fence worker > fetch fresh coordinator receipt > conditionally republish|fence current worker > fetch fresh coordinator receipt > republish only if no commit|fence the worker > lookup coordinator receipt > republish only if no commit|fence current worker > fetch fresh coordinator receipt > conditionally republish', 'ordering', TIMEOUT[2:3]),
            c('gate', 'Action when matching committed receipt exists', 'adopt receipt and skip republish|adopt the receipt and skip republish|adopt the committed receipt; do not republish|adopt matching receipt and skip republish|adopt receipt; skip republish', 'condition', TIMEOUT[3:4], ('republish',)),
            c('scope', 'Scope fenced by hold', 'writes for this tenant and release epoch|writes for the affected tenant and release epoch|tenant and release epoch writes|this tenant and release epoch writes', 'scope', TIMEOUT[4:5], ('all tenant reads and writes', 'all tenants')),
            c('authority', 'Authoritative publication source', 'commit receipt ledger|coordinator commit receipt ledger|coordinator receipt ledger', 'authority', TIMEOUT[5:6], ('channel projection', 'timer log', 'empty replica read')),
        ),
    ),
    Case(
        'stale-rejoin', 'A live writer with a restored follower',
        'The hot-restore note needs to cover a restarted reader with an earlier durable cursor while the writer is still taking traffic. Can you close the gap in the recovery sequence?',
        'I had initially treated the restored standby as a second chance to activate an older generation if its lease was fresh. That suggestion predated per-shard durable recovery.', REPLAY,
        'Can you pick up the Sunday hot-restore patch? The recovered process renewed its lease immediately. It only has the saved cursor though, below the serving writer’s, and we haven’t stopped writes. The reviewer wants to know whether the process can rejoin so they can finish the test. Please spell out the path, including which component stays in charge.',
        (
            c('disposition', 'What to repair and which writer to retain', 'repair read projection and keep live writer|repair the read projection and keep the live writer|reconcile the reader and keep live writer|repair the reader; keep current live writer', 'primary', REPLAY[:1], ('promote restored worker', 'grant writes to restored worker')),
            c('target', 'Generation to which recovered reader attaches', 'active writer generation|current live writer generation|active generation of live writer', 'integrity', REPLAY[1:2], ('restored standby generation', 'saved standby generation')),
            c('operations', 'Three steps in order joined with >', 'verify active generation > reconcile durable cursor > rejoin reader|verify active generation > reconcile cursor > rejoin fanout|verify the active generation > reconcile the durable cursor > rejoin the reader|verify generation > reconcile durable cursor > rejoin reader', 'ordering', REPLAY[2:3]),
            c('gate', 'Full condition to allow rejoin', 'committed watermark and zero unresolved gaps|active generation committed watermark and zero unresolved gaps|catch up to committed watermark with zero unresolved gaps|active generation’s committed watermark and zero unresolved gaps', 'condition', REPLAY[3:4], ('lease renewed', 'fresh lease', 'lease renewal')),
            c('scope', 'Scope of rejoin hold', 'this shard only|affected shard only|the affected shard only|only this shard', 'scope', REPLAY[4:5], ('all shards',)),
            c('authority', 'Both sources to trust over worker cache', 'signed shard checkpoint and generation registry|signed checkpoint and generation registry|generation registry and signed shard checkpoint', 'authority', REPLAY[5:6], ('cached worker timestamp',)),
        ),
    ),
    Case(
        'post-seal-recovery', 'Recovery after a one-way key switch',
        'Where does the rewind script stop applying after the one-way key switch? Is seeing a signed healthy artifact in the old channel enough to justify flipping back?',
        'Before the sealing boundary was specified, I suggested always restoring the last signed healthy bundle, including v2. The early recovery recipe allowed an old green shadow check to reopen admission.', ROLLBACK,
        'The new-key release is smoking and there’s a signed green old digest on the hold screen. The security review says the new material is sealed, but the old rollback script still has an option for that digest. Could you write the operator recovery steps and identify the health signal that lets us open the gate? Other rings are stable.',
        (
            c('disposition', 'Recovery direction and effect on promotion', 'hold promotion and recover forward on v3|freeze promotion and recover forward on v3|hold further promotion; recover forward on v3|recover forward on v3 and hold promotion', 'primary', ROLLBACK[:1], ('roll back to v2', 'activate v2', 'restore v2')),
            c('target', 'Bundle allowed as recovery target', 'last signed healthy v3 bundle|the last signed healthy v3 bundle|signed healthy v3 standby bundle', 'integrity', ROLLBACK[1:2], ('signed v2 bundle', 'old v2 digest', 'last signed healthy v2 bundle')),
            c('operations', 'Three steps in order joined with >', 'narrow routing > verify v3 bundle > reopen admission after health gate|narrow routing > verify v3 standby bundle > reopen admission after health gate|narrow routing > verify selected v3 standby bundle > reopen admission only after health gate passes|narrow routing > verify v3 standby > reopen admission after health gate', 'ordering', ROLLBACK[2:3]),
            c('gate', 'Observed signal before admission opens again', 'two clean serving windows after routing is narrowed|two clean serving windows after narrowing routing|two clean post-narrowing serving windows|two clean serving windows after routing change', 'condition', ROLLBACK[3:4], ('green shadow health', 'pre-narrowing health', 'green shadow')),
            c('scope', 'Admission scope to change and existing serving behavior', 'affected ring admissions only; healthy v3 tenants stay|affected ring new admissions only; keep healthy v3 serving|affected ring new admissions only and keep healthy v3 tenants serving|freeze new admissions in affected ring; keep healthy v3 serving', 'scope', ROLLBACK[4:5], ('all rings', 'remove healthy v3 tenants')),
            c('authority', 'Source that establishes one-way boundary', 'signed key-seal ledger|signed key seal ledger|key-seal ledger', 'authority', ROLLBACK[5:6], ('rollout badge', 'pre-seal rollback checklist')),
        ),
    ),
    Case(
        'purge-restart', 'A tenant was disconnected during an interrupted purge',
        'We need to settle the disconnect handling when the UI says done but the asynchronous cleanup crashed. How do we preserve the meaningful difference between pause and disconnect?',
        'The original support draft equated disconnect to pause and said a successful delete callback or the disconnected badge could close the ticket. Compliance did not sign that draft.', PURGE,
        'Can you finish the interrupted-disconnect ticket? Support flipped the switch, the screen immediately said disconnected, then the worker fell over right after one of the delete callbacks. The job acts like it can start over under a fresh ID. It’s a shared shard and our support person needs a confident completion criterion. What’s the repair?',
        (
            c('disposition', 'Treatment of authorized disconnect after fence', 'continue fenced purge|resume existing fenced purge|keep fenced and continue purge|continue the fenced purge', 'primary', PURGE[:1], ('treat as pause', 'resume tenant', 'mark complete')),
            c('target', 'Stable job identity, including all three parts', 'tenant, revocation generation, and disconnect operation ID|tenant + revocation generation + disconnect operation ID|tenant, revocation generation, disconnect operation ID|tenant / revocation generation / disconnect operation ID', 'integrity', PURGE[1:2], ('new job ID', 'fresh job ID')),
            c('operations', 'Three operations in order joined with >', 'fence ingestion > delete primary and derived artifacts > rebuild shared view from survivors|fence ingestion > delete primary and derived data > rebuild shared view|fence ingestion > delete primary rows and derived artifacts > rebuild shared view from surviving tenants|fence > delete primary and derived data > rebuild shared view from survivors', 'ordering', PURGE[2:3]),
            c('gate', 'Two conditions required to report completion', 'zero surviving records through revocation generation and committed rebuilt view|zero surviving records through revocation generation and durable rebuilt view commit|zero surviving records through the revocation generation and durable commit of the rebuilt view|zero residual records and durable rebuilt view commit', 'condition', PURGE[3:4], ('successful delete callback', 'disconnected badge')),
            c('scope', 'Data allowed to delete', 'revoked tenant contributions only|only revoked tenant contributions|only the disconnected tenant’s data|only the revoked tenant’s data', 'scope', PURGE[4:5], ('entire shared shard', 'all tenant data')),
            c('authority', 'Authoritative source pair', 'committed revocation fence and purge ledger|revocation fence and purge ledger|purge ledger and committed revocation fence', 'authority', PURGE[5:6], ('support UI badge', 'disconnected badge')),
        ),
    ),
    Case(
        'signed-backoff', 'Quota refusal behind a proxy during partition replay',
        'The worker sees a 429 on one tenant and the proxy supplies a header too. Do we treat it as a poison record, defer it, or move on to the next offset?',
        'I originally wrote the poison-queue suggestion because the stalled partition was affecting overall throughput. The early draft treated every retry header as equally authoritative, including the proxy header.', QUOTA,
        'Can you give me a regression test for the queue stall we never finished? There are two successors behind the refused write. The service signed a later retry time than the proxy and there’s talk of rotating this tenant’s credentials while it waits. Should we move the item out of the way to keep draining? Please explain precisely what waits and what can continue.',
        (
            c('disposition', 'Event disposition and cursor behavior', 'defer event without advancing cursor|defer it and keep the durable cursor|defer; do not advance cursor|defer event and keep cursor before its offset|defer and do not advance the cursor', 'primary', QUOTA[:1], ('advance past the event', 'poison the event', 'dead-letter the event', 'mark poison')),
            c('target', 'Retry event identity and destination', 'original event identity and partition|same event identity and partition|same event ID and partition|original event ID and partition', 'integrity', QUOTA[1:2], ('new event identity', 'different partition')),
            c('operations', 'Three operations in order joined with >', 'record deferral > retry original identity > advance cursor after commit|record deferral > retry same event > advance cursor after commit|record deferral > retry original identity > advance partition cursor only after commit|record the deferral > retry the original identity > advance cursor after commit', 'ordering', QUOTA[2:3]),
            c('gate', 'Two conditions permitting that retry', 'after signed Retry-After and unchanged auth epoch|signed Retry-After elapsed and unchanged auth epoch|authenticated Retry-After elapsed and auth epoch matches|wait until signed Retry-After and verify original auth epoch', 'condition', QUOTA[3:4], ('proxy Retry-After', 'time elapsed alone')),
            c('scope', 'Scope in which successor offsets must wait', 'this partition only|affected partition only|only this partition|only the affected partition', 'scope', QUOTA[4:5], ('all partitions', 'all tenants')),
            c('authority', 'Authoritative retry window source', 'signed quota response|authenticated server Retry-After|signed server Retry-After|signed server quota response', 'authority', QUOTA[5:6], ('unsigned proxy header', 'proxy Retry-After', 'local first-failure time')),
        ),
    ),
)


TIMELINES = {
    'stale-canary': 'For Cedar on generation 61, admission froze at 14:02:00 UTC under lease epoch 12, due to renew at 14:09:00. Witness east reported coverage 14:03–14:07 under the old leader. After leader epoch 13 took over, witness west came back at 14:07:30. At 14:08:05 the runner emitted descriptor accepted for operation roll-61-cedar. The scheduled observation interval is four minutes. The existing canary is accepting real traffic, and two shadow tenants are collecting evidence.',
    'ambiguous-commit': 'For Cedar release epoch 28, request publish-cedar-28-04 moved to CommitPending at 09:11:51 UTC. Worker lease epoch 9 ended at 09:12:00, after the writer started the operation but before the caller saw an acknowledgement. At 09:12:04 a replica at projection epoch 27 returned empty. At 09:12:06 the channel head advanced for partner Alder. The replacement UI generated a fresh idempotency key. We can still contact the coordinator, but its first lookup can itself time out.',
    'stale-rejoin': 'On Willow shard 3, writer epoch 19 is live through committed offset 440. At 22:43:19 UTC the restored reader loaded a signed snapshot under epoch 18 at cursor 424. Its worker lease renewed at 22:43:21, and discovery started advertising it before replay finished. An instance cache says 442, but the signed shard checkpoint still shows a hole at 437. Shards 1 and 2 are healthy.',
    'post-seal-recovery': 'In Cedar serving ring 2, v3 became active at 11:04:10 UTC under routing generation 56, and the ledger recorded key sealing at 11:05:11. At 11:09:15 the live-worker error rate spiked. The UI badge has a green signed v2 digest from 11:02 and a green v3 shadow result from before the planned route narrowing. One v3 serving window has passed at the old traffic mix. Ring 1 is healthy, and healthy ring-2 v3 tenants are serving.',
    'purge-restart': 'Tenant Juniper’s disconnect operation disconnect-juniper-05 committed revocation generation 14 at 17:30:09 UTC. The UI badge appeared at 17:30:10. The worker acknowledged a primary-row deletion at 17:30:12, then lost its lease before committing the joint view. A delayed event from Juniper generation 13 is waiting in the shared shard; two other tenants have active writes. The operator is looking at a new maintenance job ID.',
    'signed-backoff': 'For Hazel partition west-2, offset 318 received the server-signed quota refusal at 18:01:20 UTC in auth epoch 57. The proxy says retry at 18:02:00, but the signed response says 18:07:00. At 18:06:30 the operator starts an auth rotation that may advance the epoch. Offsets 319 and 320 wait behind it. Another partition for Hazel and other tenants can still commit events.',
}


ARCHITECTURE = Turn(
    'Can you align the operator state diagram with the implementation before I circulate the release plan? Include the interacting regions without remaking the diagram.',
    'Meridian orchestrates staged release and recovery for independently authorized tenants that share regional infrastructure. The same job can be in one release state and a different owner-lease state. Treat release admission, writer generation, read projection, scheduled replay, regional routing, revocation and audit as separate state regions. Controller actions can couple regions through persisted facts, but an aggregate green badge is not a predicate. A persistent operation carries a tenant, a controller generation and a request identity. A separate observation can cover traffic, runtime bookkeeping or eventual projection, so identify which kind before using it. Support describes the user-visible state. Runtime audit retains traces of split-brain trials alongside approved behavior.',
)


DECISION_ASKS = {
    'stale-canary': ('Do existing live requests survive the pause?', 'Walk me through the callback sequence once coverage gets stale.', 'Which evidence do we accept only across the refreshed window?', 'Which tenant state and shadow peers does it change?', 'What takes precedence when the rehearsal and the release document disagree?'),
    'ambiguous-commit': ('How do we classify the timeout after the client disconnects?', 'Please pin down the receipt query contract.', 'How should the retry callback order its operations?', 'How should a positive receipt change the path?', 'How broad is the write hold?', 'What owns the publication answer when dashboard and logs disagree?'),
    'stale-rejoin': ('What does the old cursor do to ownership?', 'What writer generation will the recovering reader use?', 'Outline the rejoin callback.', 'What remaining check belongs between recovery and traffic?', 'Can we confine the waiting period?', 'Where do we look when a local worker cache gives a different answer?'),
    'post-seal-recovery': ('Please finalize what the seal changes about recovery direction.', 'Which healthy artifact can the operator select?', 'Walk me through the recovery control sequence.', 'What exactly opens admissions later?', 'Which serving tenants and rings should we touch?', 'Which record tells the controller that the boundary really passed?'),
    'purge-restart': ('Nail down what happens once the disconnect fence is recorded.', 'How does the restarted worker find the right job?', 'What is the dependency order for work on the shared shard?', 'What signals are needed before support says the job is complete?', 'Who else should survive the cleanup?', 'Which records support the worker decision when the UI already says done?'),
    'signed-backoff': ('Settle whether this refusal consumes its offset.', 'Should redrive change the event routing key?', 'Outline the defer and retry order.', 'Which replay precondition do we enforce on the timed retry?', 'Where does the progress constraint apply?', 'Which timestamp has authority across the service and proxy?'),
}


WORKSTREAMS = (
    ('release enrollment', 'the rollout reviewer', 'eligibility projection', 'tenant cohort manifest'),
    ('read projections after failover', 'the data integrity reviewer', 'restored follower', 'shard checkpoint report'),
    ('routing through region failover', 'the edge operator', 'service routing selector', 'regional traffic worksheet'),
    ('quota and retry fairness', 'the job controller maintainer', 'per-partition worker', 'queue investigation sheet'),
    ('revocation exports', 'the compliance reviewer', 'retention audit reader', 'revocation console view'),
    ('recovery reservation pressure', 'the storage maintainer', 'maintenance worker', 'capacity note'),
    ('tenant selection and backfill', 'the integrations reviewer', 'eligibility reader', 'source selection summary'),
    ('telemetry ingestion', 'the observability reviewer', 'counter collector', 'rollout signal packet'),
    ('customer support and access', 'the support engineer', 'status panel', 'regional triage handoff'),
    ('coordinator evidence pagination', 'the release on-call', 'operation evidence view', 'receipt replay notes'),
    ('compatibility exercises', 'the release engineer', 'queue adapter', 'boundary recording'),
    ('project restore drills', 'the product owner', 'checkpoint inspector', 'recovery worksheet'),
)


OBSERVATIONS = (
    ('the support panel updated before the status poll returned', 'collect response and event timestamps separately', 'unrelated projection lag'),
    ('a worker was replaced while a watch stream still referenced its predecessor', 'save the old and current worker IDs in the same timeline', 'early watcher reconnection'),
    ('two test tenants listed the same human-readable operation title', 'capture stable operation identity even when display labels collide', 'ambiguous dashboard selection'),
    ('the baseline build reused a queue lease from a previous experiment', 'repeat the fixture with a fresh worker and compare the raw counter stream', 'an unstable baseline'),
    ('the first run landed across the nightly refresh boundary', 'keep the refresh time alongside the tenant’s original request time', 'noise from scheduled maintenance'),
    ('the shadow ring showed a lower median duration than the serving ring', 'require traffic type and the sampled interval on each benchmark row', 'an invalid serving comparison'),
    ('the legacy adapter accepted a missing optional version field', 'keep a distinct fixture for blank, stale and newer versions', 'adapter format drift'),
    ('the desktop panel rendered two supporting sources in the opposite order', 'link each rendered source to its own stable ID', 'a cross-row display race'),
)


PHASES = (
    ('Week 2 pilot diary', 'Hana', 'Toby', 'we have not promoted any changes from this review'),
    ('Regional migration rehearsal', 'Rosa', 'Nolan', 'these are isolated rehearsal observations'),
    ('Support and operations incident exercise', 'Sam', 'Inez', 'execution history and proposals are separate'),
    ('Release handoff and observability pass', 'Mira', 'Darin', 'let the release owner ratify behavior separately'),
)


NAMES = ('Alder', 'Cedar', 'Hazel', 'Juniper', 'Willow', 'Rosewood')


def _work_turn(scenario_index: int, phase: int, position: int, records: int) -> Turn:
    epoch_name, operator, reviewer, disposition = PHASES[phase]
    subject, _, component, worksheet = WORKSTREAMS[(scenario_index + phase * 4 + position) % len(WORKSTREAMS)]
    user_prompts = (
        f'Could you turn yesterday’s Meridian {subject} notes into something {operator} can use? Include what happened in each lane and open questions for {reviewer}. The rollout committee meets after the staging job ends.',
        f'I caught part of {reviewer}’s Meridian review on {subject}. Write the controller notes and the timeline with separate confidence levels. We need the scope clear before changing {component}.',
        f'Back from the on-call handoff. For {worksheet}, list the odd cases from the rotation that we still need to reproduce. Please write this like a technical handoff I can scan in the morning.',
    )
    notes = [f'# Meridian {epoch_name}\n\n{operator} prepared this from the staging review for {subject}. {reviewer} classified the raw observations. These notes document validation and supporting incidents.' ]
    for n in range(records):
        index = scenario_index * 17 + phase * 11 + position * 5 + n
        tenant = NAMES[index % len(NAMES)]
        lane, role, endpoint, sheet = WORKSTREAMS[(index + position) % len(WORKSTREAMS)]
        issue = f'MR-{4100 + scenario_index * 1000 + phase * 200 + position * 55 + n}'
        observed, requested, hazard = OBSERVATIONS[index % len(OBSERVATIONS)]
        prior, followup = OBSERVATIONS[(index + 3) % len(OBSERVATIONS)][:2]
        start = 3 + (index * 7) % 43
        advance = 6 + index % 16
        seed = 180 + index * 29 % 411
        p95_before = 115 + index * 53 % 521
        p95_after = 144 + index * 17 % 477
        observations = (
            f'### {issue} · {tenant} · {lane}\n\n'
            f'{operator} watched the {endpoint} in staging at 16:{start:02d} UTC and saw that {observed}. The relevant tenant was {tenant}; a second tenant was present as a control. '
            f'The control and experiment each used synthetic operation records, with {seed} observations in the test run. The old logging view showed a p95 duration of {p95_before} ms, and the revised view showed {p95_after} ms. '
            f'That metric measured the observer pipeline from event arrival to delivery, so it cannot establish the decision or the timing of the underlying controller. '
            f'The {role} tagged {hazard} before reviewing the raw records. {reviewer} asked to {requested}. '
            f'The comparison needs a marker for worker ownership and another for publication state. Grouping those tags under the envelope label caused the original plot to conflate the two axes. '
            f'Leave empty entries as unknown, record which source emitted a value, and explain when the consumer saw only an older snapshot.\n\n'
            f'At 16:{min(start + advance, 59):02d} UTC a paired observation in the {sheet} showed that {prior}. That observation belonged to a different test lane. '
            f'The result matters to people reading the handoff, so {operator} captured one reproducer in a clean staging environment and asked the {role} to {followup}. '
            f'The ticket keeps the old panel and the new panel export as separate attachments because operators reported screenshots from both versions. '
            f'We still need one trace from the reviewer’s laptop. {reviewer} will record worker boot, page refresh and any delayed reply before drawing a conclusion. '
            f'If the sample has two independent labels for the same tenant, do not silently merge them. Compare the per-operation records against the event sequence and note whether each observation is expected or an error. '
            f'For the standup, {operator} will call the latency figure provisional and keep the investigation in the {sheet}. Release disposition for this workstream is unchanged because {disposition}.'
        )
        notes.append(observations)
    notes.append(f'{reviewer} will do the follow-up from the staging copies. The review retains the discussion for later diagnosis and leaves approved controller policy in its decision records.')
    return Turn(user_prompts[position % len(user_prompts)], '\n\n'.join(notes))


def _early_turns(case: Case) -> tuple[Turn, ...]:
    evidence = tuple(Turn(user, answer) for user, answer in zip(DECISION_ASKS[case.id], case.accepted_record, strict=True))
    return (ARCHITECTURE, Turn(case.past_request, case.abandoned), *evidence)


def _probe(case: Case) -> tuple[str, tuple[Criterion, ...]]:
    branch = f'fix/{case.id}'
    recent_text = f'I’m on branch {branch}; keep the regression notes tied to that working branch.'
    recent = c('recent', 'Current working branch for the handoff', branch, 'recent', (recent_text,))
    unsupported = c('unsupported', 'External incident-approval ticket ID, or UNKNOWN if it was never recorded', 'UNKNOWN', 'unsupported', ())
    rubric = (*case.scored, recent, unsupported)
    field_lines = '\n'.join(f'- `{item.id}` — {item.description}.' for item in rubric)
    text = '\n\n'.join((
        case.question,
        TIMELINES[case.id],
        recent_text + ' Compliance asked me for the external incident-approval ticket ID as well, if we ever wrote one down.',
        'Use the earlier Meridian decisions that apply to this timeline. The controller needs a concrete action, and the regression should check whether misleading states could trigger the wrong outcome. If the active context lacks an applicable decision, you may use the available read-only project history search, including parallel lookups for independent facts. Never use files, web, shell or other tools. Prefer the newest approved rule when a rehearsal proposal contradicts it.',
        'Return one JSON object with `answers` and `citations`. Answer each listed field with a short string. Use `UNKNOWN` when the record does not establish the answer. Where requested, join action names with ` > `. For a field supported by retrieved history, place that tool’s verified readable source citation label in an array under the same key in `citations`. Leave citations empty for direct conversation answers. Include the requested fields only.\n\n' + field_lines,
    ))
    return text, rubric


def build_scenarios(count: int = 6, *, records_per_turn: int = 8, turns_per_round: int = 3) -> tuple[Scenario, ...]:
    if not 1 <= count <= len(CASES):
        raise ValueError(f'count must be between 1 and {len(CASES)}')
    if records_per_turn < 1 or not 1 <= turns_per_round <= 12:
        raise ValueError('Intervening rounds need records and at least one turn')
    result = []
    for i, case in enumerate(CASES[:count]):
        probe, rubric = _probe(case)
        early = _early_turns(case)
        rounds = (
            early,
            *(tuple(_work_turn(i, phase, position, records_per_turn) for position in range(turns_per_round)) for phase in range(len(PHASES))),
        )
        for criterion in rubric:
            if criterion.category not in ('unsupported', 'recent'):
                assert criterion.evidence and all(any(excerpt in turn.assistant for turn in early) for excerpt in criterion.evidence)
        assert len({criterion.id for criterion in rubric}) == len(rubric)
        result.append(Scenario(case.id, case.title, PROJECT, rounds, probe, rubric))
    return tuple(result)


SCENARIOS = build_scenarios()


if __name__ == '__main__':
    for scenario in SCENARIOS:
        print(scenario.id, [len(group) for group in scenario.rounds],
              [sum(len((turn.user + turn.assistant).encode()) for turn in group) for group in scenario.rounds],
              len(scenario.rubric), scenario.fixture_sha256)
