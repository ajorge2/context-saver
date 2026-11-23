"""Run matched, actual Codex compaction experiments in a throwaway profile."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from dataclasses import asdict, replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import queue
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback

PLUGIN = Path(os.environ.get('CONTEXT_SAVER_EVAL_PLUGIN', Path(__file__).resolve().parents[3])).resolve()
AUTH_SOURCE = Path(os.environ.get('CONTEXT_SAVER_EVAL_AUTH_FILE', Path.home() / '.codex' / 'auth.json')).expanduser()
UV_CACHE = os.environ.get('CONTEXT_SAVER_EVAL_UV_CACHE', str(Path.home() / 'Library' / 'Caches' / 'uv'))
PINNED = ['--with', 'mcp==1.26.0', '--with', 'fastembed==0.9.1', '--with', 'usearch==2.26.6']
ISOLATION = 'Use only the synthetic conversation given to you and any project history tool that is available. Do not inspect files, execute shell commands, use the web, or use any other tools.'
USAGE_FIELDS = ('inputTokens', 'cachedInputTokens', 'outputTokens', 'reasoningOutputTokens', 'totalTokens', 'cacheWriteInputTokens')


def write_json(path, content):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(content, indent=2, ensure_ascii=False) + '\n')
    temp.replace(path)


def dependencies_env():
    return {'UV_CACHE_DIR': UV_CACHE, 'UV_PYTHON': '3.12', 'UV_OFFLINE': '1', 'PYTHONDONTWRITEBYTECODE': '1'}


def profile_env(profile):
    env = dict(os.environ)
    for key in ('CODEX_SQLITE_HOME', 'CODEX_THREAD_ID', 'OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_SANDBOX', 'THREAD_HISTORY_TREE_DATA', 'CODEX_STATE_DB'):
        env.pop(key, None)
    env.update(dependencies_env())
    env['CODEX_HOME'] = str(profile)
    return env


def source_pin():
    paths = [PLUGIN / '.mcp.json', *sorted((PLUGIN / 'server').glob('*.py')),
             *sorted((PLUGIN / 'scripts').glob('thread_tree*.py'))]
    return {str(path.relative_to(PLUGIN)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


class Codex:
    def __init__(self, profile, project, root, model, timeout):
        self.profile = profile
        self.project = project
        self.root = root
        self.model = model
        self.timeout = timeout
        self.inbox = queue.Queue()
        self.past = []
        self.counter = 0
        self.resources = ExitStack()

    def __enter__(self):
        config = ['analytics.enabled=false', 'check_for_update_on_startup=false', 'web_search="disabled"', 'cli_auth_credentials_store="file"', 'mcp_servers.framer.command="/usr/bin/false"', 'mcp_servers.framer.enabled=false']
        flags = [part for value in config for part in ['-c', value]]
        self.stderr = self.resources.enter_context((self.root / ('codex-resume.stderr' if (self.root / 'codex.events.jsonl').exists() else 'codex.stderr')).open('w'))
        self.log = self.resources.enter_context((self.root / ('codex-resume.events.jsonl' if (self.root / 'codex.events.jsonl').exists() else 'codex.events.jsonl')).open('w'))
        self.process = subprocess.Popen(
            ['codex', '--no-daemon', '--disable', 'apps', '--disable', 'remote_plugin', '--disable', 'plugins', '--disable', 'hooks', *flags,
             'app-server', '--listen', 'stdio://'], cwd=self.project, env=profile_env(self.profile),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr, text=True, bufsize=1,
        )
        self.receiver = threading.Thread(target=self.read_events, daemon=True)
        self.receiver.start()
        try:
            self.call('initialize', {'clientInfo': {'name': 'context-saver-matched-eval', 'version': '1.0.0'},
                                     'capabilities': {'experimentalApi': True}})
            self.send({'method': 'initialized'})
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *exc):
        self.process.terminate()
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=8)
        self.receiver.join(timeout=2)
        self.resources.close()

    def read_events(self):
        try:
            for line in self.process.stdout:
                try:
                    self.inbox.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
        finally:
            self.inbox.put(None)

    def send(self, payload):
        self.process.stdin.write(json.dumps({'jsonrpc': '2.0', **payload}) + '\n')
        self.process.stdin.flush()

    def wait(self, matches, since=0):
        for event in self.past[since:]:
            if matches(event):
                return event
        deadline = time.monotonic() + self.timeout
        while True:
            if (remaining := deadline - time.monotonic()) <= 0:
                raise TimeoutError('Timed out receiving Codex events')
            try:
                event = self.inbox.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError('Timed out receiving Codex events') from None
            if event is None:
                raise RuntimeError(f'Codex exited ({self.process.poll()}). See {self.root / "codex.stderr"}')
            kind = event.get('method', '')
            if 'auth' in kind.lower() or 'account' in kind.lower():
                self.log.write(json.dumps({'method': kind, 'omitted': True}) + '\n')
            else:
                self.log.write(json.dumps(event, ensure_ascii=False) + '\n')
            self.log.flush()
            self.past.append(event)
            if matches(event):
                return event

    def call(self, method, params):
        self.counter += 1
        call_id = self.counter
        start = len(self.past)
        self.send({'id': call_id, 'method': method, 'params': params})
        response = self.wait(lambda event: event.get('id') == call_id and 'method' not in event, start)
        if 'error' in response:
            raise RuntimeError(f'{method}: {response["error"]}')
        return response['result']

    def inventory(self, thread_id):
        result = self.call('mcpServerStatus/list', {'threadId': thread_id, 'limit': 100})
        return {entry['name']: sorted(entry.get('tools', {})) for entry in result['data']}

    def start(self):
        response = self.call('thread/start', {'cwd': str(self.project), 'model': self.model, 'approvalPolicy': 'never',
                                               'sandbox': 'read-only', 'historyMode': 'legacy', 'baseInstructions': ISOLATION})
        assert response['model'] == self.model, response['model']
        return response['thread']

    def fork(self, base, plugin_enabled, data_dir):
        result = self.call('thread/fork', {'threadId': base, 'ephemeral': True, 'excludeTurns': True,
                                             'approvalPolicy': 'never', 'sandbox': 'read-only', 'model': self.model,
                                             'baseInstructions': ISOLATION,
                                             'config': {'mcp_servers': {**({'thread-tree': self.plugin_config(data_dir)['thread-tree']} if plugin_enabled else {}), 'framer': {'command': '/usr/bin/false', 'enabled': False}}}})
        thread = result['thread']
        assert thread['forkedFromId'] == base and thread['ephemeral'], thread['id']
        return thread['id']

    def plugin_config(self, data_dir):
        manifest = json.loads((PLUGIN / '.mcp.json').read_text())['mcpServers']['thread-tree']
        return {'thread-tree': {**manifest, 'cwd': str(PLUGIN), 'required': True,
                                'startup_timeout_sec': 25, 'tool_timeout_sec': 40,
                                'tools': {'search_project_history': {'approval_mode': 'approve'}},
                                'env': {**dependencies_env(), 'THREAD_HISTORY_TREE_DATA': str(data_dir),
                                        'CODEX_STATE_DB': str(data_dir / 'unused-host-state.sqlite')}}}

    def complete(self, thread, turn, since, started):
        def matches(event):
            params = event.get('params', {})
            return (event.get('method') == 'turn/completed' and params.get('threadId') == thread
                    and params.get('turn', {}).get('id') == turn)
        event = self.wait(matches, since)
        elapsed = time.monotonic() - started
        done = event['params']['turn']
        if done['status'] != 'completed':
            raise RuntimeError(f'Codex turn {done["status"]}: {done.get("error")}')
        events = [event for event in self.past[since:] if (params := event.get('params', {})).get('threadId') == thread
                  and (params.get('turnId') == turn or params.get('turn', {}).get('id') == turn)]
        usage = [event['params']['tokenUsage'] for event in events if event.get('method') == 'thread/tokenUsage/updated']
        items = [event['params']['item'] for event in events if event.get('method') == 'item/completed']
        messages = [item.get('text', '') for item in items if item['type'] == 'agentMessage']
        return {'thread': thread, 'turn': turn, 'elapsed_s': elapsed, 'duration_ms': done.get('durationMs'),
                'usage': usage, 'items': items, 'answer': messages[-1] if messages else '',
                'compaction_notifications': [event['method'] for event in events if 'compact' in event.get('method', '').lower()]}

    def ask(self, thread, prompt, effort):
        start = len(self.past)
        started = time.monotonic()
        result = self.call('turn/start', {'threadId': thread, 'input': [{'type': 'text', 'text': prompt}], 'effort': effort})
        return self.complete(thread, result['turn']['id'], start, started)

    def compact(self, thread):
        start = len(self.past)
        started = time.monotonic()
        self.call('thread/compact/start', {'threadId': thread})
        event = self.wait(lambda value: value.get('method') == 'item/completed'
                          and value['params'].get('threadId') == thread
                          and value['params']['item']['type'] == 'contextCompaction', start)
        return self.complete(thread, event['params']['turnId'], start, started)


def native_rollout(path, output):
    shutil.copyfile(path, output)
    return [json.loads(line) for line in output.read_text().splitlines()]


def index(project, transcript, data):
    env = dict(os.environ)
    for key in ('CODEX_HOME', 'CODEX_SQLITE_HOME', 'CODEX_THREAD_ID', 'OPENAI_API_KEY', 'CODEX_API_KEY'):
        env.pop(key, None)
    env.update(dependencies_env())
    env.update(THREAD_HISTORY_TREE_DATA=str(data), CODEX_STATE_DB=str(data / 'unused-host-state.sqlite'))
    command = ['uv', 'run', '--offline', '--no-project', *PINNED, 'python', __file__,
               '--index', str(project), str(transcript), str(data)]
    start = time.monotonic()
    result = subprocess.run(command, env=env, cwd=project, text=True, capture_output=True, timeout=420)
    if result.returncode != 0:
        raise RuntimeError('Index seed failed: ' + result.stderr[-3000:])
    return {**json.loads(result.stdout), 'elapsed_s': time.monotonic() - start}


def index_child(project, transcript, data):
    sys.path.insert(0, str(PLUGIN / 'scripts'))
    import thread_tree as tree
    import thread_tree_pipeline as pipeline
    from contextlib import closing
    data.mkdir()
    tree.save_scope_config({'schemaVersion': 1, 'configured': True, 'paused': False,
                            'projects': [{'path': str(project), 'includeNewChats': True}], 'pausePolicy': {'mode': 'manual'}})
    queued = pipeline.enqueue_transcript(transcript, supplied_cwd=str(project), enforce_scope=True)
    result = pipeline.process_project(queued['project_id'])
    if not queued['queued_turns'] or result['failures'] or not result['processed_turns']:
        raise RuntimeError(f'Actual rollout did not index: {queued}, {result}')
    with closing(tree.connect_db()) as database:
        counts = database.execute('SELECT COUNT(*), COUNT(embedding) FROM turn_chunks WHERE evicted = 0').fetchone()
    print(json.dumps({'queue': queued, 'processing': result, 'chunks': counts[0], 'vectors': counts[1]}))


def reuse_seed(root, profile, host, history):
    from datetime import datetime
    source = root / 'before-compaction.jsonl'
    records = [json.loads(line) for line in source.read_text().splitlines()]
    assert records[0]['type'] == 'session_meta'
    metadata = records[0]['payload']
    assert metadata['cwd'] == str(host.project)
    thread_id = metadata['id']
    original_inputs = [record['payload']['message'] for record in records
                       if record['type'] == 'event_msg' and record['payload'].get('type') == 'user_message']
    assert original_inputs == list(history.history_prompts), 'Prepared rollout uses different fixture prompts'
    stamp = datetime.fromisoformat(metadata['timestamp'].replace('Z', '+00:00'))
    current_path = profile / 'sessions' / stamp.strftime('%Y/%m/%d') / f"rollout-{stamp.strftime('%Y-%m-%dT%H-%M-%S')}-{thread_id}.jsonl"
    current_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, current_path)
    state = host.call('thread/resume', {'threadId': thread_id, 'path': str(current_path), 'cwd': str(host.project),
                                        'model': host.model, 'approvalPolicy': 'never', 'sandbox': 'read-only',
                                        'baseInstructions': ISOLATION, 'excludeTurns': True})['thread']
    assert state['id'] == thread_id and state['path'] == str(current_path)
    saved = [json.loads(line) for line in (root / 'codex.events.jsonl').read_text().splitlines()]
    done = [event['params']['turn'] for event in saved if event.get('method') == 'turn/completed']
    token_usage = {event['params']['turnId']: event['params']['tokenUsage'] for event in saved
                   if event.get('method') == 'thread/tokenUsage/updated'}
    assert len(done) == len(history.history_prompts)
    seed_turns = [{'thread': thread_id, 'turn': turn['id'], 'duration_ms': turn['durationMs'],
                   'elapsed_s': turn['durationMs'] / 1000, 'usage': [token_usage[turn['id']]]} for turn in done]
    return state, seed_turns


def read_index(data_dir):
    from sqlite3 import connect
    with connect((data_dir / 'index.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        chunks = [row[0] for row in db.execute('SELECT text FROM turn_chunks WHERE evicted=0')]
        counts = db.execute('SELECT COUNT(*), COUNT(embedding) FROM turn_chunks WHERE evicted=0').fetchone()
        turns = dict(db.execute('SELECT state,COUNT(*) FROM turn_ingestion GROUP BY state'))
        fits = dict(db.execute('SELECT state,COUNT(*) FROM fit_runs GROUP BY state'))
    report = {'chunks': counts[0], 'vectors': counts[1], 'turns': turns, 'fits': fits}
    return report, chunks


def parse_generated_record(raw, keys):
    raw = raw.strip()
    if raw.startswith('```json') and raw.endswith('```'):
        raw = raw[len('```json'):-len('```')].strip()
    fields = json.loads(raw)
    assert set(fields) == {*keys, '_record'}, 'Invalid generated evidence fields'
    note = fields.pop('_record')
    assert isinstance(note, str) and note.strip()
    assert all(isinstance(fields[key], str) and fields[key] and fields[key] in note for key in keys), fields
    return fields, note


def finalize_generated_gold(history, authored, notes):
    gold = {key: ' | '.join(authored[field] for field in field_names) if field_names else 'UNKNOWN'
            for key, field_names in history.generated_contract.items()}
    assert set(gold) == set(history.gold)
    assert authored['initial_profile'] != authored['current_decision']
    assert re.fullmatch(r'[1-9][0-9]* seconds', authored['witness_lease']), authored['witness_lease']
    text = '\n'.join((*history.history_prompts, history.query_prompt)).casefold()
    for field, value in authored.items():
        if field != 'witness_lease':
            assert value.casefold() not in text, f'Generated value accidentally visible in question or seed: {field}'
    evidence = {key: tuple(dict.fromkeys(notes[field] for field in field_names))
                for key, field_names in history.generated_contract.items()}
    if 'current_decision' in evidence:
        evidence['current_decision'] = (notes['initial_profile'], *evidence['current_decision'])
    return replace(history, gold=gold, evidence=evidence)


def run_history(history, root, profile, args):
    root.mkdir(exist_ok=True)
    project = root / 'workspace'
    project.mkdir(exist_ok=True)
    data_dir = root / 'index'
    report = {'fixture': asdict(history), 'source': str(project), 'model': args.model, 'effort': args.effort,
              'seed_turns': [], 'results': {}, 'conditions': []}
    print(f'{history.history_id}: starting native thread', flush=True)
    if args.reuse_prepared:
        deadline = time.monotonic() + 260
        while not (root / 'error.txt').exists():
            if time.monotonic() >= deadline:
                raise RuntimeError('Prepared seed index is not ready')
            time.sleep(1)
    with Codex(profile, project, root, args.model, args.timeout) as host:
        pre_rollout = root / 'before-compaction.jsonl'
        if args.reuse_prepared:
            base, report['seed_turns'] = reuse_seed(root, profile, host, history)
            report['seed_elapsed_s'] = None
            report['indexing'], chunks = read_index(data_dir)
            report['indexing']['elapsed_s'] = None
            assert report['indexing']['turns'] == {'indexed': len(history.history_prompts)}, report['indexing']
            pre_records = [json.loads(line) for line in pre_rollout.read_text().splitlines()]
            print(f'{history.history_id}: recovered byte-identical prepared seed', flush=True)
        else:
            base = host.start()
            range_start = time.monotonic()
            authored = {}
            by_field = {}
            for position, prompt in enumerate(history.history_prompts):
                result = host.ask(base['id'], prompt, args.effort)
                assert all(item['type'] in {'userMessage', 'agentMessage', 'reasoning'} for item in result['items']), 'Unexpected seed tool use'
                report['seed_turns'].append(result)
                if position in getattr(history, 'generated_fields', {}):
                    fields, note = parse_generated_record(result['answer'], history.generated_fields[position])
                    authored.update(fields)
                    by_field.update({key: note for key in fields})
            if authored:
                history = finalize_generated_gold(history, authored, by_field)
                report['fixture'] = asdict(history)
                report['authored_historical_fields'] = authored
            report['seed_elapsed_s'] = time.monotonic() - range_start
            pre_records = native_rollout(Path(base['path']), pre_rollout)
            report['indexing'] = index(project, pre_rollout, data_dir)
            metadata, chunks = read_index(data_dir)
            report['indexing'].update(metadata)
            write_json(root / 'prepared.json', report)
        report['base_thread'] = base['id']
        report['parent_before_usage'] = report['seed_turns'][-1]['usage'][-1]['total']
        path = Path(base['path'])
        assert path.is_relative_to(profile), path
        assert not any(record['type'] == 'compacted' for record in pre_records), 'Native automatic compaction occurred before baseline'
        report['parent_before_hash'] = hashlib.sha256(pre_rollout.read_bytes()).hexdigest()
        joined = '\n'.join(chunks).casefold()
        report['confirmed_indexed'] = {key: value == 'UNKNOWN' or all(component.strip().casefold() in joined
                                                                    for component in value.split('|'))
                                       for key, value in history.gold.items()}
        assert all(report['confirmed_indexed'].values()), report['confirmed_indexed']
        print(f"{history.history_id}: {report['indexing']['chunks']} exact-rollout chunks indexed", flush=True)
        rng = random.Random(f'{args.seed}:{history.history_id}')
        order = [False, True]
        rng.shuffle(order)
        for phase, phase_order in [('pre', order), ('post', list(reversed(order)))]:
            if phase == 'post':
                report['compaction'] = host.compact(base['id'])
                assert sum(item['type'] == 'contextCompaction' for item in report['compaction']['items']) == 1
                post_rollout = root / 'after-compaction.jsonl'
                post = native_rollout(path, post_rollout)
                markers = [record for record in post if record['type'] == 'compacted']
                assert len(markers) == 1, [record['type'] for record in post]
                report['parent_after_hash'] = hashlib.sha256(post_rollout.read_bytes()).hexdigest()
                report['compaction_summary'] = markers[0]['payload']
                report['parent_after_usage'] = report['compaction']['usage'][-1]['total'] if report['compaction']['usage'] else report['parent_before_usage']
                print(f"{history.history_id}: native compaction complete", flush=True)
            for plugin_enabled in phase_order:
                condition = f'{phase}_{"on" if plugin_enabled else "off"}'
                checkpoint = time.monotonic()
                fork = host.fork(base['id'], plugin_enabled, data_dir)
                inventory = host.inventory(fork)
                assert ('thread-tree' in inventory) == plugin_enabled, inventory
                if plugin_enabled:
                    assert any(name.endswith('search_project_history') for name in inventory['thread-tree']), inventory
                result = host.ask(fork, history.query_prompt, args.effort)
                result['mcp_inventory'] = inventory
                result['fork_and_answer_elapsed_s'] = time.monotonic() - checkpoint
                result['parent_hash'] = report['parent_after_hash' if phase == 'post' else 'parent_before_hash']
                result['plugin_enabled'] = plugin_enabled
                report['results'][condition] = result
                report['conditions'].append(condition)
                write_json(root / 'result.json', report)
                print(f"{history.history_id}: {condition} {result['elapsed_s']:.1f}s, usage snapshots {len(result['usage'])}", flush=True)
        source_after_forks = native_rollout(path, root / 'parent-final.jsonl')
        assert sum(record['type'] == 'compacted' for record in source_after_forks) == 1
    write_json(root / 'result.json', report)
    return history.history_id


def replay_history(history, root, profile, args):
    from datetime import datetime
    prior = args.replay_source / history.history_id
    report = json.loads((prior / 'result.json').read_text())
    assert report['fixture']['history_id'] == history.history_id
    root.mkdir()
    project = prior / 'workspace'
    data_dir = prior / 'index'
    report['results'] = {}
    report['replayed_from'] = str(prior)
    for phase in ('pre', 'post'):
        before = phase == 'pre'
        checkpoint_file = 'before-compaction.jsonl' if before else 'after-compaction.jsonl'
        checkpoint_key = 'parent_before_hash' if before else 'parent_after_hash'
        checkpoint = prior / checkpoint_file
        assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == report[checkpoint_key]
        shutil.copyfile(checkpoint, root / checkpoint_file)
        metadata = json.loads(checkpoint.read_text().splitlines()[0])['payload']
        stamp = datetime.fromisoformat(metadata['timestamp'].replace('Z', '+00:00'))
        base_id = report['base_thread']
        assert metadata['id'] == base_id
        rollout = profile / 'sessions' / stamp.strftime('%Y/%m/%d') / f"rollout-{stamp.strftime('%Y-%m-%dT%H-%M-%S')}-{base_id}.jsonl"
        rollout.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(checkpoint, rollout)
        with Codex(profile, project, root, args.model, args.timeout) as host:
            parent = host.call('thread/resume', {'threadId': base_id, 'path': str(rollout), 'cwd': str(project),
                                                 'model': args.model, 'approvalPolicy': 'never', 'sandbox': 'read-only',
                                                 'baseInstructions': ISOLATION, 'excludeTurns': True})['thread']
            assert parent['id'] == base_id
            for condition in [name for name in report['conditions'] if name.startswith(phase + '_')]:
                enabled = condition.endswith('_on')
                start = time.monotonic()
                fork = host.fork(base_id, enabled, data_dir)
                inventory = host.inventory(fork)
                assert ('thread-tree' in inventory) == enabled
                if enabled:
                    assert 'search_project_history' in inventory['thread-tree']
                answer = host.ask(fork, history.query_prompt, args.effort)
                answer['fork_and_answer_elapsed_s'] = time.monotonic() - start
                answer['mcp_inventory'] = inventory
                answer['parent_hash'] = report[checkpoint_key]
                answer['plugin_enabled'] = enabled
                report['results'][condition] = answer
                print(f"{history.history_id}: approved replay {condition} {answer['elapsed_s']:.1f}s", flush=True)
                write_json(root / 'result.json', report)
    return history.history_id


def load_fixtures(path):
    spec = importlib.util.spec_from_file_location('matched_fixtures', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--index', nargs=3, type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--fixture-module', type=Path, default=Path(__file__).with_name('context-saver-matched-fixtures.py'))
    parser.add_argument('--count', type=int, default=8)
    parser.add_argument('--workers', type=int, default=5)
    parser.add_argument('--seed', default='context-saver-matched-2026-11-17-v1')
    parser.add_argument('--effort', default='low')
    parser.add_argument('--model', default='gpt-6-sol')
    parser.add_argument('--timeout', type=int, default=240)
    parser.add_argument('--only', nargs='+')
    parser.add_argument('--reuse-prepared', action='store_true')
    parser.add_argument('--replay-source', type=Path, help='Repeat answer forks from previously saved real native compaction checkpoints')
    args = parser.parse_args()
    if args.index:
        index_child(*args.index)
        return
    assert args.output and args.output.is_absolute()
    args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    histories = load_fixtures(args.fixture_module).build_histories(args.count)
    if args.only:
        histories = [history for history in histories if history.history_id in args.only]
    assert histories
    write_json(args.output / 'run-manifest.json', {'host': 'Codex CLI', 'version': subprocess.check_output(['codex', '--version'], text=True).strip(),
                                                   'model': args.model, 'effort': args.effort, 'seed': args.seed, 'workers': args.workers,
                                                   'histories': [history.history_id for history in histories], 'reused_prepared_seed': args.reuse_prepared, 'replayed_existing_checkpoints': bool(args.replay_source), 'candidate_source_sha256': source_pin(),
                                                   'fixture_sha256': hashlib.sha256(args.fixture_module.read_bytes()).hexdigest()})
    failures = {}
    def isolated_history(history):
        with tempfile.TemporaryDirectory(prefix='context-saver-codex-matched-private-', dir='/private/tmp') as temporary_profile:
            profile = Path(temporary_profile)
            target = profile / 'auth.json'
            with open(target, 'xb', opener=lambda path, flags: os.open(path, flags, 0o600)) as destination:
                destination.write(AUTH_SOURCE.read_bytes())
            try:
                run = replay_history if args.replay_source else run_history
                return run(history, args.output / history.history_id, profile, args)
            finally:
                target.unlink(missing_ok=True)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        work = {executor.submit(isolated_history, history): history.history_id for history in histories}
        for future in as_completed(work):
            try:
                print(f'{future.result()}: all four conditions complete', flush=True)
            except Exception as error:
                name = work[future]
                failures[name] = str(error)
                directory = args.output / name
                directory.mkdir(exist_ok=True)
                (directory / ('resume-error.txt' if args.reuse_prepared else 'error.txt')).write_text(traceback.format_exc())
                print(f'{name}: failed — {error}', flush=True)
    write_json(args.output / 'execution.json', {'failures': failures, 'complete': len(histories) - len(failures)})
    if failures:
        sys.exit(1)


if __name__ == '__main__':
    main()
