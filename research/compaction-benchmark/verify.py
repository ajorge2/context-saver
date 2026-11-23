#!/usr/bin/env python3
"""Verify public benchmark integrity, arithmetic, and generated output offline.

No model calls or network access. Tests challenge the analyzer with deliberately
corrupted copies as well as comparing it with saved historical summaries.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import importlib.util
import math
from pathlib import Path
import sys
import unittest

import analyze

ROOT = Path(__file__).resolve().parent


def equivalent(actual, expected, path="root"):
    """Compare all cached values with absolute/relative floating-point tolerance."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            raise AssertionError(f"{path}: dictionary keys differ")
        for key in expected:
            equivalent(actual[key], expected[key], f"{path}.{key}")
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise AssertionError(f"{path}: list shape differs")
        for i, value in enumerate(expected):
            equivalent(actual[i], value, f"{path}[{i}]")
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not isinstance(actual, (int, float)) or isinstance(actual, bool) or not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-9):
            raise AssertionError(f"{path}: {actual!r} != {expected!r}")
    elif actual != expected or type(actual) is not type(expected):
        raise AssertionError(f"{path}: {actual!r} != {expected!r}")


def validate(data):
    summary = analyze.summarize(data)
    cached = data["cached-summaries"]
    equivalent(summary["semantic"], cached["semantic"]["conditions"], "semantic.conditions")
    equivalent(summary["r3_changes"]["corrected"], cached["semantic"]["r3_paired_corrected_fields"], "paired.corrected")
    equivalent(summary["r3_changes"]["regressed"], cached["semantic"]["r3_paired_regressed_fields"], "paired.regressed")
    for category in ("strict_accuracy", "strict_quality", "cost", "maintenance", "diagnostics"):
        equivalent(summary[category], cached[category], category)
    return summary


class PublicBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = analyze.read_data()
        cls.summary = validate(cls.data)

    def test_historical_summaries_all_recomputed(self):
        """Every republished cached arithmetic summary agrees with underlying records."""
        validate(self.data)

    def test_complete_unique_answer_matrix(self):
        records = self.data["records"]["records"]
        self.assertEqual(len(records), 42)
        self.assertEqual(len({r["record_id"] for r in records}), 42)
        self.assertEqual(len({(r["case_id"], r["condition"]) for r in records}), 42)
        self.assertEqual(len(self.data["fixtures"]["cases"]), 6)
        self.assertEqual(self.summary["authored_turn_count"], 101)
        for r in records:
            self.assertEqual(r["record_id"], r["case_id"] + "--" + r["condition"])
            self.assertEqual(set(r["fields"]), set(analyze.FIELDS))
            self.assertEqual(set(r["semantic_grades"]), set(analyze.FIELDS))
            for field in r["fields"].values():
                self.assertIsInstance(field["actual"], str)
                self.assertIsInstance(field["supplied_citations"], list)

    def test_frozen_headline_and_controls(self):
        expected = {"r0_off":36,"r0_on":36,"r1_off":24,"r1_on":32,"r3_off":19,"r3_on":33,"long_off":35}
        for condition, count in expected.items():
            self.assertEqual(self.summary["semantic"][condition]["decision_fields"], count)
            self.assertEqual(self.summary["semantic"][condition]["all_fields"], count+12)
            self.assertEqual(self.summary["semantic"][condition]["field_correct_counts"]["recent"],6)
            self.assertEqual(self.summary["semantic"][condition]["field_correct_counts"]["unsupported"],6)
        self.assertEqual(self.summary["decision_denominator_per_condition"],36)
        self.assertEqual(self.summary["control_denominator_per_condition"],12)
        self.assertEqual(self.summary["r3_changes"],{"corrected":15,"regressed":1,"both_correct":18,"both_incorrect":2})
        self.assertEqual(self.summary["semantic"]["r3_off"]["full_decisions"],1)
        self.assertEqual(self.summary["semantic"]["r3_on"]["full_decisions"],3)
        self.assertEqual(self.summary["semantic"]["r3_off"]["main_actions"],5)
        self.assertEqual(self.summary["semantic"]["r3_on"]["main_actions"],5)

    def test_individual_incident_pairing_and_regression(self):
        keyed={(r["case_id"],r["condition"]):r for r in self.data["records"]["records"]}
        expected={"stale-canary":(2,6),"ambiguous-commit":(1,5),"stale-rejoin":(2,6),
                  "post-seal-recovery":(3,6),"purge-restart":(6,5),"signed-backoff":(5,5)}
        for case,(before,after) in expected.items():
            self.assertEqual(sum(keyed[case,"r3_off"]["semantic_grades"][f] for f in analyze.DECISIONS),before)
            self.assertEqual(sum(keyed[case,"r3_on"]["semantic_grades"][f] for f in analyze.DECISIONS),after)
        regressions=[c for c in self.summary["changes"] if c["round"]==3 and c["change"]=="regressed"]
        self.assertEqual([(r["case_id"],r["field"]) for r in regressions],[("purge-restart","operations")])

    def test_token_subtotals_are_not_double_counted(self):
        for record in self.data["records"]["records"]:
            u=record["usage"]
            self.assertEqual(u["inputTokens"]+u["outputTokens"],u["totalTokens"],record["record_id"])
            self.assertEqual(u["inputTokens"]-u["cachedInputTokens"],u["uncachedInputTokens"])
            self.assertLessEqual(u["cachedInputTokens"],u["inputTokens"])
            self.assertLessEqual(u["reasoningOutputTokens"],u["outputTokens"])
            self.assertGreaterEqual(u["model_requests"],1)
            self.assertTrue(math.isclose(record["elapsed_s"]+record["setup_s"],record["fork_and_answer_elapsed_s"],abs_tol=1e-8))
            self.assertEqual(record["mcp_calls"],record["mcp_completed"]+record["mcp_failed"])
        final=self.summary["cost"]["r3"]
        self.assertAlmostEqual(final["totalTokens"]["paired_mean"],45785.5)
        self.assertAlmostEqual(final["cachedInputTokens"]["paired_mean"],29760)
        self.assertAlmostEqual(final["uncachedInputTokens"]["paired_mean"],15688.166666666666)
        self.assertAlmostEqual(final["outputTokens"]["paired_mean"],337.3333333333333)
        self.assertAlmostEqual(sum(final[key]["paired_mean"] for key in ("cachedInputTokens","uncachedInputTokens","outputTokens")),final["totalTokens"]["paired_mean"])
        self.assertAlmostEqual(final["fork_and_answer_elapsed_s"]["paired_mean"],11.666167757153744)

    def test_shared_compactions_and_searches(self):
        scenarios=self.data["measurements"]["scenarios"]
        self.assertEqual(sum(len(s["compactions"]) for s in scenarios),18)
        for s in scenarios:
            self.assertEqual({c["round"] for c in s["compactions"]},{1,2,3})
            for c in s["compactions"]:
                u=c["provider_usage"]
                self.assertEqual(u["input_tokens"]+u["output_tokens"],u["total_tokens"])
        quality=self.summary["strict_quality"]["r3_on"]
        self.assertEqual(quality["completed_lookups"],19)
        self.assertEqual(quality["failed_lookups"],0)
        self.assertEqual(quality["lookup_answers"],4)
        self.assertEqual(quality["exposed_verified_evidence"],24)

    def test_export_file_hashes_and_privacy_whitelist(self):
        manifest=self.data["provenance"]["export_sha256"]
        actual={p.name for p in (ROOT/"data").glob("*.json") if p.name!="provenance.json"}
        self.assertEqual(set(manifest),actual)
        for name,digest in manifest.items():
            content=(ROOT/"data"/name).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(),digest,name)
            for forbidden in (b"/Users/",b"/home/",b"/private/",b"encrypted_content",b"compaction_response_id",b"access_token",b"refresh_token"):
                self.assertNotIn(forbidden,content,name)
        for record in self.data["records"]["records"]:
            self.assertFalse({"thread","turn","response_id","items"}&set(record))
            for field in record["fields"].values():
                self.assertNotIn("matching_evidence",field)
        for scenario in self.data["measurements"]["scenarios"]:
            for compaction in scenario["compactions"]:
                self.assertFalse({"thread","turn","items","usage","answer","compaction_response_id"}&set(compaction))

    def test_archived_fixture_and_harness_source_hashes(self):
        harness=ROOT/"harness"/"meridian-compaction-2026-11-17"/"reproduction"
        provenance={p["source_relative_path"]:p for p in self.data["provenance"]["source_artifacts"]}
        for basename in ("context-saver-human-fixtures.py","context-saver-human-run.py","context-saver-human-score.py"):
            content=(harness/basename).read_bytes()
            entry=provenance["reproduction/"+basename]
            self.assertEqual(hashlib.sha256(content).hexdigest(),entry["sha256"],basename)
            self.assertEqual(len(content),entry["bytes"])
        fixture_path=harness/"context-saver-human-fixtures.py"
        self.assertEqual(hashlib.sha256(fixture_path.read_bytes()).hexdigest(),self.data["run-manifest"]["fixture_sha256"])
        spec=importlib.util.spec_from_file_location("public_frozen_fixture_verification",fixture_path)
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
        spec.loader.exec_module(module)
        original=[]
        for scenario in module.SCENARIOS:
            case=asdict(scenario);case["rounds"]=case["rounds"][:4];original.append(case)
        # JSON normalization changes tuple arrays only, not authored strings or rules.
        import json
        original=json.loads(json.dumps(original,ensure_ascii=False))
        exported=[{k:v for k,v in c.items() if k!="note"} for c in self.data["fixtures"]["cases"]]
        self.assertEqual(original,exported)

    def test_generated_outputs_current_and_deterministic(self):
        first=analyze.outputs(self.data,self.summary)
        second=analyze.outputs(deepcopy(self.data),analyze.summarize(deepcopy(self.data)))
        self.assertEqual(first,second)
        for name,text in first.items():
            self.assertEqual((ROOT/"analysis"/name).read_text(encoding="utf-8"),text,name)
        for case in self.data["fixtures"]["cases"]:
            text=first[f"cases/{case['id']}.md"]
            for condition in analyze.CONDITIONS:
                self.assertIn(f'id="{condition}"',text)
            for record in self.data["records"]["records"]:
                if record["case_id"]==case["id"]:
                    for field in record["fields"].values():
                        self.assertIn(field["actual"],text)

    def test_negative_control_changed_grade_is_detected(self):
        corrupt=deepcopy(self.data)
        answer=next(r for r in corrupt["records"]["records"] if r["condition"]=="r3_on" and r["case_id"]=="stale-canary")
        answer["semantic_grades"]["gate"]=False
        with self.assertRaisesRegex(AssertionError,"semantic.conditions"):
            validate(corrupt)

    def test_negative_control_changed_token_cost_is_detected(self):
        corrupt=deepcopy(self.data)
        answer=next(r for r in corrupt["records"]["records"] if r["condition"]=="r3_on")
        # Preserve internal input/total arithmetic while changing an actual cost.
        for key in ("inputTokens","uncachedInputTokens","totalTokens"):
            answer["usage"][key]+=100
        with self.assertRaisesRegex(AssertionError,"cost"):
            validate(corrupt)

    def test_negative_control_changed_elapsed_cost_is_detected(self):
        corrupt=deepcopy(self.data)
        answer=next(r for r in corrupt["records"]["records"] if r["condition"]=="r3_on")
        answer["elapsed_s"]+=1;answer["fork_and_answer_elapsed_s"]+=1
        with self.assertRaisesRegex(AssertionError,"cost"):
            validate(corrupt)

    def test_negative_controls_missing_and_duplicate_answers(self):
        corrupt=deepcopy(self.data);corrupt["records"]["records"].pop()
        with self.assertRaisesRegex(ValueError,"every case"):
            validate(corrupt)
        corrupt=deepcopy(self.data);corrupt["records"]["records"].append(deepcopy(corrupt["records"]["records"][0]))
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            validate(corrupt)

    def test_negative_control_non_boolean_grade_is_detected(self):
        corrupt=deepcopy(self.data)
        corrupt["records"]["records"][0]["semantic_grades"]["gate"]="false"
        with self.assertRaisesRegex(ValueError,"must be booleans"):
            validate(corrupt)

    def test_negative_control_cached_summary_tampering(self):
        corrupt=deepcopy(self.data)
        corrupt["cached-summaries"]["semantic"]["conditions"]["r3_on"]["decision_fields"]=34
        with self.assertRaisesRegex(AssertionError,"semantic.conditions"):
            validate(corrupt)


if __name__=="__main__":
    unittest.main(verbosity=2)
