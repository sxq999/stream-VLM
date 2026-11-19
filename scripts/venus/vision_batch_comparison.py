"""Gated matched-workload comparison of the existing visual feed batching flag."""
import argparse
from contextlib import contextmanager
import functools
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from session_probe import dump, module, signature, step
from single_probe import Recorder, normal_case, question


def workload_changes(a, b, fields):
    """Keep structural work checks distinct from text/waveform byte identity."""
    return [field for field in fields if a.get(field) != b.get(field)]


@contextmanager
def visual_option(duplex, enabled):
    cls = type(duplex)
    original = cls.streaming_prefill
    @functools.wraps(original)
    def prefill(instance, *args, **kwargs):
        if instance is duplex:
            kwargs['batch_vision_feed'] = enabled
        return original(instance, *args, **kwargs)
    cls.streaming_prefill = prefill
    try:
        yield
    finally:
        cls.streaming_prefill = original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ['reference', 'model', 'hf-home', 'gpus', 'out', 'plan', 'state-module',
                'fastpath-module', 'baseline-plan', 'reference-results']:
        parser.add_argument('--' + arg, required=True)
    args = parser.parse_args()
    indices = args.gpus.split(',')
    if len(indices) != 2 or len(set(indices)) != 2 or not all(s.isdigit() for s in indices):
        parser.error('Two distinct GPU indices required')
    os.environ.update(CUDA_VISIBLE_DEVICES=args.gpus, HF_HOME=args.hf_home,
        REALTIME_VENUS_MODEL_PATH=args.model, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
        OMP_NUM_THREADS='8', MKL_NUM_THREADS='8', OPENBLAS_NUM_THREADS='8',
        PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True')
    out = Path(args.out); out.mkdir(parents=True, exist_ok=False)
    plan = json.loads(Path(args.plan).read_text())
    source_files = [Path(__file__), Path(args.plan), Path(args.state_module), Path(args.fastpath_module),
        Path(args.baseline_plan), Path(__file__).with_name('session_probe.py'), Path(__file__).with_name('single_probe.py')]
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    dump(out/'frozen.json', dict(plan=plan, source_sha256=hashes, argv=sys.argv, unix=time.time()))
    try:
        previous = Path(args.reference_results)
        assert json.loads((previous/'completion.json').read_text())['complete']
        old = json.loads((previous/'frozen.json').read_text())
        for name in ['single_probe.py', 'session_probe.py', Path(args.state_module).name, Path(args.fastpath_module).name]:
            assert hashes[name] == old['source_sha256'][name], name
        for key in ['units', 'families', 'questions', 'period_s']:
            assert plan[key] == old['plan'][key], key
        for _ in range(2):
            raw = subprocess.check_output(['nvidia-smi', '-i', args.gpus,
                '--query-gpu=memory.free,utilization.gpu', '--format=csv,noheader,nounits'], text=True)
            if not all(int(r.split(',')[0]) >= 23800 and int(r.split(',')[1]) <= 5 for r in raw.splitlines()):
                raise RuntimeError('Selected devices not idle')
            time.sleep(2)
        ref = Path(args.reference)
        official = module(ref/'official/frontend/Realtime-Venus-Omni/duplex_chat.py', 'venus_visual_compare_official')
        torch = official.torch
        import numpy as np
        base = official.load_model(Path(args.model)); duplex = base.as_duplex()
        wave = module(ref/'workloads_v1/waveform_backend.py', 'venus_visual_compare_wave')
        wave.route_waveform(torch, base.tts.audio_tokenizer, 1); duplex.prepare()
        assert inspect.signature(type(duplex).streaming_prefill).parameters['batch_vision_feed'].default is False
        dump(out/'runtime.json', dict(torch=torch.__version__, cuda=torch.version.cuda,
            source_sha256=hashlib.sha256(Path(inspect.getfile(type(duplex))).read_bytes()).hexdigest()))
        frames, audios, _ = official.get_video_frame_audio_segments(str(Path(args.model)/'assets/sample_1_real.mp4'),
            stack_frames=1, use_ffmpeg=True, adjust_audio_length=True)
        state = module(Path(args.state_module), 'venus_visual_compare_state')
        fast = module(Path(args.fastpath_module), 'venus_visual_compare_fast')
        bank = state.NativeSessionBank(duplex, torch, np); identity = bank.weight_identity()
        source_gate = json.loads(Path(args.baseline_plan).read_text())['source_gate']
        expected = {}; changes = []; value_changes = []
        gate_dir = out/'gate'; gate_dir.mkdir()
        with fast.hidden_only_feed(duplex.decoder, torch, **source_gate):
            for family in plan['families']:
                reference = [json.loads(s) for s in (previous/'references'/(family+'.jsonl')).read_text().splitlines()]
                expected[family] = {}
                for enabled in [False, True]:
                    variant = 'batch' if enabled else 'unbatched'
                    bank.clear(); bank.create('single')
                    bank.restore(bank.sessions['single'].state); bank.rng_set(bank.initial_rng)
                    records = []
                    with visual_option(duplex, enabled), (gate_dir/(family+'_'+variant+'.jsonl')).open('x') as log:
                        for seq in range(plan['units']):
                            r = step(duplex, torch, np, frames[seq], audios[seq], question(plan, family, seq), seq, 'single')
                            records.append(r); log.write(json.dumps(r)+'\n'); log.flush()
                            if not enabled and signature(r) != signature(reference[seq]):
                                raise RuntimeError(f'Unbatched reference drift: {family}/{seq+1}')
                            if enabled:
                                a = expected[family]['unbatched'][seq]
                                fields = workload_changes(a, r, plan['workload_fields'])
                                if fields:
                                    changes.append(dict(family=family, unit=seq+1, fields=fields,
                                        unbatched={k:a.get(k) for k in fields}, batch={k:r.get(k) for k in fields}))
                                values = workload_changes(a, r, ['text', 'waveform_sha256'])
                                if values: value_changes.append(dict(family=family, unit=seq+1, fields=values))
                            if (seq+1)%24 == 0: print('GATE', family, variant, seq+1, flush=True)
                    expected[family][variant] = records
            passed = not changes
            dump(out/'workload_gate.json', dict(passed=passed, units_per_variant_family=plan['units'],
                total_units=plan['units']*len(plan['families'])*2, workload_changes=changes,
                numerical_or_text_changes=value_changes, unbatched_matches_frozen=True,
                strict_byte_equivalence_claimed=False, quality_evaluated=False))
            if passed:
                runs = out/'runs'; runs.mkdir(); results=[]
                pair_index = 0
                for repeat in range(plan['repeats']):
                    families = list(reversed(plan['families'])) if repeat%2 else plan['families']
                    for family in families:
                        variants = [True, False] if pair_index%2 else [False, True]
                        for enabled in variants:
                            variant = 'batch' if enabled else 'unbatched'; name=f'{family}_r{repeat}_{variant}'
                            with visual_option(duplex, enabled), Recorder(duplex, bank, torch) as recorder:
                                summary = normal_case(bank, torch, np, frames, audios, plan, family,
                                    runs/name, expected[family][variant], recorder)
                            if summary['stop_reason'] != 'complete' or not summary['load_generator_qualified'] or not summary['talk_qualified']:
                                raise RuntimeError('Incomplete/unqualified run '+name)
                            results.append(dict(case=name, summary=summary));dump(out/'cases.json', results)
                        pair_index += 1
            assert identity == bank.weight_identity();bank.clear()
        dump(out/'completion.json', dict(complete=True, workload_gate_passed=passed,
            timing_performed=passed, decision='paired timing completed' if passed else 'workload drift; performance comparison withheld', unix=time.time()))
    except BaseException:
        dump(out/'failure.json', dict(error=traceback.format_exc(), unix=time.time()));raise


if __name__ == '__main__':
    main()
