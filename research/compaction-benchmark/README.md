# Can a coding assistant retain project decisions after compaction?

Context Saver is a plugin that saves and indexes coding-agent conversations, then lets the agent retrieve original project evidence when it needs earlier decisions. Long-running assistants periodically **compact** a chat: they replace earlier conversation content with a shorter working representation. A broad plan can survive while the exception or ordering constraint behind it disappears. This experiment tests whether retrieving those earlier decisions helps an assistant answer a later, specific engineering question.

**After three compactions of each of six fictional project chats, Codex received credit for 19 of 36 decision details without Context Saver, versus 33 with it.** Each incident tested six details: what action to take, which object to use, the steps in order, the requirements for proceeding, who is affected, and which earlier decision takes precedence. These are called operational decision fields in the data. The gain came with a mean **11.67 additional seconds and 45,786 additional observed tokens per answer**. Tokens are the units of text processed by the model; the report separates cached input from new input rather than treating the total as a dollar charge.

This is a published analysis of one fixed experiment, run on November 17, 2026. The six chats concern one fictional software system; the 36 fields are correlated checks within those six cases. The scores describe this run, rather than a general accuracy rate for all coding tasks or a guarantee of safe implementation.

## Read the evidence at the level you need

| If you want to know… | Start here |
|---|---|
| What was tested, and what changed? | [The task](#what-the-assistant-had-to-do), [results](#results-at-each-compaction-checkpoint), and [case-by-case differences](#where-the-difference-came-from) below |
| Why was the experiment designed this way? | [Methodology: design, controls, grading, and scope](METHODOLOGY.md) |
| What exactly were the questions and correct rules? | [Six complete questions and their 36 governing field rules](CASEBOOK.md) |
| What did the assistant actually say? | [All six answer reports](analysis/cases/), with preserved field-level answer text, citations, and reviewer grades for every condition |
| What was in the earlier chats? | [All six authored conversations](analysis/chats/) and the [machine-readable fixture](data/fixtures.json) |
| Can I check the arithmetic myself? | [Generated results](analysis/results.md), [analysis script](analyze.py), and [machine-readable summary](analysis/summary.json) |
| Where did these records come from? | [Preserved experiment records](data/records.json), [run manifest](data/run-manifest.json), and [provenance and file hashes](data/provenance.json) |
| How do I read the data files or run the analysis? | [Data guide](DATA_GUIDE.md) and [offline reproduction instructions](REPRODUCING.md) |

The answer reports expose the exact answer strings and citation metadata retained by the original scorer. The archived scorer did not retain the complete original response envelopes; the public reports do not reconstruct them as if they were raw transcripts.

## What the assistant had to do

The fictional project, **Meridian**, manages software releases for multiple customers. Its **state machine** defines the conditions under which the system may move from one situation to another. Those rules separately track customer consent, permission for a worker to act, versions of data, records of completed operations, release health, and processing events in order. For example, renewing a worker's permission to run does not prove that it has caught up on data it missed during an outage.

Each of the six independent chats begins with authored engineering discussions that establish approved rules. The history also contains older proposals that were superseded, followed by intervening work. A later incident question provides a concrete timeline containing incomplete or misleading evidence. The assistant must apply the earlier approved rules, resolve the conflict, and return a structured decision.

The questions were designed around the details that humans often refer back to indirectly: “the pause patch from a while ago,” “the old rehearsal note,” or “the queue stall we never finished.” They require following a chain from the current incident to the earlier decision and its exceptions. They do not ask the assistant to recall arbitrary hidden strings.

In the incident descriptions below, a **canary** is a small trial release, a **lease** is temporary permission for a worker to act, and a **partition** is one subdivision of the data. A **committed** operation has been durably accepted; a missing or delayed display does not prove that it failed. The [casebook introduces the other recurring terms](CASEBOOK.md#choose-an-incident) before presenting the unedited technical questions.

| Case | Decision the question tests | Why generic engineering advice is insufficient |
|---|---|---|
| [One-sided canary pause](CASEBOOK.md#a-one-sided-canary-pause) | Keep an existing small rollout serving while withholding expansion. | Observer evidence must cover the same **new** window; an old partial interval and descriptor acknowledgement do not count. |
| [Publish timed out](CASEBOOK.md#a-publish-timed-out-after-issuing-a-receipt) | Reconcile a write that may already have committed. | The lookup must use the original operation and release version; a missing replica result does not justify retrying. |
| [Restored follower](CASEBOOK.md#a-live-writer-with-a-restored-follower) | Repair a reader without replacing the writer that is still serving. | Renewed permission to run does not prove the reader has caught up through the last accepted record or resolved every missing event. |
| [One-way key switch](CASEBOOK.md#recovery-after-a-one-way-key-switch) | Recover forward after an irreversible security change. | An old healthy version cannot be reactivated, and health evidence must come from after routing was narrowed. |
| [Interrupted purge](CASEBOOK.md#a-tenant-was-disconnected-during-an-interrupted-purge) | Resume deletion after a crash without harming another customer's data. | The repair must keep the original job identity, block new data from the disconnected customer, remove their records and associated indexes, and save a rebuilt view of the surviving data. |
| [Quota refusal](CASEBOOK.md#quota-refusal-behind-a-proxy-during-partition-replay) | Retry a blocked event without violating order or authorization. | The signed retry time and original authorization version control eligibility; unrelated partitions may continue. |

For each incident, six fields were graded: **action, target, step order, prerequisites, scope, and authority**. “Complete incident” means all six fields were correct. Two additional controls checked a working branch stated in the current question and an external ticket ID that was never recorded. They passed in all 42 answers and are excluded from the 36-field operational denominator. [Field definitions and exact controls](CASEBOOK.md#how-to-read-these-cases)

The model answered the questions only. It did not build this fictional project, edit source files, or execute the suggested regression tests. This measures retention and application of project decisions, not implementation success.

## How the comparison worked

The run used **Codex CLI 0.157.1, `gpt-6-sol`, low reasoning effort**. Each case had its own Codex chat and separate local search index of the early decision records. Before compaction, after one compaction, and after three compactions, the test runner created two new chats from the same saved conversation state:

- **Without Context Saver:** answer from the active conversation representation.
- **With Context Saver:** answer from the same checkpoint, with access to the real read-only project-history search tool. The agent could choose whether and how to retrieve, including parallel independent searches.

A seventh condition answered after the same scripted intervening work **without any compaction and without Context Saver**. This checks whether the question was still answerable from the full conversation; it scored 35/36. All seven conditions across six cases produced **42 answers**. Prior probe answers were not added to the continuing histories.

| Design choice | What it helps distinguish |
|---|---|
| Same question and parent checkpoint for each off/on pair | Retrieval availability from a different question or different conversation history |
| Baseline before compaction | Recovery of lost detail from rules the model could not apply even when available |
| One and three native compactions | How the observed difference changes along a repeated compaction trajectory |
| Same-script uncompacted control | Effects of the compacted trajectory from merely seeing more intervening work |
| Independent case indexes, fixture-only evidence | Recovery of the intended project's records from accidental access to unrelated history |
| Current-context and never-recorded controls | Historical recall from recent reading comprehension and unsupported invention |
| Frozen governing rules; blinded semantic review | Correct application of the established rule from condition-aware scoring |
| Per-case costs alongside scores | Accuracy gains from an assumption that retrieval has negligible overhead |

These controls support a paired comparison in this fixture. They do not make the six cases independent projects, repeated model samples, or a large population study. Compaction was explicitly invoked through the native host; this is not a measurement of automatic near-limit compaction under every host configuration. [Full method and replay boundaries](METHODOLOGY.md)

## Results at each compaction checkpoint

![Operational decision fields correct before compaction, after one compaction, and after three compactions, with a same-script uncompacted control.](analysis/figures/accuracy.svg)

| Checkpoint | Without Context Saver | With Context Saver | Complete incidents without / with |
|---|---:|---:|---:|
| Before compaction | 36/36 · 100.0% | 36/36 · 100.0% | 6/6 / 6/6 |
| After one compaction | 24/36 · 66.7% | 32/36 · 88.9% | 1/6 / 3/6 |
| After three compactions | 19/36 · 52.8% | 33/36 · 91.7% | 1/6 / 3/6 |
| Same scripted work, no compaction | 35/36 · 97.2% | Not run | 5/6 / — |

After three compactions, the enabled answers corrected **15 fields** that their paired controls missed and regressed **one**, for a net improvement of **14/36 fields, or 38.9 percentage points**. Both conditions got the broad action correct in **5/6 cases**. The larger difference lay in carrying the action out under the project's exact rules.

The compacted disabled answers returned `UNKNOWN` for **nine answerable operational fields**; the enabled answers did so for **zero**. That is distinct from the unsupported-ticket control, for which `UNKNOWN` was always correct.

All values in these tables are derived from the archived semantic reviewer labels. [Complete generated tables and calculations](analysis/results.md) · [Machine-readable source records](data/records.json)

## Where the difference came from

Each score below counts the same six operational fields after the third compaction. The links open the preserved answers beside the governing rules and grades.

| Incident | Without | With | Fields corrected by the enabled answer | Fields still marked incorrect with Context Saver |
|---|---:|---:|---|---|
| [Canary pause](analysis/cases/stale-canary.md) | 2/6 | 6/6 | Order, prerequisite evidence, scope, authority | None |
| [Ambiguous publish](analysis/cases/ambiguous-commit.md) | 1/6 | 5/6 | Target, order, scope, authority | Action |
| [Restored reader](analysis/cases/stale-rejoin.md) | 2/6 | 6/6 | Order, catch-up prerequisite, scope, authority | None |
| [One-way key change](analysis/cases/post-seal-recovery.md) | 3/6 | 6/6 | Recovery target, order, health prerequisite | None |
| [Interrupted purge](analysis/cases/purge-restart.md) | 6/6 | 5/6 | None; the order field regressed | Order |
| [Quota retry](analysis/cases/signed-backoff.md) | 5/6 | 5/6 | None | Order |

For a concrete example, the [key-change question](CASEBOOK.md#recovery-after-a-one-way-key-switch) presented a healthy old-version digest after an irreversible switch. The disabled answer correctly avoided rollback but returned `UNKNOWN` for both the eligible recovery target and the health prerequisite. The enabled answer named the last signed healthy new-version bundle and required two clean serving windows **after** narrowing routing. It also recovered the prescribed sequence. Read the [disabled answer](analysis/cases/post-seal-recovery.md#r3_off), [enabled answer](analysis/cases/post-seal-recovery.md#r3_on), and [original conversation](analysis/chats/post-seal-recovery.md).

The [purge regression](analysis/cases/purge-restart.md#r3_on) matters as well. The enabled answer said to fence “generation 14 ingestion,” whereas the disabled answer explicitly included a delayed generation-13 event. The approved rule fences the revoked customer's ingestion, so older delayed events must not slip through. The published reviewer marked the enabled operation sequence incorrect. In both conditions, the [quota case](analysis/cases/signed-backoff.md) omitted the required final cursor advancement after a successful retry. The report preserves failures alongside gains.

The following breakdown shows why a broad “got the action right” metric would miss much of the observed effect:

| Operational field | Without after three compactions | With after three compactions |
|---|---:|---:|
| Action (`disposition`) | 5/6 | 5/6 |
| Target | 4/6 | 6/6 |
| Steps in order (`operations`) | 1/6 | 4/6 |
| Prerequisites (`gate`) | 3/6 | 6/6 |
| Scope | 3/6 | 6/6 |
| Controlling evidence (`authority`) | 3/6 | 6/6 |

## Accuracy had a measurable cost

![Mean answer wall time and total token usage by compaction checkpoint, with and without Context Saver.](analysis/figures/overhead.svg)

| Mean per answer | Before compaction, without / with | After one, without / with | After three, without / with |
|---|---:|---:|---:|
| Wall time, including fork and setup | 7.56 / 7.54 s | 9.23 / 17.29 s | 8.20 / 19.87 s |
| Observed total tokens | 8,996 / 9,766 | 9,116 / 32,715 | 9,448 / 55,234 |

At the third checkpoint, the mean enabled-minus-disabled difference was **+11.67 seconds** and **+45,786 total tokens per answer**. The token difference includes approximately **29,760 cached input**, **15,688 uncached input**, and **337 output** tokens; separately rounded components need not add exactly to the rounded total. Observed total tokens are not a dollar-cost estimate: cached input and uncached input have different billing implications, and no pricing conversion is applied here.

The final enabled answers made **19 history searches across four of six answer turns**, returning verified source evidence for **24 operational fields**. The mean individual search took **243 ms**. End-to-end answer time also includes the model's additional requests and provider scheduling, so search latency alone does not describe the user-facing overhead. Two enabled final answers made no search; “enabled” means the tool was available, not that every answer used it.

The native experiment took **77 seconds wall time** because the six cases and paired answer forks ran concurrently. This is the elapsed time for the native run, not the sum of answer latencies or the time spent designing and reviewing the study. The 18 native compactions were shared checkpoints for the paired conditions; their costs are recorded separately rather than charged twice to the comparison. [Telemetry, concurrency, and cost definitions](METHODOLOGY.md) · [Derived cost tables](analysis/results.md)

## How the grades were produced

The first scoring pass used exact accepted aliases. It rejected semantically equivalent prose so aggressively that it marked every broad action wrong, even in the uncompacted baseline. Those initial scores are retained in the [archived records](data/records.json); they are **not** the 19/36 and 33/36 results reported here.

The headline results come from a later **blinded semantic review**. Two AI reviewers each judged three cases against the original frozen rule meanings. They did not receive the condition, compaction checkpoint, or citations. Equivalent wording could pass; all material requirements of a field had to be present. Each case had **one reviewer**, rather than two independent votes or human consensus.

The saved semantic review retains Boolean field judgments without per-field explanations. These are inspectable assessments, not an automatic ground truth: a reader can compare every label with the preserved answer and rule, including the [ambiguous-publish action marked incorrect](analysis/cases/ambiguous-commit.md#r3_on). The offline analysis reproduces the published labels and arithmetic without silently regrading them. [Detailed grading method](METHODOLOGY.md) · [All answer reports](analysis/cases/)

## What this experiment establishes

The result supports a focused engineering claim: **in these six authored incident chats, access to original project history helped Codex recover operational details lost along a repeated compaction trajectory.** The same-script uncompacted control remained at 35/36, while the compacted control fell to 19/36. The enabled compacted condition recovered to 33/36, with a visible latency and token tradeoff.

The study covers one model configuration, one run, one fictional project, and manually triggered native compactions. It measures structured decisions rather than completed patches. It does not establish production incident rates, broad superiority across agents or repositories, long-term indexing performance, or a universal overhead budget. Additional runs, independent projects, human grading, and implementation-level outcomes would test those separate claims.

## Inspect or recompute without an agent account

The saved records, fixture, reports, and calculations are included in this directory. Reviewing them does not require a Codex login, access to a private project, or another paid model run. Run the included offline analyzer from this directory to regenerate the derived tables and figures:

```sh
python3 analyze.py
python3 verify.py
```

The historical model run and blinded AI judgments are saved observations; rerunning arithmetic does not rerun the model or reproduce identical future answers. The [reproduction guide](REPRODUCING.md) distinguishes the offline audit from the environment needed for a new model experiment, including which historical artifacts are unavailable.

[Return to the plugin README](../../README.md) · [Read the exact questions](CASEBOOK.md) · [Open the complete generated results](analysis/results.md) · [Automated calculation checks](https://github.com/ajorge2/context-saver/actions/workflows/benchmark-analysis.yml)
