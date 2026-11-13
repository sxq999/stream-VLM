"""Export small, source-hashed acceptance evidence; preserve full runs separately."""
import argparse
import hashlib
import json
import re
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--single',required=True);p.add_argument('--pd',required=True);p.add_argument('--out',required=True)
args=p.parse_args();single=Path(args.single);pd=Path(args.pd);out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
s=json.loads((single/'measurement/summary.json').read_text())
d=json.loads((pd/'measurement/summary.json').read_text())
pd_evidence=json.loads((pd/'pd-evidence.json').read_text())
rows=[]
for r in s['runs']:
    requests=[json.loads(line) for line in (Path(r['artifact'])/'requests.jsonl').read_text().splitlines()]
    completed=[x for x in requests if x['status']=='complete']
    output_lengths=[x['usage'].get('completion_tokens') for x in completed]
    rows.append(dict(name=r['case']['name'],mode=r['case']['mode'],concurrency=r['case']['concurrency'],
        input_frames=r['case']['input_frames'],max_tokens=r['case']['max_tokens'],offered=r['offered_requests'],completed=r['completed_requests'],
        peak_client=r['peak_client_requests'],success_fraction=r['success_fraction'],status_counts=r['status_counts'],
        first_text_p95_s=r['first_text_after_scheduled_s']['p95'],completion_p95_s=r['completion_after_scheduled_s']['p95'],
        max_chunk_gap_p95_s=r['max_text_chunk_gap_s']['p95'],requests_per_s=r['completed_requests_per_s'],
        completion_tokens_per_s=r['completion_tokens_per_s'],slo_attainment=r['slo_attainment_all_offered'],
        actual_output_tokens_min=min(output_lengths) if output_lengths else None,
        actual_output_tokens_max=max(output_lengths) if output_lengths else None,
        measurement_status=r['measurement_status']))
sources=[single/'measurement/summary.json',single/'measurement/identity.json',single/'measurement/comparison.csv',
         single/'measurement/deployment-0/engine-runtime.json',pd/'pd-evidence.json',pd/'measurement/summary.json']
test_log=single.parent/'tests-final3.log'
sources.append(test_log)
test_text=test_log.read_text()
test_count=int(re.search(r'Ran (\d+) tests',test_text).group(1))
engine_logs=[pd/f'measurement/deployment-{i}/server.log' for i in (0,1)]
for f in engine_logs:sources.append(f)
consumer=engine_logs[1].read_text(errors='replace')
injections=[line.split('] ',1)[-1] for line in consumer.splitlines() if 'Inject KV cache of' in line]
evidence=dict(status='pass' if s['status']=='complete' and d['status']=='complete' and all(r.get('success_fraction')==1 for r in d['runs']) and pd_evidence['status']=='pass' else 'failed',
    model='Qwen3-VL-8B-Instruct',hardware='RTX 3090 24GB; single serving on GPU 0; debug P/D on GPUs 1 and 3',
    engine='vLLM 0.11.0 / Torch 2.8.0+cu128',single_runs=rows,pd_debug=pd_evidence,pd_consumer_injection_lines=injections,
    tests=dict(linux=dict(count=test_count,status='pass' if '\nOK\n' in test_text else 'failed')),
    totals=dict(single_offered=sum(r['offered'] for r in rows),single_completed=sum(r['completed'] for r in rows),
        pd_measured_requests=sum(r['offered_requests'] for r in d['runs'])),
    raw_runs=dict(single=str(single),pd=str(pd)),
    source_sha256={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in sources},
    limits=['Synthetic small color-image fixtures, full prefix replay, deterministic text generation; no real continuous-video quality evaluation.',
            'Client first-text latency and SSE chunk gaps; not native TTFT/TPOT. Output lengths are reported, not assumed from max_tokens.',
            'One repeat per case; not confidence intervals, maximum sustainable capacity or an optimization speedup claim.',
            'Shared laboratory host; other GPUs and CPU/I/O activity may coexist. No machine-exclusive performance attribution.',
            'Engine max-num-seqs=32. 64/128 clients include engine waiting; they are not claims of that many GPU sequences computing simultaneously.',
            'SharedStorageConnector transfers real KV through disk; not RDMA/GPU-direct, not production PD performance.',
            'No native duplex, multi-turn state return, adaptive P/D policy, GDN log transfer or modified vLLM scheduling algorithm.'])
(out/'validation-serving.json').write_text(json.dumps(evidence,indent=2,ensure_ascii=False),encoding='utf-8')
def number(x):return '—' if x is None else f'{x:.3f}'
lines=['# Serving 与压力测试实测记录','',
 '本记录验证软件功能和测量链路；全部负载来自仓库小尺寸颜色图，不据此断言真实视频容量或论文优化收益。','',
 '## 运行条件','',
 'Qwen3-VL-8B-Instruct，RTX 3090 24GB，vLLM 0.11.0，Torch 2.8.0+cu128；单卡 serving 在 GPU 0，PD 调试在 GPU 1 与 3。引擎 max-num-seqs=32。各 case 一次测量，预热单列。','',
 '## 单卡结果','',
 '| case | offered / 完成 | 实测客户端峰值 | 首文本 p95 秒 | 完成 p95 秒 | 文本块间隔 p95 秒 | req/s | 达标率 |',
 '|---|---:|---:|---:|---:|---:|---:|---:|']
for r in rows:
    lines.append(f"| {r['name']} | {r['offered']} / {r['completed']} | {r['peak_client']} | {number(r['first_text_p95_s'])} | {number(r['completion_p95_s'])} | {number(r['max_chunk_gap_p95_s'])} | {number(r['requests_per_s'])} | {number(r['slo_attainment'])} |")
lines+=['','首文本是客户端观察指标；文本块间隔不等于 token 间隔。达标条件为该 case 冻结配置，常规配置为首文本不超过 5 秒且相邻文本块间隔不超过 0.5 秒，失败与拒绝均计入分母。req/s 包含排空时间。','',
 '输出较长 case 必须看实际 usage；详情在 validation-serving.json 的 actual_output_tokens_min/max。输入图片小、视觉 token 少且缓存预热，本表不代表真实视频压测上限。','',
 '## PD 真实状态交接','',
 f"串行调试测量 {evidence['totals']['pd_measured_requests']} 次请求；consumer 外部 KV 命中与注入证据状态：{pd_evidence['status']}。存储了 {pd_evidence['files']} 个 KV 文件，共 {pd_evidence['bytes']} 字节。",'',
 '这验证 P→共享磁盘→D 的实际 KV 加载，不是仅 HTTP 转发。磁盘调试路径不能和生产级 PD 比性能，也没有实现多轮 D→P 回传。','',
 '## 后续如何用','',
 '先将相同测量迁移到真实视频片段与不同视觉 token 数，做多次重复；再联合分析输入量、引擎排队和输出停顿。现阶段不把客户端数量当作 GPU 同时计算的 batch，也不把最大已测并发当作最大可用并发。','',
 '完整配置、逐请求日志、资源采样、引擎指标和源代码快照保留在服务器原始目录，机器可读证据含原始文件 SHA256。']
(out/'SERVING_RESULTS.zh-CN.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps(dict(status=evidence['status'],cases=len(rows),totals=evidence['totals'])))
