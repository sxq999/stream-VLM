"""Export evidence from finite video-serving runs; never infer GPU-direct from CUDA buffers."""
import argparse,hashlib,json,re
from pathlib import Path
from stream_pipeline.report import quantile
from stream_pipeline.stress import templates

p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--out',required=True);a=p.parse_args()
root=Path(a.root).resolve();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
files={};raw_by_mode={};table=[];plans=[]
def read(path):
    path=Path(path);files[str(path.relative_to(root))]=hashlib.sha256(path.read_bytes()).hexdigest()
    return json.loads(path.read_text())
dataset=read(root/'video-1fps-448/provenance.json')
final_dataset=read(root/'video-1fps-448-final/provenance.json')
assert dataset['images_sha256']==final_dataset['images_sha256']
assert (root/'video-1fps-448/events.jsonl').read_bytes()==(root/'video-1fps-448-final/events.jsonl').read_bytes()
manifest=root/'video-1fps-448/events.jsonl';files[str(manifest.relative_to(root))]=hashlib.sha256(manifest.read_bytes()).hexdigest()
values=templates(manifest)
for name,digest in dataset['images_sha256'].items():
    assert hashlib.sha256((manifest.parent/name).read_bytes()).hexdigest()==digest
transport=read(root/'transport-preflight.json')
pd=read(root/'video-nccl-001/nccl-evidence.json')
replay=read(root/'realtime-replay-002/acceptance.json')
assert replay['status']=='pass' and replay['all_kv_checksums_equal'] and all(r['passed'] for r in replay['color_checks'])
tests=(root/'tests-final.log').read_text();files['tests-final.log']=hashlib.sha256((root/'tests-final.log').read_bytes()).hexdigest()
assert '\nOK\n' in tests
for mode in ['single','replicas','nccl']:
    runroot=root/f'video-{mode}-001';summary=read(runroot/'measurement/summary.json')
    assert summary['status']=='complete'
    spec=read(runroot/'campaign.json');read(runroot/'measurement/identity.json')
    groups={};raw_by_mode[mode]={}
    for run in summary['runs']:
        case=run['case'];casepath=runroot/'measurement'/case['name']/f"repeat-{run['repeat']:02d}"/'requests.jsonl'
        files[str(casepath.relative_to(root))]=hashlib.sha256(casepath.read_bytes()).hexdigest()
        rows=[json.loads(line) for line in casepath.read_text().splitlines()]
        assert len(rows)==run['offered_requests'] and len({r['index'] for r in rows})==len(rows)
        assert all(r['status']=='complete' for r in rows)
        eligible=[(q,fs) for q,fs in values if len(fs)>=case['input_frames']]
        for r in rows:
            q,frames=eligible[r['index']%len(eligible)];frames=frames[-case['input_frames']:]
            assert all(f['capture_end_ms']<=q['evidence_cutoff_ms'] and f['ready_ms']<=q['ready_ms'] for f in frames)
            plans.append(dict(mode=mode,case=case['name'],repeat=run['repeat'],index=r['index'],template_query=q['event_id'],
                              evidence_cutoff_ms=q['evidence_cutoff_ms'],source_ids=[f['event_id'] for f in frames],
                              frame_pts_ms=[f['frame_pts_ms'] for f in frames]))
            raw_by_mode[mode][(case['name'],run['repeat'],r['index'])]=r
        g=groups.setdefault(case['name'],dict(rows=[],elapsed=0,repeats=0))
        g['rows']+=rows;g['elapsed']+=run['elapsed_including_drain_s'];g['repeats']+=1
    for name,g in groups.items():
        rows=g['rows'];lengths=[r['usage']['completion_tokens'] for r in rows]
        table.append(dict(mode=mode,case=name,repeats=g['repeats'],offered=len(rows),completed=len(rows),
            first_text_p95_s=quantile([r['first_text_after_scheduled_s'] for r in rows],.95),
            completion_p95_s=quantile([r['completion_after_scheduled_s'] for r in rows],.95),
            requests_per_s=len(rows)/g['elapsed'],output_tokens_min=min(lengths),output_tokens_max=max(lengths)))
assert pd['status']=='pass' and pd['send_bytes']==pd['receive_bytes'] and pd['send_tensors']==pd['receive_tensors']
same_budget={}
for key in ('max_active','max_pending','queue_timeout_s','upstream_timeout_s'):
    left=json.loads((root/'video-replicas-001/gateway.json').read_text())[key]
    right=json.loads((root/'video-nccl-001/gateway.json').read_text())[key]
    assert left==right;same_budget[key]=left
agreements={}
for other in ('single','replicas'):
    keys=set(raw_by_mode[other])&set(raw_by_mode['nccl'])
    agreements[other+'_vs_nccl']=dict(compared=len(keys),same_output_sha256=sum(raw_by_mode[other][k]['output_sha256']==raw_by_mode['nccl'][k]['output_sha256'] for k in keys),
        interpretation='Supplementary deterministic-text agreement; not numerical KV equality or task-quality accuracy.')
evidence=dict(status='pass',tests_linux=int(re.search(r'Ran (\d+) tests',tests).group(1)),
    dataset=dict(frames=dataset['frames'],duration_s=dataset['duration_s'],fps=dataset['fps'],width_cap=dataset['width_cap'],source_sha256=dataset['source_sha256']),
    runs=table,nccl=pd,realtime_replay=replay,media_final_reproduction='identical manifest bytes and all decoded image hashes',
    peer_access=transport['cuda_peer_access'],equal_two_gpu_gateway=same_budget,output_agreement=agreements,
    totals=dict(measured_requests=sum(r['offered'] for r in table),run_repeats=30,causal_plans=len(plans),realtime_queries=3,color_queries=3),
    source_sha256=files,raw_root=str(root),limits=[
        'One 12-second local sports clip, query snapshots, no audio or native duplex; two repeats per case.',
        'NCCL SHM path on selected RTX 3090 pair; GPU peer-direct is not available/claimed.',
        'Replica and PD modes use the same two GPUs and admission limits. Single mode admits up to 8, two-GPU modes up to 4.',
        'Auditing wraps synchronous official NCCL calls; no scheduling/kernel innovation or optimal throughput claim.',
        'SSE first-text and chunk gaps are client observations, not native engine TTFT/TPOT.',
        'Shared laboratory host and warm media caches; not exclusive, cold-cache production benchmarking.',
        'Performance uses the counter-only plugin snapshot; opt-in CPU byte checksums were added and tested in separate intrusive replay/functional validation. Exact tested sources remain archived.',
        'Long generated descriptions are not byte-identical across batch/deployment shapes; color tests and KV byte checks are separate, not broad model-quality certification.'])
(out/'validation-serving-v2.json').write_text(json.dumps(evidence,indent=2,ensure_ascii=False))
(root/'causal-input-plan-audit.json').write_text(json.dumps(dict(status='pass',meaning='Input plans reconstructed from frozen manifest and deterministic selection code; not a byte-level network capture.',requests=plans),indent=2))
lines=['# 视频 serving 与 NCCL PD 验收','',
 '本轮补齐真实视频快照负载与不落盘的 NCCL PD 基线。模型仍为 Qwen3-VL-8B-Instruct，vLLM 0.11.0；不含新的调度算法或模型训练。','',
 '## 完成了什么','',
 '- 本地 12 秒体育视频，1 fps 抽帧、宽度上限 448，保留源 PTS 与因果查询截止点。音频不送入模型。',
 '- 单卡、同两张 GPU 的双副本、NCCL PD 三种部署，各 5 组负载、每组重复两次。',
 f"- 共 {evidence['totals']['measured_requests']} 个测量请求全部完成，预热独立；Linux {evidence['tests_linux']} 项测试通过。",
 f"- NCCL 发送/接收各 {pd['send_tensors']} 个张量、{pd['send_bytes']} 字节，对应 {pd['unique_injected_requests']} 次请求注入（含预热），无缺失/形状/溢出警告。",'',
 f"- 独立实时回放 3 个查询，快照帧数为 4/8/8；生成期间收到的新帧不进入当前快照。另有 3 个并发颜色问答通过，{replay['kv_tensors_checked']} 个 KV 张量的发送/接收 SHA256 逐一相同。",'',
 '## 实际传输通路','',
 'CUDA 预检显示 GPU 2→3、3→2 的 peer access 均为 false；NCCL 实际通路为 SHM/direct/direct。KV 通过 NCCL 的主机共享内存通路传递，不生成 KV 磁盘缓存文件，也不经过网关。不能称为 GPU peer-direct。','',
 '## 结果','',
 '下表合并同一 case 两次重复的原始样本计算 p95；吞吐为完成数除以两次测量与排空时长之和。单位为秒和请求/秒。','',
 '| 部署 | 负载 | 请求数 | 首文本 p95 | 完成 p95 | req/s | 实际输出 token 范围 |','|---|---|---:|---:|---:|---:|---:|']
for r in table:
    lines.append(f"| {r['mode']} | {r['case']} | {r['offered']} | {r['first_text_p95_s']:.3f} | {r['completion_p95_s']:.3f} | {r['requests_per_s']:.3f} | {r['output_tokens_min']}–{r['output_tokens_max']} |")
lines+=['','双副本与 PD 使用同一 GPU 2/3，网关活动上限均为 4。单卡用 GPU 0、活动上限为 8，只作参照，不能把单卡与 PD 的比值当成等资源加速。所有模式关闭前缀缓存与 chunked prefill，保留多模态处理缓存。','',
 '两次重复和一个短视频不足以给出生产容量结论。NCCL 采用同步 PUT，且加入传输审计；本表用于检查功能、成本和瓶颈线索，不声称 PD 应当更快或这是最优实现。','',
 '## 正确性边界','',
 '性能运行中的长文本输出跨部署不全部相同，不能用输出哈希把它们称为逐 token 等价。本轮额外使用独立验证运行核对 KV 原始字节和三个受控颜色问题。字节校验显式复制张量到 CPU 计算 SHA256，属于侵入式验证，不进入上表性能数据，也不代表完整任务质量评测。','',
 '## 可复现材料','',
 '运行方式见 [SERVING_V2.zh-CN.md](SERVING_V2.zh-CN.md)。机器可读证据见 [validation-serving-v2.json](validation-serving-v2.json)。原始目录保留逐请求结果、完整配置、每次实际源码快照、引擎/NCCL 日志、GPU 资源采样、媒体来源哈希和重建的因果输入计划。','',
 f'服务器原始目录：`{root}`。视频和 KV/张量内容不提交 Git。']
(out/'SERVING_V2_RESULTS.zh-CN.md').write_text('\n'.join(lines)+'\n')
print(json.dumps(dict(status='pass',totals=evidence['totals'],output_agreement=agreements)))
