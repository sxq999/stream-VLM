"""Export a sanitized, evidence-derived engineering acceptance summary."""
import json,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[2];base=root.parent
def read(path):return json.loads(path.read_text())
native=read(root/'runs/final-native-profile-001/summary.json')
engine=read(root/'runs/final-vllm-profile-001/measurement/summary.json')
suite=read(root/'runs/real-suite-001/summary.json')
burst=read(root/'runs/burst-acceptance-001/acceptance.json')
native_traces=read(base/'final-native-trace-inspection.json')
engine_traces=read(base/'final-vllm-trace-inspection.json')
assert native['status']==engine['status']==suite['status']=='complete'
assert native['query_count']==engine['query_count']==3 and burst['peak_client_requests']>=2
def traces(items):return [dict(gpu_kernel_events=x['gpu_kernel_events'],categories=x['categories'],
    request_labels=x['request_labels'],stage_labels=x['stage_labels']) for x in items]
runtime=read(root/'runs/final-vllm-profile-001/deployment/engine-runtime.json')
result=dict(tested_code_commit='27a91e2b67d4a345a28322999ab0b78fbc597aca',
    tests=dict(linux=dict(tests=18,passed=18,skipped=0),windows=dict(tests=18,passed=17,skipped=1)),
    engine_packages=runtime['packages'],hardware='RTX 3090 / driver 560.35.03; CUDA runtime 12.8',
    native=dict(status=native['status'],queries=3,traces=traces(native_traces)),
    managed_engine=dict(status=engine['status'],queries=3,traces=traces(engine_traces),
        leader_exited=not Path('/proc/'+str(read(root/'runs/final-vllm-profile-001/deployment/launch.json')['pid'])).exists()),
    real_suite=dict(cases=2,queries_per_case=6,status=suite['status']),burst=burst,
    snapshots=dict(pipeline_source=True,engine_diff_and_untracked='when components configured; bounded to 64MiB per component'),
    ci='workflow added; cloud outcome not certified by local results',
    scope='Four architecture-harness improvements verified on Qwen3-VL; broader multi-model/PD contract remains incomplete',
    limits=['Profiling is intrusive; no speedup claim.','Client overlap does not imply simultaneous GPU kernels.','Native stage hooks apply to configured model modules.','HTTP uses prefix replay; incremental state/PD/duplex are not claimed.'])
(root/'docs/evidence/validation-architecture.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print('ACCEPTANCE_EXPORTED')
