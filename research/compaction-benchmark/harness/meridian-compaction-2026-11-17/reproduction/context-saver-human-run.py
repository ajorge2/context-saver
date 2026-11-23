"""Run real matched Codex probes through three native compactions."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys
import tempfile
import time
import traceback


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve().parent
OLD = load_module('parallel_cdx_base', HERE.parents[1] / 'matched-compaction-2026-11-17' / 'reproduction' / 'context-saver-matched-codex.py')
ANCHOR = 'Got it. Close this work block with a single ACK. No tools, actions, recap, or new decisions.'
USAGE = OLD.USAGE_FIELDS


class ParallelCodex(OLD.Codex):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.completed_at = {}

    def read_events(self):
        try:
            for line in self.process.stdout:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get('method') == 'turn/completed':
                    params = event['params']
                    self.completed_at[params['threadId'], params['turn']['id']] = time.monotonic()
                self.inbox.put(event)
        finally:
            self.inbox.put(None)

    def plugin_config(self, data_dir):
        servers = super().plugin_config(data_dir)
        cfg = servers['thread-tree']
        cfg['enabled_tools'] = ['search_project_history']
        cfg['supports_parallel_tool_calls'] = True
        return servers

    def inject(self, thread, turns):
        items = [{'type': 'message', 'role': role, 'content': [
            {'type': 'input_text' if role == 'user' else 'output_text', 'text': text}]}
                 for user, assistant in turns for role, text in [('user', user), ('assistant', assistant)] if text]
        self.call('thread/inject_items', {'threadId': thread, 'items': items})

    def dispatch(self, name, thread, probe, effort, setup, checkpoint, plugin_enabled, inventory):
        start = time.monotonic()
        since = len(self.past)
        result = self.call('turn/start', {'threadId': thread, 'input': [{'type': 'text', 'text': probe}], 'effort': effort})
        return {'name': name, 'thread': thread, 'id': result['turn']['id'], 'since': since, 'start': start, 'setup': setup,
                'checkpoint': checkpoint, 'plugin_enabled': plugin_enabled, 'inventory': inventory}

    def finish_dispatch(self, pending):
        thread, turn = pending['thread'], pending['id']
        result = self.complete(thread, turn, pending['since'], pending['start'])
        finish = self.completed_at[thread, turn]
        result['elapsed_s'] = finish - pending['start']
        result['fork_and_answer_elapsed_s'] = pending['setup'] + result['elapsed_s']
        result['parent_hash'] = pending['checkpoint']['snapshot_sha256']
        result['plugin_enabled'] = pending['plugin_enabled']
        result['mcp_inventory'] = pending['inventory']
        result['started_monotonic_s'] = pending['start']
        result['completed_monotonic_s'] = finish
        result['usage_delta'] = usage_delta(result['usage'], pending['checkpoint']['baseline_usage'])
        assert not result['compaction_notifications'] and not any(row['type'] == 'contextCompaction' for row in result['items'])
        # Neither arm can see the other arm's answer or any local source files.
        banned = {'commandExecution', 'webSearch', 'fileChange', 'collabAgentToolCall', 'dynamicToolCall'}
        assert not (banned & {row['type'] for row in result['items']}), 'Agent used a forbidden source'
        for row in result['items']:
            if row['type'] == 'mcpToolCall':
                assert pending['plugin_enabled'] and row['server'] == 'thread-tree' and row['tool'] == 'search_project_history', row['type']
        return result


def usage_delta(snapshots, baseline):
    previous = {field: baseline.get(field, 0) for field in USAGE}
    totals = dict(previous)
    requests = 0
    for event in snapshots:
        usage = event['total']
        delta = {field: usage.get(field, 0) - totals[field] for field in USAGE}
        if not any(delta.values()):
            continue
        last = event['last']
        assert all(delta[field] >= 0 and delta[field] == last.get(field, 0) for field in USAGE), (delta, last)
        assert delta['inputTokens'] + delta['outputTokens'] == delta['totalTokens']
        totals = {field: usage.get(field, 0) for field in USAGE}
        requests += 1
    assert requests, 'Missing native answer token accounting'
    total = {field: totals[field] - previous[field] for field in USAGE}
    total['uncachedInputTokens'] = total['inputTokens'] - total['cachedInputTokens']
    total['model_requests'] = requests
    return total


def write_checkpoint(source, out, usage, count, index_report, authored):
    rows = OLD.native_rollout(source, out)
    marker_count = sum(row['type'] == 'compacted' for row in rows)
    assert marker_count == count, (marker_count, count)
    raw = [part['text'] for row in rows if row['type'] == 'response_item' and row['payload'].get('type') == 'message'
           and row['payload'].get('role') in {'user', 'assistant'} for part in row['payload']['content'] if 'text' in part]
    order = iter(raw)
    for message in authored:
        assert any(message == item for item in order), 'Expected native authored item was not found in sequence'
    return {'path': str(out), 'snapshot_sha256': hashlib.sha256(out.read_bytes()).hexdigest(),
            'baseline_usage': usage[-1]['total'] if usage else dict.fromkeys(USAGE, 0), 'compaction_count': count,
            'index': index_report, 'anchor_request_input_tokens': usage[-1]['last']['inputTokens'] if usage else None,
            'authored_messages': len(authored)}, rows


def provider_compaction(rows):
    marker = [row['payload'] for row in rows if row['type'] == 'compacted'][-1]
    record = marker.get('latest_token_usage_record')
    if not record:
        return {'provider_usage': None, 'compaction_response_id': marker.get('compaction_response_id'),
                'window_number': marker.get('window_number')}
    response = marker['compaction_response_id']
    assert record['response_id'] == response
    matching = [row['payload'] for row in rows if row['type'] == 'token_usage_record' and row['payload'].get('response_id') == response]
    assert len(matching) == 1 and matching[0]['usage'] == record['usage']
    plaintext = [part['text'] for item in marker.get('replacement_history', []) if item.get('type') == 'message'
                 for part in item.get('content', []) if isinstance(part, dict) and 'text' in part]
    return {'provider_usage': record['usage'], 'compaction_response_id': response,
            'window_number': marker.get('window_number'), 'visible_message_count': len(plaintext),
            'visible_text_bytes': len('\n'.join(plaintext).encode()),
            'opaque_items': sum(item.get('type') == 'compaction' for item in marker.get('replacement_history', []))}


def validate_offline_index(data, scenario):
    info, chunks = OLD.read_index(data)
    evidence = '\n'.join(chunks).casefold()
    wanted = {criterion.id: [text for text in criterion.evidence if text] for criterion in scenario.rubric}
    missing = {key: [text for text in texts if text.casefold() not in evidence] for key, texts in wanted.items()}
    missing = {key: values for key, values in missing.items() if values}
    return info, {'fields_with_evidence': sum(bool(texts) for texts in wanted.values()), 'missing_exact_source_excerpts': missing}


def run_scenario(scenario, target, args):
    target.mkdir()
    project = target / 'workspace'
    project.mkdir()
    report = {'fixture': asdict(scenario), 'model': args.model, 'effort': args.effort,
              'checkpoints': {}, 'results': {}, 'conditions': [], 'compactions': [], 'anchors': [], 'probe_pair_overlap': {}}
    assert len(scenario.rounds) == 4
    start_scenario = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='context-saver-human-private-', dir='/private/tmp') as private:
        profile = Path(private)
        auth = profile / 'auth.json'
        with open(auth, 'xb', opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
            stream.write(OLD.AUTH_SOURCE.read_bytes())
        with ParallelCodex(profile, project, target, args.model, args.timeout) as host:
            base = host.start()
            long = host.start()
            assert base['id'] != long['id'] and Path(base['path']).is_relative_to(profile) and Path(long['path']).is_relative_to(profile)
            report['parent_thread'] = base['id']
            report['long_parent_thread'] = long['id']
            data = target / 'index'
            authored = []
            pending = []
            index_report = None
            rng = random.Random(f'{args.seed}:{scenario.id}')

            def collect():
                intervals = []
                for scheduled in pending:
                    result = host.finish_dispatch(scheduled)
                    name = scheduled['name']
                    intervals.append((result['started_monotonic_s'], result['completed_monotonic_s']))
                    report['results'][name] = result
                    print(f"{scenario.id} {name} completed in {result['elapsed_s']:.1f}s ({result['usage_delta']['model_requests']} requests)", flush=True)
                    OLD.write_json(target / 'partial.json', report)
                if len(intervals) >= 2:
                    a,b = intervals[:2]
                    report['probe_pair_overlap'][pending[0]['name'].split('_')[0]] = max(0, min(a[1], b[1]) - max(a[0], b[0]))
                pending.clear()

            def dispatch_pair(phase, parent_id, states):
                specs = []
                checkpoint = report['checkpoints'][phase]
                for enabled in states:
                    started = time.monotonic()
                    fork = host.fork(parent_id, enabled, data)
                    inventory = host.inventory(fork)
                    active = {server: tools for server, tools in inventory.items() if tools}
                    assert active == ({'thread-tree': ['search_project_history']} if enabled else {})
                    specs.append((f'{phase}_{"on" if enabled else "off"}', fork, enabled, inventory, time.monotonic()-started))
                for name, fork, enabled, inventory, setup in specs:
                    report['conditions'].append(name)
                    pending.append(host.dispatch(name, fork, scenario.probe, args.effort, setup, checkpoint, enabled, inventory))

            for phase_index, chapter in enumerate(scenario.rounds):
                messages = [(turn.user, turn.assistant) for turn in chapter]
                authored.extend(text for pair in messages for text in pair if text)
                host.inject(base['id'], messages)
                host.inject(long['id'], messages)
                anchor = host.ask(base['id'], ANCHOR, args.effort)
                assert anchor['answer'].strip() == 'ACK' and not anchor['compaction_notifications'], anchor['answer'][:250]
                host.inject(long['id'], [(ANCHOR, anchor['answer'])])
                report['anchors'].append({'round': phase_index, 'usage': anchor['usage'][-1], 'elapsed_s': anchor['elapsed_s']})
                usage = anchor['usage']
                if phase_index:
                    compaction = host.compact(base['id'])
                    assert sum(item['type'] == 'contextCompaction' for item in compaction['items']) == 1
                    usage = compaction['usage'] or usage
                    _, compact_rows = write_checkpoint(Path(base['path']), target/f'parent-compact-{phase_index}.jsonl', usage, phase_index, index_report, authored)
                    record = {**compaction, **provider_compaction(compact_rows), 'round': phase_index, 'mark_count': phase_index}
                    report['compactions'].append(record)
                    print(f"{scenario.id} native compaction {phase_index} in {compaction['elapsed_s']:.1f}s", flush=True)
                if phase_index == 0:
                    snapshot = target / 'frozen-design-record.jsonl'
                    OLD.native_rollout(Path(base['path']), snapshot)
                    index_report = OLD.index(project, snapshot, data)
                    index_counts, coverage = validate_offline_index(data, scenario)
                    index_report = {'chunks': index_counts['chunks'], 'vectors': index_counts['vectors'], 'elapsed_s': index_report['elapsed_s'],
                                    **coverage, 'archive_round': 0}
                    print(f"{scenario.id} scoped index ready ({index_counts['chunks']} chunks)", flush=True)
                if phase_index in {0, 1, 3}:
                    if pending:
                        collect()
                    label = f'r{phase_index}'
                    checkpoint, _ = write_checkpoint(Path(base['path']), target/f'{label}.jsonl', usage, phase_index, index_report, authored)
                    checkpoint['anchor_request_input_tokens'] = anchor['usage'][-1]['last']['inputTokens']
                    report['checkpoints'][label] = checkpoint
                    pair = [False, True]
                    rng.shuffle(pair)
                    dispatch_pair(label, base['id'], pair)
            if args.no_long:
                collect()
            else:
                long_checkpoint, _ = write_checkpoint(Path(long['path']), target/'long.jsonl', [], 0, None, authored)
                report['checkpoints']['long'] = long_checkpoint
                dispatch_pair('long', long['id'], [False])
                collect()
    report['elapsed_s'] = time.monotonic()-start_scenario
    OLD.write_json(target/'result.json', report)
    (target/'partial.json').unlink(missing_ok=True)
    return scenario.id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture-module', type=Path, default=HERE/'context-saver-human-fixtures.py')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--count', type=int, default=6)
    parser.add_argument('--only', nargs='+')
    parser.add_argument('--model', default='gpt-6-sol')
    parser.add_argument('--effort', default='low')
    parser.add_argument('--timeout', type=int, default=135)
    parser.add_argument('--seed', default='meridian-matched-workflows-nov17-v1')
    parser.add_argument('--no-long', action='store_true')
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(mode=0o700)
    module = load_module('matched_human_fixtures', args.fixture_module.resolve())
    scenarios = [replace(case, rounds=case.rounds[:4]) for case in module.build_scenarios(args.count)]
    if args.only:
        scenarios = [scenario for scenario in scenarios if scenario.id in args.only]
    assert scenarios
    started = time.monotonic()
    index = {scenario.id: scenario for scenario in scenarios}
    manifest = {'host': 'Codex CLI', 'version': subprocess.check_output(['codex','--version'],text=True).strip(),
                'model': args.model, 'effort': args.effort, 'parallel_scenarios': args.workers,'workers': args.workers,
                'probe_rounds': [0,1,3], 'scenarios': list(index),'seed': args.seed,
                'candidate_source_sha256': OLD.source_pin(), 'fixture_sha256': hashlib.sha256(args.fixture_module.read_bytes()).hexdigest(),
                'paired_arms_concurrent': True, 'agent_parallel_mcp_allowed': True, 'long_off': not args.no_long}
    OLD.write_json(args.output/'run-manifest.json',manifest)
    failures = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_scenario, fixture, args.output / name, args): name for name,fixture in index.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()
                print(f'{name} complete',flush=True)
            except Exception as error:
                failures[name] = str(error)
                (args.output/name/'error.txt').write_text(traceback.format_exc())
                print(f'{name} failed: {type(error).__name__}: {error}',flush=True)
    OLD.write_json(args.output/'execution.json',{'failures': failures, 'complete': len(scenarios)-len(failures),'elapsed_s':time.monotonic()-started})
    if failures:
        sys.exit(1)


if __name__=='__main__':
    main()
