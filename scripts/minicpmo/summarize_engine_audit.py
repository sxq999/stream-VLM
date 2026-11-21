"""Summarize diagnostic scheduler metadata; no GPU duration or KV-byte claims."""
import argparse
from collections import Counter
import json
from pathlib import Path


def summarize(directory):
    sessions = {}
    kinds = Counter()
    errors = []
    for path in sorted(directory.glob('*.jsonl')):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            try:
                event = json.loads(line)
            except ValueError:
                errors.append({'file': path.name, 'line': number, 'error': 'invalid JSON'})
                continue
            stage, pid, kind = event['stage'], event['pid'], event['kind']
            kinds[str(stage) + ':' + kind] += 1
            rows = event.get('requests', []) if kind == 'schedule' else [event]
            for row in rows:
                state = row.get('state') or row.get('after') or row.get('after_schedule') or {}
                request_id = row.get('request_id') or state.get('request_id')
                if request_id is None:
                    continue
                key = (stage, pid, request_id)
                item = sessions.setdefault(key, {'stage': stage, 'request': len(sessions) + 1,
                    'initial_positions': 0, 'update_events': 0, 'received_update_positions': 0,
                    'scheduled_positions': 0, 'scheduled_steps': 0, 'kv_block_samples': 0,
                    'max_prompt_positions': None, 'max_computed_positions': None,
                    'max_kv_blocks_by_group': None, 'reanchors': [], 'prompt_reductions': [],
                    'kv_block_decreases': [], 'first_s': event['at_s'], 'last_s': event['at_s']})
                item['last_s'] = event['at_s']
                for name, dest in (('num_prompt_tokens', 'max_prompt_positions'),
                                   ('num_computed_tokens', 'max_computed_positions')):
                    value = state.get(name)
                    if value is not None:
                        item[dest] = max(item[dest] if item[dest] is not None else value, value)
                if kind == 'initial_admission':
                    item['initial_positions'] += row['input']['prompt_positions']
                elif kind == 'streaming_update':
                    item['update_events'] += 1
                    item['received_update_positions'] += row['input']['prompt_positions']
                    before, after = row['before'], row['after']
                    old = before.get('num_prompt_tokens')
                    new = after.get('num_prompt_tokens')
                    relative_s = event['at_s'] - item['first_s']
                    if old is not None and new is not None and new < old:
                        item['prompt_reductions'].append({'relative_s': relative_s, 'before': old, 'after': new})
                    a = before.get('_minicpmo45_reanchor_count') or 0
                    b = after.get('_minicpmo45_reanchor_count') or 0
                    if b > a:
                        item['reanchors'].append({'relative_s': relative_s, 'counter_before': a,
                            'counter_after': b, 'prompt_before': old, 'prompt_after': new})
                elif kind == 'schedule':
                    item['scheduled_positions'] += row['scheduled_positions']
                    item['scheduled_steps'] += 1
                    blocks = row.get('kv_blocks_by_group')
                    if blocks is not None:
                        item['kv_block_samples'] += 1
                        previous = item.get('_previous_blocks')
                        if previous is not None and len(previous) == len(blocks) and any(a > b for a, b in zip(previous, blocks)):
                            item['kv_block_decreases'].append({'relative_s': event['at_s'] - item['first_s'],
                                                              'before': previous, 'after': blocks})
                        peak = item['max_kv_blocks_by_group']
                        item['max_kv_blocks_by_group'] = [max(a, b) for a, b in zip(peak, blocks)] if peak is not None else blocks
                        item['_previous_blocks'] = blocks
                    if 'kv_blocks_unavailable' in row:
                        errors.append({'request': item['request'], 'error': row['kv_blocks_unavailable']})
    result = []
    for item in sessions.values():
        item.pop('_previous_blocks', None)
        item['observed_span_s'] = item.pop('last_s') - item.pop('first_s')
        result.append(item)
    return {'scope': 'diagnostic scheduler metadata, not uninstrumented performance',
            'covered_stages': sorted({item['stage'] for item in result}),
            'event_counts': dict(kinds), 'requests': result, 'errors': errors,
            'limitations': ['received positions may contain control or placeholder tokens; modalities are not separated',
                'scheduled positions can contain recomputation and are not new-input counts',
                'KV groups report blocks, not bytes or all model-side memory',
                'scheduler computed-position counts can include in-flight work; they are not a GPU completion fence',
                'these AR hooks do not instrument the Code2Wav generation scheduler',
                'window counters and block decreases prove mechanics, not retained-context quality',
                'CPU hook timestamps are not GPU kernel durations or complete input-freshness measurements']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.input)
    if not result['requests']:
        result['errors'].append({'error': 'no request records'})
    args.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'requests': len(result['requests']), 'errors': len(result['errors']), 'out': str(args.out)}))
    return 1 if result['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
