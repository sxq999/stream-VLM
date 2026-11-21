"""Export compact, anonymous evidence from a completed finite campaign.

Keeps all run outcomes. Raw media, absolute paths, session IDs and GPU process
identities remain private. No GPU calls, replays, or changes to archived logs.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


PROGRESS = {'response.listen', 'response.done', 'response.output_audio.delta',
            'response.output_audio_transcript.delta', 'response.output_text.delta'}

SESSION_FIELDS = ('session', 'official_ok', 'event_counts', 'sent_audio_packets', 'sent_video_only_packets',
    'sent_pcm_seconds', 'sent_wire_video_images', 'input_span_s', 'sender_relative_drift_ms', 'send_block_ms_max',
    'audio_chunks', 'send_block_scope', 'wire_timing_packets', 'wire_sender_relative_drift_ms',
    'wire_send_block_ms_max', 'audit_before_send_ms_max', 'observable_progress', 'official_collector_work_ms',
    'audit_writer', 'audio_seconds', 'responses', 'completed_responses', 'unterminated_responses',
    'response_created_to_first_audio_ms', 'simulated_playback', 'engine_snapshot_count')


def public_session(directory, row, start_s):
    result = {k: row[k] for k in SESSION_FIELDS if k in row}
    result['error_count'] = len(row['errors']) if isinstance(row.get('errors'), list) else None
    if row.get('failure'):
        result['failure'] = {'present': True, 'details': 'retained in private run; inspect before attributing cause'}
    rows = [json.loads(line) for line in (directory / 'audit.jsonl').read_text().splitlines() if line]
    sends = [x for x in rows if x['kind'] == 'send' and x.get('ok') and x.get('media_end_ms') is not None]
    receives = [x for x in rows if x['kind'] == 'receive']
    origin = sends[0]['wire_start_s'] if sends else None
    opened = next((x for x in rows if x['kind'] == 'session_open'), None)
    result['actual_input_start_from_barrier_s'] = origin - start_s if origin is not None else None
    result['actual_session_open_from_barrier_s'] = opened['start_s'] - start_s if opened else None
    first_audio = next((x['at_s'] for x in receives if x.get('audio_seconds', 0) > 0), None)
    result['first_input_to_first_audio_ms'] = (first_audio - origin) * 1000 if first_audio is not None and origin is not None else None
    result['first_audio_scope'] = 'from first client input, includes question duration; NOT question-end TTFT'
    def response_id(event):
        return event.get('response_id') or (event.get('response') or {}).get('id')
    completed = next((x for x in receives if x['event'].get('type') == 'response.done'
                      and (x['event'].get('response') or {}).get('status') == 'completed'), None)
    result['first_completed_response_audio'] = None
    if completed is not None and origin is not None:
        rid = response_id(completed['event'])
        chunks = [x for x in receives if rid and response_id(x['event']) == rid and x.get('audio_seconds', 0) > 0]
        result['first_completed_response_audio'] = {
            'selection': 'first completed response, not worst case',
            'chunks': [{'arrival_from_first_input_s': x['at_s'] - origin, 'audio_seconds': x['audio_seconds']} for x in chunks],
            'completed_from_first_input_s': completed['at_s'] - origin,
            'scope': 'client arrival times and PCM durations; no physical player'}
    prefix = [x for x in sends if x.get('media_clock_source') == 'derived_1fps_video_index']
    if prefix:
        pcm = next((x['wire_start_s'] for x in sends if x.get('audio_bytes', 0) > 0), None)
        during_prefix = [x for x in receives if origin <= x['at_s'] < (pcm if pcm is not None else sends[-1]['wire_end_s'])]
        result['video_only_prefix'] = {'packets': len(prefix), 'duration_before_pcm_s': pcm - origin if pcm is not None else None,
            'model_progress_events_before_pcm': dict(Counter(x['event']['type'] for x in during_prefix if x['event'].get('type') in PROGRESS)),
            'meaning': 'observed events, not proof that every image was consumed; no source audio precedes tail PCM'}
    return result


def export(campaign):
    state = json.loads((campaign / 'status.json').read_text())
    plan = json.loads((campaign / 'cases.json').read_text())
    out = {'scope': plan['scope'], 'created_utc': state['created_utc'], 'updated_utc': state['updated_utc'],
           'status': state['status'], 'case_plan_sha256': state['case_plan_sha256'],
           'measurement_script_sha256': state['measurement_script_sha256'],
           'config_sha256': state['preflight']['config_sha256'], 'gpu_count': 2, 'gpu_model': 'RTX 3090',
           'window': plan['window'], 'input_clock_limit_ms': plan['client_clock_validation']['max_send_lateness_ms'],
           'cases': plan['cases'], 'skipped': state['skipped'], 'runs': [],
           'backend_healthy_after': state.get('backend_healthy_after'),
           'limitations': plan['limitations'] + ['first input to first audio is not question-end TTFT',
               'full-chain audio observations do not establish isolated Talker/Code2Wav capacity',
               'independent source-separated tokens, complete input freshness and causal GPU subphases are not measured']}
    runtime = campaign / 'runtime-reviewed.json'
    if runtime.exists():
        out['runtime_review_after_campaign'] = json.loads(runtime.read_text())
    out['versions_reference'] = 'configs/minicpmo/campaign.json'
    for row in state['results']:
        name = 'warmup' if row['warmup'] else f"{row['case']}-round-{row['round']}"
        directory = campaign / name
        path = directory / 'summary.json'
        details = json.loads(path.read_text()) if path.exists() else None
        public = {k: v for k, v in row.items() if k != 'summary_file'}
        if details:
            go = json.loads((directory / 'repeat-1/go.json').read_text())['start_s']
            run_manifest = json.loads((directory / 'manifest.json').read_text())
            gpu_order = run_manifest['gpu_ids'].split(',')
            roles = {gpu_order[0]: 'thinker_gpu', gpu_order[1]: 'speech_gpu'}
            public['sessions'] = [public_session(directory / 'repeat-1' / session['session'], session, go)
                                  if session.get('status') != 'missing_audit' else session for session in details['sessions']]
            public['sampled_gpu_peaks'] = {roles[k]: v
                                          for k, v in details['sampled_gpu_peaks'].items()}
            for key in ('common_input_overlap_s', 'engine_reported_counters', 'sampled_peak_kv_pool_fraction', 'kv_pool_peak_scope'):
                public[key] = details[key]
            public['private_summary_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        out['runs'].append(public)
    measured = [row for row in out['runs'] if not row['warmup']]
    sessions = [session for row in measured for session in row.get('sessions', [])]
    out['totals'] = {'conditions': len(plan['cases']), 'executed_runs': len(measured),
        'sessions': sum(len(row.get('sessions', [])) for row in measured),
        'protocol_successful_runs': sum(row['returncode'] == 0 for row in measured),
        'input_clock_valid_runs': sum(row['input_clock_valid'] for row in measured),
        'complete_response_drain_runs': sum(row['complete_response_drain'] for row in measured),
        'observed_audio_seconds': sum(row['audio_seconds'] for row in measured),
        'completed_responses': sum(session.get('completed_responses', 0) for session in sessions),
        'unterminated_responses': sum(session.get('unterminated_responses', 0) for session in sessions),
        'all_audit_writers_flushed': bool(sessions) and all((session.get('audit_writer') or {}).get('flush_complete') for session in sessions),
        'max_send_lateness_ms': max((session['wire_sender_relative_drift_ms']['max'] for session in sessions
                                   if session.get('wire_sender_relative_drift_ms', {}).get('max') is not None), default=None)}
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = export(args.campaign)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result['totals']))


if __name__ == '__main__':
    main()
