# Native platform validation

## Version 0.1.21 — complete native matrix

The [completed native run](https://github.com/ajorge2/context-saver/actions/runs/44475727933) validated source commit `4c1e33bc7434b2b3237bc0818c60d94ef3c5e150` on all three platforms. This includes full-history browsing, hierarchy preservation, direct UMAP/HDBSCAN clustering and scoped topic names. The workflow ran from 06:55:33 to 07:04:16 UTC on November 19, 2026.

| Runner | Python methods | Platform-only skips | Node tests | Chromium scenarios | Installed hosts and trust/upgrade |
|---|---:|---:|---:|---:|---|
| Ubuntu 24.04 x86-64 | 254 | 2 Windows-only | 5 | 36 | Passed |
| macOS 15 arm64 | 254 | 2 Windows-only | 5 | 36 | Passed |
| Windows Server 2025 x64 | 254 | 0 | 5 | 36 | Passed |

Each platform passed Codex and Claude installation/MCP checks, all nine Codex hook-trust and upgrade assertions, and all three Claude workspace-trust assertions. Codex trust checks include exactly-once completed-turn ingestion and verified retrieval after upgrade. Claude checks include refusing trust before model/index activity, accepting one turn and retaining trust on reopen. The separate native embedding diagnostics also passed on all three runners.

The runtime pins Python 3.12, FastEmbed 0.9.1, USearch 2.26.6, umap-learn 0.5.12 and HDBSCAN 0.8.44. Codex CLI 0.157.1 and Claude Code 2.1.312 are the tested hosts. Tests use disposable profiles, synthetic chats and loopback host responses; they do not use personal chats or signed-in model accounts. Native model and clustering tests execute the installed numerical libraries. [Workflow](../.github/workflows/platform-validation.yml) · [Changes and regression contracts](browse-hierarchy-repair.md)

The validation cycle removed a platform-dependent 75-of-80 membership quota from a single-family test. That fixture now checks guarded native root selection, support and preservation of native strengths/noise. Exact separated-family recovery gates remain unchanged. The [density report](density-clustering-experiments.json) records the observed 76/80 versus 71/80 variation. Ubuntu setup also replaces a stalled regional HTTP mirror with the official HTTPS mirror and bounds APT retries/timeouts; required browser dependencies remain installed.

## Earlier version 0.1.20 validation

Context Saver 0.1.20 passed native validation with Codex and Claude Code on Linux, Windows and macOS. Each runner installs the actual host packages, uses synthetic chats in temporary projects, and stores its index and host settings in disposable directories. The completed runs and exact scopes are recorded below. [Validation workflow](../.github/workflows/platform-validation.yml)

This historical section records the earlier portable release. The current browse, hierarchy and density runtime is validated separately above.

### Environments

| Runner image | Recorded native model environment | Architecture |
|---|---|---|
| `ubuntu-24.04` | Ubuntu userspace with glibc 2.39; model diagnostics on AMD EPYC 7763 and Intel Xeon 6975P-C runners | x86-64 |
| `windows-2025` | Windows Server 2025, build `10.0.26100` | AMD64 |
| `macos-15` | macOS 15.8.2 in CI; macOS 26.5.1 in the local isolated recheck | arm64 |

The recorded runs installed Codex CLI **0.157.1**, Claude Code **2.1.312**, Python **3.12**, Node.js **22**, uv **0.9.5**, FastEmbed **0.9.1**, USearch **2.26.6**, and Playwright **1.56.0** with Chromium. Recorded embedding diagnostics used ONNX Runtime **1.32.0**, NumPy **2.5.5**, and tokenizers **0.23.3**. Windows terminal interaction uses pywinpty **3.0.2**. Model conversion tests additionally install ONNX **1.23.2** as an authoring dependency.

The current workflow additionally installs **umap-learn 0.5.12** and **hdbscan 0.8.44** for direct topic clustering. USearch remains the retrieval index. Use the current [server requirements](../plugins/thread-tree/server/requirements.txt) when reproducing the updated runtime.

Windows checks run against native Windows processes, including `cmd.exe`, PowerShell, native Python and the installed host entrypoints. Terminal tests use ConPTY through pywinpty. Linux and macOS terminal tests use POSIX pseudo-terminals. The recorded Windows runner uses the Git environment supplied by the runner image.

### Isolation

The host harness creates new project folders, local plugin marketplaces, Codex and Claude configuration directories, secure-storage directories, Context Saver indexes, and synthetic transcript files for each case. `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, `CLAUDE_SECURESTORAGE_CONFIG_DIR`, `CODEX_STATE_DB`, and `THREAD_HISTORY_TREE_DATA` point into those temporary fixtures. Account token and API-key variables inherited by the runner are removed before host startup. [Host fixture setup](../tests/native_hosts.py)

Host conversation tests direct model requests to a temporary HTTP server bound to `127.0.0.1`. That server returns a predetermined synthetic answer and records whether a request occurred. This exercises the real host's transcript and lifecycle behavior with reproducible content. The local embedding lane runs the bundled model against an authored corpus. Dependency installation downloads packages during runner setup. Optional Ollama discovery in local-model fixtures uses an inert URL. [Local model fixtures](../tests/test_thread_tree_embeddings.py) · [Synthetic host responses](../tests/native_hosts.py)

Native installation runs each client's real marketplace and plugin commands against the temporary marketplace. The installed MCP launcher is then exercised using each host's package-root convention. Hooks receive paths containing spaces, accented letters, Greek characters and ampersands. Each temporary project has its own consent configuration.

### Coverage and recorded results

| Lane | What the checks establish | Final release result |
|---|---|---|
| Python regression | Turn capture, idempotent replay, scope enforcement, source verification, filtering, retention schedules, interruption recovery, and atomic publication. The full run executed 174 core and portability test methods. The follow-up run executed those methods plus the terminal argument regression; four terminal-driver regressions now separately cover argument boundaries, delayed termination and cleanup failures. | Passed on all three platforms |
| Native processes and paths | Kernel exclusion, owner death, long Windows lock contention, background completion after launcher exit, Windows path identity, Unicode paths, native shell hooks and PowerShell hooks. | Passed on all three platforms |
| Windows index storage | An active cached reader permits a separate process to republish and invalidate an index. Windows restores copy under the project lock, while Unix retains memory-mapped reads. | Passed, including the Windows-only contention case |
| Model upgrade | A failed or interrupted upgrade preserves previous vectors and sources. Staged publication handles concurrent deletion and correction, clears incompatible centroids, and schedules a replacement tree. Genuine custom model settings remain selected. | Passed on all three platforms |
| Bundled semantic quality | Model checksum, exact-query recall, paraphrase recall, rank quality, current-versus-obsolete results and absent-evidence checks through the shipped retrieval path. | Passed on all three platforms |
| Browser | Five JavaScript unit tests and 31 Chromium scenarios cover search, project switching, filter intersections, accessible metadata, disconnect recovery, late-response races and reload behavior. Two scenarios use the real HTTP handler and SQLite. | Passed on all three platforms |
| Installed hosts | Actual Codex and Claude marketplace installation and MCP connection. Claude produces and indexes one synthetic completed turn through its installed hooks. | Passed on all three platforms |
| Claude workspace trust | Refusing the native trust dialog prevents the model request and indexing. Accepting permits one indexed turn, and relaunch preserves workspace trust. | Passed on all three platforms |
| Codex hook trust and upgrade | Fresh untrusted hooks stay inactive, individual approvals persist, only a changed hook needs reapproval after upgrade, completed turns index once, and the upgraded package retrieves the original verified source. | Passed on all three platforms |

Counts describe distinct test methods and browser scenarios. Retention matrices and repeated failure schedules execute additional cases inside individual methods. The full browser and model lanes ran at `540f57e`. The follow-up at `be8bc92` added the terminal argument regression. Windows trust completed at `d790673` after the test driver gained graceful shutdown and bounded cleanup diagnostics. Production runtime, model and viewer files are identical across these commits. Linux and macOS skip the two Windows-only tests; Windows runs both. The four final driver regressions passed locally and on Windows. [Python runner](../tests/run.py) · [Windows storage regressions](../tests/test_windows_storage.py) · [Model upgrade regressions](../tests/test_model_upgrade.py) · [Browser suite](../tests/browser/)

### What the trust tests actually do

Claude's trust test drives the visible Yes and No choices through a native terminal. It checks persisted workspace state, the loopback API's request count, the indexed synthetic turn and behavior after reopening the workspace. [Claude trust harness](../tests/native_trust.py)

Codex's test opens `/hooks`, observes the command details for a newly installed hook and the changed Stop hook, and checks that inspection preserves the previous trust state. Individual approvals are written through the Codex app-server's native `config/batchWrite` API. The harness then reloads the native hook inventory and checks that only the intended trust entry changed. It exercises an untrusted turn, a trusted turn, an upgrade with a changed Stop command, the still-blocked changed hook, and the turn after reapproval. Finally it retrieves the original evidence through the upgraded installed MCP server. [Codex trust harness](../tests/native_codex_trust.py)

These checks establish the persisted native trust transitions and their effects on plugin execution. The Codex approval step uses the native API, while terminal interaction verifies the review screens. The synthetic model server supplies a fixed answer, so this lane measures host integration and lifecycle enforcement.

### Model portability diagnostics completed

Each native runner encoded the same 50 authored passages and searched 50 paraphrase queries. The corpus pairs a current decision with an obsolete proposal for each of 25 information needs. Recall@5 records whether the expected current passage appears among the first five results.

| Native environment | Exact cosine Recall@5 | Native USearch Recall@5 | Query count |
|---|---|---|---|
| Linux x86-64 | 100% | 100% | 50 |
| Windows AMD64 | 100% | 100% | 50 |
| macOS arm64 | 100% | 100% | 50 |

All three diagnostic reports verify the unsigned v2 artifact's SHA-256 `0a65b9f383a5da3833a7ecb16778bf27e04373f45a3af1c5919a4b87f51a4422`. Each report records the platform, dependency versions, execution provider, vector norms, cosine distributions, batch consistency and per-query rankings. The accompanying NPZ contains the synthetic vectors for comparison. These are retrieval measurements. The paired chat-compaction experiment separately measures how a coding model uses recovered evidence in an answer. [Diagnostic implementation](../tests/embedding_diagnostics.py) · [Model provenance](../plugins/thread-tree/assets/models/granite-small-r2-int8/PROVENANCE.md)

The native matrix exposed a large paraphrase-quality loss with the older signed artifact on one Linux runner. The portable artifact offsets both each signed weight and its zero point by 128, preserving every centered integer coefficient and its scale. This selects the unsigned multiplication route and avoids the signed-weight saturation path documented for some x86 processors. On the local arm64 validation machine, all 50 document vectors and 50 query vectors remained bitwise identical. [Reproducible conversion](../tools/convert_portable_model.py) · [ONNX Runtime quantization guidance](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html#when-and-why-do-i-need-to-try-u8u8)

### Reproduction and artifacts

The GitHub Actions workflow runs the three native platform lanes independently and uploads `context-saver-<runner>` artifacts. Separate `embeddings-<runner>` artifacts contain the diagnostic JSON and NPZ. The platform artifact contains `regression.json`, `native-hosts.json`, `claude-trust.json`, `codex-trust.json`, command inventories and terminal transcripts. Retained browser traces and screenshots accompany failures. Each file is emitted after its harness finishes its assertions.

From the repository root, the corresponding harness entrypoints are `python tests/run.py`, `python tests/native_hosts.py`, `python tests/native_trust.py`, and `python tests/embedding_diagnostics.py`. Run `npm test` and `npm run test:e2e` from `tests/browser`. The workflow pins setup commands, dependency versions and per-lane time limits. [Native workflow](../.github/workflows/platform-validation.yml)

The [full native run](https://github.com/ajorge2/context-saver/actions/runs/44379421386) records 174 Python cases, five JavaScript cases, 31 browser scenarios, model diagnostics and native installation on each platform. Linux and macOS completed their trust and upgrade checks in that run. Windows completed its core suites and Claude trust; the Codex terminal driver needed separate argument and shutdown corrections. The [follow-up](https://github.com/ajorge2/context-saver/actions/runs/44381355224) passed 175 Python cases on Linux and Windows, and Linux repeated native trust successfully. Its redundant queued macOS job was cancelled after a local isolated macOS recheck passed 175 cases and both hosts’ native checks. The [final Windows run](https://github.com/ajorge2/context-saver/actions/runs/44382304441) passed all four driver regressions, both installed hosts, Claude workspace trust, and the full Codex trust and upgrade sequence. The final graceful Codex shutdown sequence also passed locally on macOS.

The historical focused workflow modes skipped unchanged browser and model lanes and completed the terminal-driver follow-up. Those recorded results apply to that release snapshot. The later browse, hierarchy, and density changes have the separate verification scope linked above.
