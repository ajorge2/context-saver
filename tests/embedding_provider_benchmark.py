#!/usr/bin/env python3
"""Benchmark local FastEmbed candidates for Thread Tree retrieval.

Run once with ``--phase download`` against an empty per-model cache, then in a
fresh process with ``--phase benchmark``. The benchmark uses paired current and
obsolete project-history evidence, two exact and two lexical-disjoint
paraphrase queries per information need, and held-out unrelated queries for an
``uncovered`` threshold screen.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import statistics
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from fastembed import TextEmbedding
    from psutil import Process


@dataclass(frozen=True)
class RetrievalCase:
    key: str
    code: str
    obsolete_code: str
    current: str
    obsolete: str
    paraphrases: tuple[str, str]
    exact_queries: tuple[str, str]


CASES = [
    RetrievalCase("session-revocation", "AURORA-17", "AURORA-09", "Final decision AURORA-17: revoke every active login session within ninety seconds after an administrator removes an elevated role.", "Obsolete proposal AURORA-09: allow issued login sessions to remain valid for fifteen minutes after an administrator removes an elevated role.", ("How quickly should existing sign-ins die after someone loses privileged access?", "What delay is tolerated between demotion and invalidating credentials already in circulation?"), ("What does AURORA-17 require?", "Which session policy uses code AURORA-17?")),
    RetrievalCase("deployment-gate", "BRAVO-28", "BRAVO-11", "Final decision BRAVO-28: pause the regional deployment automatically when that region exhausts its error budget.", "Obsolete proposal BRAVO-11: continue the regional deployment after its error budget is exhausted and alert an operator.", ("What happens when one geography consumes all of its reliability allowance during rollout?", "Does shipping halt automatically after a region spends the permitted failure margin?"), ("What does BRAVO-28 require?", "Which rollout gate uses BRAVO-28?")),
    RetrievalCase("audit-retention", "CEDAR-39", "CEDAR-12", "Final decision CEDAR-39: retain immutable audit exports for seven complete calendar years.", "Obsolete proposal CEDAR-12: delete immutable audit exports after eighteen months.", ("How long must tamper-proof compliance records remain available?", "What is the preservation period for write-once regulatory logs?"), ("What does CEDAR-39 require?", "Which audit rule uses CEDAR-39?")),
    RetrievalCase("key-rotation", "DELTA-40", "DELTA-18", "Final decision DELTA-40: require a second human approver before rotating production encryption keys.", "Obsolete proposal DELTA-18: permit one on-call engineer to rotate production encryption keys alone.", ("How many people must sign off before live cryptographic secrets can change?", "Can one operator replace the keys protecting production data?"), ("What does DELTA-40 require?", "Which key policy uses DELTA-40?")),
    RetrievalCase("offline-conflicts", "EMBER-51", "EMBER-22", "Final decision EMBER-51: reconcile offline edits by applying the server's causal ordering when a device reconnects.", "Obsolete proposal EMBER-22: accept the device timestamp as authoritative when offline edits reconnect.", ("How are disconnected changes ordered after the client comes back online?", "Which side decides edit precedence when a device resynchronizes?"), ("What does EMBER-51 require?", "Which synchronization rule uses EMBER-51?")),
    RetrievalCase("restore-point", "FJORD-62", "FJORD-31", "Final decision FJORD-62: database recovery must restore to a point no more than five minutes before the incident.", "Obsolete proposal FJORD-31: database recovery may lose up to one hour of writes.", ("What is the maximum acceptable amount of recent data lost during restoration?", "How far behind the failure may the recovered database be?"), ("What does FJORD-62 require?", "Which recovery objective uses FJORD-62?")),
    RetrievalCase("canary-share", "GROVE-73", "GROVE-44", "Final decision GROVE-73: keep the canary at ten percent of traffic for thirty minutes before expansion.", "Obsolete proposal GROVE-44: send half of traffic to the canary immediately.", ("What fraction of requests reaches the trial release before broad rollout, and for how long?", "Describe the limited exposure period used before increasing deployment traffic."), ("What does GROVE-73 require?", "Which canary rule uses GROVE-73?")),
    RetrievalCase("migration-lock", "HARBOR-84", "HARBOR-33", "Final decision HARBOR-84: abort a schema migration if its database lock lasts longer than eight seconds.", "Obsolete proposal HARBOR-33: allow schema migration locks to wait without a time limit.", ("When should a structure change be cancelled because it blocks the database too long?", "What is the maximum blocking interval allowed for altering tables?"), ("What does HARBOR-84 require?", "Which migration rule uses HARBOR-84?")),
    RetrievalCase("billing-reconcile", "IRIS-95", "IRIS-42", "Final decision IRIS-95: compare ledger totals with processor settlements at the end of every UTC day.", "Obsolete proposal IRIS-42: reconcile ledger totals with processor settlements once each month.", ("How often are internal balances checked against money actually received from the payment network?", "When should accounting compare its books with external settlement records?"), ("What does IRIS-95 require?", "Which reconciliation rule uses IRIS-95?")),
    RetrievalCase("incident-severity", "JUNIPER-16", "JUNIPER-07", "Final decision JUNIPER-16: classify an outage affecting checkout in two regions as severity one.", "Obsolete proposal JUNIPER-07: classify a multi-region checkout outage as severity two.", ("What priority applies when customers cannot purchase in two geographies?", "How critical is a payment-flow outage spanning multiple regions?"), ("What does JUNIPER-16 require?", "Which incident rule uses JUNIPER-16?")),
    RetrievalCase("webhook-retry", "KITE-27", "KITE-13", "Final decision KITE-27: retry failed webhooks with exponential backoff for twenty-four hours.", "Obsolete proposal KITE-13: retry every failed webhook once after five minutes.", ("For how long and with what pacing should undelivered callbacks be attempted again?", "What retry schedule applies when an outbound event cannot reach its recipient?"), ("What does KITE-27 require?", "Which webhook policy uses KITE-27?")),
    RetrievalCase("flag-expiry", "LANTERN-38", "LANTERN-20", "Final decision LANTERN-38: every temporary feature flag needs an owner and an automatic expiration date.", "Obsolete proposal LANTERN-20: temporary feature flags may remain indefinitely without an owner.", ("What metadata prevents short-lived release switches from becoming permanent?", "How do we ensure experimental toggles are eventually removed?"), ("What does LANTERN-38 require?", "Which feature-flag rule uses LANTERN-38?")),
    RetrievalCase("index-refresh", "MEADOW-49", "MEADOW-15", "Final decision MEADOW-49: searchable catalog updates must appear within two minutes of a committed product change.", "Obsolete proposal MEADOW-15: rebuild the searchable catalog once overnight.", ("How stale may discovery results be after product data is saved?", "What delay is allowed before a changed item becomes findable?"), ("What does MEADOW-49 require?", "Which indexing rule uses MEADOW-49?")),
    RetrievalCase("export-encryption", "NIMBUS-50", "NIMBUS-21", "Final decision NIMBUS-50: encrypt every customer export with a unique data key before it reaches object storage.", "Obsolete proposal NIMBUS-21: store customer exports unencrypted inside the private bucket.", ("How are downloadable account archives protected before being persisted?", "Does each generated customer package receive separate cryptographic protection?"), ("What does NIMBUS-50 require?", "Which export policy uses NIMBUS-50?")),
    RetrievalCase("deletion-sla", "ORCHID-61", "ORCHID-30", "Final decision ORCHID-61: finish verified customer-data deletion within thirty days of an authenticated request.", "Obsolete proposal ORCHID-30: complete customer-data deletion within ninety days.", ("How soon must a confirmed right-to-erasure request be fully completed?", "What is the deadline for proving an account's information has been removed?"), ("What does ORCHID-61 require?", "Which deletion rule uses ORCHID-61?")),
    RetrievalCase("rate-limit", "PINE-72", "PINE-41", "Final decision PINE-72: allow each API token six hundred write requests per minute with a short burst of fifty.", "Obsolete proposal PINE-41: allow unlimited write requests from authenticated API tokens.", ("What sustained mutation volume and temporary spike may one credential send?", "How aggressively do we throttle writes made with a single developer key?"), ("What does PINE-72 require?", "Which throttling rule uses PINE-72?")),
    RetrievalCase("mobile-merge", "QUARTZ-83", "QUARTZ-52", "Final decision QUARTZ-83: preserve both versions and request user resolution when mobile edits conflict semantically.", "Obsolete proposal QUARTZ-52: silently keep the newest mobile edit whenever changes conflict.", ("What should the app do when two disconnected changes cannot be reconciled safely?", "Are competing device updates discarded automatically or shown for human choice?"), ("What does QUARTZ-83 require?", "Which mobile conflict rule uses QUARTZ-83?")),
    RetrievalCase("log-redaction", "RIVER-94", "RIVER-63", "Final decision RIVER-94: remove access tokens, passwords, and payment numbers before application logs leave the process.", "Obsolete proposal RIVER-63: redact sensitive fields later in the centralized logging pipeline.", ("At what point are secrets stripped from diagnostic events?", "Can credentials ever be transmitted to the shared log collector before masking?"), ("What does RIVER-94 require?", "Which logging rule uses RIVER-94?")),
    RetrievalCase("artifact-retention", "SUMMIT-15", "SUMMIT-04", "Final decision SUMMIT-15: retain signed production build artifacts for one year after deployment.", "Obsolete proposal SUMMIT-04: remove production build artifacts seven days after deployment.", ("How long are verifiable release binaries kept after shipping?", "What preservation period applies to signed packages that reached production?"), ("What does SUMMIT-15 require?", "Which build-retention rule uses SUMMIT-15?")),
    RetrievalCase("rollback-checkpoint", "TUNDRA-26", "TUNDRA-08", "Final decision TUNDRA-26: create a verified rollback checkpoint immediately before every irreversible data migration.", "Obsolete proposal TUNDRA-08: rely on the nightly backup before irreversible data migrations.", ("When must a recoverable snapshot be confirmed around a one-way data change?", "What safety point is required just before modifying information in a nonreversible way?"), ("What does TUNDRA-26 require?", "Which rollback rule uses TUNDRA-26?")),
    RetrievalCase("dead-letter", "UMBER-37", "UMBER-19", "Final decision UMBER-37: move a message to the dead-letter queue after eight failed processing attempts.", "Obsolete proposal UMBER-19: retry a poison message forever.", ("After how many unsuccessful consumptions is an event quarantined?", "When does repeatedly failing work stop returning to the normal queue?"), ("What does UMBER-37 require?", "Which queue rule uses UMBER-37?")),
    RetrievalCase("cache-ttl", "VALE-48", "VALE-24", "Final decision VALE-48: cache public profile responses for fifteen seconds and purge them on privacy changes.", "Obsolete proposal VALE-24: cache public profile responses for ten minutes without event-driven purging.", ("How briefly may a visible user page remain stale, and what change invalidates it immediately?", "What caching behavior applies to profile data after visibility settings change?"), ("What does VALE-48 require?", "Which cache rule uses VALE-48?")),
    RetrievalCase("reset-token", "WILLOW-59", "WILLOW-29", "Final decision WILLOW-59: password-reset links expire after twenty minutes and become invalid after first use.", "Obsolete proposal WILLOW-29: password-reset links remain reusable for twenty-four hours.", ("How long can an account-recovery URL work, and may it be redeemed twice?", "What lifetime and reuse rule applies to credentials sent for forgotten passwords?"), ("What does WILLOW-59 require?", "Which recovery-link rule uses WILLOW-59?")),
    RetrievalCase("data-residency", "XENON-60", "XENON-32", "Final decision XENON-60: keep European customer content and backups inside European Union regions.", "Obsolete proposal XENON-32: permit European customer backups in any global region.", ("Where may information and recovery copies belonging to EU accounts physically reside?", "Can disaster-recovery data for European tenants leave the union?"), ("What does XENON-60 require?", "Which residency rule uses XENON-60?")),
    RetrievalCase("contrast-exception", "YARROW-71", "YARROW-40", "Final decision YARROW-71: the disabled-state contrast exception applies only when an adjacent text label conveys the same status.", "Obsolete proposal YARROW-40: all disabled controls may ignore contrast requirements without another cue.", ("When may an inactive control use faint colors without losing accessibility information?", "What alternative indication is required before reduced contrast is acceptable for a disabled element?"), ("What does YARROW-71 require?", "Which accessibility exception uses YARROW-71?")),
]


NEGATIVE_QUERIES = [
    "Which restaurant caters the Friday lunch?",
    "What color paint was selected for the conference room?",
    "Who won the company softball tournament?",
    "Which airline should employees book for travel?",
    "What soup recipe does the cafeteria use?",
    "Where is the holiday party venue?",
    "Who waters the office plants on weekends?",
    "Which brand of coffee beans is stocked?",
    "What is the parking garage access code?",
    "When is the next volunteer beach cleanup?",
    "Which printer model is in the reception area?",
    "Who designed the company T-shirts?",
    "What music playlist is used in the lobby?",
    "Which hotel is preferred for the annual retreat?",
    "What is the mascot's birthday?",
    "Who orders birthday cakes for employees?",
    "Which chairs were purchased for the kitchen?",
    "What board game is played on Wednesdays?",
    "Where are spare bicycle locks stored?",
    "Which florist supplies the front desk?",
    "What time does the office yoga class begin?",
    "Which museum is planned for the team outing?",
    "Who maintains the rooftop vegetable garden?",
    "What brand of sparkling water is ordered?",
    "Where are the spare projector remotes kept?",
]

STOPWORDS = {
    "a", "about", "after", "again", "all", "also", "am", "an", "and", "any",
    "are", "as", "at", "be", "because", "been", "before", "being", "but", "by",
    "can", "could", "did", "do", "does", "doing", "each", "for", "from", "had",
    "has", "have", "having", "he", "her", "here", "hers", "him", "his", "how",
    "i", "if", "in", "into", "is", "it", "its", "just", "me", "more", "most",
    "my", "no", "not", "of", "on", "or", "our", "out", "over", "she", "so",
    "some", "that", "the", "their", "them", "then", "there", "these", "they",
    "this", "those", "through", "to", "too", "up", "us", "use", "was", "we",
    "were", "what", "when", "where", "which", "who", "why", "will", "with",
    "would", "you", "your", "yes", "yeah", "okay", "ok", "hmm", "hmmm",
}


def cache_size(path: Path) -> int:
    if not path.exists():
        return 0
    seen: set[tuple[int, int]] = set()
    total = 0
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        stat = item.stat()
        identity = (stat.st_dev, stat.st_ino)
        if identity in seen:
            continue
        seen.add(identity)
        total += stat.st_size
    return total


def normalize(vector: Iterable[float]) -> list[float]:
    values = [float(value) for value in vector]
    length = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / length for value in values]


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def tokens(text: str) -> list[str]:
    """Match Thread Tree's production lexical tokenizer."""

    return [
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text.lower())
        if token not in STOPWORDS and not token.isdigit()
    ]


def lexical_similarity(left: str, right: str) -> float:
    left_tokens, right_tokens = set(tokens(left)), set(tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / math.sqrt(len(left_tokens) * len(right_tokens))


def lexical_scores(db: sqlite3.Connection, query: str, documents: list[str]) -> dict[int, float]:
    """Reproduce the lexical half of ``search_project`` for this fixed corpus."""

    query_tokens = tokens(query)
    unique_tokens = list(dict.fromkeys(query_tokens))
    selected_tokens = unique_tokens[:16] + unique_tokens[-16:] if len(unique_tokens) > 32 else unique_tokens
    if not selected_tokens:
        return {}
    fts_query = " OR ".join(f'"{token}"' for token in selected_tokens)
    scores: dict[int, float] = {}
    try:
        rows = db.execute(
            "SELECT document_id FROM documents_fts WHERE documents_fts MATCH ? ORDER BY bm25(documents_fts) LIMIT 100",
            (fts_query,),
        )
        for position, row in enumerate(rows):
            document_id = int(row[0])
            document = documents[document_id]
            document_tokens = tokens(document)
            query_set, document_set = set(query_tokens), set(document_tokens)
            query_bigrams = set(zip(query_tokens, query_tokens[1:]))
            document_bigrams = set(zip(document_tokens, document_tokens[1:]))
            base_score = max(0.25, 0.96 - position * 0.02)
            coverage = len(query_set & document_set) / len(query_set) if query_set else 0.0
            bigram_coverage = len(query_bigrams & document_bigrams) / len(query_bigrams) if query_bigrams else 0.0
            exact_phrase = int(query.casefold() in document.casefold())
            scores[document_id] = min(
                1.0,
                base_score * 0.55
                + coverage * 0.20
                + lexical_similarity(query, document) * 0.15
                + bigram_coverage * 0.10
                + exact_phrase * 0.10,
            )
    except sqlite3.OperationalError:
        return {}
    return scores


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)] if ordered else 0.0


class MemorySampler:
    def __init__(self, process: Process) -> None:
        self.process = process
        self.baseline = self.process.memory_info().rss
        self.peak = self.baseline
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self._stop.wait(0.01):
            self.peak = max(self.peak, self.process.memory_info().rss)

    def __enter__(self) -> "MemorySampler":
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join()
        self.peak = max(self.peak, self.process.memory_info().rss)


def rank(vector: list[float], documents: list[list[float]]) -> tuple[list[int], list[float]]:
    scored = sorted(enumerate(documents), key=lambda item: cosine(vector, item[1]), reverse=True)
    return [index for index, _ in scored], [cosine(vector, value) for _, value in scored]


def best_threshold(positive_scores: list[float], negative_scores: list[float]) -> float:
    candidates = sorted(set(positive_scores + negative_scores))
    best = (float("-inf"), 0.0)
    for threshold in candidates:
        true_positive = sum(score >= threshold for score in positive_scores)
        true_negative = sum(score < threshold for score in negative_scores)
        balanced = 0.5 * (true_positive / len(positive_scores) + true_negative / len(negative_scores))
        if balanced > best[0]:
            best = (balanced, threshold)
    return best[1]


def embed(model: TextEmbedding, texts: list[str], *, query: bool) -> list[list[float]]:
    method = model.query_embed if query else model.passage_embed
    return [normalize(vector) for vector in method(texts)]


def benchmark(model_name: str, cache_dir: Path, specific_model_path: Path | None = None) -> dict[str, Any]:
    from fastembed import TextEmbedding
    from psutil import Process

    process = Process()
    baseline = process.memory_info().rss
    with MemorySampler(process) as memory:
        started = time.perf_counter()
        model_kwargs: dict[str, Any] = {}
        if specific_model_path is not None:
            model_kwargs["specific_model_path"] = str(specific_model_path)
        model = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir), threads=4, **model_kwargs)
        first_vector = embed(model, ["A fresh-process embedding readiness probe."], query=True)[0]
        cold_seconds = time.perf_counter() - started

        documents: list[str] = []
        current_indices: dict[str, int] = {}
        obsolete_indices: dict[str, int] = {}
        for case in CASES:
            current_indices[case.key] = len(documents)
            documents.append(case.current)
            obsolete_indices[case.key] = len(documents)
            documents.append(case.obsolete)
        document_vectors = embed(model, documents, query=False)
        lexical_db = sqlite3.connect(":memory:")
        lexical_db.execute("CREATE VIRTUAL TABLE documents_fts USING fts5(document_id UNINDEXED, text)")
        lexical_db.executemany(
            "INSERT INTO documents_fts(document_id, text) VALUES (?, ?)",
            enumerate(documents),
        )

        exact_queries = [(case, query) for case in CASES for query in case.exact_queries]
        paraphrase_queries = [(case, query) for case in CASES for query in case.paraphrases]
        # Production receives one lookup at a time. Query embeddings are
        # therefore measured one-by-one rather than in a shared padded batch;
        # some transformer exports have small batch-shape-dependent shifts.
        exact_vectors = [embed(model, [query], query=True)[0] for _, query in exact_queries]
        paraphrase_vectors = [
            embed(model, [query], query=True)[0] for _, query in paraphrase_queries
        ]
        negative_vectors = embed(model, NEGATIVE_QUERIES, query=True)

        warm_latencies: list[float] = []
        for _, query in paraphrase_queries * 2:
            query_started = time.perf_counter()
            list(model.query_embed([query]))
            warm_latencies.append((time.perf_counter() - query_started) * 1000)

        throughput_texts = [case.current for case in CASES] * 8
        throughput_started = time.perf_counter()
        throughput_vectors = list(model.passage_embed(throughput_texts))
        throughput_seconds = time.perf_counter() - throughput_started
    steady = process.memory_info().rss

    def evaluate(items: list[tuple[RetrievalCase, str]], vectors: list[list[float]]) -> dict[str, Any]:
        vector_ranks: list[int] = []
        hybrid_ranks: list[int] = []
        vector_current_over_obsolete = 0
        hybrid_current_over_obsolete = 0
        top_scores: list[float] = []
        for (case, query), vector in zip(items, vectors):
            order, scores = rank(vector, document_vectors)
            current_rank = order.index(current_indices[case.key]) + 1
            obsolete_rank = order.index(obsolete_indices[case.key]) + 1
            vector_ranks.append(current_rank)
            vector_current_over_obsolete += int(current_rank < obsolete_rank)
            top_scores.append(scores[0])
            lexical = lexical_scores(lexical_db, query, documents)
            hybrid_scores = [
                max(0.0, cosine(vector, document_vector)) * 0.65 + lexical.get(index, 0.0) * 0.35
                for index, document_vector in enumerate(document_vectors)
            ]
            hybrid_order = sorted(range(len(documents)), key=lambda index: hybrid_scores[index], reverse=True)
            hybrid_current_rank = hybrid_order.index(current_indices[case.key]) + 1
            hybrid_obsolete_rank = hybrid_order.index(obsolete_indices[case.key]) + 1
            hybrid_ranks.append(hybrid_current_rank)
            hybrid_current_over_obsolete += int(hybrid_current_rank < hybrid_obsolete_rank)

        def metrics(ranks: list[int], current_over_obsolete: int) -> dict[str, Any]:
            return {
                "recall_at_1": round(statistics.mean(value == 1 for value in ranks), 4),
                "recall_at_5": round(statistics.mean(value <= 5 for value in ranks), 4),
                "mrr": round(statistics.mean(1 / value for value in ranks), 4),
                "current_beats_obsolete": round(current_over_obsolete / len(ranks), 4),
                "ranks": ranks,
            }

        return {
            "vector": {
                **metrics(vector_ranks, vector_current_over_obsolete),
                "median_top_score": round(statistics.median(top_scores), 4),
            },
            "hybrid": metrics(hybrid_ranks, hybrid_current_over_obsolete),
        }

    exact = evaluate(exact_queries, exact_vectors)
    paraphrase = evaluate(paraphrase_queries, paraphrase_vectors)
    lexical_db.close()
    positive_scores = [rank(vector, document_vectors)[1][0] for vector in paraphrase_vectors]
    negative_scores = [rank(vector, document_vectors)[1][0] for vector in negative_vectors]
    threshold = best_threshold(positive_scores[:30], negative_scores[:10])
    held_positive = positive_scores[30:]
    held_negative = negative_scores[10:]
    threshold_positive_recall = statistics.mean(score >= threshold for score in held_positive)
    threshold_negative_precision = statistics.mean(score < threshold for score in held_negative)
    return {
        "model": model_name,
        "dimension": len(first_vector),
        "case_count": len(CASES),
        "document_count": len(documents),
        "exact_query_count": len(exact_queries),
        "paraphrase_query_count": len(paraphrase_queries),
        "negative_query_count": len(NEGATIVE_QUERIES),
        "model_cache_bytes": cache_size(specific_model_path or cache_dir),
        "cold_start_seconds": round(cold_seconds, 4),
        "baseline_rss_mib": round(baseline / (1024 * 1024), 2),
        "steady_rss_mib": round(steady / (1024 * 1024), 2),
        "peak_rss_mib": round(memory.peak / (1024 * 1024), 2),
        "peak_rss_delta_mib": round((memory.peak - memory.baseline) / (1024 * 1024), 2),
        "warm_query_p50_ms": round(percentile(warm_latencies, 0.50), 3),
        "warm_query_p95_ms": round(percentile(warm_latencies, 0.95), 3),
        "warm_query_p99_ms": round(percentile(warm_latencies, 0.99), 3),
        "batch_embeddings_per_second": round(len(throughput_vectors) / throughput_seconds, 2),
        "exact": exact,
        "paraphrase": paraphrase,
        "uncovered_threshold": round(threshold, 4),
        "held_out_positive_recall": round(threshold_positive_recall, 4),
        "held_out_negative_uncovered_precision": round(threshold_negative_precision, 4),
        "positive_top_score_p05": round(percentile(positive_scores, 0.05), 4),
        "negative_top_score_p95": round(percentile(negative_scores, 0.95), 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--phase", choices=("download", "benchmark"), required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--specific-model-path", type=Path)
    args = parser.parse_args()
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    if args.phase == "download":
        from fastembed import TextEmbedding

        model_kwargs: dict[str, Any] = {}
        if args.specific_model_path is not None:
            model_kwargs["specific_model_path"] = str(args.specific_model_path)
        model = TextEmbedding(model_name=args.model, cache_dir=str(args.cache_dir), threads=4, **model_kwargs)
        dimension = len(list(model.query_embed(["download verification probe"]))[0])
        result: dict[str, Any] = {
            "model": args.model,
            "phase": "download",
            "dimension": dimension,
            "download_and_first_embedding_seconds": round(time.perf_counter() - started, 3),
            "model_cache_bytes": cache_size(args.specific_model_path or args.cache_dir),
        }
    else:
        result = {
            "phase": "benchmark",
            **benchmark(args.model, args.cache_dir, args.specific_model_path),
        }
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
