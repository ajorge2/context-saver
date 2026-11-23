# Historical experiment code

These four Python files record how a coding-agent memory experiment was run. Context Saver, the plugin under test, lets the agent search earlier project chats. The runner compared answers with and without that search after the coding host compacted each authored conversation.

The files are copied without modification from the November 17, 2026 experiment archive. Their existing sibling directory layout is required by the runner's helper import.

| File | Role |
|---|---|
| [Conversation and question fixtures](meridian-compaction-2026-11-17/reproduction/context-saver-human-fixtures.py) | Defines six fictional incidents, the earlier decisions, distracting later work, exact questions, and grading rules. A fixture is fixed input data for a test. |
| [Experiment runner](meridian-compaction-2026-11-17/reproduction/context-saver-human-run.py) | Builds the isolated index, creates paired answer forks, schedules three native compactions, and collects usage. |
| [Original diagnostic scorer](meridian-compaction-2026-11-17/reproduction/context-saver-human-score.py) | Checks raw run structure, citations, exact answer phrases, timing, and tokens. Its phrase-based accuracy totals were replaced by the meaning-based grades used in the report. |
| [Shared Codex helper](matched-compaction-2026-11-17/reproduction/context-saver-matched-codex.py) | Starts a disposable coding profile, restricts tools, communicates with the host, and seeds the local history index. |

The public [offline analysis](../analyze.py) is separate from this historical runner. It recomputes the report from the retained answer fields, semantic grades, and measurements without a model account. Read the [reproduction guide](../REPRODUCING.md) before attempting a new live experiment: the historical checkpoints and exact plugin source snapshot are not included, and the runner has host-version and macOS environment assumptions.
