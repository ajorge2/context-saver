# Inspect the benchmark analysis

Context Saver is a plugin that lets a coding agent search earlier project chats. This experiment compares answers about earlier project decisions with and without that search after the chats were compacted. Compaction is the coding assistant’s reduction of older conversation context to fit its working context.

Start with the [recomputed results](results.md), then follow any incident into its original retained answer fields, scoring rules and full authored source chat. These files are rendered directly by GitHub and can also be regenerated offline.

- [Results, changes, token/time overhead and limitations](results.md)
- [Machine-readable recomputed totals](summary.json)
- [Every individual answer field and grade](answer-fields.csv)
- [Per-incident paired overhead](paired-costs.csv)

## Inspect a complete evidence chain

- A one-sided canary pause: [answers and grades](cases/stale-canary.md) · [complete authored chat](chats/stale-canary.md)
- A publish timed out after issuing a receipt: [answers and grades](cases/ambiguous-commit.md) · [complete authored chat](chats/ambiguous-commit.md)
- A live writer with a restored follower: [answers and grades](cases/stale-rejoin.md) · [complete authored chat](chats/stale-rejoin.md)
- Recovery after a one-way key switch: [answers and grades](cases/post-seal-recovery.md) · [complete authored chat](chats/post-seal-recovery.md)
- A tenant was disconnected during an interrupted purge: [answers and grades](cases/purge-restart.md) · [complete authored chat](chats/purge-restart.md)
- Quota refusal behind a proxy during partition replay: [answers and grades](cases/signed-backoff.md) · [complete authored chat](chats/signed-backoff.md)
