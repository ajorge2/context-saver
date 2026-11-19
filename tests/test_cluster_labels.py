#!/usr/bin/env python3
"""Synthetic, local-only regressions for whole-cluster topic naming."""

from __future__ import annotations

import _support

import random
import unittest
from unittest.mock import patch

import thread_tree_labels as labels
import thread_tree_pipeline as pipeline


def rows(*texts: str) -> list[dict[str, str]]:
    return [{"id": f"synthetic-{index}", "text": text} for index, text in enumerate(texts)]


def large_groups() -> list[list[dict[str, str]]]:
    adjectives = "database payment browser memory network account document calendar storage search".split()
    nouns = "indexing reconciliation navigation caching scheduling validation retrieval routing migration monitoring".split()
    variations = (
        "validates complete source records", "tracks incremental refresh progress",
        "measures concurrent traffic behavior", "compares historical performance measurements",
        "preserves durable evidence links",
    )
    return [rows(*[
        f"USER: Please review {adjective} {noun} workflows.\n"
        f"ASSISTANT: {adjective} {noun} {variations[index % len(variations)]}. "
        "Common software maintenance remains documented."
        for index in range(100)
    ]) for adjective in adjectives for noun in nouns]


class ClusterLabelTests(unittest.TestCase):
    def test_role_prefixes_and_conversation_scaffolding_do_not_name_the_cluster(self) -> None:
        cluster = rows(*[
            f"{role}: Please help me with database query optimization.\n"
            "ASSISTANT: Database query optimization uses index tuning and query plans."
            for role in ("USER", "ASSISTANT", "SYSTEM")
        ])
        title, summary, keywords = pipeline._representation(cluster)
        self.assertEqual(title, "Database query optimization · Index tuning")
        self.assertIn("query plans", summary)
        self.assertNotRegex((title + summary).casefold(), r"user|assistant|system|please|help")
        self.assertIn("database query optimization", keywords)
        self.assertEqual((title, summary, keywords), labels.representation(cluster))

    def test_long_repetitive_first_message_cannot_outvote_the_cluster(self) -> None:
        cluster = rows("USER: " + "Vacation flights. " * 200, *[
            "USER: Database query optimization improves latency.\n"
            "ASSISTANT: Index tuning reduces query costs."
            for _ in range(9)
        ])
        title, summary, _ = labels.representation(cluster)
        self.assertIn("Database query optimization", title)
        self.assertNotIn("Vacation", title)
        self.assertNotIn("vacation", summary)
        self.assertIn("query costs", summary)

    def test_background_discounts_generic_terms_shared_by_other_clusters(self) -> None:
        cluster = rows(*["Common software maintenance. Database query optimization."] * 4,
                       *["Common software maintenance."] * 16)
        others = rows(*["Common software maintenance. Access token expiration."] * 80)
        context = labels.build_background(cluster + others)
        title, _, _ = labels.representation(cluster, context)
        self.assertEqual(title, "Database query optimization")
        other_title, _, _ = labels.representation(others, context)
        self.assertIn("Access token expiration", other_title)
        self.assertNotIn("Common software", other_title)

    def test_input_order_and_background_order_do_not_change_labels(self) -> None:
        cluster = rows(*[
            "SQL query planning and SQLite indexes.",
            "SQLite indexes improve SQL query planning.",
            "SQL query planning includes execution plans.",
        ] * 3)
        background = cluster + rows("API rate limits and request throttling.")
        expected = labels.representation(cluster, labels.build_background(background))
        random.Random(71).shuffle(cluster)
        random.Random(39).shuffle(background)
        self.assertEqual(expected, labels.representation(cluster, labels.build_background(background)))

    def test_code_syntax_is_omitted_and_readable_identifiers_remain_available(self) -> None:
        cluster = rows(*[
            "USER: API rate limits and request throttling.\n"
            "```javascript\nconst value = await db.execute(query);\nreturn value;\n```\n"
            "ASSISTANT: API rate limits use request throttling.\n"
            "const unusedValue = null;"
            for _ in range(4)
        ])
        title, summary, keywords = labels.representation(cluster)
        self.assertEqual(title, "API rate limits · Request throttling")
        self.assertNotRegex((title + summary).casefold(), r"const|unused|execute|null|javascript")
        self.assertTrue(all(1 <= len(phrase.split()) <= 3 for phrase in keywords))
        identifier_title, _, _ = labels.representation(rows(
            "Use `queryPlanCache` and `query_plan_cache` for repeated lookups."
        ))
        self.assertIn("Query plan cache", identifier_title)

    def test_acronyms_proper_names_and_title_length_are_preserved(self) -> None:
        cluster = rows(*[
            "SQLite query planning and SQL indexes. API request throttling. "
            "PostgreSQL execution plans and database performance measurements."
            for _ in range(3)
        ])
        title, summary, _ = labels.representation(cluster)
        self.assertLessEqual(len(title), 64)
        self.assertIn("SQLite", title + summary)
        self.assertNotIn("Sqlite", title + summary)
        self.assertIn("SQL", title + summary)
        self.assertIn("API", title + summary)
        self.assertTrue(all(1 <= len(phrase.split()) <= 3 for phrase in title.split(" · ")))

    def test_upper_layer_labels_use_all_child_themes_without_summary_scaffolding(self) -> None:
        first = labels.representation(rows(*["API rate limits and request throttling."] * 3))
        second = labels.representation(rows(*["Access token expiration and session renewal."] * 3))
        children = rows(*[f"{title}\n{summary}" for title, summary, _ in (first, second)])
        title, summary, keywords = labels.representation(children)
        self.assertTrue(any(phrase in (title + summary).casefold() for phrase in (
            "api rate limits", "request throttling", "access token expiration", "session renewal",
        )))
        self.assertNotIn("topics", " ".join(keywords))
        self.assertNotIn("include", " ".join(keywords))
        self.assertNotIn("USER:", summary)

    def test_empty_or_code_only_content_has_an_honest_generic_fallback(self) -> None:
        for cluster in ([], rows("USER: Please help."), rows("```python\nreturn None\n```")):
            self.assertEqual(labels.representation(cluster), (
                "Conversation topic", "No readable topic terms were found.", [],
            ))

    def test_acknowledgments_are_named_as_acknowledgments_without_a_domain_guess(self) -> None:
        cluster = rows("USER: All right, carry on.", "ASSISTANT: Certainly, understood.")
        title, summary, keywords = labels.representation(cluster)
        self.assertEqual(title, "Acknowledgments")
        self.assertIn("acknowledgments", summary)
        self.assertEqual(keywords, [])

    def test_instruction_and_judgment_fragments_use_a_neutral_fallback(self) -> None:
        examples = (
            rows("Tell me precisely which part needs attention.", "That should already be shown above."),
            rows("It seems obvious in hindsight.", "The remaining bits appear reasonable."),
            rows("The draft can wait until tomorrow.", "Someone should confirm the last step."),
            rows("An employee noticed the voblum.", "Another employee responded privately."),
        )
        for cluster in examples:
            with self.subTest(cluster=cluster):
                title, summary, keywords = labels.representation(cluster)
                self.assertEqual(title, "Conversation notes")
                self.assertEqual(summary, "No sufficiently specific topic phrase was found.")
                self.assertEqual(keywords, [])

    def test_varied_natural_technical_text_keeps_domain_phrases_and_rejects_clause_fragments(self) -> None:
        cluster = rows(
            "Requests are arriving faster than the service permits.",
            "Request throttling prevents overload.",
            "Add exponential backoff after HTTP 429 responses.",
            "Bound the retry budget and add jitter to the delay.",
        )
        title, summary, keywords = labels.representation(cluster)
        self.assertEqual(title, "Exponential backoff · Request throttling")
        self.assertNotIn("arriving", summary)
        self.assertNotIn("permits", summary)
        self.assertIn("request throttling", keywords)
        self.assertIn("retry budget", keywords)

    def test_repeated_generic_singletons_do_not_defeat_specific_phrases(self) -> None:
        cluster = rows("Request.", "Request.", "Request.", "Request throttling.", "Network timeouts.")
        title, _, keywords = labels.representation(cluster)
        self.assertEqual(title, "Network timeouts · Request throttling")
        self.assertNotIn("request", keywords)
        self.assertEqual(labels.representation(rows("Request.", "Request."))[0], "Conversation notes")

    def test_meaningful_acronyms_proper_names_and_imperative_objects_survive(self) -> None:
        for term in ("API", "SQL", "PostgreSQL"):
            self.assertEqual(labels.representation(rows(term))[0], term)
        cluster = rows("Inspect cache keys.", "Cache keys determine Redis connection reuse.",
                       "Redis connection reuse improves cache keys.")
        title, summary, _ = labels.representation(cluster)
        self.assertIn("Cache keys", title)
        self.assertNotIn("inspect", title.casefold())
        self.assertIn("Redis", title + summary)

    def test_diverse_domain_free_chatter_does_not_turn_into_confident_topic_names(self) -> None:
        examples = (
            ("Could you put everything where it belongs?", "Go back and try the other option."),
            ("That looks right.", "It might be necessary."),
            ("Do the same thing with the later part.", "Pick whatever makes the most sense."),
            ("Someone else needs to decide soon.", "We have reached the point where it is obvious."),
            ("You can refer to the previous answer.", "I checked and it remained unchanged."),
            ("Something similar happened before.", "The answer seems plausible enough."),
            ("Which one would you prefer?", "It could turn out differently."),
            ("The outcome is still uncertain.", "Please spell this out carefully."),
            ("That is precisely what I was trying to say.", "Looks clear enough already."),
            ("Proceed whenever you think appropriate.", "Those sections seem unrelated to me."),
        )
        for pair in examples:
            with self.subTest(pair=pair):
                title, _, keywords = labels.representation(rows(*pair))
                self.assertIn(title, {"Conversation notes", "Conversation topic", "Acknowledgments"})
                self.assertEqual(keywords, [])

    def test_fragment_suffix_checks_do_not_reject_nouns_or_proper_names(self) -> None:
        family = rows(*["Family budgeting and emergency savings."] * 3)
        title, summary, _ = labels.representation(family)
        self.assertIn("Family budgeting", title + summary)
        garden = rows(*["Seed germination and garden soil."] * 3)
        title, summary, _ = labels.representation(garden)
        self.assertIn("Seed germination", title + summary)

    def test_upper_layers_do_not_promote_fallback_explanations_into_topic_facts(self) -> None:
        neutral = labels.representation(rows("Tell me which part needs attention.", "Someone should confirm it."))
        children = rows(*[f"{neutral[0]}\n{neutral[1]}"] * 4)
        title, _, keywords = labels.representation(children)
        self.assertIn(title, {"Conversation notes", "Conversation topic"})
        self.assertEqual(keywords, [])
        acknowledgment = labels.representation(rows("All right, carry on.", "Certainly, understood."))
        children = rows(*[f"{acknowledgment[0]}\n{acknowledgment[1]}"] * 4)
        self.assertEqual(labels.representation(children)[0], "Acknowledgments")

    def test_negated_requirements_never_become_affirmative_action_labels(self) -> None:
        examples = (
            "Do not delete production data.",
            "Never retry an already charged payment.",
            "The signed original must not be overwritten.",
            "Avoid replacing the archived photograph.",
            "Don't publish the unfinished recording.",
        )
        for text in examples:
            with self.subTest(text=text):
                title, summary, keywords = labels.representation(rows(text))
                self.assertEqual(title, "Constraints and caveats")
                self.assertIn("negative requirements", summary)
                self.assertEqual(keywords, [])

    def test_mixed_cluster_marks_constraints_without_extracting_prohibited_actions(self) -> None:
        cluster = rows("Never remove the only backup.", "Request throttling.", "Request throttling.")
        title, summary, keywords = labels.representation(cluster)
        self.assertEqual(title, "Request throttling")
        self.assertIn("negative requirements", summary)
        self.assertNotIn("remove", title.casefold())
        self.assertNotIn("backup", " ".join(keywords))
        self.assertEqual(keywords, ["request throttling"])

    def test_multi_sentence_topics_survive_an_independent_prohibition(self) -> None:
        cluster = rows(
            "Pinecone vector search supports metadata filtering. "
            "Do not delete production data. Index tuning improves query latency."
        )
        title, summary, keywords = labels.representation(cluster)
        self.assertIn("vector search", (title + summary).casefold())
        self.assertIn("index tuning", (title + summary).casefold())
        self.assertFalse(title.startswith("Constraints"))
        self.assertIn("negative requirements", summary)
        self.assertNotIn("delete", " ".join(keywords))
        self.assertNotIn("production data", " ".join(keywords))

    def test_semantic_singleton_inherits_its_useful_child_title(self) -> None:
        row = {"id": "semantic-child", "text": "Qdrant\nTopics include vector indexing.",
               "descendant_members": [("synthetic-chunk", 1.0)]}
        self.assertEqual(pipeline._representation([row])[:2], ("Qdrant", "Topics include vector indexing."))
        old_prefix = {**row, "text": "Constraints · Qdrant\nTopics include vector indexing."}
        self.assertEqual(pipeline._representation([old_prefix])[0], "Qdrant")
        # A raw chunk must still be named from its complete content.
        raw = {**row, "seq": 1, "thread_id": "synthetic-chat"}
        self.assertNotEqual(pipeline._representation([raw])[0], "Qdrant")

    def test_incomplete_trailing_verb_is_not_a_topic_or_inherited_title(self) -> None:
        title, _, _ = labels.representation(rows("Technical write.", "Technical write."))
        self.assertNotIn("Technical write", title)
        row = {"id": "semantic-child", "text": "Vector indexing · Technical write\nTopics include vector indexing.",
               "descendant_members": [("synthetic-chunk", 1.0)]}
        self.assertEqual(pipeline._representation([row])[0], "Vector indexing")

    def test_ten_thousand_rows_are_processed_twice_not_once_per_cluster(self) -> None:
        groups = large_groups()
        corpus = [row for group in groups for row in group]
        self.assertEqual(len(corpus), 10_000)
        with patch.object(labels, "_document", wraps=labels._document) as extract:
            context = labels.build_background(corpus)
            outputs = [labels.representation(group, context) for group in groups]
        # An operation-count regression is stable across machines. There is
        # deliberately no wall-clock threshold for this representative corpus.
        self.assertEqual(extract.call_count, 20_000)
        self.assertEqual(context.document_count, 10_000)
        self.assertLess(len(context.term_documents), 100)
        self.assertEqual(len({title for title, _, _ in outputs}), 100)
        self.assertTrue(all(len(title) <= 64 for title, _, _ in outputs))


if __name__ == "__main__":
    unittest.main()
