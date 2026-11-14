"""Verify and summarize sustained campaigns without inferring production capacity."""
import argparse
import hashlib
import json
from pathlib import Path

from stream_pipeline.stress import aggregate
from stream_pipeline.stress_metrics import windows


def export(measurement, destination):
    root, out = Path(measurement).resolve(), Path(destination).resolve()
    summary = json.loads((root/'summary.json').read_text(encoding='utf-8'))
    spec = json.loads((root/'stress-config.json').read_text(encoding='utf-8'))
    files = {}
    def record(path):
        files[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ('summary.json', 'stress-config.json', 'identity.json', 'resources.jsonl'):
        record(root/name)
    results = []
    for run in summary['runs']:
        case = run['case']
        path = root/case['name']/f"repeat-{run['repeat']:02d}"
        raw = path/'requests.jsonl'
        record(raw)
        rows = [json.loads(s) for s in raw.read_text(encoding='utf-8').splitlines()]
        if run['measurement_status'] != 'complete' or len(rows) != case['requests']:
            raise ValueError('incomplete campaign: '+str(path))
        if {r['index'] for r in rows} != set(range(case['requests'])):
            raise ValueError('missing or duplicated request indices')
        elapsed = run['elapsed_including_drain_s']
        calculated = aggregate(rows, elapsed, case)
        timeline = windows(rows, elapsed, case, spec.get('time_window_s', 5))
        stored = json.loads((path/'time-windows.json').read_text(encoding='utf-8'))
        if stored != timeline:
            raise ValueError('time-window artifact does not match raw clocks')
        record(path/'time-windows.json')
        for key in ('offered_requests','completed_requests','status_counts','slo_attainment_all_offered'):
            if calculated[key] != run[key]:
                raise ValueError('summary does not match raw requests: '+key)
        lengths = [r['usage']['completion_tokens'] for r in rows if r['status']=='complete'
                   and type(r.get('usage',{}).get('completion_tokens')) is int]
        results.append(dict(case=case['name'],repeat=run['repeat'],offered=len(rows),
            completed=calculated['completed_requests'],status_counts=calculated['status_counts'],
            first_text_p95_s=calculated['first_text_after_scheduled_s']['p95'],
            gateway_queue_p95_s=calculated['gateway_queue_s']['p95'],
            p_round_trip_p95_s=calculated['gateway_p_round_trip_s']['p95'],
            slo_all_offered=calculated['slo_attainment_all_offered'],
            requests_per_s_including_drain=calculated['completed_requests_per_s'],
            actual_output_tokens_min=min(lengths) if lengths else None,
            actual_output_tokens_max=max(lengths) if lengths else None,
            arrival_duration_s=case.get('duration_s'),
            elapsed_including_drain_s=elapsed))
    evidence = dict(status='raw_artifacts_verified',
        evidence_kind=spec.get('evidence_kind','unclassified; verify deployment and GPU logs'),
        measured_requests=sum(r['offered'] for r in results),run_repeats=len(results),runs=results,
        source_sha256=files,limitations=[
            'No maximum concurrency or stable production capacity is certified.',
            'SSE first text and chunk gaps are not native engine TTFT/TPOT.',
            'Arrival-cohort latency includes drain; completed-per-window uses finish time.',
            'Queue distributions from response headers cover completed requests; failures remain in SLO denominator.',
            'Engine timeline scrapes and gateway samples have independent timestamps and sampling overhead.',
            'Warmup exclusion does not make caches cold. Repeated snapshots may hit prefix/media caches.',
            'Persistent same-session append and novel PD strategies are not implemented by this campaign.'])
    lines=['# 持续压力测试结果','',
           '下表逐次报告，不将重复实验合并后掩盖波动。req/s 的分母包含排空时间，不作为稳定容量。','',
           '| case | repeat | 完成/到达 | 首文本 p95(s) | 网关排队 p95(s) | SLO 达成率 | req/s（含排空） |',
           '|---|---:|---:|---:|---:|---:|---:|']
    def fmt(value): return '—' if value is None else f'{value:.3f}'
    for r in results:
        lines.append(f"| {r['case']} | {r['repeat']} | {r['completed']}/{r['offered']} | "
                     f"{fmt(r['first_text_p95_s'])} | {fmt(r['gateway_queue_p95_s'])} | "
                     f"{fmt(r['slo_all_offered'])} | {fmt(r['requests_per_s_including_drain'])} |")
    lines += ['', '证据类型：`'+evidence['evidence_kind']+'`。HTTP 模拟后端结果不能解释为 GPU 性能。','',
              '每组 time-windows.json 分开记录到达分组延迟和实际完成速率；resources.jsonl 保留网关和 GPU 采样。',
              '没有足够的持续时间、独立重复、质量及负载覆盖时，不认定服务稳定容量。','']
    out.mkdir(parents=True,exist_ok=False)
    (out/'evidence.json').write_text(json.dumps(evidence,indent=2,ensure_ascii=False),encoding='utf-8')
    (out/'RESULTS.zh-CN.md').write_text('\n'.join(lines),encoding='utf-8')
    return evidence


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--measurement',required=True)
    parser.add_argument('--out',required=True)
    args=parser.parse_args()
    result=export(args.measurement,args.out)
    print(json.dumps(dict(status=result['status'],requests=result['measured_requests'])))
