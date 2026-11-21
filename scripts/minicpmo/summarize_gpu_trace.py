"""Summarize Nsight 2024 SQLite CUDA kernels by explicitly verified stage PID.

Stage map: {"0": {"pid": 123, "gpu": 0}, "1": {"pid": 456, "gpu": 1}, ...}.
GPU numbers are physical placement from deployment/process evidence, not CUPTI's
process-local deviceId. Raw PIDs are omitted from this public summary.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sqlite3


def merge(intervals):
    result = []
    for start, end in sorted(intervals):
        if end < start:
            raise ValueError('negative duration')
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return result


def union_ns(intervals):
    return sum(end - start for start, end in merge(intervals))


def overlap_ns(left, right):
    left, right = merge(left), merge(right)
    i = j = total = 0
    while i < len(left) and j < len(right):
        a, b = left[i], right[j]
        total += max(0, min(a[1], b[1]) - max(a[0], b[0]))
        if a[1] <= b[1]:
            i += 1
        else:
            j += 1
    return total


def summarize(database, stage_map):
    pids = {int(value['pid']): str(stage) for stage, value in stage_map.items()}
    if len(pids) != len(stage_map):
        raise ValueError('each stage needs a distinct verified PID')
    intervals = defaultdict(list)
    totals, counts, graphs = defaultdict(int), defaultdict(int), defaultdict(int)
    kernels = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    unknown = set()
    with sqlite3.connect(f'file:{database.resolve().as_posix()}?mode=ro', uri=True) as connection:
        rows = connection.execute('''SELECT k.start,k.end,p.pid,s.value,k.graphNodeId
            FROM CUPTI_ACTIVITY_KIND_KERNEL k
            LEFT JOIN PROCESSES p ON p.globalPid=k.globalPid
            LEFT JOIN StringIds s ON s.id=k.demangledName''')
        for start, end, pid, name, graph in rows:
            if pid not in pids:
                unknown.add(pid)
                continue
            stage = pids[pid]
            intervals[stage].append((start, end))
            totals[stage] += end - start
            counts[stage] += 1
            graphs[stage] += int(bool(graph))
            group = kernels[stage][name or '<unknown>']
            group[0] += end - start
            group[1] += 1
    stages, cards = [], defaultdict(list)
    for stage, value in stage_map.items():
        stage = str(stage)
        data = intervals[stage]
        cards[value['gpu']].extend(data)
        stages.append({'stage': stage, 'configured_physical_gpu': value['gpu'],
            'kernel_count': counts[stage], 'graph_node_kernel_count': graphs[stage],
            'kernel_sum_ms': totals[stage] / 1e6, 'kernel_union_ms': union_ns(data) / 1e6,
            'top_kernels': [{'name': name, 'sum_ms': total / 1e6, 'count': count}
                for name, (total, count) in sorted(kernels[stage].items(), key=lambda p: p[1][0], reverse=True)[:5]]})
    all_intervals = [item for values in intervals.values() for item in values]
    pairs = []
    keys = list(stage_map)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if stage_map[a]['gpu'] == stage_map[b]['gpu']:
                pairs.append({'stages': [str(a), str(b)],
                    'kernel_overlap_ms': overlap_ns(intervals[str(a)], intervals[str(b)]) / 1e6})
    return {'scope': 'single instrumented capture, not capacity or interference causality',
        'stages': stages,
        'configured_cards': [{'physical_gpu': gpu, 'kernel_union_ms': union_ns(data) / 1e6} for gpu, data in cards.items()],
        'shared_card_overlap': pairs,
        'observed_first_to_last_kernel_span_s': (max(b for a, b in all_intervals) - min(a for a, b in all_intervals)) / 1e9
                                               if all_intervals else None,
        'unmapped_kernel_process_count': len(unknown),
        'errors': (['unmapped kernel processes; stage coverage incomplete'] if unknown else []) +
                  [f'no kernels for stage {stage}' for stage in stage_map if not intervals[str(stage)]],
        'limitations': ['kernel sums double-count overlap; union and intersection are separate',
            'CUDA copies, idle time, CPU scheduling, encoding/attention/PD subphases are not decomposed here',
            'first-to-last kernel span is not capture duration, user TTFT or utilization denominator',
            'graph-node profiling has overhead; do not use these times as uninstrumented baseline timings',
            'overlap does not prove interference; controlled replay/isolation comparisons remain necessary']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sqlite', type=Path, required=True)
    parser.add_argument('--stage-map', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.sqlite, json.loads(args.stage_map.read_text()))
    args.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'stages': len(result['stages']), 'errors': result['errors'], 'out': str(args.out)}))
    return 1 if result['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
