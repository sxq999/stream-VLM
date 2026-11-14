"""Join historical requests to gateway events; no new GPU execution or GPU-stage attribution."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from statistics import mean

from stream_pipeline.stress_metrics import distribution


def analyze(root, out):
    root, out = Path(root).resolve(), Path(out).resolve()
    hashes, groups, count = {}, [], 0
    def load_lines(path):
        hashes[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    for mode in ('single','replicas','nccl'):
        measurement = root/f'video-{mode}-001'/'measurement'
        events = load_lines(measurement/'service/service-events.jsonl')
        p_times = {e['request_id']:e['duration_s'] for e in events if e['kind']=='prefill_response'}
        finished = {e['request_id']:e for e in events if e['kind']=='finished' and e['status']=='complete'}
        summary = json.loads((measurement/'summary.json').read_text(encoding='utf-8'))
        hashes[str((measurement/'summary.json').relative_to(root))] = hashlib.sha256((measurement/'summary.json').read_bytes()).hexdigest()
        cases = {}
        for run in summary['runs']:
            name = run['case']['name']
            rows = load_lines(measurement/name/f"repeat-{run['repeat']:02d}"/'requests.jsonl')
            for row in rows:
                if row['status']!='complete':
                    raise ValueError('historical phase audit expects completed V2 acceptance requests')
                ident = row.get('gateway_request_id')
                if not ident:
                    match = re.search(r'([0-9a-f]{32})$',row.get('server_request_id',''))
                    if not match: raise ValueError('request identity unavailable')
                    ident = match.group(1)
                if ident not in finished: raise ValueError('request not matched to gateway completion')
                if mode=='nccl' and ident not in p_times: raise ValueError('PD request lacks P response event')
                first = row['first_text_after_send_s']
                queue = row['gateway_queue_s']
                p = p_times.get(ident,0)
                remaining = first-queue-p
                if remaining < -.001:
                    raise ValueError('inconsistent clock decomposition')
                value=dict(first_text_after_send_s=first,gateway_queue_s=queue,p_round_trip_s=p,
                           remaining_to_first_text_s=remaining,
                           visible_answer_span_s=row['completion_after_scheduled_s']-row['first_text_after_scheduled_s'])
                cases.setdefault(name,[]).append(value)
                count+=1
        for name,values in cases.items():
            metrics={key:dict(mean=mean(v[key] for v in values),**distribution([v[key] for v in values]))
                     for key in values[0]}
            groups.append(dict(mode=mode,case=name,requests=len(values),metrics=metrics))
    evidence=dict(status='historical_logs_joined',new_gpu_runs=0,matched_requests=count,groups=groups,
        source_sha256=hashes,limitations=[
            'Historical V2 acceptance, not a new or sustained GPU experiment.',
            'P round trip includes HTTP, engine processing, transfer and one sampled token.',
            'Remaining delay is a residual observation, not a pure D prefill or transfer measurement.',
            'Visible answer span includes client-visible transport and sampling, not isolated GPU decode.',
            'Percentiles of separate components must not be added. Means share matched request sets.',
            'One clip, two repetitions, shared laboratory host and previously documented configuration.'])
    lines=['# 既有 GPU 日志的阶段复核','',
        f'重新关联此前 V2 的 {count} 个测量请求；本次没有新增 GPU 实验。下表为同组匹配请求的均值，单位秒。','',
        '| 部署 | case | 请求数 | 首文本（发送后） | 网关排队 | P 服务往返 | 其余首文本等待 | 可见回答阶段 |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    keys=('first_text_after_send_s','gateway_queue_s','p_round_trip_s','remaining_to_first_text_s','visible_answer_span_s')
    for group in groups:
        lines.append(f"| {group['mode']} | {group['case']} | {group['requests']} | "+
                     ' | '.join(f"{group['metrics'][key]['mean']:.3f}" for key in keys)+' |')
    lines+=['','## 可以支持的观察','']
    for mode in ('single','replicas','nccl'):
        value=next(g['metrics'] for g in groups if g['mode']==mode and g['case']=='rate4')
        fraction=value['gateway_queue_s']['mean']/value['first_text_after_send_s']['mean']
        lines.append(f"- {mode} 的 rate4：网关平均排队占发送后平均首文本等待的 {fraction:.1%}。")
    lines+=['','旧配置的两 GPU 网关只允许 4 个活动请求；这提示首先检查接纳上限与引擎实际利用的关系。',
        '不能仅据此断言 GPU 已饱和、传输是瓶颈，或简单提高上限一定更好；需要持续负载与接纳上限对照。']
    lines+=['','“其余首文本等待”= 客户端发送后首文本时间 − 网关排队 − P 服务往返。',
        '该余项包含客户端/HTTP 开销、D 排队、输入处理及首个输出等，不能命名为纯 D prefill。',
        'P 服务往返也不是纯 GPU prefill；可见回答阶段不是纯 GPU decode。',
        '各阶段分位数不能相加。旧实验只有短时重复，不认定稳定容量或 PD 算法优劣。','']
    out.mkdir(parents=True,exist_ok=False)
    (out/'evidence.json').write_text(json.dumps(evidence,indent=2,ensure_ascii=False),encoding='utf-8')
    (out/'PHASES.zh-CN.md').write_text('\n'.join(lines),encoding='utf-8')
    return evidence


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args();result=analyze(args.root,args.out)
    print(json.dumps(dict(status=result['status'],matched_requests=result['matched_requests'])))
