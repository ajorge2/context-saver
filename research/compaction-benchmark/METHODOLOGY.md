# How the experiment tested recovery of earlier decisions

[Start with the findings](README.md) · [Read the questions and governing rules](CASEBOOK.md) · [Inspect every answer and calculation](analysis/README.md) · [Recompute the results](REPRODUCING.md)

Context Saver gives a coding agent a way to search earlier project conversations. This experiment asks whether that access helps the agent apply old project decisions after its chat has been **compacted**. Compaction is the coding host's process for replacing earlier conversation context with a shorter representation. It can preserve the overall direction of a project while losing an exception, an ordering requirement, or the reason one earlier proposal was rejected.

The experiment measures the accuracy of answers about earlier decisions. It also measures the time and tokens used to produce those answers. It does not ask the model to implement a project or demonstrate that the proposed repair works in running software.

## 1. A project with decisions that cannot be guessed safely

The fictional project, **Meridian**, is software for controlling releases across multiple customers. Its rules distinguish, for example, a worker being alive from its data being up to date, and a request timing out from that request having failed. Those distinctions create situations where a plausible general answer can still be wrong for this particular project.

Six separate authored chats describe six different incidents in that project. Each chat first introduces the design, an older proposal that was superseded, and the approved rules. That initial discussion contains seven user/assistant exchanges in the trial-release case and eight in each other case. Nine later exchanges contain lengthy technical handoffs about other work, supplied in three blocks. A final incident question requires the agent to recover and combine the relevant earlier rules with the new timeline.

The six incidents cover a paused trial release, an uncertain publication outcome, a restored reader, recovery after an irreversible key change, an interrupted deletion, and retrying an event after a quota refusal. [The casebook](CASEBOOK.md) explains each incident and preserves the exact questions and authoritative statements. The [fixture source](harness/meridian-compaction-2026-11-17/reproduction/context-saver-human-fixtures.py) contains the authored conversations and their construction rules.

This design tests conditional reasoning grounded in conversation history. A useful response must recover what this project actually decided, including exceptions and conflicting evidence, rather than offer generic software advice. The transcripts are synthetic, not customer conversations or production incident records.

## 2. The question is split into six requirements

Each incident asks for six operational fields. A **field** is one named part of the answer. Each field passes only if it satisfies all material requirements in its frozen rule.

| Field in the saved data | Meaning for a reader | Why test it separately? |
|---|---|---|
| `disposition` | What should happen now? | A response can choose the wrong overall action. |
| `target` | Which specific object, version, or operation should be used? | The right action on stale or incorrect state is still wrong. |
| `operations` | What steps must happen, in what order? | Omitting a fence or changing the order can invalidate a repair. |
| `gate` | What evidence must exist before proceeding? | A convenient signal may prove less than the approved rule requires. |
| `scope` | Which customers, shards, or release groups are affected? | A local problem should not unnecessarily stop unrelated work. |
| `authority` | Which recorded decision or source takes precedence? | Older proposals and attractive UI signals may conflict with approved rules. |

Six incidents multiplied by six requirements gives **36 scored decision fields per condition**. A completely correct incident requires all six to pass. The fields within an incident are related; treating them as 36 independent experiments would exaggerate the amount of evidence.

Two additional fields provide controls. `recent` asks for the working branch stated in the current question; `unsupported` asks for an external approval ID that was never supplied. They test whether the model can use current information and decline to invent missing information. Both are excluded from the 36-field headline score. Including them gives 48 fields per condition.

## 3. The same chat checkpoint is tested with and without search

The runner creates an isolated coding-host profile and workspace for each incident. It inserts the authored user and assistant messages into native Codex chats. These are scripted histories, not conversations whose earlier answers were generated afresh by the tested model.

For each incident, one parent chat goes through three native compactions. At checkpoints before compaction, after one compaction, and after three compactions, the runner creates two answer forks from that same parent checkpoint. A **fork** is a new chat starting from the parent's current context. Both forks receive the exact same incident question:

- The disabled fork has no history-search tool.
- The enabled fork can call the real `search_project_history` tool against its incident's isolated index.

The parent never receives either fork's answer. This prevents later checkpoints from inheriting an answer generated for an earlier probe. The enabled and disabled answers run concurrently; their starting order is shuffled using a recorded seed. [Runner: creation of paired forks and checkpoint sequence](harness/meridian-compaction-2026-11-17/reproduction/context-saver-human-run.py#L196).

The comparison changes access to saved history, rather than changing the question or giving one arm a different compacted parent. Both questions explicitly permit read-only history search if available. This tests the value of having that tool available under that instruction; it does not establish how often an unprompted real user session would invoke it.

## 4. The saved index contains earlier evidence, not the test answers

Each incident's index is created from the initial design discussion before the first compaction. The runner records whether the index contains each required source excerpt. In the saved run, all six operational fields had their evidence present; the current-branch control was absent as intended. Later work and incident probe answers are not added to that index. The recent branch and deliberately absent approval ID therefore cannot be recovered from an indexed answer key.

The indexed messages do contain the approved decisions. That is intentional: the product's proposed benefit is recovering earlier statements the agent could previously read. The benchmark tests retrieval and application of those statements, not inference of facts that were never recorded. [Evidence-presence check](harness/meridian-compaction-2026-11-17/reproduction/context-saver-human-run.py#L147) · [Index creation](harness/matched-compaction-2026-11-17/reproduction/context-saver-matched-codex.py#L218).

Only the enabled arm has the search tool. The runner inspects its tool inventory and rejects responses that use shell commands, files, web search, or other forbidden sources. It also rejects an unexpected additional compaction during an answer. These checks help keep the difference between conditions focused on history access. [Inventory and response checks](harness/meridian-compaction-2026-11-17/reproduction/context-saver-human-run.py#L73).

## 5. A separate control receives the same work without compaction

A second parent chat receives the same authored messages and acknowledgment text but is never deliberately compacted. At the end, a plugin-disabled fork answers the incident question. This condition is called `long_off` in the data.

It tests whether the longer scripted conversation alone makes the question hard. This control scored 35/36, compared with 19/36 for the disabled fork after three compactions. That contrast supports compaction as a contributor to the accuracy loss in this workload. It is not a population estimate of compaction's effect across projects or models.

The runner invokes Codex's native compaction operation at scheduled points and verifies the resulting compaction markers. It does **not** wait for the model to reach the context limit and compact automatically. Consequently, this is a repeated-compaction experiment, not a demonstrated full-context-window endurance test. [Native checkpoint checks](harness/meridian-compaction-2026-11-17/reproduction/context-saver-human-run.py#L117).

## 6. Seven conditions produce 42 original answers

| Saved condition | Conversation state | Search available? | Purpose |
|---|---|---|---|
| `r0_off` | Before compaction | No | Check that the model can answer with the original design in context. |
| `r0_on` | Before compaction | Yes | Check the starting comparison with the tool available. |
| `r1_off` | After one compaction | No | Measure answers after the first context reduction. |
| `r1_on` | After one compaction | Yes | Measure whether saved history helps at that checkpoint. |
| `r3_off` | After three compactions | No | Measure the later compacted comparison. |
| `r3_on` | After three compactions | Yes | Measure whether saved history helps after repeated compaction. |
| `long_off` | Same authored work, no scheduled compaction | No | Distinguish a long conversation from a compacted one. |

Each condition has six incident answers, for **42 original answers**. Each of the six compacted parent chats undergoes three compactions, for 18 actual compaction operations. The paired answer forks share those parent operations; they are not 36 separate compactions.

The saved configuration records Codex CLI 0.157.1, model `gpt-6-sol`, low reasoning effort, six scenario workers, and the seed used to order paired arms. The run is dated November 17, 2026. [Run manifest](data/run-manifest.json).

## 7. The headline uses meaning-based grading, not literal phrase matching

The rules were authored before the model run. The first automated scorer accepted a fixed list of exact phrases after basic normalization. It penalized equivalent prose so strongly that even correct baseline actions failed. Its accuracy totals therefore do not support the headline claim. The original scorer is preserved so readers can inspect that failed measurement approach and its self-checks. [Historical exact-phrase scorer](harness/meridian-compaction-2026-11-17/reproduction/context-saver-human-score.py).

The reported accuracy comes from a later **blinded semantic review**: two AI reviewers received the frozen rules and original answer text without the enabled/disabled labels, checkpoint labels, or citations. Each reviewer handled three incidents, so each incident had one reviewer. Equivalent wording counted, but omitting a material clause failed the field. No partial credit was assigned within a field.

The saved grades are judgments, not an independently proven truth. The public package lets readers compare the exact rule and answer for every field, including every failure and the regression. Recomputing totals verifies the arithmetic over those grades; it does not independently validate the reviewers' judgments or recreate their deliberations. The package does not contain a separately collected human grading study or reviewer agreement measurement.

## 8. Time and token cost use per-answer observations

Each answer has recorded timing and host-reported token usage. The analysis compares the six enabled answers with the six disabled answers at the same checkpoint. The displayed elapsed time includes the answer fork and setup as well as model response time.

**Observed total tokens** means the input and output tokens reported across the requests needed for that answer. Repeated cached input can be counted again on successive requests. It is not a count of unique history stored by the plugin, and it cannot be read directly as an uncached bill. The analysis separately reports cached input, uncached input, and output. No dollar estimate is inferred without the applicable provider pricing and account terms.

Compaction has its own time and token cost. The paired enabled and disabled answers share each compacted parent, so those costs are reported separately. A local search can be fast while the full enabled answer is slower because it adds model requests and retrieved input. The results report both local search latency and end-to-end overhead where the saved telemetry supports them.

## 9. What the results establish

Within these authored conversations and this model run, access to saved project history improved the recovery of detailed earlier rules after compaction. The benefit was largest for step order, prerequisites, scope, and controlling evidence. The final headline action was correct in five of six incidents in both arms, so the result is more specific than saying the tool simply made the model choose better actions.

After three compactions, the enabled arm corrected 15 fields missed by the disabled arm and regressed one that the disabled arm got right. Three enabled incidents were completely correct, compared with one disabled incident. The remaining errors and added cost are part of the result, not exceptions removed from it. [Full results and incident drilldowns](analysis/README.md).

This is a small, synthetic, single-model experiment with related fields, one realization of each condition, and AI grading. It does not establish the same gain for live customer projects, other model versions, Claude Code, or the current plugin release. The recorded source fingerprints identify the historical candidate; they do not turn a newer release into the version measured here. A broader efficacy study would need repeated runs, additional independently authored projects, independent grading, and separately measured host/model combinations.

## 10. Where inspection ends

The public package contains the authored corpus, original answer strings retained for each field, saved per-field judgments, answer telemetry, recorded run configuration, analysis code, and historical runner code. The complete original response envelopes and raw search-result bodies are not retained. The [data guide](DATA_GUIDE.md) explains each exported file and distinguishes the two grading systems. The [reproduction guide](REPRODUCING.md) separates offline recomputation from running a new model experiment and identifies unavailable historical artifacts. Local profile paths and other nonessential machine details are removed or normalized as described in the data provenance record. Private account credentials, personal chat history, and opaque provider compaction payloads are not published.
