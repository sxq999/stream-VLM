"""Summarize client audits without inventing GPU phase or user TTFT metrics."""
import argparse
import importlib.util
import json
from pathlib import Path
import re

spec = importlib.util.spec_from_file_location('audit', Path(__file__).with_name('characterize.py'))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def prometheus(text):
    result = {}
    for line in text.splitlines():
        if not line.startswith('vllm:'):
            continue
        match = re.match(r'([^\s{]+)\{([^}]*)\}\s+([-+0-9.eE]+)', line)
        if match:
            name, labels, value = match.groups()
            fields = dict(re.findall(r'(\w+)="([^"]*)"', labels))
            if 'stage' in fields:
                key = (name, fields['stage'], fields.get('replica', '0'))
                result[key] = float(value)
    return result


def summarize(directory):
    before = prometheus((directory / 'metrics-before.prom').read_text()) if (directory / 'metrics-before.prom').exists() else {}
    after = prometheus((directory / 'metrics-after.prom').read_text()) if (directory / 'metrics-after.prom').exists() else {}
    counters = []
    for key in sorted(set(before) | set(after)):
        name, stage, replica = key
        if name not in ('vllm:prompt_tokens_total', 'vllm:generation_tokens_total'):
            continue
        a, b = before.get(key), after.get(key)
        delta = b - a if a is not None and b is not None and b >= a else None
        counters.append({'metric': name, 'stage': stage, 'replica': replica, 'before': a, 'after': b,
                         'reported_delta': delta, 'semantics': 'engine-reported; not yet verified as all incremental duplex input/codec positions'})
    peaks = {}
    resources = directory / 'resources.jsonl'
    if resources.exists():
        for line in resources.read_text().splitlines():
            row = json.loads(line)
            for gpu in row.get('gpus', '').splitlines():
                values = [v.strip() for v in gpu.split(',')]
                if len(values) >= 6:
                    try:
                        key = values[0]
                        p = peaks.setdefault(key, {'sampled_peak_memory_mib': 0, 'sampled_peak_utilization_percent': 0})
                        p['sampled_peak_memory_mib'] = max(p['sampled_peak_memory_mib'], float(values[2]))
                        p['sampled_peak_utilization_percent'] = max(p['sampled_peak_utilization_percent'], float(values[3]))
                    except ValueError:
                        continue
    sessions = []
    intervals = []
    for session in sorted(directory.glob('session-*')):
        if not session.is_dir():
            continue
        path = session / 'audit.jsonl'
        if not path.exists():
            sessions.append({'session': session.name, 'status': 'missing_audit'})
            continue
        rows = [json.loads(x) for x in path.read_text().splitlines() if x]
        analysis = audit.analyze(rows)
        sends = [r for r in rows if r['kind'] == 'send' and r.get('media_end_ms') is not None and r.get('ok')]
        if sends:
            intervals.append((sends[0]['start_s'], sends[-1]['end_s']))
        result_path = session / 'official/result.json'
        result = json.loads(result_path.read_text()) if result_path.exists() else {}
        turns = analysis['responses']
        latency = [x['response_created_to_first_audio_ms'] for x in turns if x['response_created_to_first_audio_ms'] is not None]
        metadata = []
        for r in rows:
            event = r.get('event', {})
            if event.get('type') not in ('response.listen', 'response.done'):
                continue
            meta = (event.get('response') or {}).get('metadata') or event.get('metadata') or {}
            stage_metrics = (meta.get('vllm_omni') or {}).get('stage_metrics')
            if stage_metrics:
                metadata.append({'event_type': event['type'], 'at_s': r['at_s'], 'stage_metrics': stage_metrics})
        # Keep provenance for follow-up, not a misleading sum of growing contexts.
        (session / 'engine-snapshots.json').write_text(json.dumps({'samples': metadata,
            'warning': 'context lengths and stage timings can be cumulative; do not sum as new tokens or GPU kernel duration'}, indent=2))
        sessions.append({'session': session.name, 'official_ok': result.get('ok'), 'errors': result.get('errors'),
            'event_counts': analysis['event_counts'], 'input_span_s': analysis['input_span_s'],
            'sender_relative_drift_ms': analysis['sender_relative_drift_ms'],
            'send_block_ms_max': analysis['send_block_ms_max'], 'audio_chunks': sum(x['audio_chunks'] for x in turns),
            'audio_seconds': sum(x['audio_seconds'] for x in turns), 'responses': len(turns),
            'response_created_to_first_audio_ms': {'p50': audit.percentile(latency, .5), 'p95': audit.percentile(latency, .95)},
            'simulated_playback': [{'startup_buffer_ms': b, 'gaps': sum(x['simulated_underflow'][i]['gaps'] for x in turns if not x['cancelled']),
                'total_gap_ms': sum(x['simulated_underflow'][i]['total_ms'] for x in turns if not x['cancelled'])}
                for i, b in enumerate((0, 100, 300))], 'engine_snapshot_count': len(metadata),
            'model_decision': result.get('model_decision')})
    return {'repeat': directory.name, 'sessions': sessions,
        'common_input_overlap_s': max(0, min(x[1] for x in intervals) - max(x[0] for x in intervals)) if intervals else None,
        'sampled_gpu_peaks': peaks, 'engine_reported_counters': counters,
        'limitations': ['sampled peaks can miss transients', 'response.created may be emitted late; this is not question-end TTFT',
            'offline playback ACK follows upstream demo, not a physical player', 'same-clip measurement validation is not saturation or diverse workload evaluation',
            'kernel timing, actual input freshness, per-session KV and source-separated token counts remain unavailable']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    repeats = sorted(args.input.glob('**/repeat-*'))
    rows = [summarize(p) | {'case': p.parent.name} for p in repeats if p.is_dir()]
    args.out.write_text(json.dumps({'scope': 'preliminary_client_measurements', 'runs': rows}, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'runs': len(rows), 'out': str(args.out)}))


if __name__ == '__main__':
    main()
