# Can Context Saver recover decisions after a long chat is compacted?

Context Saver is a plugin that lets a coding agent search earlier project conversations and recover the messages behind a decision. This matters when a long chat is **compacted**: the coding host replaces its earlier conversation context with a shorter representation, and some details can be lost.

In six fictional software incident chats, Codex answered **33 of 36 decision details correctly with Context Saver, compared with 19 without it**, after three compactions per chat. The experiment also measured added time and token use, recorded the cases that still failed, and included an incident whose score got worse.

**[Read the complete experiment →](research/compaction-benchmark/README.md)**

The report is the starting point for reviewers. It links to:

- [What each question asked and which earlier decisions established the answer](research/compaction-benchmark/CASEBOOK.md).
- [How the comparison worked and why each control was included](research/compaction-benchmark/METHODOLOGY.md).
- [Original answers, saved grades, and generated calculations](research/compaction-benchmark/analysis/README.md).
- [How to rerun the analysis, and what is required for a new model experiment](research/compaction-benchmark/REPRODUCING.md).

The 36 details are six related requirements in each of six incidents. They are not 36 independent chats. The report states the scoring method, the additional cost, and the limits on what this experiment establishes.
