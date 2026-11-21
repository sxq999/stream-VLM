"""Plot the archived four-stream failure, without inferring missing samples."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--preview', type=Path)
    args = parser.parse_args()
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    evidence = json.loads(args.input.read_text(encoding='utf-8'))['n4']
    timeline = sorted(evidence['stage0_timeline'], key=lambda row: row['relative_s'])
    before = [row for row in timeline if row['relative_s'] < 0]
    samples = [row for row in timeline if row['relative_s'] >= 0]
    if not before or len(samples) < 2:
        raise ValueError('pre-run counter and multiple in-run samples are required')
    base = before[-1]['generation_tokens_total']
    times = [row['relative_s'] for row in samples]
    last_result = max(row['last_model_result_relative_s'] for row in evidence['clients'])
    last_send = max(row['last_send_relative_s'] for row in evidence['clients'])
    fig, axes = plt.subplots(2, 1, figsize=(9, 5.7), sharex=True)
    for ax in axes:
        ax.axvspan(last_result, last_send, color='#fae5df', alpha=.8)
        ax.axvline(last_result, color='#bb483b', linestyle='--', linewidth=1)
        ax.grid(axis='y', color='#e5e7eb')
        ax.spines[['top', 'right']].set_visible(False)
    axes[0].plot(times, [100 * row['kv_cache_usage_perc'] for row in samples], 'o-', color='#275c92', linewidth=2)
    axes[0].set_ylabel('Thinker KV pool used (%)')
    axes[0].set_ylim(0, 105)
    axes[0].set_title('Archived two-GPU run: four persistent input streams', loc='left', fontsize=12, pad=16)
    axes[0].text(85, 52, 'No further model-result events\nwhile inputs keep arriving', color='#8b332b', fontsize=10)
    axes[0].annotate('~99.7%', xy=(times[-1], 100 * samples[-1]['kv_cache_usage_perc']),
                     xytext=(-48, -24), textcoords='offset points', fontsize=10)
    axes[1].plot(times, [row['generation_tokens_total'] - base for row in samples], 'o-', color='#4a7463', linewidth=2)
    axes[1].set_ylabel('Thinker generation counter\n(increase from pre-run value)')
    axes[1].set_xlabel('Seconds from input start')
    axes[1].set_xlim(0, last_send + 4)
    axes[1].set_ylim(bottom=0)
    axes[1].text(last_result + 3, 80, f'Last result: ~{last_result:.0f}s\nLast input: ~{last_send:.0f}s', color='#8b332b', fontsize=10)
    fig.text(.12, .025, 'Dots are observed samples; lines only connect them. Counter values are not source-separated tokens.\n'
             'This shows correlated occupancy and stalled progress, not allocator root cause or GPU compute saturation.', fontsize=8, color='#4b5563')
    fig.tight_layout(rect=(0, .09, 1, 1))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, bbox_inches='tight')
    if args.preview:
        fig.savefig(args.preview, dpi=150, bbox_inches='tight')
    plt.close(fig)


if __name__ == '__main__':
    main()
