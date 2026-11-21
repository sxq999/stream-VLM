"""Execute the finite fixed-configuration input campaign on the Linux server.

Run under experiment_access.py. Does not start/stop a model service or tune it.
Raw media, process identities, logs and detailed summaries stay in --out.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_plan(plan):
    ids = [case['id'] for case in plan['cases']]
    if len(ids) != len(set(ids)) or not ids:
        raise ValueError('case IDs must be nonempty and unique')
    for order in plan['round_orders']:
        if sorted(order) != sorted(ids):
            raise ValueError('each round must contain every frozen case exactly once')
    for case in plan['cases']:
        if not 1 <= len(case['sessions']) <= 4 or case['planned_repeats'] != len(plan['round_orders']):
            raise ValueError('invalid frozen session/repeat count')
        for session in case['sessions']:
            if set(session) - {'media', 'input_delay_s', 'join_delay_s', 'stack_frames'}:
                raise ValueError('session plan may change inputs only')


def descendant(pid, parent):
    for _ in range(24):
        if pid == parent:
            return True
        try:
            pid = int(next(x.split()[1] for x in (Path('/proc') / str(pid) / 'status').read_text().splitlines()
                           if x.startswith('PPid:')))
        except (OSError, StopIteration):
            return False
        if pid <= 1:
            return False
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--input-inventory', type=Path, required=True)
    parser.add_argument('--gpus', default='5,6')
    args = parser.parse_args()
    plan = json.loads(args.cases.read_text())
    validate_plan(plan)
    if len(args.gpus.split(',')) != 2:
        parser.error('this campaign freezes a two-GPU deployment')
    args.out.mkdir(parents=True, exist_ok=False)
    script_dir = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location('stress_summary', script_dir / 'summarize_characterization.py')
    summary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(summary)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def healthy():
        try:
            with opener.open('http://127.0.0.1:18999/health', timeout=3) as response:
                return response.status == 200
        except Exception:
            return False

    def interrupted(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    state = {'status': 'preflight', 'created_utc': datetime.now(timezone.utc).isoformat(),
             'case_plan_sha256': digest(args.cases), 'results': [], 'skipped': [],
             'scope': plan['scope'], 'measurement_script_sha256': digest(script_dir / 'characterize.py')}

    def save():
        (args.out / 'status.json').write_text(json.dumps(state, indent=2) + '\n')

    save()
    try:
        active = json.loads((args.root / 'control/active-deployment.json').read_text())
        config = Path(active['config'])
        parent = active['server_pid']
        expected_config = plan['config_sha256']
        if digest(config) != expected_config or not healthy():
            raise RuntimeError('frozen deployment or backend health not verified')
        proc_status = (Path('/proc') / str(parent) / 'status').read_text()
        uid = int(next(x.split()[1] for x in proc_status.splitlines() if x.startswith('Uid:')))
        if uid != os.getuid():
            raise RuntimeError('model server belongs to another user')
        inventory = subprocess.check_output(['nvidia-smi', '--query-gpu=index,uuid', '--format=csv,noheader'], text=True)
        uuids = {line.split(',')[1].strip() for line in inventory.splitlines()
                 if line.split(',')[0].strip() in args.gpus.split(',')}
        if len(uuids) != 2 or active['physical_gpus'] != [int(x) for x in args.gpus.split(',')]:
            raise RuntimeError('selected GPUs do not match verified active deployment')

        def gpu_pids():
            raw = subprocess.check_output(['nvidia-smi', '--query-compute-apps=pid,gpu_uuid', '--format=csv,noheader'], text=True)
            return {int(line.split(',')[0]) for line in raw.splitlines()
                    if line.strip() and line.split(',')[1].strip() in uuids}

        expected_pids = gpu_pids()
        if len(expected_pids) != 3 or not all(descendant(pid, parent) for pid in expected_pids):
            raise RuntimeError('foreign or unexpected selected-GPU processes')
        state['preflight'] = {'config_sha256': expected_config, 'server_pid': parent,
                              'selected_gpu_processes': sorted(expected_pids), 'gpu_inventory': inventory}
        media = {key: args.root / 'model/assets' / name for key, name in
                 [('omni1', 'omni_duplex1.mp4'), ('omni2', 'omni_duplex2.mp4'), ('skiing', 'Skiing.mp4')]}
        source_inventory = json.loads(args.input_inventory.read_text())
        for path in media.values():
            source = next(x for x in source_inventory['files'] if x['file'] == path.name)
            if digest(path) != source['sha256']:
                raise RuntimeError('source media hash mismatch: ' + path.name)
        (args.out / 'media').mkdir()
        loop = args.out / 'media/omni1-loop180.mp4'
        command = ['ffmpeg', '-nostdin', '-v', 'warning', '-stream_loop', '-1', '-i', str(media['omni1']),
                   '-t', '180', '-c', 'copy', str(loop)]
        with (args.out / 'media/prepare.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        media['omni1_loop180'] = loop
        sources = []
        for key, path in media.items():
            probe = subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)], text=True)
            sources.append({'id': key, 'sha256': digest(path), 'ffprobe': json.loads(probe)})
        (args.out / 'media/inventory.json').write_text(json.dumps({'sources': sources, 'derived_command': command}, indent=2))
        (args.out / 'cases.json').write_bytes(args.cases.read_bytes())

        def run_case(case, number, warmup=False):
            if digest(config) != expected_config or digest(script_dir / 'characterize.py') != state['measurement_script_sha256']:
                raise RuntimeError('configuration or measurement script changed during frozen campaign')
            if gpu_pids() != expected_pids or not healthy():
                raise RuntimeError('GPU process identity or health changed before workload')
            name = 'warmup' if warmup else f"{case['id']}-round-{number}"
            settings = [{**{k: v for k, v in session.items() if k != 'media'}, 'video': str(media[session['media']])}
                        for session in case['sessions']]
            input_plan = args.out / (name + '-inputs.json')
            input_plan.write_text(json.dumps(settings, indent=2))
            out = args.out / name
            command = [sys.executable, str(script_dir / 'characterize.py'), 'run', '--root', str(args.root),
                       '--out', str(out), '--video', settings[0]['video'], '--session-plan', str(input_plan),
                       '--sessions', str(len(settings)), '--repeats', '1', '--timeout', '420', '--gpus', args.gpus]
            print(json.dumps({'case': case['id'], 'round': number, 'status': 'starting', 'warmup': warmup}), flush=True)
            with (args.out / (name + '.log')).open('w') as log, (args.out / (name + '-processes.jsonl')).open('w', buffering=1) as monitor:
                child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    while child.poll() is None:
                        current = gpu_pids()
                        monitor.write(json.dumps({'at_s': time.monotonic(), 'pids': sorted(current)}) + '\n')
                        if current != expected_pids:
                            raise RuntimeError('selected-GPU processes changed; abort workload only')
                        time.sleep(3)
                finally:
                    if child.poll() is None:
                        os.killpg(child.pid, signal.SIGTERM)
                        try:
                            child.wait(timeout=20)
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid, signal.SIGKILL)
                            child.wait()
            details = summary.summarize(out / 'repeat-1') if (out / 'repeat-1').exists() else None
            if details:
                (out / 'summary.json').write_text(json.dumps(details, indent=2) + '\n')
            sessions = details['sessions'] if details else []
            clock_limit = plan['client_clock_validation']['max_send_lateness_ms']
            row = {'case': case['id'], 'round': number, 'warmup': warmup, 'returncode': child.returncode,
                   'backend_healthy_after': healthy(), 'summary_file': str(out / 'summary.json'),
                   'input_clock_valid': bool(sessions) and all(s.get('wire_sender_relative_drift_ms', {}).get('max') is not None
                       and s['wire_sender_relative_drift_ms']['max'] <= clock_limit for s in sessions),
                   'complete_response_drain': bool(sessions) and all(s.get('unterminated_responses') == 0 for s in sessions),
                   'audio_seconds': sum(s.get('audio_seconds', 0) for s in sessions),
                   'speech_scope': 'full-chain observations only; zero audio does not establish speech-stage capacity'}
            state['results'].append(row)
            save()
            print(json.dumps(row), flush=True)
            if not row['backend_healthy_after']:
                raise RuntimeError('backend unhealthy after case; stop rather than tune/restart')
            return child.returncode

        state['status'] = 'running'
        save()
        if run_case({'id': 'warmup', 'sessions': [{'media': 'omni1'}]}, 0, warmup=True):
            raise RuntimeError('warmup failed')
        failures = {case['id']: 0 for case in plan['cases']}
        by_id = {case['id']: case for case in plan['cases']}
        for number, order in enumerate(plan['round_orders'], start=1):
            for case_id in order:
                if failures[case_id] >= plan['max_same_condition_failures']:
                    state['skipped'].append({'case': case_id, 'round': number, 'reason': 'same-condition failure already confirmed'})
                    save()
                    continue
                if run_case(by_id[case_id], number):
                    failures[case_id] += 1
        state['status'] = 'finished_with_observations'
        state['backend_healthy_after'] = healthy()
    except BaseException as exc:
        state['status'] = 'stopped'
        state['error'] = repr(exc)
        raise
    finally:
        state['updated_utc'] = datetime.now(timezone.utc).isoformat()
        save()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
