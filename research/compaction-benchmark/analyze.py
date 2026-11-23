#!/usr/bin/env python3
"""Offline, deterministic analysis of the archived synthetic compaction experiment.

Python 3.10+ standard library only. No account, model, network, index or runtime
plugin is read. Boolean semantic grades are preserved historical judgments;
this program recomputes their arithmetic, not their truth.
"""
from __future__ import annotations

import argparse
import csv
import html
import io
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parent
CONDITIONS = ("r0_off", "r0_on", "r1_off", "r1_on", "r3_off", "r3_on", "long_off")
DECISIONS = ("disposition", "target", "operations", "gate", "scope", "authority")
CONTROLS = ("recent", "unsupported")
FIELDS = DECISIONS + CONTROLS
LABELS = {
    "r0_off": "Before compaction · Context Saver off",
    "r0_on": "Before compaction · Context Saver on",
    "r1_off": "After one compaction · Context Saver off",
    "r1_on": "After one compaction · Context Saver on",
    "r3_off": "After three compactions · Context Saver off",
    "r3_on": "After three compactions · Context Saver on",
    "long_off": "Same intervening work, never compacted · off",
}
FIELD_LABELS = {
    "disposition": "Action to take", "target": "Object or identity to use",
    "operations": "Steps in the required order", "gate": "Conditions before proceeding",
    "scope": "Who is affected or preserved", "authority": "Source that overrides conflicting evidence",
    "recent": "Current branch (control)", "unsupported": "Unrecorded ticket ID (control)",
}
INTRO = ("Context Saver is a plugin that lets a coding agent search earlier project chats. "
         "This experiment compares answers about earlier project decisions with and without that search "
         "after the chats were compacted. Compaction is the coding assistant’s reduction of older "
         "conversation context to fit its working context.")
COST_METRICS = ("elapsed_s", "setup_s", "fork_and_answer_elapsed_s", "inputTokens",
                "cachedInputTokens", "uncachedInputTokens", "outputTokens",
                "reasoningOutputTokens", "totalTokens", "model_requests")


def read_data(data_dir: Path = ROOT / "data") -> dict:
    return {name: json.loads((data_dir / f"{name}.json").read_text(encoding="utf-8"))
            for name in ("records", "fixtures", "measurements", "cached-summaries", "run-manifest", "provenance")}


def metric(record: dict, key: str) -> float:
    return record[key] if key in record else record["usage"][key]


def summarize(data: dict) -> dict:
    records = data["records"]["records"]
    cases = data["fixtures"]["cases"]
    keyed = {(r["case_id"], r["condition"]): r for r in records}
    if len(keyed) != len(records):
        raise ValueError("Duplicate case/condition answer record")
    expected = {(c["id"], condition) for c in cases for condition in CONDITIONS}
    if set(keyed) != expected:
        raise ValueError("Answer records must contain every case × condition exactly once")
    for record in records:
        if set(record["fields"]) != set(FIELDS) or set(record["semantic_grades"]) != set(FIELDS):
            raise ValueError("Each answer must contain exactly six decision fields and two controls")
        if any(type(v) is not bool for v in record["semantic_grades"].values()):
            raise ValueError("Semantic grades must be booleans")
    semantic = {}
    quality = {}
    strict = {key: {} for key in data["cached-summaries"]["strict_accuracy"]}
    for condition in CONDITIONS:
        observed = [keyed[c["id"], condition] for c in cases]
        fields = [field for record in observed for field in record["fields"].values()]
        counts = {f: sum(r["semantic_grades"][f] for r in observed) for f in FIELDS}
        semantic[condition] = {
            "decision_fields": sum(counts[f] for f in DECISIONS),
            "all_fields": sum(counts.values()),
            "full_decisions": sum(all(r["semantic_grades"][f] for f in DECISIONS) for r in observed),
            "main_actions": counts["disposition"], "field_correct_counts": counts,
        }
        for name in strict:
            if name in ("full", "primary"):
                values = [r[f"strict_{name}_correct"] for r in observed]
            else:
                values = [f["correct"] for f in fields if name == "fields" or f["category"] == name
                          or (name == "supported" and not f["unsupported"])]
            strict[name][condition] = {"correct": sum(values), "total": len(values)}
        quality[condition] = {
            "answers": len(observed), "lookup_answers": sum(bool(r["mcp_calls"]) for r in observed),
            "lookup_calls": sum(r["mcp_calls"] for r in observed),
            "completed_lookups": sum(r["mcp_completed"] for r in observed),
            "failed_lookups": sum(r["mcp_failed"] for r in observed),
            "explicitly_harmful_answers": sum(r["strict_harmful"] for r in observed),
            "explicitly_harmful_fields": sum(f["harmful"] for f in fields),
            "false_abstentions": sum(f["outcome"] == "false_abstention" for f in fields),
            "unsupported_claims": sum(f["outcome"] == "unsupported_claim" for f in fields),
            "malformed_answers": sum(bool(r["format_issues"]) for r in observed),
            "exposed_verified_evidence": sum(f["verified_evidence_returned"] for f in fields),
            "exposed_and_correct": sum(f["verified_evidence_returned"] and f["correct"] for f in fields),
            "all_verified_evidence_cited": sum(f["all_verified_evidence_cited"] for f in fields),
            "exposed_correct_and_cited": sum(f["citation_complete"] for f in fields),
        }
    changes = []
    costs = {}
    cost_pairs = []
    for round_number in (0, 1, 3):
        tag = f"r{round_number}"
        costs[tag] = {}
        for key in COST_METRICS:
            off = [metric(keyed[c["id"], f"{tag}_off"], key) for c in cases]
            on = [metric(keyed[c["id"], f"{tag}_on"], key) for c in cases]
            deltas = [b-a for a, b in zip(off, on)]
            costs[tag][key] = {"off_mean": statistics.fmean(off), "on_mean": statistics.fmean(on),
                               "paired_mean": statistics.fmean(deltas), "paired_median": statistics.median(deltas)}
            for case, a, b, delta in zip(cases, off, on, deltas):
                cost_pairs.append({"case_id": case["id"], "round": round_number,
                                   "metric": key, "off": a, "on": b, "on_minus_off": delta})
        for case in cases:
            for field in DECISIONS:
                off = keyed[case["id"], f"{tag}_off"]["semantic_grades"][field]
                on = keyed[case["id"], f"{tag}_on"]["semantic_grades"][field]
                status = {(True, True): "both_correct", (False, False): "both_incorrect",
                          (False, True): "corrected", (True, False): "regressed"}[off, on]
                changes.append({"case_id": case["id"], "round": round_number,
                                "field": field, "off_correct": off, "on_correct": on, "change": status})
    measurements = data["measurements"]["scenarios"]
    maintenance = {}
    for round_number in (1, 2, 3):
        compactions = [next(c for c in s["compactions"] if c["round"] == round_number) for s in measurements]
        usage = [c["provider_usage"] for c in compactions if c.get("provider_usage") is not None]
        maintenance[str(round_number)] = {"wall_s_mean": statistics.fmean(c["elapsed_s"] for c in compactions),
            "usage_records": len(usage), "total_records": len(compactions),
            "usage_means": {key: statistics.fmean(u.get(key, 0) for u in usage)
                            for key in ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")}}
    diagnostics = {}
    for round_number in (0, 1, 3):
        tag = f"r{round_number}"
        observed = [keyed[c["id"], f"{tag}_on"] for c in cases]
        timings = [r["native_mcp_timing"] for r in observed if r["mcp_calls"]]
        durations = [v for t in timings for v in t["durations_ms"]]
        overlaps = [s["probe_pair_overlap_s"][tag] for s in measurements]
        visibility = [len(s["checkpoints"][tag]["older_fields_with_all_exact_evidence_visible"])
                      for s in measurements if "older_fields_with_all_exact_evidence_visible" in s["checkpoints"][tag]]
        diagnostics[tag] = {"overlap_seconds_mean": statistics.fmean(overlaps),
            "overlapping_pairs": sum(v > 0 for v in overlaps),
            "search_turns": len(timings), "search_calls": len(durations),
            "lookup_seconds_mean": statistics.fmean(durations)/1000 if durations else None,
            "active_lookup_seconds_per_search_turn_mean": statistics.fmean(t["active_union_ms"] for t in timings)/1000 if timings else None,
            "search_turns_with_parallel_mcp_calls": sum(t["peak_parallel"] > 1 for t in timings),
            "peak_concurrent_mcp_calls": max((t["peak_parallel"] for t in timings), default=0),
            "older_fields_all_exact_evidence_visible": sum(visibility) if visibility else None}
    final_changes = [c for c in changes if c["round"] == 3]
    return {"semantic": semantic, "strict_accuracy": strict, "strict_quality": quality, "cost": costs,
            "maintenance": maintenance, "diagnostics": diagnostics, "changes": changes, "cost_pairs": cost_pairs,
            "r3_changes": {key: sum(c["change"] == key for c in final_changes)
                           for key in ("corrected", "regressed", "both_correct", "both_incorrect")},
            "decision_denominator_per_condition": len(cases)*len(DECISIONS),
            "control_denominator_per_condition": len(cases)*len(CONTROLS),
            "answer_count": len(records), "case_count": len(cases),
            "authored_turn_count": sum(len(round_) for c in cases for round_ in c["rounds"])}


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)+"\n"


def csv_text(rows: list[dict]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader(); writer.writerows(rows)
    return stream.getvalue()


def cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def literal(text: str) -> str:
    # The archive's field text remains byte-for-byte within the text fence.
    fence = "`" * max(3, max((len(s) for s in __import__("re").findall(r"`+", text)), default=0)+1)
    return f"{fence}text\n{text}\n{fence}"


def case_page(case: dict, records: dict, summary: dict) -> str:
    cid = case["id"]
    lines = [f"# {case['title']}", "", INTRO, "", "[Results overview](../results.md) · [Complete authored chat](../chats/"+cid+".md) · [All retained answer data](../../data/records.json)", "",
             "This is one synthetic incident in a fictional software release controller. Each answer below came from the same final question at the indicated history checkpoint. Compaction is the coding assistant's reduction of older chat context to fit its working context.", "",
             "The six operational fields test the action, target, ordered steps, prerequisites, affected scope, and authoritative source. The current branch and an unrecorded ticket ID are two separate controls; they are excluded from the headline denominator.", "",
             "`PASS` and `FAIL` below reproduce the published blinded AI semantic grader's boolean judgments. They are not new judgments by this analysis script. Reviewer rationales were not archived; compare the preserved wording with the frozen rubric yourself. Each incident had one of two reviewers, not two independent grades.", "",
             "The original archive retains parsed field strings and readable citations, not a byte-for-byte full JSON response envelope. Field text inside each text block is preserved unchanged. Citation labels are original strings; synthetic chunk IDs and native session IDs were removed.", "", "## Compare the seven answers", "", "| Checkpoint and plugin state | Operational fields correct | Controls correct |", "|---|---:|---:|"]
    for condition in CONDITIONS:
        r = records[cid, condition]; grades = r["semantic_grades"]
        lines.append(f"| [{LABELS[condition]}](#{condition}) | {sum(grades[f] for f in DECISIONS)}/6 | {sum(grades[f] for f in CONTROLS)}/2 |")
    lines += ["", "## Final question", "", literal(case["probe"]), "", "## Frozen scoring rules", "", "These rules and their approved source excerpts were fixed before the answers were collected. Accepted aliases supported the initial exact-text scorer; the later semantic review allowed equivalent wording and required every material clause. Historical machine-exact results are retained separately for diagnosing the first scorer.", ""]
    for rule in case["rubric"]:
        lines += [f"### `{rule['id']}` — {rule['description']}", "", "**Approved source excerpt(s):**", ""]
        lines += [literal(v)+"\n" for v in rule["evidence"]] if rule["evidence"] else ["None: this is the control for a fact never recorded in the chat.", ""]
        lines += ["**Frozen accepted aliases:**", "", *[f"- {cell(v)}" for v in rule["accepted"]], ""]
        if rule["harmful"]:
            lines += ["**Explicitly harmful alternatives specified in the original rubric:**", "", *[f"- {cell(v)}" for v in rule["harmful"]], ""]
    for condition in CONDITIONS:
        r = records[cid, condition]
        lines += [f'<a id="{condition}"></a>', "", f"## {LABELS[condition]}", "", f"Record: `{r['record_id']}`. Operational score: **{sum(r['semantic_grades'][f] for f in DECISIONS)}/6**. Controls: **{sum(r['semantic_grades'][f] for f in CONTROLS)}/2**.", "",
                  f"Observed fork-and-answer time: **{r['fork_and_answer_elapsed_s']:.3f} s**; model input: **{r['usage']['inputTokens']:,}** tokens (including **{r['usage']['cachedInputTokens']:,}** cached input); output: **{r['usage']['outputTokens']:,}** tokens; model requests: **{r['usage']['model_requests']}**; completed history searches: **{r['mcp_completed']}**.", ""]
        for f in FIELDS:
            field = r["fields"][f]
            lines += [f"### {FIELD_LABELS[f]} — {'PASS' if r['semantic_grades'][f] else 'FAIL'}", "", literal(field["actual"]), "",
                      "Citations returned in this field: "+("; ".join(f"`{v}`" for v in field["supplied_citations"]) if field["supplied_citations"] else "none (an answer may still be supported directly by the chat)."), "",
                      f"Archived exact-text scorer: `{field['outcome']}`. Verified source evidence was {'returned' if field['verified_evidence_returned'] else 'not returned'} by a history lookup for this field. Exact-text scoring is not the headline semantic grade.", ""]
    return "\n".join(lines).rstrip()+"\n"


def chat_page(case: dict) -> str:
    cid = case["id"]
    lines = [f"# Complete authored chat: {case['title']}", "", INTRO, "", f"[Answer and scoring records](../cases/{cid}.md) · [Results overview](../results.md) · [Machine-readable fixture](../../data/fixtures.json)", "",
             "This is an authored synthetic conversation used to seed the experiment, not a natural customer chat. User and assistant messages below are fixture text. The responding Codex model was asked only the final question; it did not implement the fictional controller or generate these intervening work reports.", "",
             "The initial design records establish the approved rules and superseded proposals. Three rounds of intervening work then provide distracting, plausible project discussion. The compacted history received native compaction after each round. The uncompacted control received the same authored messages and acknowledgments, without compaction. Earlier probe answers were never fed into later checkpoints.", "",
             "Only the early design and three work rounds actually used by the archived experiment are shown. Native compacted checkpoint contents are not available in this public archive, so these are source histories rather than reconstructions of what each compacted model could see.", ""]
    turn = 0
    for phase, turns in enumerate(case["rounds"]):
        lines += [f"## {'Initial design records' if phase == 0 else f'Intervening work round {phase}'}", ""]
        for pair in turns:
            turn += 1
            lines += [f"### Turn {turn} — user", "", literal(pair["user"]), "", f"### Turn {turn} — authored assistant", "", literal(pair["assistant"]), ""]
    lines += ["## Final question used at each checkpoint", "", literal(case["probe"]), ""]
    return "\n".join(lines)


def svg_header(title: str, description: str, height: int) -> list[str]:
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="{height}" viewBox="0 0 1000 {height}" role="img" aria-labelledby="title desc">',
            f'<title id="title">{html.escape(title)}</title>', f'<desc id="desc">{html.escape(description)}</desc>',
            '<rect width="100%" height="100%" rx="12" fill="#f8fafc"/>',
            '<g font-family="Arial, Helvetica, sans-serif" fill="#172033">',
            f'<text x="32" y="42" font-size="23" font-weight="700">{html.escape(title)}</text>']


def accuracy_svg(summary: dict) -> str:
    svg = svg_header("Decision accuracy before and after chat compaction", "Correct operational fields out of 36 per condition. Six synthetic incidents, six fields each. Historical blinded AI semantic grades.", 565)
    svg += ['<text x="32" y="70" font-size="15">Six synthetic incidents × six operational fields; historical blinded AI semantic grades</text>']
    for i, condition in enumerate(CONDITIONS):
        y = 112+i*54; n = summary["semantic"][condition]["decision_fields"]
        color = "#2563eb" if condition.endswith("_on") else ("#64748b" if condition=="long_off" else "#b45309")
        svg += [f'<text x="32" y="{y+17}" font-size="14">{html.escape(LABELS[condition])}</text>',
                f'<rect x="432" y="{y}" width="450" height="26" rx="4" fill="#e2e8f0"/>',
                f'<rect x="432" y="{y}" width="{450*n/36:.3f}" height="26" rx="4" fill="{color}"/>',
                f'<text x="898" y="{y+18}" font-size="16" font-weight="700">{n}/36</text>']
    svg += ['<text x="32" y="520" font-size="14">Two controls per answer are excluded. The 36 fields are correlated within the six incidents.</text>',
            '<text x="32" y="544" font-size="14">Off/on answer forks share the same question and history checkpoint; this is one archived run.</text>', '</g></svg>']
    return "\n".join(svg)+"\n"


def overhead_svg(summary: dict) -> str:
    costs = summary["cost"]["r3"]
    svg = svg_header("The accuracy gain also added time and token usage", "After three compactions: mean fork-and-answer latency and input/output token usage across six answers per arm. Cached input is part of input, not an extra token subtotal.", 520)
    svg += ['<text x="32" y="70" font-size="15">After three compactions · six answers per arm · mean observed usage</text>',
            '<text x="32" y="115" font-size="18" font-weight="700">Fork-and-answer seconds</text>']
    for i, arm in enumerate(("off", "on")):
        y = 135+i*47; value = costs["fork_and_answer_elapsed_s"][arm+"_mean"]
        svg += [f'<text x="32" y="{y+20}" font-size="15">Context Saver {arm}</text>',
                f'<rect x="200" y="{y}" width="{value/25*650:.3f}" height="29" fill="{("#64748b" if arm=="off" else "#2563eb")}" rx="4"/>',
                f'<text x="{215+value/25*650:.3f}" y="{y+21}" font-size="16">{value:.2f} s</text>']
    svg += ['<text x="32" y="270" font-size="18" font-weight="700">Input plus output tokens (cached input counted once)</text>']
    for i, arm in enumerate(("off", "on")):
        y = 295+i*50; x=200.0
        svg += [f'<text x="32" y="{y+20}" font-size="15">Context Saver {arm}</text>']
        for key, color in (("cachedInputTokens", "#93c5fd"), ("uncachedInputTokens", "#2563eb"), ("outputTokens", "#c2410c")):
            width=costs[key][arm+"_mean"]/60000*650
            svg.append(f'<rect x="{x:.3f}" y="{y}" width="{width:.3f}" height="29" fill="{color}"/>');x+=width
        svg.append(f'<text x="{x+12:.3f}" y="{y+21}" font-size="16">{costs["totalTokens"][arm+"_mean"]:,.1f}</text>')
    for x, color, text in ((32,"#93c5fd","Cached input"),(220,"#2563eb","Uncached input"),(445,"#c2410c","Output")):
        svg += [f'<rect x="{x}" y="405" width="16" height="16" fill="{color}"/>',f'<text x="{x+25}" y="418" font-size="14">{text}</text>']
    svg += ['<text x="32" y="463" font-size="14">Observed token usage is not a bill: cached input and output can have different prices.</text>',
            '<text x="32" y="487" font-size="14">Shared native compaction costs are reported separately and are not plugin overhead.</text>', '</g></svg>']
    return "\n".join(svg)+"\n"


def outputs(data: dict, summary: dict) -> dict[str, str]:
    cases=data["fixtures"]["cases"]; keyed={(r["case_id"],r["condition"]):r for r in data["records"]["records"]}
    condition_rows=[{"condition":c,"description":LABELS[c],**{k:v for k,v in summary["semantic"][c].items() if k!="field_correct_counts"},"decision_denominator":36,"control_correct":sum(summary["semantic"][c]["field_correct_counts"][f] for f in CONTROLS),"control_denominator":12} for c in CONDITIONS]
    case_rows=[{"case_id":case["id"],"incident":case["title"],"condition":c,"decision_correct":sum(keyed[case["id"],c]["semantic_grades"][f] for f in DECISIONS),"decision_total":6,"controls_correct":sum(keyed[case["id"],c]["semantic_grades"][f] for f in CONTROLS),"controls_total":2} for case in cases for c in CONDITIONS]
    field_rows=[{"condition":c,"field":f,"description":FIELD_LABELS[f],"in_headline":f in DECISIONS,"correct":summary["semantic"][c]["field_correct_counts"][f],"total":6} for c in CONDITIONS for f in FIELDS]
    answer_rows=[{"record_id":r["record_id"],"case_id":r["case_id"],"condition":r["condition"],"field":f,"answer":r["fields"][f]["actual"],"semantic_correct":r["semantic_grades"][f],"strict_alias_correct":r["fields"][f]["correct"],"citation_labels":"; ".join(r["fields"][f]["supplied_citations"])} for r in data["records"]["records"] for f in FIELDS]
    lines=["# Recomputed benchmark results", "", INTRO, "", "[Research overview](../README.md) · [File guide](../DATA_GUIDE.md) · [Method](../METHODOLOGY.md) · [Reproduce the arithmetic](../REPRODUCING.md)", "",
           "This report is generated entirely from the public archived records by `python3 analyze.py`. It makes no model calls and reads no current user history. The six incidents belong to an authored fictional software release controller. Compaction means the coding assistant reduces older conversation context to fit its working context.", "",
           "After three native Codex compactions, the historical blinded AI grades credit **19/36 operational fields with Context Saver off** and **33/36 with it on**. Each incident contributes six fields: action, target, ordered operations, prerequisites, scope, and authority. Those fields are correlated; this is six synthetic incidents in one run, not 36 independent tasks or a population estimate.", "",
           "![Accuracy across compaction checkpoints](figures/accuracy.svg)", "", "## Conditions and denominators", "",
           "Off and on answers at a checkpoint start from the same parent history and receive the same final question. Before compaction means the early decisions are still directly available. The final uncompacted control receives the same intervening work as the three-compaction arm, with no compaction.", "",
           "| History checkpoint and plugin state | Operational fields | Complete incidents (all six fields) | Main action | Controls |", "|---|---:|---:|---:|---:|"]
    for row in condition_rows:
        lines.append(f"| {row['description']} | {row['decision_fields']}/36 | {row['full_decisions']}/6 | {row['main_actions']}/6 | {row['control_correct']}/12 |")
    lines += ["", "The two controls ask for a branch stated in the current question and an external approval ticket never supplied in the chat (`UNKNOWN` is correct). All 84 control fields passed across the 42 answers. They are deliberately excluded from the 36-field headline, because they do not measure retention of the older project decisions.", "",
              "## Follow an incident from conversation to grade", "", "Each incident page contains its exact final question, frozen rules and source excerpts, all seven retained field-level answers, citations, boolean grades, and answer-specific token/time usage. The chat link shows every authored source turn used by the run.", "",
              "| Incident | After three compactions, off → on | Corrected / regressed fields | Inspect |", "|---|---:|---:|---|"]
    for case in cases:
        cid=case["id"];off=sum(keyed[cid,"r3_off"]["semantic_grades"][f] for f in DECISIONS);on=sum(keyed[cid,"r3_on"]["semantic_grades"][f] for f in DECISIONS)
        cs=[v for v in summary["changes"] if v["case_id"]==cid and v["round"]==3]
        lines.append(f"| {case['title']} | {off}/6 → {on}/6 | {sum(v['change']=='corrected' for v in cs)} / {sum(v['change']=='regressed' for v in cs)} | [Answers and grading](cases/{cid}.md#r3_off) · [Full authored chat](chats/{cid}.md) |")
    lines += ["", "## Which details changed?", "", "| Operational field | Off after three compactions | On after three compactions |", "|---|---:|---:|"]
    for f in DECISIONS:
        lines.append(f"| {FIELD_LABELS[f]} | {summary['semantic']['r3_off']['field_correct_counts'][f]}/6 | {summary['semantic']['r3_on']['field_correct_counts'][f]}/6 |")
    ch=summary["r3_changes"]
    lines += ["",f"The paired comparison has **{ch['corrected']} corrected**, **{ch['regressed']} regressed**, **{ch['both_correct']} correct in both**, and **{ch['both_incorrect']} incorrect in both** operational fields. Net improvement is 14 fields. The main action itself passed in five of six incidents in both arms; much of the separation was in the details needed to carry out that action safely.", "",
              "| Incident | Field | Change | Inspect both retained answers |", "|---|---|---|---|"]
    for change in summary["changes"]:
        if change["round"]==3 and change["change"] in ("corrected","regressed"):
            case=next(c for c in cases if c["id"]==change["case_id"]);cid=case["id"]
            lines.append(f"| {case['title']} | {FIELD_LABELS[change['field']]} | {change['change']} | [Off](cases/{cid}.md#r3_off) · [On](cases/{cid}.md#r3_on) |")
    lines += ["", "The three enabled-arm failures remaining after three compactions are the immediate action in the ambiguous-publish case, the operation order in the interrupted-purge case, and the operation order in the quota-retry case. These are the archived grader labels. In particular, the ambiguous-publish answer explicitly mentions reconciliation hold; no reviewer rationale was archived to explain why that action field failed. The original judgment is retained for audit rather than silently rescored.", "",
              "## Time, tokens, and retrieval work", "", "![Observed time and token overhead](figures/overhead.svg)", "",
              "Times include fork setup plus answer generation. Paired overhead is the on answer minus its off counterpart within the same incident, averaged across six incidents. Input token counts include cached input; total tokens equal input plus output. Cached input must not be added to total a second time. Reasoning output is likewise already included in output. These records are observed usage, not dollar bills.", "",
              "| Mean per answer | Before: off / on | After one: off / on | After three: off / on |", "|---|---:|---:|---:|"]
    for key,label,fmt in (("fork_and_answer_elapsed_s","Fork-and-answer seconds",".2f"),("totalTokens","Input plus output tokens",",.1f"),("cachedInputTokens","Cached input tokens (subset of input)",",.1f"),("uncachedInputTokens","Uncached input tokens",",.1f"),("outputTokens","Output tokens (includes reasoning)",",.1f"),("model_requests","Model requests",".2f")):
        vals=[f"{summary['cost'][tag][key]['off_mean']:{fmt}} / {summary['cost'][tag][key]['on_mean']:{fmt}}" for tag in ("r0","r1","r3")]
        lines.append(f"| {label} | "+" | ".join(vals)+" |")
    cost=summary["cost"]["r3"];diag=summary["diagnostics"]["r3"];qual=summary["strict_quality"]["r3_on"]
    lines += ["", f"After three compactions the mean paired increase is **{cost['fork_and_answer_elapsed_s']['paired_mean']:.2f} seconds** and **{cost['totalTokens']['paired_mean']:,.1f} input-plus-output tokens**: {cost['cachedInputTokens']['paired_mean']:,.1f} cached input, {cost['uncachedInputTokens']['paired_mean']:,.1f} uncached input, and {cost['outputTokens']['paired_mean']:,.1f} output. The category values sum to total before display rounding.", "",
              f"The enabled final answers completed **{qual['completed_lookups']} history searches across {qual['lookup_answers']} of six answers**, with no archived failed searches. Mean individual search latency was **{diag['lookup_seconds_mean']*1000:.1f} ms**. Verified evidence was returned for {qual['exposed_verified_evidence']} answer fields. This flag records evidence exposure, not proof of semantic correctness or perfect citation formatting. End-to-end overhead also includes extra model requests and provider scheduling; it is not explained by retrieval latency alone.", "",
              "[Per-incident paired time/token measurements](paired-costs.csv) · [Every answer field and grade](answer-fields.csv) · [Condition totals](conditions.csv) · [Per-case scores](per-case.csv) · [Per-field scores](per-field.csv) · [Every paired field change](paired-changes.csv)", "",
              "## Shared compaction work", "", "Native compaction creates the shared checkpoint used by both answer arms. Its cost is recorded separately and is not added to the plugin's paired overhead.", "", "| Compaction round | Histories | Mean seconds | Mean provider total tokens |", "|---|---:|---:|---:|"]
    for n,c in summary["maintenance"].items():
        lines.append(f"| {n} | {c['total_records']} | {c['wall_s_mean']:.2f} | {c['usage_means']['total_tokens']:,.1f} |")
    lines += ["", "## What this analysis verifies—and what remains a judgment", "",
              "The script sums the saved boolean semantic grades, checks denominators, pairs the same incidents, and computes overhead from individual usage/timing records. The separate verifier checks these calculations against the historical cached summaries and rejects deliberately corrupted grades, token counts, costs, and missing records. It does not automatically regrade language or establish that every historical AI grading judgment was correct.", "",
              "The initial exact-alias scorer rejected equivalent wording and even marked all baseline main actions wrong. Its original per-field outcomes are visible on the case pages and in the data; they are a diagnostic for the initial scorer, not the 33/36 semantic result. No rationale or adjudication transcript was archived for the later semantic judgments.", "",
              "The public archive includes the authored source chats and retained answer fields, but not original full response envelopes, native compacted checkpoints, raw retrieval bodies, or all historical runtime source. It reproduces the data analysis offline; it cannot independently replay every historical provider event. The method, scope and missing evidence are documented in the [method](../METHODOLOGY.md) and [provenance record](../data/provenance.json).", ""]
    result={"results.md":"\n".join(lines), "summary.json":json_text(summary),
            "conditions.csv":csv_text(condition_rows),"per-case.csv":csv_text(case_rows),
            "per-field.csv":csv_text(field_rows),"answer-fields.csv":csv_text(answer_rows),
            "paired-changes.csv":csv_text(summary["changes"]),"paired-costs.csv":csv_text(summary["cost_pairs"]),
            "figures/accuracy.svg":accuracy_svg(summary),"figures/overhead.svg":overhead_svg(summary)}
    index=["# Inspect the benchmark analysis", "", INTRO, "", "Start with the [recomputed results](results.md), then follow any incident into its original retained answer fields, scoring rules and full authored source chat. These files are rendered directly by GitHub and can also be regenerated offline.", "", "- [Results, changes, token/time overhead and limitations](results.md)","- [Machine-readable recomputed totals](summary.json)","- [Every individual answer field and grade](answer-fields.csv)","- [Per-incident paired overhead](paired-costs.csv)", "", "## Inspect a complete evidence chain", ""]
    for case in cases:
        cid=case["id"];result[f"cases/{cid}.md"]=case_page(case,keyed,summary);result[f"chats/{cid}.md"]=chat_page(case)
        index.append(f"- {case['title']}: [answers and grades](cases/{cid}.md) · [complete authored chat](chats/{cid}.md)")
    result["README.md"]="\n".join(index)+"\n"
    return result


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir",type=Path,default=ROOT/"data")
    parser.add_argument("--output",type=Path,default=ROOT/"analysis")
    parser.add_argument("--check",action="store_true",help="Fail if any generated artifact differs; do not write files")
    args=parser.parse_args()
    data=read_data(args.data_dir); summary=summarize(data); rendered=outputs(data,summary)
    differences=[]
    for name,content in rendered.items():
        target=args.output/name
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8")!=content: differences.append(name)
        else:
            target.parent.mkdir(parents=True,exist_ok=True);target.write_text(content,encoding="utf-8",newline="")
    if differences:
        raise SystemExit("Generated files differ: "+", ".join(differences))
    print(f"{'Verified' if args.check else 'Generated'} {len(rendered)} artifacts from {summary['answer_count']} answer records: r3 off {summary['semantic']['r3_off']['decision_fields']}/36, on {summary['semantic']['r3_on']['decision_fields']}/36.")


if __name__=="__main__":
    main()
