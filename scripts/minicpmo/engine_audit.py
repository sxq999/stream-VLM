"""Opt-in metadata instrumentation for the pinned upstream AR scheduler.

NOT a scheduling policy. No tensor reads, synchronization, token/queue changes.
Run separately from baseline timings; CPU hooks and JSONL have overhead.
Install on an isolated diagnostic source copy/server, never silently on baseline.
"""
import functools
import json
import os
from pathlib import Path
import sys
import time

_streams = {}


def record(scheduler, kind, **data):
    directory = os.environ.get('STREAM_VLM_ENGINE_AUDIT_DIR')
    if not directory:
        return
    try:
        stage = scheduler.vllm_config.model_config.stage_id
        key = (os.getpid(), stage)
        if key not in _streams:
            p = Path(directory)
            p.mkdir(parents=True, exist_ok=True)
            _streams[key] = (p / f'stage-{stage}-pid-{os.getpid()}.jsonl').open('a', buffering=1)
        _streams[key].write(json.dumps({'at_s': time.monotonic(), 'pid': os.getpid(),
            'stage': stage, 'kind': kind, **data}) + '\n')
    except Exception as exc:
        print(f'STREAM_VLM_AUDIT_FAILURE: {exc}', file=sys.stderr, flush=True)


def state(request):
    return {name: getattr(request, name, None) for name in
        ('request_id', 'num_prompt_tokens', 'num_computed_tokens', 'num_output_tokens',
         'num_output_placeholders', '_minicpmo45_reanchor_count')}


def input_shape(request):
    positions = []
    for feature in getattr(request, 'mm_features', None) or []:
        pos = getattr(feature, 'mm_position', None)
        positions.append({'modality': str(getattr(feature, 'modality', 'unknown')),
            'offset': getattr(pos, 'offset', None), 'length': getattr(pos, 'length', None)})
    return {'prompt_positions': len(getattr(request, 'prompt_token_ids', None) or []), 'multimodal_positions': positions}


def install(cls):
    if cls.__dict__.get('_stream_vlm_audited'):
        return
    cls._stream_vlm_audited = True
    add, update, schedule = cls.add_request, cls._update_request_as_session, cls.schedule

    @functools.wraps(add)
    def audited_add(self, request, *args, **kwargs):
        if request.request_id not in self.requests:
            record(self, 'initial_admission', state=state(request), input=input_shape(request))
        return add(self, request, *args, **kwargs)

    @functools.wraps(update)
    def audited_update(self, session, update_value, *args, **kwargs):
        before = state(session)
        shape = input_shape(update_value)
        intermediate = getattr(update_value, 'model_intermediate_buffer', None) or {}
        duplex = intermediate.get('duplex', {}) if isinstance(intermediate, dict) else {}
        seq = duplex.get('seq') if isinstance(duplex, dict) else None
        arrived = time.monotonic()
        try:
            return update(self, session, update_value, *args, **kwargs)
        finally:
            record(self, 'streaming_update', before=before, after=state(session), input=shape,
                   unit_seq=seq, cpu_started_s=arrived)

    @functools.wraps(schedule)
    def audited_schedule(self, *args, **kwargs):
        before = {k: state(v) for k, v in self.requests.items()}
        started = time.monotonic()
        result = schedule(self, *args, **kwargs)
        counts = getattr(result, 'num_scheduled_tokens', {})
        if counts:
            rows = []
            for req_id, n in counts.items():
                request = self.requests.get(req_id)
                row = {'request_id': req_id, 'scheduled_positions': n, 'before': before.get(req_id),
                       'after_schedule': state(request) if request is not None else None}
                # Metadata only. Block counts are not yet per-session KV bytes.
                try:
                    blocks = self.kv_cache_manager.get_blocks(req_id)
                    row['kv_blocks_by_group'] = [len(group) for group in blocks.blocks]
                except Exception as exc:
                    row['kv_blocks_unavailable'] = str(exc)
                rows.append(row)
            record(self, 'schedule', cpu_started_s=started, requests=rows)
        return result

    cls.add_request, cls._update_request_as_session, cls.schedule = audited_add, audited_update, audited_schedule


def prepare():
    """Add an opt-in import on an explicit detached diagnostic worktree only."""
    import argparse
    import hashlib
    import subprocess
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    source = args.source_root.resolve()
    if not (source / '.git').is_file():
        parser.error('use a separate git worktree; baseline checkout is not modified')
    expected = '5917730a4b02aedb44d374173cdc1b10484ccd52'
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    if actual != expected:
        parser.error('scheduler instrumentation is qualified only for the pinned Omni revision')
    path = source / 'vllm_omni/core/sched/omni_ar_scheduler.py'
    original = path.read_bytes()
    marker = b'# STREAM_VLM_DIAGNOSTIC_ONLY'
    if marker in original or args.receipt.exists():
        parser.error('diagnostic patch or receipt already exists')
    hook = b'''\n# STREAM_VLM_DIAGNOSTIC_ONLY: metadata hooks, separate from baseline timings.\nimport os as _stream_vlm_os\nif _stream_vlm_os.environ.get("STREAM_VLM_ENGINE_AUDIT_DIR"):\n    from engine_audit import install as _stream_vlm_install\n    _stream_vlm_install(OmniARScheduler)\n'''
    backup = args.receipt.with_suffix('.original.py')
    if backup.exists():
        parser.error('backup already exists')
    backup.write_bytes(original)
    path.write_bytes(original + hook)
    args.receipt.write_text(json.dumps({'revision': actual, 'file': str(path),
        'original_sha256': hashlib.sha256(original).hexdigest(),
        'instrumented_sha256': hashlib.sha256(original + hook).hexdigest(),
        'scope': 'opt-in metadata only; not performance baseline'}, indent=2))
    print(args.receipt)


if __name__ == '__main__':
    prepare()
