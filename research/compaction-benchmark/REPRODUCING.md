# Reproduce the calculations or run a new experiment

[Read the findings](README.md) · [Understand the test design](METHODOLOGY.md) · [Inspect the saved evidence](analysis/README.md)

Context Saver lets a coding agent search earlier project conversations. This package records an experiment asking whether that access helps after a chat is compacted, meaning the coding host replaces earlier context with a shorter representation.

There are two different things a reviewer may want to reproduce: the calculations behind the published result, or a new set of model responses. The first works offline from this repository. The second requires model access and produces a new experiment, not an exact replay of the historical answers.

## Recompute the published results without an account

Clone the repository and use Python 3.12. The analysis uses only Python's standard library. It does not install the plugin, open a coding account, call a model, or read your chats.

```sh
git clone https://github.com/ajorge2/context-saver.git
cd context-saver/research/compaction-benchmark
python3 -B analyze.py
python3 -B verify.py
```

On Windows, use `py -3.12` in place of `python3` if needed.

`analyze.py` reads the published evidence in [`data/`](data/), counts the saved per-field grades, calculates timing and token differences, and writes the tables, case pages, and charts under [`analysis/`](analysis/README.md). The saved summary from the original experiment is a cross-check, rather than the source of the recomputed totals.

`verify.py` checks the data's structure and expected comparisons, tests that corrupted inputs are rejected, and checks that regenerating the outputs produces the committed results. Read the [verification source](verify.py) to see exactly what is checked. This verifies the analysis pipeline and its arithmetic. It does not independently decide whether an AI reviewer's pass/fail judgment was correct.

To inspect a result without running anything, open an [incident's answer page](analysis/README.md), compare its rule with the answer text and saved grade, then inspect the corresponding entry in [`records.json`](data/records.json). The [casebook](CASEBOOK.md) preserves the exact final questions and approved rules; the authored chat pages show the earlier conversations and intervening work.

The repository's [automated analysis checks on GitHub](https://github.com/ajorge2/context-saver/actions/workflows/benchmark-analysis.yml) run these calculations and checks in a fresh Python environment. The [workflow source](../../.github/workflows/benchmark-analysis.yml) shows every command. A passing run means the saved evidence and published calculations agree; it does not mean the model experiment was rerun or independently graded.

## Understand what has been preserved

| Artifact | Available here? | What it lets you check |
|---|---|---|
| Authored conversation corpus and final questions | Yes | Which facts were supplied, which proposal was superseded, and what the model was asked. |
| Exact retained answer strings for each field | Yes | What each condition answered. The original response envelope is not preserved. |
| Citation labels and recorded retrieval diagnostics | Yes, to the extent retained in the original scored export | Which fields were associated with retrieved evidence and what the diagnostic scorer recorded. |
| Saved per-field semantic grades | Yes | Every judgment used in the headline totals. |
| Independent reviewer explanations for each grade | No | The archive contains the judgments, not a complete account of their reasoning. |
| Answer timing, token usage, and retained checkpoint/compaction measurements | Yes | Recompute reported accuracy and cost summaries from the retained observations. |
| Historical fixture and runner/scorer source | Yes | Inspect the actual experiment protocol and original diagnostic scorer. |
| Recorded host/model configuration and candidate source hashes | Yes | Identify the configuration and source fingerprints recorded at the time. |
| Complete historical plugin source snapshot matching those hashes | No | The manifest alone cannot reconstruct source files that subsequently changed. |
| Original native chat checkpoints, complete host event logs, and seeded index files | No | Exact replay and independent revalidation of every native event are unavailable. |
| Credentials, personal chats, opaque provider compaction payloads | No | These are not public benchmark evidence. |

The [provenance record](data/provenance.json) records the source artifacts, hashes, export decisions, and missing-artifact boundary. The exported data removes or normalizes nonessential local paths and machine identifiers. It preserves the retained answer field wording and grades. It does not reconstruct a raw JSON response by pretending a parsed answer is the original byte sequence.

## Check the historical diagnostic scorer

The original scorer tried to recognize fixed answer phrases. It was too strict about equivalent wording, so its accuracy totals are **not** the reported 19/36 and 33/36. The later meaning-based review supplied those headline grades.

You can run the original scorer's internal checks offline:

```sh
python3 -B harness/meridian-compaction-2026-11-17/reproduction/context-saver-human-score.py --self-check
```

These checks exercise step order, harmful answers, abstention, citations, duplicate JSON keys, paired calculations, and token accounting. Passing them does not mean that exact-phrase grading was a valid accuracy measure for the answers produced. The failed measurement approach remains inspectable alongside the method that replaced it.

## Inspect or adapt the runner for a new model experiment

The [four archived Python files](harness/README.md) preserve the historical experiment code without modification. They show how chats were seeded, indexes built, tools restricted, paired forks dispatched, native compaction verified, and usage collected. The directory layout preserves the runner's import of its shared helper.

The recorded run used:

- Codex CLI 0.157.1 and its experimental app-server methods for injecting messages, forking chats, and compacting context.
- Model `gpt-6-sol` with low reasoning effort, through an authenticated coding account.
- Python 3.12 and an already populated `uv` cache. The helper pins `mcp==1.26.0`, `fastembed==0.9.1`, and `usearch==2.26.6` for its offline subprocesses.
- A compatible Context Saver source tree, specified through `CONTEXT_SAVER_EVAL_PLUGIN`.
- macOS-specific temporary-directory and cache defaults. This historical runner is not a separately validated cross-platform benchmark harness.

The helper reads authentication from `CONTEXT_SAVER_EVAL_AUTH_FILE`, defaulting to the account's `~/.codex/auth.json`, and copies it into a disposable profile with restricted file permissions. Installed hooks and unrelated plugins are disabled; each enabled answer fork is explicitly given the search tool. **Running the live experiment uses your coding account and can consume paid model usage.** The offline analysis above never does this.

For a compatible, deliberately prepared environment, the historical invocation is:

```sh
# Supply your own paths. The source directory must contain .mcp.json,
# server/, and scripts/ for the compatible plugin candidate.
export CONTEXT_SAVER_EVAL_PLUGIN=/absolute/path/to/compatible/plugin
export CONTEXT_SAVER_EVAL_AUTH_FILE=/absolute/path/to/your/auth.json
export CONTEXT_SAVER_EVAL_UV_CACHE=/absolute/path/to/prewarmed/uv/cache

python3 -B harness/meridian-compaction-2026-11-17/reproduction/context-saver-human-run.py \
  --workers 6 --count 6 --output /private/tmp/context-saver-new-experiment
```

The output directory must not already exist. The runner uses the six authored scenarios, creates new native compactions and answers, and records new source hashes and telemetry. It does not restore the missing original checkpoints. The latest public plugin may require different runtime dependencies or API adaptations; a run against it measures that new candidate, not the historical one.

The original scorer can inspect a complete fresh run directory:

```sh
python3 -B harness/meridian-compaction-2026-11-17/reproduction/context-saver-human-score.py \
  /private/tmp/context-saver-new-experiment \
  --output /private/tmp/context-saver-new-diagnostics
```

That generates the original exact-phrase diagnostic. A new meaning-based accuracy evaluation must separately grade the new answers against the frozen rules. Hide condition, checkpoint, and citation labels from reviewers, retain their judgments and reasons, and report disagreement. Do not reuse the historical semantic grades for new answers.

## What a stronger follow-up should add

A broader study should repeat each condition, use additional independently authored projects, include independent human grading, and test other host/model combinations. It should archive a complete source snapshot and safe native-run artifacts at collection time. Naturally triggered compactions near the context limit would address a separate question from the scheduled compactions used here. Cost reporting should keep cached input separate from uncached input and use the relevant account's pricing if dollar estimates are published.

Those are follow-up experiments. They are not described as completed work in this report.
