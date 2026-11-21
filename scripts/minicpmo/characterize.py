"""Audit upstream duplex replay; client timing is NOT GPU timing or user TTFT.

Use the fixed server Python, under experiment_access.py run. Keeps the model,
scheduler, media pacing, playback ACK and session protocol upstream-owned.
"""
import argparse
import asyncio
import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import urllib.request


def emit(path, value):
    with Path(path).open('a', encoding='utf-8') as f:
        f.write(json.dumps(value, ensure_ascii=False) + '\n')
        f.flush()


class QueuedAudit:
    """Bounded off-path disk writer; failure/overflow invalidates the run."""
    def __init__(self, path, capacity=8192):
        self.path = Path(path)
        self.queue = queue.Queue(maxsize=capacity)
        self.stop = threading.Event()
        self.error = None
        self.enqueued = self.written = self.peak = 0
        self.thread = threading.Thread(target=self._write, daemon=True)
        self.thread.start()

    def _write(self):
        try:
            with self.path.open('a', encoding='utf-8', buffering=1) as stream:
                while not self.stop.is_set() or not self.queue.empty():
                    try:
                        line = self.queue.get(timeout=.1)
                    except queue.Empty:
                        continue
                    stream.write(line + '\n')
                    stream.flush()
                    self.written += 1
        except Exception as exc:
            self.error = exc

    def put(self, value):
        if self.error:
            raise RuntimeError('audit writer failed') from self.error
        try:
            self.queue.put_nowait(json.dumps(value, ensure_ascii=False))
        except queue.Full as exc:
            self.error = RuntimeError('audit queue overflow; measurement invalid')
            raise self.error from exc
        self.enqueued += 1
        self.peak = max(self.peak, self.queue.qsize())

    def close(self):
        self.stop.set()
        self.thread.join(timeout=30)
        result = {'enqueued': self.enqueued, 'written': self.written,
                  'queue_peak_approx': self.peak, 'flush_complete':
                  not self.thread.is_alive() and self.error is None and self.enqueued == self.written}
        if not result['flush_complete']:
            raise RuntimeError('audit did not flush completely: ' + str(result)) from self.error
        return result


def progress_stalled(now, state, timeout):
    first, last = state['first_input_s'], state['last_sent_s']
    progress = state['last_progress_s'] if state['last_progress_s'] is not None else first
    return bool(timeout > 0 and first is not None and last is not None and
                now - last < 2 and now - progress > timeout)


def redact(value, key=''):
    if key in {'audio', 'delta'} and isinstance(value, str) and len(value) > 1024:
        return {'length': len(value), 'sha256': hashlib.sha256(value.encode()).hexdigest()}
    if key in {'video_frames', 'ref_audio'}:
        return {'count': len(value) if isinstance(value, list) else 1, 'payload_omitted': True}
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    return values[round((len(values) - 1) * p)]


def analyze(rows):
    sends = [r for r in rows if r['kind'] == 'send' and r.get('media_end_ms') is not None and r.get('ok')]
    receives = [r for r in rows if r['kind'] == 'receive']
    response = {}
    for r in receives:
        event = r['event']
        rid = event.get('response_id') or (event.get('response') or {}).get('id')
        if not rid:
            continue
        d = response.setdefault(rid, {'response_id': rid, 'chunks': [], 'created_s': None,
                                     'cancelled': False, 'terminal_status': None})
        if event.get('type') == 'response.created':
            d['created_s'] = r['at_s']
        if event.get('type') == 'response.done':
            d['terminal_status'] = (event.get('response') or {}).get('status')
            d['cancelled'] = d['terminal_status'] == 'cancelled'
        if r.get('audio_seconds', 0) > 0:
            d['chunks'].append((r['at_s'], r['audio_seconds']))
    turns = []
    for d in response.values():
        chunks = d.pop('chunks')
        d['audio_chunks'] = len(chunks)
        d['audio_seconds'] = sum(length for _, length in chunks)
        d['playback_aggregate_eligible'] = d['terminal_status'] == 'completed'
        d['response_created_to_first_audio_ms'] = ((chunks[0][0] - d['created_s']) * 1000
                                                   if chunks and d['created_s'] is not None else None)
        d['simulated_underflow'] = []
        for buffer_ms in (0, 100, 300):
            end = chunks[0][0] + buffer_ms / 1000 if chunks else 0
            gaps = []
            for arrival, length in chunks:
                if arrival > end + 1e-6:
                    gaps.append(arrival - end)
                end = max(end, arrival) + length
            d['simulated_underflow'].append({'startup_buffer_ms': buffer_ms,
                'gaps': len(gaps), 'total_ms': sum(gaps) * 1000,
                'excluded_from_aggregate_if_cancelled': d['cancelled']})
        turns.append(d)
    drift = []
    if sends:
        # Upstream sends each packet at its interval START, then sleeps to END.
        origin_ms = sends[0].get('media_start_ms', 0)
        origin_s = sends[0]['start_s']
        drift = [(r['start_s'] - origin_s - (r['media_start_ms'] - origin_ms) / 1000) * 1000 for r in sends]
    wire = [r for r in sends if r.get('wire_start_s') is not None and r.get('wire_end_s') is not None]
    wire_complete = bool(sends) and len(wire) == len(sends)
    wire_drift = [(r['wire_start_s'] - wire[0]['wire_start_s'] -
                   (r['media_start_ms'] - wire[0]['media_start_ms']) / 1000) * 1000 for r in wire] if wire_complete else []
    progress_events = [r['at_s'] for r in receives if r['event'].get('type') in
                       ('response.listen', 'response.done', 'response.output_audio.delta',
                        'response.output_audio_transcript.delta')]
    first_input = (sends[0].get('wire_start_s', sends[0]['start_s'])) if sends else None
    last_input = (sends[-1].get('wire_end_s', sends[-1]['end_s'])) if sends else None
    during_input = sorted(at for at in progress_events if first_input is not None and first_input <= at <= last_input)
    checkpoints = [first_input, *during_input, last_input] if sends else []
    progress_summary = {
        'last_sent_source_end_ms': sends[-1]['media_end_ms'] if sends else None,
        'last_model_progress_relative_s': max(progress_events) - first_input if progress_events and sends else None,
        'no_progress_at_input_end_s': last_input - (during_input[-1] if during_input else first_input) if sends else None,
        'max_no_progress_within_input_span_s': max((b - a for a, b in zip(checkpoints, checkpoints[1:])), default=None),
        'scope': 'observable listen/output/done events, not exact input consumption; input pacing must be validated separately'}
    collector_times = [(r['end_s'] - r['start_s']) * 1000 for r in rows if r['kind'] == 'collector_complete']
    return {'event_counts': dict(Counter(r['event'].get('type') for r in receives)),
        'sent_audio_packets': len(sends), 'input_span_s': sends[-1]['end_s'] - sends[0]['start_s'] if sends else None,
        'sender_relative_drift_ms': {'p50': percentile(drift, .5), 'p95': percentile(drift, .95), 'max': max(drift) if drift else None},
        'send_block_ms_max': max(((r['end_s'] - r['start_s']) * 1000 for r in sends), default=None),
        'send_block_scope': 'whole client wrapper, including local audit I/O; not just transport',
        'wire_timing_packets': len(wire),
        'wire_sender_relative_drift_ms': {'p50': percentile(wire_drift, .5), 'p95': percentile(wire_drift, .95),
                                           'max': max(wire_drift) if wire_drift else None},
        'wire_send_block_ms_max': max(((r['wire_end_s'] - r['wire_start_s']) * 1000 for r in wire), default=None)
                                  if wire_complete else None,
        'audit_before_send_ms_max': max(((r['wire_start_s'] - r['start_s']) * 1000 for r in wire), default=None)
                                   if wire_complete else None,
        'observable_progress': progress_summary,
        'official_collector_work_ms': {'samples': len(collector_times), 'p95': percentile(collector_times, .95),
            'max': max(collector_times, default=None),
            'missing_reason': None if collector_times else 'no callback intervals recorded; legacy log or no callbacks',
            'scope': 'upstream synchronous receive callback including output handling; not model compute'},
        'responses': turns,
        'completed_responses': sum(d['terminal_status'] == 'completed' for d in turns),
        'unterminated_responses': sum(d['terminal_status'] is None for d in turns),
        'question_end_to_first_text_ms': None,
        'missing': {'question_end_to_first_text_ms': 'no annotated question-end association',
            'gpu_phase_durations': 'client audit is not a GPU trace',
            'per_session_tokens_and_kv': 'requires verified stage instrumentation',
            'input_freshness': 'send success does not identify latest model-consumed media',
            **({'wire_send_timing': 'no complete wire timestamps (legacy logs or no successful audio packets)'} if not wire_complete else {})},
        'scope': 'client measurement validation; not capacity, quality or GPU interference proof'}


def child(args):
    audit = args.out / 'audit.jsonl'
    args.out.mkdir(parents=True, exist_ok=False)
    writer = None
    def write_audit(value):
        writer.put(value) if writer else emit(audit, value)
    progress = {'first_input_s': None, 'last_sent_s': None, 'last_progress_s': None}
    source = args.root / 'sources/vllm-omni/examples/online_serving/minicpmo/realtime_duplex_demo.py'
    spec = importlib.util.spec_from_file_location('upstream_replay', source)
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    original_client, original_collector = demo._TimedInputClient, demo._StreamingEventCollector

    class Client(original_client):
        async def __aenter__(self):
            result = await super().__aenter__()
            (args.out / 'ready.json').write_text(json.dumps({'session_id': self.session_info.get('id')}))
            deadline = time.monotonic() + args.timeout
            while not args.go.exists():
                if time.monotonic() > deadline:
                    raise TimeoutError('input start barrier timed out')
                await asyncio.sleep(.05)
            start = json.loads(args.go.read_text())['start_s']
            await asyncio.sleep(max(0, start - time.monotonic()))
            return result

        async def send(self, event):
            start = time.monotonic()
            # Persist attempts even when a transport exception interrupts send.
            write_audit({'kind': 'send_attempt', 'at_s': start, 'event': redact(event)})
            ok, eid = False, None
            wire_start = time.monotonic()
            try:
                eid = await super().send(event)
                ok = True
                return eid
            finally:
                wire_end = time.monotonic()
                audio = event.get('audio', '')
                duration_ms = len(base64.b64decode(audio)) / 32 if audio else 0
                end_ms = event.get('audio_end_ms')
                if ok and end_ms is not None:
                    if progress['first_input_s'] is None:
                        progress['first_input_s'] = wire_end
                    progress['last_sent_s'] = wire_end
                write_audit({'kind': 'send', 'start_s': start, 'end_s': time.monotonic(), 'ok': ok,
                    'wire_start_s': wire_start, 'wire_end_s': wire_end,
                    'event_id': eid, 'type': event.get('type'), 'media_end_ms': end_ms,
                    'media_start_ms': end_ms - duration_ms if end_ms is not None else None,
                    'audio_bytes': round(duration_ms * 32), 'video_frames': len(event.get('video_frames') or [])})

    class Collector(original_collector):
        def add(self, event, *, received_at_s=None):
            at = time.monotonic() if received_at_s is None else received_at_s
            raw = event if isinstance(event, dict) else event.raw
            if raw.get('type') in ('response.listen', 'response.done', 'response.output_audio.delta',
                                   'response.output_audio_transcript.delta'):
                progress['last_progress_s'] = at
            row = {'kind': 'receive', 'at_s': at, 'event': redact(raw)}
            if raw.get('type') == 'response.output_audio.delta':
                pcm = base64.b64decode(raw.get('delta') or raw.get('audio') or '')
                row['audio_seconds'] = len(pcm) / (2 * (raw.get('sample_rate_hz') or 24000))
            write_audit(row)
            started = time.monotonic()
            try:
                super().add(event, received_at_s=at)
            finally:
                write_audit({'kind': 'collector_complete', 'start_s': started, 'end_s': time.monotonic(),
                             'event_type': raw.get('type')})

    demo._TimedInputClient, demo._StreamingEventCollector = Client, Collector
    sys.argv = [str(source), '--url', args.url, '--input-video', str(args.video),
        '--ref-audio', str(args.root / 'model/assets/HT_ref_audio.wav'), '--output-dir', str(args.out / 'official'),
        '--model', 'openbmb/MiniCPM-o-4_5', '--video-fps', '1', '--stack-frames', '1',
        '--sliding-window-mode', 'basic', '--tail-silence-s', '5', '--timeout-s', '120']
    writer = QueuedAudit(audit) if args.audit_mode == 'thread' else None
    exit_code = 0
    async def monitored_demo():
        task = asyncio.create_task(demo.run_demo(demo.parse_args()))
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=1)
                if not task.done() and progress_stalled(time.monotonic(), progress, args.no_progress_timeout_s):
                    raise TimeoutError('continuing input but no observable model progress for '
                                       + str(args.no_progress_timeout_s) + ' seconds')
            return task.result()
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    try:
        result = asyncio.run(monitored_demo())
        if not result.get('ok'):
            exit_code = 1
    except Exception as exc:
        failure = {'kind': 'failure', 'at_s': time.monotonic(), 'error': f'{type(exc).__name__}: {exc}'}
        (args.out / 'failure.json').write_text(json.dumps(failure), encoding='utf-8')
        try:
            write_audit(failure)
        except Exception:
            pass
        exit_code = 1
    finally:
        if writer:
            try:
                receipt = writer.close()
            except Exception as exc:
                receipt = {'flush_complete': False, 'error': str(exc)}
                exit_code = 1
            (args.out / 'audit-writer.json').write_text(json.dumps(receipt), encoding='utf-8')
        rows = [json.loads(line) for line in audit.read_text().splitlines() if line] if audit.exists() else []
        (args.out / 'analysis.json').write_text(json.dumps(analyze(rows), indent=2), encoding='utf-8')
    return exit_code


def snapshot(directory, label, gpu_ids, port):
    row = {'at_s': time.monotonic(), 'label': label}
    try:
        p = subprocess.run(['nvidia-smi', '--id=' + gpu_ids,
            '--query-gpu=index,uuid,memory.used,utilization.gpu,utilization.memory,power.draw',
            '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=8)
        row['gpus'] = p.stdout.strip()
        row['gpu_query_returncode'] = p.returncode
    except Exception as exc:
        row['gpu_error'] = str(exc)
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/metrics', timeout=5) as r:
            text = r.read().decode()
        path = directory / f'metrics-{label}.prom'
        path.write_text(text, encoding='utf-8')
        row['metrics_file'] = path.name
    except Exception as exc:
        row['metrics_error'] = str(exc)
    emit(directory / 'resources.jsonl', row)


def run(args):
    args.out.mkdir(parents=True, exist_ok=False)
    manifest = {'created_utc': datetime.now(timezone.utc).isoformat(), 'sessions': args.sessions,
        'repeats': args.repeats, 'video': str(args.video), 'video_sha256': hashlib.sha256(args.video.read_bytes()).hexdigest(),
        'gpu_ids': args.gpus, 'window': {'mode': 'basic', 'high': 8000, 'low': 6000},
        'audit_mode': args.audit_mode, 'no_progress_timeout_s': args.no_progress_timeout_s,
        'measurement_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'upstream_replay_sha256': hashlib.sha256((args.root / 'sources/vllm-omni/examples/online_serving/minicpmo/realtime_duplex_demo.py').read_bytes()).hexdigest(),
        'scope': 'client audit and bounded long-concurrency diagnostic; not full T1/T2, SLO or saturated capacity', 'runs': []}
    (args.out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    for i in range(args.repeats):
        directory = args.out / f'repeat-{i + 1}'
        directory.mkdir()
        processes, logs = [], []
        go = directory / 'go.json'
        try:
            snapshot(directory, 'before', args.gpus, args.port)
            for n in range(args.sessions):
                log = (directory / f'session-{n + 1}.log').open('w', encoding='utf-8')
                logs.append(log)
                command = [sys.executable, str(Path(__file__).resolve()), 'child', '--root', str(args.root),
                    '--out', str(directory / f'session-{n + 1}'), '--video', str(args.video), '--go', str(go),
                    '--url', args.url, '--timeout', str(args.timeout), '--audit-mode', args.audit_mode,
                    '--no-progress-timeout-s', str(args.no_progress_timeout_s)]
                processes.append(subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT))
            deadline = time.monotonic() + args.timeout
            sample = 0
            while any(p.poll() is None for p in processes):
                if time.monotonic() > deadline:
                    raise TimeoutError('campaign repeat timed out')
                if not go.exists() and all((directory / f'session-{n + 1}/ready.json').exists() for n in range(args.sessions)):
                    temporary = directory / 'go.tmp'
                    temporary.write_text(json.dumps({'start_s': time.monotonic() + 1}), encoding='utf-8')
                    temporary.replace(go)
                if any(p.poll() not in (None, 0) for p in processes):
                    raise RuntimeError('a session failed; stop peer sessions and preserve partial evidence')
                snapshot(directory, f'{sample:04d}', args.gpus, args.port)
                sample += 1
                time.sleep(2)
            snapshot(directory, 'after', args.gpus, args.port)
            codes = [p.returncode for p in processes]
            manifest['runs'].append({'repeat': i + 1, 'returncodes': codes, 'status': 'pass' if not any(codes) else 'fail'})
            if any(codes):
                break
        except Exception as exc:
            manifest['runs'].append({'repeat': i + 1, 'status': 'fail', 'error': str(exc)})
            break
        finally:
            for p in processes:
                if p.poll() is None:
                    p.terminate()
            for p in processes:
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
            for log in logs:
                log.close()
            (args.out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    passed = len(manifest['runs']) == args.repeats and all(r['status'] == 'pass' for r in manifest['runs'])
    print(json.dumps({'status': 'pass' if passed else 'fail', 'out': str(args.out), 'runs': manifest['runs']}), flush=True)
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['run', 'child'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--go', type=Path)
    parser.add_argument('--sessions', type=int, default=1)
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--timeout', type=float, default=240)
    parser.add_argument('--audit-mode', choices=['thread', 'sync'], default='thread')
    parser.add_argument('--no-progress-timeout-s', type=float, default=60)
    parser.add_argument('--gpus', default='5,6')
    parser.add_argument('--port', type=int, default=18999)
    parser.add_argument('--url', default='ws://127.0.0.1:18999/v1/realtime?duplex=1')
    args = parser.parse_args()
    if not 1 <= args.sessions <= 4 or args.repeats < 1 or args.timeout <= 0 or args.no_progress_timeout_s < 0:
        parser.error('validated campaign supports 1..4 sessions, positive repeats and timeout')
    if args.mode == 'child' and args.go is None:
        parser.error('child requires --go')
    return child(args) if args.mode == 'child' else run(args)


if __name__ == '__main__':
    raise SystemExit(main())
