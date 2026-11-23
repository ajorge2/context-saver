"""Grade matched Codex decisions using an immutable, independently authored rubric."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import re
import statistics
import sys
import unicodedata

ROUNDS = (0, 1, 3)
ARMS = ('off', 'on')
TOKEN_FIELDS = ('inputTokens', 'cachedInputTokens', 'outputTokens', 'reasoningOutputTokens', 'totalTokens', 'cacheWriteInputTokens')
TIME_FIELDS = ('elapsed_s', 'setup_s', 'fork_and_answer_elapsed_s')
USAGE_LABELS = {
    'elapsed_s': 'Answer elapsed seconds',
    'setup_s': 'Fork and setup seconds',
    'fork_and_answer_elapsed_s': 'Total elapsed seconds',
    'inputTokens': 'Input tokens',
    'cachedInputTokens': 'Cached input tokens',
    'uncachedInputTokens': 'Uncached input tokens',
    'outputTokens': 'Output tokens',
    'reasoningOutputTokens': 'Reasoning output tokens',
    'totalTokens': 'Total input and output tokens',
    'model_requests': 'Model requests',
}
FORBIDDEN_TOOLS = {'commandExecution', 'webSearch', 'fileChange', 'imageGeneration', 'dynamicToolCall', 'collabAgentToolCall'}
ABSTENTION = {'unknown', 'insufficient evidence', 'not enough information', 'cannot determine', 'undetermined'}


def load_module(path):
    spec = importlib.util.spec_from_file_location('human_benchmark_fixture', path)
    if spec is None or spec.loader is None:
        raise ValueError(f'Cannot load fixture from {path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key {key!r}')
        result[key] = value
    return result


def load_json(path):
    return json.loads(path.read_text(), object_pairs_hook=unique_object)


def normalize(value):
    if not isinstance(value, str):
        return None
    value = unicodedata.normalize('NFKC', value).casefold()
    value = value.replace('`', '').strip()
    value = re.sub(r'\s*(?:--?>|=>|→|⇒|>)\s*', ' > ', value)
    value = re.sub(r'[\s_\-‐‑]+', ' ', value)
    return value.strip().removesuffix('.').strip()


def validate_scenario(scenario):
    fields = [criterion.id for criterion in scenario.rubric]
    if not fields or len(fields) != len(set(fields)):
        raise ValueError(f'{scenario.id}: empty or duplicate criterion IDs')
    if sum(criterion.category == 'primary' for criterion in scenario.rubric) != 1:
        raise ValueError(f'{scenario.id}: expected one primary disposition')
    for criterion in scenario.rubric:
        accepted = set(map(normalize, criterion.accepted))
        harmful = set(map(normalize, criterion.harmful))
        if not accepted or None in accepted or '' in accepted or accepted & harmful:
            raise ValueError(f'{scenario.id}/{criterion.id}: ambiguous rubric')
        if criterion.category == 'unsupported' and not accepted & ABSTENTION:
            raise ValueError(f'{scenario.id}/{criterion.id}: unsupported field must allow explicit abstention')


def parse_answer(text, rubric):
    fields = {criterion.id for criterion in rubric}
    try:
        output = json.loads(text, object_pairs_hook=unique_object)
    except (TypeError, ValueError) as error:
        return {}, {}, [f'invalid JSON: {error}']
    if not isinstance(output, dict):
        return {}, {}, ['expected one JSON object']
    errors = []
    if set(output) != {'answers', 'citations'}:
        errors.append('expected top-level answers and citations')
    answers = output.get('answers')
    if not isinstance(answers, dict):
        errors.append('expected the answers object')
        answers = {}
    if set(answers) != fields:
        errors.append(f'wrong answer keys, missing {sorted(fields - set(answers))}, extra {sorted(set(answers) - fields)}')
    for key in sorted(answers.keys() & fields):
        if not isinstance(answers[key], str):
            errors.append(f'expected a string answer for {key}')
    citations = output.get('citations')
    if not isinstance(citations, dict):
        errors.append('expected the citations object')
        citations = {}
    valid_citations = {}
    for key, labels in citations.items():
        if key in fields and isinstance(labels, list) and all(isinstance(label, str) and label for label in labels):
            valid_citations[key] = labels
        else:
            errors.append(f'invalid citation array for {key}')
    return {key: answers[key] for key in fields & answers.keys() if isinstance(answers[key], str)}, valid_citations, errors


def mcp_evidence(item):
    result = item.get('result')
    if not isinstance(result, dict):
        return []
    candidates = [result.get('structuredContent'), result]
    for part in result.get('content') or []:
        if isinstance(part, dict) and part.get('type') == 'text':
            try:
                candidates.append(json.loads(part.get('text', '')))
            except ValueError:
                continue
    for payload in candidates:
        if isinstance(payload, dict) and isinstance(payload.get('evidence'), list):
            return [chunk for chunk in payload['evidence'] if isinstance(chunk, dict)]
    return []


def evidence_groups(criterion, chunks):
    # An actual returned, verified transcript excerpt must match each evidence requirement.
    groups = []
    for excerpt in criterion.evidence:
        matches = []
        for chunk in chunks:
            source = chunk.get('source') or {}
            text = chunk.get('text') or ''
            if source.get('verified') is True and isinstance(text, str) and excerpt in text:
                matches.append({'label': source.get('citation_label'), 'chunk_id': chunk.get('chunk_id')})
        groups.append(matches)
    return groups


def grade(criterion, raw, cited, returned_chunks):
    actual = normalize(raw)
    expected = set(map(normalize, criterion.accepted))
    harmful_values = set(map(normalize, criterion.harmful))
    explicit_steps = {actual, *(actual.split(' > ') if actual else [])}
    correct = actual in expected
    harmful = not correct and bool(explicit_steps & harmful_values)
    unsupported = criterion.category == 'unsupported'
    if correct:
        outcome = 'correct'
    elif actual is None or actual == '':
        outcome = 'missing_or_malformed'
    elif harmful:
        outcome = 'harmful_action'
    elif unsupported:
        outcome = 'unsupported_claim'
    elif actual in ABSTENTION:
        outcome = 'false_abstention'
    else:
        outcome = 'incorrect'
    evidence = evidence_groups(criterion, returned_chunks)
    exposed = bool(evidence) and all(evidence)
    labels = {match['label'] for group in evidence for match in group if match['label']}
    cited_support = [value for value in cited if value in labels]
    citation_complete = exposed and all(any(match['label'] in cited_support for match in group) for group in evidence)
    return {'category': criterion.category, 'actual': raw, 'accepted': list(criterion.accepted), 'outcome': outcome,
            'correct': correct, 'harmful': harmful, 'unsupported': unsupported, 'evidence_requirements': len(evidence),
            'verified_evidence_returned': exposed, 'all_verified_evidence_cited': citation_complete,
            'citation_complete': correct and citation_complete,
            'supplied_citations': cited, 'matching_citations': cited_support, 'matching_evidence': evidence}


def check_tokens(measurement, baseline):
    samples = measurement.get('usage') or []
    if not samples:
        raise ValueError('No native token usage telemetry for answer')
    previous = baseline
    requests = 0
    for sample in samples:
        now = sample['total']
        delta = {name: now.get(name, 0) - previous.get(name, 0) for name in TOKEN_FIELDS}
        if not any(delta.values()):
            continue
        if any(value < 0 for value in delta.values()) or any(value != sample['last'].get(name, 0) for name, value in delta.items()):
            raise ValueError(f'Native cumulative and request counters differ: {delta}')
        if delta['inputTokens'] + delta['outputTokens'] != delta['totalTokens']:
            raise ValueError('Native total tokens disagree with input plus output')
        if delta['cachedInputTokens'] > delta['inputTokens'] or delta['reasoningOutputTokens'] > delta['outputTokens']:
            raise ValueError('Native cached/reasoning usage exceeds its subtotal')
        previous = now
        requests += 1
    usage = {name: previous.get(name, 0) - baseline.get(name, 0) for name in TOKEN_FIELDS}
    if not requests or not usage['totalTokens']:
        raise ValueError('No positive answer token delta')
    usage['uncachedInputTokens'] = usage['inputTokens'] - usage['cachedInputTokens']
    usage['model_requests'] = requests
    return usage


def evaluate_cell(scenario, answer, baseline, mode, expected_prompt=None):
    if expected_prompt is not None:
        supplied = [fragment['text'] for item in answer['items'] if item.get('type') == 'userMessage'
                    for fragment in item.get('content', []) if fragment.get('type') == 'text']
        if supplied != [expected_prompt]:
            raise ValueError(f'{scenario.id}/{mode}: native user prompt differs from the frozen probe')
    if answer.get('compaction_notifications') or any(item.get('type') == 'contextCompaction' for item in answer['items']):
        raise ValueError(f'{scenario.id}/{mode}: the isolated answer fork itself compacted')
    if answer.get('status', 'completed') != 'completed':
        raise ValueError(f'{scenario.id}/{mode}: answer did not complete')
    active_tools = {server: names for server, names in (answer.get('mcp_inventory') or {}).items() if names}
    if active_tools != ({'thread-tree': ['search_project_history']} if mode == 'on' else {}):
        raise ValueError(f'{scenario.id}/{mode}: unexpected active tools {active_tools}')
    history_calls = []
    forbidden = []
    for item in answer['items']:
        kind = item.get('type')
        if kind == 'mcpToolCall':
            if mode == 'on' and item.get('server') == 'thread-tree' and item.get('tool', '').endswith('search_project_history'):
                history_calls.append(item)
            else:
                forbidden.append(f"{item.get('server')}/{item.get('tool')}")
        elif kind in FORBIDDEN_TOOLS:
            forbidden.append(kind)
    if forbidden:
        raise ValueError(f'{scenario.id}/{mode}: forbidden tool events {forbidden}')
    successful_calls = [call for call in history_calls if call.get('status') == 'completed']
    chunks = [chunk for call in successful_calls for chunk in mcp_evidence(call)]
    answers, citations, issues = parse_answer(answer['answer'], scenario.rubric)
    fields = {criterion.id: grade(criterion, answers.get(criterion.id), citations.get(criterion.id, []), chunks)
              for criterion in scenario.rubric}
    usage = check_tokens(answer, baseline)
    included = answer['fork_and_answer_elapsed_s']
    elapsed = answer['elapsed_s']
    if not 0 < elapsed <= included:
        raise ValueError(f'{scenario.id}/{mode}: invalid elapsed times')
    return {'fields': fields, 'format_issues': issues, 'usage': usage, 'elapsed_s': elapsed,
            'setup_s': included - elapsed, 'fork_and_answer_elapsed_s': included,
            'mcp_calls': len(history_calls), 'mcp_completed': len(successful_calls),
            'mcp_failed': len(history_calls) - len(successful_calls), 'returned_chunks': len(chunks),
            'primary_correct': next(value['correct'] for value in fields.values() if value['category'] == 'primary'),
            'full_correct': not issues and all(value['correct'] for value in fields.values()),
            'harmful': any(value['harmful'] for value in fields.values()),
            'thread': answer.get('thread'), 'turn': answer.get('turn')}


def checkpoint_summary(root, checkpoint, expected_count):
    path = Path(checkpoint['path'])
    if not path.is_absolute():
        path = root / path
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != checkpoint['snapshot_sha256']:
        raise ValueError(f'{path}: checkpoint digest differs from run')
    records = [json.loads(line) for line in content.splitlines()]
    count = sum(record.get('type') == 'compacted' for record in records)
    if count != expected_count or count != checkpoint['compaction_count']:
        raise ValueError(f'{path}: expected {expected_count} native compactions, got {count}')
    markers = [record['payload'] for record in records if record.get('type') == 'compacted']
    current = markers[-1] if markers else None
    replacement = current.get('replacement_history', []) if current else None
    plaintext = None if replacement is None else '\n'.join(
        fragment['text'] for value in replacement if value.get('type') == 'message'
        for fragment in value.get('content', []) if isinstance(fragment, dict) and isinstance(fragment.get('text'), str))
    return {'sha256': digest, 'compaction_count': count, 'retained_plaintext': plaintext,
            'anchor_request_input_tokens': checkpoint.get('anchor_request_input_tokens'),
            'snapshot_bytes': len(content), 'index': checkpoint.get('index')}


def is_group_checkpoint(group):
    return group == 'long' or group in {f'r{number}' for number in ROUNDS}


def canonical_fixture(scenario):
    from dataclasses import asdict, replace
    planned = replace(scenario, rounds=scenario.rounds[:4])
    return json.loads(json.dumps(asdict(planned)))


def verify_native_events(root, row):
    expected = {(cell['thread'], cell['turn']): name for name, cell in row['results'].items()}
    base_parents = {cell['thread']: row['long_parent_thread'] if name.startswith('long_') else row['parent_thread']
                    for name, cell in row['results'].items()}
    turns = set()
    forks = set()
    usage = {key: [] for key in expected}
    compactions = {(item['thread'], item['turn']) for item in row['compactions']}
    events = set()
    complete_compactions = set()
    tool_timings = {}
    for trace in sorted(root.glob('*events.jsonl')):
        with trace.open() as reader:
            for line in reader:
                event = json.loads(line)
                result = event.get('result') or {}
                thread = result.get('thread') or {}
                if thread.get('id') in base_parents and thread.get('forkedFromId'):
                    if thread['forkedFromId'] != base_parents[thread['id']] or not thread['ephemeral']:
                        raise ValueError(f'{trace}: unexpected fork lineage')
                    if result.get('model') != row['model']:
                        raise ValueError(f'{trace}: answer fork model differs')
                    forks.add(thread['id'])
                kind = event.get('method')
                params = event.get('params') or {}
                turn_id = params.get('turnId') or (params.get('turn') or {}).get('id')
                key = params.get('threadId'), turn_id
                item = params.get('item') or {}
                if key in expected and item.get('type') == 'mcpToolCall':
                    call = tool_timings.setdefault(expected[key], {}).setdefault(item['id'], {})
                    if kind == 'item/started':
                        call['started_ms'] = params.get('startedAtMs')
                    elif kind == 'item/completed':
                        call['completed_ms'] = params.get('completedAtMs')
                        call['duration_ms'] = item.get('durationMs')
                if kind == 'thread/tokenUsage/updated' and key in expected:
                    usage[key].append(params['tokenUsage'])
                elif kind == 'turn/completed' and key in expected:
                    if params['turn']['status'] != 'completed' or key in turns:
                        raise ValueError(f'{trace}: malformed or duplicated answer completion')
                    turns.add(key)
                elif kind == 'turn/completed' and key in compactions:
                    if params['turn']['status'] != 'completed' or key in complete_compactions:
                        raise ValueError(f'{trace}: malformed or duplicated compaction completion')
                    complete_compactions.add(key)
                elif kind == 'item/completed' and key in compactions and params['item']['type'] == 'contextCompaction':
                    if key in events:
                        raise ValueError(f'{trace}: duplicated compaction event')
                    events.add(key)
    if turns != set(expected) or forks != set(base_parents) or events != compactions or complete_compactions != compactions:
        raise ValueError(f'{root}: missing native answer lineage or compaction events')
    for key, name in expected.items():
        if usage[key] != row['results'][name]['usage']:
            raise ValueError(f'{root}: recorded answer token events differ from native telemetry for {name}')
    return tool_timings


def tool_timing_summary(calls, count):
    if len(calls) != count or any(set(row) != {'started_ms', 'completed_ms', 'duration_ms'} for row in calls.values()):
        raise ValueError('Native MCP start and completion events do not cover every lookup')
    durations = [row['duration_ms'] for row in calls.values()]
    endpoints = sorted((stamp, delta) for row in calls.values()
                       for stamp, delta in ((row['started_ms'], 1), (row['completed_ms'], -1)))
    peak, busy, active = 0, 0, 0
    previous = endpoints[0][0] if endpoints else 0
    for point, delta in endpoints:
        if active > 0:
            busy += point - previous
        active += delta
        peak = max(peak, active)
        previous = point
    return {'durations_ms': durations, 'active_union_ms': busy, 'peak_parallel': peak}


def verify_compaction_records(root, compactions):
    for compaction in compactions:
        round_number = compaction['round']
        path = root / f'parent-compact-{round_number}.jsonl'
        rows = [json.loads(line) for line in path.read_bytes().splitlines()]
        markers = [record['payload'] for record in rows if record.get('type') == 'compacted']
        if len(markers) != round_number:
            raise ValueError(f'{path}: wrong number of native compaction markers')
        marker = markers[-1]
        usage_record = marker.get('latest_token_usage_record')
        if not usage_record:
            if compaction.get('provider_usage') is not None:
                raise ValueError(f'{path}: provider token metrics have no native compaction record')
            continue
        response = marker['compaction_response_id']
        token_records = [row['payload'] for row in rows if row['type'] == 'token_usage_record'
                         and row['payload'].get('response_id') == response]
        if (compaction.get('provider_usage') != usage_record['usage'] or
            compaction['compaction_response_id'] != response or token_records != [usage_record]):
            raise ValueError(f'{path}: compaction provider usage differs from matched native token record')


def score_scenario(root, scenario):
    validate_scenario(scenario)
    row = load_json(root / 'result.json')
    if row['fixture'] != canonical_fixture(scenario):
        raise ValueError(f'{root}: recorded fixture differs from independent frozen fixture')
    checkpoints = row['checkpoints']
    required = {f'r{round_number}_{mode}' for round_number in ROUNDS for mode in ARMS}
    observed = set(row['results'])
    if not required <= observed or observed - required - {'long_off'}:
        raise ValueError(f'{root}: incomplete or unexpected cells {observed}; required {required}')
    if set(row['conditions']) != observed or len(row['conditions']) != len(observed):
        raise ValueError(f'{root}: observed invocation order disagrees with answer cells')
    if 'long_off' in observed and 'long' not in checkpoints:
        raise ValueError(f'{root}: long control missing its checkpoint')
    native_compactions = row['compactions']
    if len(native_compactions) != 3 or [item['round'] for item in native_compactions] != [1, 2, 3]:
        raise ValueError(f'{root}: expected three ordered compaction completions')
    if [item['mark_count'] for item in native_compactions] != [1, 2, 3]:
        raise ValueError(f'{root}: native compaction marker counts are not cumulative')
    tool_timings = verify_native_events(root, row)
    verify_compaction_records(root, native_compactions)
    state = {}
    results = {}
    for key, answer in row['results'].items():
        group, mode = key.split('_')
        if not is_group_checkpoint(group) or group not in checkpoints:
            raise ValueError(f'{root}: unknown answer checkpoint for {key}')
        checkpoint = checkpoints[group]
        if group not in state:
            state[group] = checkpoint_summary(root, checkpoint, 0 if group == 'long' else int(group[1:]))
        if answer['parent_hash'] != state[group]['sha256'] or answer['plugin_enabled'] != (mode == 'on'):
            raise ValueError(f'{root}: {key} references a different checkpoint or tool arm')
        recorded_prompt = row.get('prompt') or row.get('query_prompt')
        expected_prompt = recorded_prompt or scenario.probe
        if recorded_prompt and scenario.probe not in recorded_prompt:
            raise ValueError(f'{root}: recorded answer prompt does not include frozen probe')
        scored = evaluate_cell(scenario, answer, checkpoint['baseline_usage'], mode, expected_prompt)
        recorded_usage = answer.get('usage_delta') or {}
        for field in TOKEN_FIELDS:
            if field in recorded_usage and recorded_usage[field] != scored['usage'][field]:
                raise ValueError(f'{root}: answer {key} usage delta differs for {field}')
        scored['native_mcp_timing'] = tool_timing_summary(tool_timings.get(key, {}), scored['mcp_calls'])
        results[key] = scored
    threads = {result['thread'] for result in results.values()}
    turns = {result['turn'] for result in results.values()}
    if None in threads or None in turns or len(threads) != len(results) or len(turns) != len(results):
        raise ValueError(f'{root}: expected unique ephemeral answer forks and answer turns')
    for checkpoint in state.values():
        text = checkpoint.pop('retained_plaintext')
        if text is not None:
            checkpoint['older_fields_with_all_exact_evidence_visible'] = [criterion.id for criterion in scenario.rubric
                                                                          if criterion.evidence and criterion.category not in {'recent', 'unsupported'}
                                                                          and all(excerpt in text for excerpt in criterion.evidence)]
    return {'id': scenario.id, 'title': scenario.title, 'project_slug': scenario.project_slug,
            'conditions': row['conditions'], 'checkpoints': state, 'compactions': native_compactions,
            'probe_pair_overlap_s': row.get('probe_pair_overlap', {}), 'results': results}


def percentile(samples, fraction):
    values = sorted(samples)
    index = (len(values) - 1) * fraction
    low, high = math.floor(index), math.ceil(index)
    return values[low] + (values[high] - values[low]) * (index - low)


def bootstrap(observations, seed, draws):
    """Resample scenario identities, keeping all rubric fields and experimental cells paired."""
    if len(observations) < 2 or not draws:
        return None
    rng = random.Random(seed)
    samples = []
    for _ in range(draws):
        picked = rng.choices(observations, k=len(observations))
        numerator = sum(value for value, _ in picked)
        denominator = sum(count for _, count in picked)
        samples.append(numerator / denominator)
    return [percentile(samples, 0.025), percentile(samples, 0.975)]


def field_accuracy(scenario, cell, target):
    result = scenario['results'][cell]
    if target in {'full', 'primary'}:
        return int(result[f'{target}_correct']), 1
    exposed_fields = [field for field in result['fields'].values()
                      if target == 'fields' or field['category'] == target
                      or (target == 'supported' and not field['unsupported'])]
    return sum(field['correct'] for field in exposed_fields), len(exposed_fields)


def totals(scenarios, cell, metric):
    counted = [field_accuracy(scenario, cell, metric) for scenario in scenarios if cell in scenario['results']]
    return {'correct': sum(correct for correct, _ in counted), 'total': sum(count for _, count in counted)}


def contrast(scenarios, coefficients, metric, draws):
    observations = []
    for scenario in scenarios:
        if not set(coefficients) <= scenario['results'].keys():
            continue
        counted = {cell: field_accuracy(scenario, cell, metric) for cell in coefficients}
        denominators = {value[1] for value in counted.values()}
        if len(denominators) != 1:
            raise ValueError('Paired contrast has different rubric fields across matched cells')
        count = denominators.pop()
        if count:
            observations.append((sum(weight * counted[cell][0] for cell, weight in coefficients.items()), count))
    denominator = sum(count for _, count in observations)
    name = f'{sorted(coefficients.items())}/{metric}'
    return {'delta': sum(difference for difference, _ in observations) / denominator if denominator else None,
            'interval': bootstrap(observations, f'human-state-machine-accuracy/{name}', draws),
            'scenarios': len(observations), 'denominator': denominator}


def matched_flips(scenarios, left, right, metric):
    changes = Counter()
    for scenario in scenarios:
        if left not in scenario['results'] or right not in scenario['results']:
            continue
        prior = scenario['results'][left]
        current = scenario['results'][right]
        if metric in {'full', 'primary'}:
            pairs = [(prior[f'{metric}_correct'], current[f'{metric}_correct'])]
        else:
            pairs = [(value['correct'], current['fields'][key]['correct']) for key, value in prior['fields'].items()
                     if metric == 'fields' or value['category'] == metric
                     or (metric == 'supported' and not value['unsupported'])]
        for before, after in pairs:
            label = {(True, True): 'both_correct', (False, False): 'both_incorrect',
                     (False, True): 'improved', (True, False): 'regressed'}[(before, after)]
            changes[label] += 1
    return {key: changes[key] for key in ('improved', 'regressed', 'both_correct', 'both_incorrect')}


def retrieve_quality(scenarios, cell):
    observed = [scenario['results'][cell] for scenario in scenarios if cell in scenario['results']]
    fields = [field for result in observed for field in result['fields'].values()]
    return {'answers': len(observed), 'lookup_answers': sum(bool(answer['mcp_calls']) for answer in observed),
            'lookup_calls': sum(answer['mcp_calls'] for answer in observed),
            'completed_lookups': sum(answer['mcp_completed'] for answer in observed),
            'failed_lookups': sum(answer['mcp_failed'] for answer in observed),
            'explicitly_harmful_answers': sum(answer['harmful'] for answer in observed),
            'explicitly_harmful_fields': sum(field['harmful'] for field in fields),
            'false_abstentions': sum(field['outcome'] == 'false_abstention' for field in fields),
            'unsupported_claims': sum(field['outcome'] == 'unsupported_claim' for field in fields),
            'malformed_answers': sum(bool(answer['format_issues']) for answer in observed),
            'exposed_verified_evidence': sum(field['verified_evidence_returned'] for field in fields),
            'exposed_and_correct': sum(field['verified_evidence_returned'] and field['correct'] for field in fields),
            'all_verified_evidence_cited': sum(field['all_verified_evidence_cited'] for field in fields),
            'exposed_correct_and_cited': sum(field['citation_complete'] for field in fields)}


def cost(scenarios, left, right, draws):
    pairs = [(scenario['results'][left], scenario['results'][right]) for scenario in scenarios
             if left in scenario['results'] and right in scenario['results']]
    results = {}
    for field in USAGE_LABELS:
        if field in TIME_FIELDS:
            before, after = [[result[field] for result in column] for column in zip(*pairs)]
        else:
            before, after = [[result['usage'][field] for result in column] for column in zip(*pairs)]
        differences = [new - old for old, new in zip(before, after)]
        results[field] = {'off_mean': statistics.fmean(before), 'on_mean': statistics.fmean(after),
                          'paired_mean': statistics.fmean(differences), 'paired_median': statistics.median(differences),
                          'interval': bootstrap([(difference, 1) for difference in differences],
                                                f'human-state-machine-cost/{left}/{right}/{field}', draws)}
    return results


def report(run, scenarios, fixture_digest, draws, candidate_root=None):
    available = {folder.name for folder in run.iterdir() if folder.is_dir() and (folder / 'result.json').is_file()}
    known = {scenario.id for scenario in scenarios}
    if known != available:
        raise ValueError(f'Run must include every declared scenario. Missing {sorted(known - available)}, unexpected {sorted(available - known)}')
    graded = [score_scenario(run / scenario.id, scenario) for scenario in scenarios]
    if len({scenario['project_slug'] for scenario in graded}) != 1:
        raise ValueError('Expected all independent chats to concern one project')
    manifest_path = run / 'run-manifest.json'
    manifest = load_json(manifest_path) if manifest_path.exists() else {}
    for name in ('fixture_sha256', 'fixtures_sha256'):
        if name in manifest and manifest[name] != fixture_digest:
            raise ValueError('Frozen fixture digest differs from the recorded run')
    source_files_verified = None
    if candidate_root is not None:
        pinned = manifest.get('candidate_source_sha256') or {}
        if not pinned:
            raise ValueError('Run manifest does not pin the candidate source')
        base = candidate_root.resolve()
        for name, expected in pinned.items():
            source = (base / name).resolve()
            if not source.is_relative_to(base) or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
                raise ValueError(f'Candidate digest differs for {name}')
        source_files_verified = len(pinned)
    cells = [f'r{round_number}_{mode}' for round_number in ROUNDS for mode in ARMS]
    if any('long_off' in scenario['results'] for scenario in graded):
        cells.append('long_off')
    group_names = {field['category'] for scenario in graded for field in scenario['results']['r0_off']['fields'].values()}
    groups = ['full', 'primary', 'fields', 'supported', *sorted(group_names - {'primary'})]
    metrics = {group: {cell: totals(graded, cell, group) for cell in cells} for group in groups}
    pair_names = {f'r{round_number} plugin effect': {f'r{round_number}_off': -1, f'r{round_number}_on': 1} for round_number in ROUNDS}
    for mode in ARMS:
        for round_number in ROUNDS[1:]:
            pair_names[f'{mode} r0 to r{round_number}'] = {f'r0_{mode}': -1, f'r{round_number}_{mode}': 1}
    pair_names['r3 plugin × compaction interaction'] = {'r0_on': -1, 'r0_off': 1, 'r3_on': 1, 'r3_off': -1}
    if 'long_off' in cells:
        pair_names['long vs r3 off'] = {'r3_off': -1, 'long_off': 1}
    effects = {pair: {group: contrast(graded, definitions, group, draws) for group in groups}
               for pair, definitions in pair_names.items()}
    flips = {}
    for pair, definitions in pair_names.items():
        if len(definitions) == 2:
            left, right = [next(cell for cell, coefficient in definitions.items() if coefficient == weight) for weight in (-1, 1)]
            flips[pair] = {group: matched_flips(graded, left, right, group) for group in groups}
    diagnostics = {}
    for round_number in ROUNDS:
        round_key = f'r{round_number}'
        records = [scenario['results'][f'{round_key}_on'] for scenario in graded]
        search_turns = [result['native_mcp_timing'] for result in records if result['mcp_calls']]
        lookup_durations = [value for turn in search_turns for value in turn['durations_ms']]
        overlaps = [scenario['probe_pair_overlap_s'][round_key] for scenario in graded
                    if round_key in scenario['probe_pair_overlap_s']]
        visibility = [len(scenario['checkpoints'][round_key]['older_fields_with_all_exact_evidence_visible'])
                      for scenario in graded if 'older_fields_with_all_exact_evidence_visible' in scenario['checkpoints'][round_key]]
        diagnostics[round_key] = {
            'overlap_seconds_mean': statistics.fmean(overlaps) if overlaps else None,
            'overlapping_pairs': sum(value > 0 for value in overlaps),
            'search_turns': len(search_turns), 'search_calls': len(lookup_durations),
            'lookup_seconds_mean': statistics.fmean(lookup_durations) / 1000 if lookup_durations else None,
            'active_lookup_seconds_per_search_turn_mean': statistics.fmean(turn['active_union_ms'] for turn in search_turns) / 1000 if search_turns else None,
            'search_turns_with_parallel_mcp_calls': sum(turn['peak_parallel'] > 1 for turn in search_turns),
            'peak_concurrent_mcp_calls': max((turn['peak_parallel'] for turn in search_turns), default=0),
            'older_fields_all_exact_evidence_visible': sum(visibility) if visibility else None,
        }
    maintenance = {}
    for round_number in range(1, 4):
        measured = [next(value for value in scenario['compactions'] if value['round'] == round_number) for scenario in graded]
        observed_usage = [value['provider_usage'] for value in measured if value.get('provider_usage') is not None]
        maintenance[str(round_number)] = {
            'wall_s_mean': statistics.fmean(value['elapsed_s'] for value in measured),
            'usage_records': len(observed_usage), 'total_records': len(measured),
            'usage_means': {key: statistics.fmean(value.get(key, 0) for value in observed_usage)
                            for key in ('input_tokens', 'cached_input_tokens', 'output_tokens', 'total_tokens')} if observed_usage else None,
        }
    return {'method': {'fixture_sha256': fixture_digest, 'scenario_count': len(graded), 'rounds': list(ROUNDS),
                       'bootstrap_draws': draws, 'run_manifest': manifest, 'candidate_source_files_verified': source_files_verified},
            'accuracy': metrics, 'contrasts': effects, 'flips': flips,
            'quality': {cell: retrieve_quality(graded, cell) for cell in cells},
            'cost': {f'r{round_number}': cost(graded, f'r{round_number}_off', f'r{round_number}_on', draws) for round_number in ROUNDS},
            'maintenance': maintenance, 'diagnostics': diagnostics, 'scenarios': graded}


def fmt_score(value):
    if not value['total']:
        return '—'
    return f"{value['correct']}/{value['total']} ({value['correct']/value['total']:.1%})"


def fmt_delta(value, factor=1):
    if value['delta'] is None:
        return '—'
    estimate = f"{value['delta'] * factor:+.1f}"
    if value['interval']:
        low, high = value['interval']
        estimate += f' [{low * factor:+.1f}, {high * factor:+.1f}]'
    return estimate


def fmt_cost(value, units):
    precision = 2 if units == 'sec' else 0
    def val(number, signed=False):
        sign = '+' if signed else ''
        return f'{number:{sign},.{precision}f}'
    answer = f"{val(value['off_mean'])} / {val(value['on_mean'])} ({val(value['paired_mean'], True)})"
    if value['interval']:
        low, high = value['interval']
        answer += f' [{val(low, True)}, {val(high, True)}]'
    return answer


def render(analysis):
    count = analysis['method']['scenario_count']
    slug = analysis['scenarios'][0]['project_slug']
    cells = list(analysis['quality'])
    head = [f'# {slug} matched state-machine decisions', '',
            f'{count} isolated chats exercised one fictional distributed state machine. A native parent compacted three times as work continued. Fresh answer forks use the exact same parent checkpoint and prompt within each pair. Each criterion was frozen before model evaluation. Exact aliases are normalized for casing, whitespace, punctuation at the end, hyphens, and sequence arrows. A complete correct decision requires all fields and a usable JSON envelope.', '',
            '| Criterion group | ' + ' | '.join(cells) + ' |', '|---|' + '|'.join('---:' for _ in cells) + '|']
    for group, values in analysis['accuracy'].items():
        group_label = {'full': 'Complete decisions', 'primary': 'Primary action', 'fields': 'All fields'}.get(group, group)
        head.append('| ' + ' | '.join([group_label, *(fmt_score(values[cell]) for cell in cells)]) + ' |')
    head.extend(['', '## Paired accuracy contrasts', '',
                 'Positive values favor the later or enabled condition. The interval resamples entire matched chats and retains their full rubric and arms. A synthetic fixture interval describes variability within this workload.', '',
                 '| Contrast | Complete decision, pp | Primary action, pp | All fields, pp | Supported fields, pp | Primary gains | Primary losses |',
                 '|---|---:|---:|---:|---:|---:|---:|'])
    for pair, effects in analysis['contrasts'].items():
        flips = analysis['flips'].get(pair, {}).get('primary', {})
        head.append('| ' + ' | '.join([pair, *(fmt_delta(effects[group], 100) for group in ('full', 'primary', 'fields', 'supported')),
                                        str(flips.get('improved', '—')), str(flips.get('regressed', '—'))]) + ' |')
    head.extend(['', '## Safety and retrieval', '',
                 '| Cell | Answers | Harmful action | False abstention fields | Unsupported claims | Format deviations | Lookups completed / total | Fields with verified evidence | All evidence cited | Exact alias and fully cited |',
                 '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|'])
    for cell, metrics in analysis['quality'].items():
        fields = [metrics['answers'], metrics['explicitly_harmful_answers'], metrics['false_abstentions'],
                  metrics['unsupported_claims'], metrics['malformed_answers'], f"{metrics['completed_lookups']}/{metrics['lookup_calls']}",
                  metrics['exposed_verified_evidence'], metrics['all_verified_evidence_cited'],
                  metrics['exposed_correct_and_cited']]
        head.append('| ' + ' | '.join(map(str, [cell, *fields])) + ' |')
    head.extend(['', 'Harm counts require an explicit harmful action from the frozen rubric in a scored field. A citation requires every supporting excerpt to appear in verified tool evidence and carry the returned label. Other responses remain available in the machine-readable results for review.', '',
                 '## Time and tokens', '',
                 'Cells show off / on means and the paired change with its interval. Total wall time includes fork and MCP setup. Token counts subtract the matching parent baseline and verify every native request increment. Cached input is included once in total input.', '',
                 '| Metric | Before compaction | After one compaction | After three compactions |', '|---|---:|---:|---:|'])
    for field, title in USAGE_LABELS.items():
        units = 'sec' if field in TIME_FIELDS else 'tokens'
        head.append('| ' + ' | '.join([title, *(fmt_cost(analysis['cost'][f'r{round_number}'][field], units) for round_number in ROUNDS)]) + ' |')
    head.extend(['', '## Parallel execution and available source text', '',
                 '| Checkpoint | Overlapping pairs | Mean pair overlap, s | Search turns | Parallel search turns | Lookup calls | Peak concurrent calls | Mean local lookup, s | Mean local lookup window per search turn, s | Older fields whose exact excerpts remain readable |',
                 '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|'])
    for label, metrics in analysis['diagnostics'].items():
        entries = [metrics[key] for key in ('overlapping_pairs', 'overlap_seconds_mean', 'search_turns',
                   'search_turns_with_parallel_mcp_calls', 'search_calls', 'peak_concurrent_mcp_calls',
                   'lookup_seconds_mean', 'active_lookup_seconds_per_search_turn_mean', 'older_fields_all_exact_evidence_visible')]
        head.append('| ' + ' | '.join([label, *('—' if value is None else f'{value:.2f}' if isinstance(value, float) else str(value) for value in entries)]) + ' |')
    head.extend(['', 'Search windows use native tool start and completion timestamps and count overlapping calls only once. Readable source coverage looks at the replacement history. The opaque compaction item may still carry relevant information.', '',
                 '## Shared compaction', '',
                 '| Round | Mean compaction seconds | Provider usage records | Mean input | Mean cached input | Mean output | Mean total tokens |',
                 '|---|---:|---:|---:|---:|---:|---:|'])
    for number, metrics in analysis['maintenance'].items():
        measured = metrics['usage_means']
        tokens = [f'{measured[key]:,.0f}' for key in ('input_tokens', 'cached_input_tokens', 'output_tokens', 'total_tokens')] if measured else ['—'] * 4
        head.append('| ' + ' | '.join([number, f"{metrics['wall_s_mean']:.2f}",
                                         f"{metrics['usage_records']}/{metrics['total_records']}", *tokens]) + ' |')
    head.extend(['', 'The paired answers share the parent compaction. These elapsed times and provider usage are the cost of making the checkpoint. Runtime overhead above measures the differences between the answer arms.', '',
                 '## Individual decisions', '',
                 '| Scenario | ' + ' | '.join(cells) + ' |', '|---|' + '|'.join('---:' for _ in cells) + '|'])
    for scenario in analysis['scenarios']:
        summary = []
        for cell in cells:
            if cell not in scenario['results']:
                summary.append('—')
                continue
            result = scenario['results'][cell]
            summary.append(f"{sum(field['correct'] for field in result['fields'].values())}/{len(result['fields'])} ({'primary correct' if result['primary_correct'] else 'primary wrong'})")
        head.append('| ' + ' | '.join([scenario['title'], *summary]) + ' |')
    return '\n'.join(head) + '\n'


def self_check():
    from types import SimpleNamespace
    action = SimpleNamespace(id='order', accepted=('fence > replay',), harmful=('publish',), category='primary', evidence=('fence the current executor epoch',))
    unknown = SimpleNamespace(id='unknown', accepted=('UNKNOWN',), harmful=(), category='unsupported', evidence=())
    scenario = SimpleNamespace(id='test', rubric=(action, unknown))
    validate_scenario(scenario)
    answers, citations, issues = parse_answer('{"answers":{"order":"fence → replay","unknown":"UNKNOWN"},"citations":{"order":["local-proof"]}}', scenario.rubric)
    assert not issues
    chunk = {'text': 'must fence the current executor epoch first', 'source': {'verified': True, 'citation_label': 'local-proof'}}
    assert grade(action, answers['order'], citations['order'], [chunk])['citation_complete']
    assert not grade(action, answers['order'], citations['order'], [{**chunk, 'source': {**chunk['source'], 'verified': False}}])['citation_complete']
    assert grade(action, 'publish > fence', [], [])['harmful']
    assert not grade(action, 'replay > fence', [], [])['correct']
    assert grade(action, 'UNKNOWN', [], [])['outcome'] == 'false_abstention'
    assert grade(unknown, 'permit override', [], [])['outcome'] == 'unsupported_claim'
    assert grade(unknown, 'UNKNOWN', [], [])['correct']
    assert parse_answer('{"answers":{}, "answers":{}, "citations":{}}', scenario.rubric)[2]
    baseline = dict(inputTokens=20, cachedInputTokens=10, outputTokens=5, reasoningOutputTokens=2, totalTokens=25)
    delta = dict(inputTokens=50, cachedInputTokens=20, outputTokens=8, reasoningOutputTokens=3, totalTokens=58)
    now = {field: baseline[field] + delta[field] for field in baseline}
    assert check_tokens({'usage': [{'total': now, 'last': delta}, {'total': now, 'last': delta}]}, baseline)['uncachedInputTokens'] == 30
    assert bootstrap([(1, 1), (1, 1), (1, 1)], 'test', 40) == [1, 1]
    print('Scorer probes passed for order, harm, abstention, citations, JSON uniqueness, paired bootstrap and native token deltas.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path, nargs='?')
    parser.add_argument('--fixture', type=Path, default=Path(__file__).with_name('context-saver-human-fixtures.py'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--candidate-root', type=Path)
    parser.add_argument('--bootstrap', type=int, default=10_000)
    parser.add_argument('--self-check', action='store_true')
    args = parser.parse_args()
    if args.self_check:
        self_check()
        if args.run is None:
            return
    if args.run is None or args.output is None:
        parser.error('run and --output are required')
    if args.bootstrap < 0:
        parser.error('--bootstrap must be nonnegative')
    fixture = load_module(args.fixture)
    digest = hashlib.sha256(args.fixture.read_bytes()).hexdigest()
    analysis = report(args.run, fixture.SCENARIOS, digest, args.bootstrap, args.candidate_root)
    args.output.with_suffix('.json').write_text(json.dumps(analysis, indent=2, ensure_ascii=False) + '\n')
    args.output.with_suffix('.md').write_text(render(analysis))
    print(args.output.with_suffix('.md'))


if __name__ == '__main__':
    main()
