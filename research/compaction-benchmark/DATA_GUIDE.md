# Follow a number back to the recorded evidence

[Read the findings](README.md) · [Understand the experiment](METHODOLOGY.md) · [Browse the generated results](analysis/README.md) · [Run the calculations](REPRODUCING.md)

Context Saver lets a coding agent search earlier project chats. This experiment compared the agent's answers about earlier decisions with and without that search after the chats were compacted. This guide explains the files behind the report so a reader can inspect one answer, challenge a grade, or check a calculation without knowing the project beforehand.

## Start with the question you want to check

| Your question | Follow this evidence |
|---|---|
| What did the model need to remember? | [Exact incident questions and approved rules](CASEBOOK.md). |
| What did the whole earlier conversation contain? | [Authored chat pages](analysis/README.md) and [`fixtures.json`](data/fixtures.json). |
| What did each enabled and disabled answer actually say? | [Incident answer pages](analysis/README.md), then `fields.<field>.actual` in [`records.json`](data/records.json). |
| Why was that field counted as correct? | Compare the approved rule, retained answer string, and `semantic_grades.<field>`; the archive has no per-field reviewer rationale. A saved grade can be disputed. |
| Where did 19/36 and 33/36 come from? | Count the six operational `semantic_grades` in the six `r3_off` and six `r3_on` records; inspect [`analyze.py`](analyze.py). |
| What changed between conditions? | The generated case/field comparisons show every corrected field, remaining failure, and regression. |
| How much time and token usage did search add? | Per-answer `fork_and_answer_elapsed_s` and `usage` in [`records.json`](data/records.json); the analysis averages paired enabled-minus-disabled differences. |
| What did the original runner do? | [Historical source files](harness/README.md) and [protocol explanation](METHODOLOGY.md). |
| What was removed from the public export? | [`provenance.json`](data/provenance.json) and the [reproduction boundary](REPRODUCING.md#understand-what-has-been-preserved). |

## What is in each data file?

All files are UTF-8 JSON. A **record** is one incident answer under one condition. A **condition** identifies whether the conversation was compacted and whether search was available. Those names are defined in the [methodology table](METHODOLOGY.md#6-seven-conditions-produce-42-original-answers).

| File | Contents and use |
|---|---|
| [`fixtures.json`](data/fixtures.json) | Six authored conversations, their exact questions, approved evidence statements, and grading rules. Each conversation's `rounds` contains the initial design and three later work blocks actually used in the experiment. |
| [`records.json`](data/records.json) | All 42 retained answer records. Includes original parsed answer field strings, citations, saved semantic judgments, original exact-phrase diagnostics, timing, and host-reported token use. |
| [`measurements.json`](data/measurements.json) | Retained checkpoint measurements, 18 native compaction measurements, and paired-answer overlap measurements. A saved checkpoint hash identifies an original file; it does not provide the missing file's contents. |
| [`run-manifest.json`](data/run-manifest.json) | Recorded host, model, reasoning effort, test seed, scenario IDs, concurrency settings, fixture hash, and historical plugin source hashes. |
| [`cached-summaries.json`](data/cached-summaries.json) | Aggregates retained from the original export. The analysis compares its newly computed values with these saved summaries; it does not take its headline totals from them. |
| [`provenance.json`](data/provenance.json) | Original artifact hashes, public export hashes, transformations, and missing material. A hash checks file identity and integrity; it is not proof from an independent observer that an experiment occurred. |

## Read one answer correctly

Find an entry in `records.json` by `case_id` and `condition`. For example, `stale-canary` identifies the paused trial-release incident, and `r3_on` means its answer after three compactions with history search available.

There are two different grading systems in the retained record:

- `semantic_grades.<field>` is the saved meaning-based pass/fail judgment used in the report. `true` contributes one point. The six operational fields are `disposition`, `target`, `operations`, `gate`, `scope`, and `authority`.
- `fields.<field>.correct`, `outcome`, and the `strict_*` fields belong to the original **exact-phrase diagnostic**. That approach rejected correct paraphrases and was replaced for the headline accuracy calculation. It is preserved for inspection and must not be mistaken for the semantic grade.

`fields.<field>.actual` preserves the answer wording retained by the original scorer. It is a string extracted from the model's structured response, not a byte-for-byte copy of the complete original response. The `accepted` lists are the strict scorer's phrases; the authoritative evidence statements and meaning-based grades are what matter when auditing the published accuracy.

`recent` and `unsupported` are control fields. They test recall of a fact in the current question and refusal to invent a fact that was never supplied. They are reported separately and excluded from the 36-point operational score.

## Read retrieval diagnostics without overinterpreting them

`mcp_calls`, `mcp_completed`, and `mcp_failed` count recorded calls to the history-search tool. MCP is the protocol the coding host uses to call that tool. Tool availability does not mean a search happened: an enabled answer may choose not to search.

Citation labels and verified-evidence flags are retained diagnostics from the original scorer. They help show where retrieved evidence was associated with an answer. Raw search-result bodies and complete host event logs are not in the public archive, so those diagnostics cannot be independently reconstructed from native events here. They also do not by themselves establish that the final answer is correct.

## Read timing and token measurements

`elapsed_s` is answer time in seconds; `setup_s` is fork/setup time; `fork_and_answer_elapsed_s` includes both. `native_mcp_timing.durations_ms` records tool durations in milliseconds. `active_union_ms` represents elapsed time covered by at least one active tool, so overlapping calls are not added as if they happened in sequence.

`usage.inputTokens` includes cached input, `cachedInputTokens` is the cached portion, and `uncachedInputTokens` is their difference. `outputTokens` counts generated output; `totalTokens` is input plus output. `model_requests` counts the model requests represented by the answer's usage deltas. These are observed request tokens, including repeated cached input, not unique saved-history size or dollar charges.

For a checkpoint, the reported mean overhead is the mean of six paired differences: each incident's enabled observation minus that same incident's disabled observation. Detailed CSVs and JSON preserve more precision than the rounded report tables. Compaction costs are separate because the enabled and disabled forks share the compacted parent.

## How to cite or challenge the report

Link to the [main report](README.md) for the experiment as a whole, or to an incident answer page when discussing a particular failure. For a citation that must not change when the repository is updated, use GitHub's **Copy permalink** option on the file to obtain a commit-pinned URL.

A useful grading correction identifies the incident, condition, field, retained answer text, governing rule, and proposed change. A recalculation can then show how that change affects the aggregate result. Keeping the original observations separate from generated summaries makes such a correction auditable.
