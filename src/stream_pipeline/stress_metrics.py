"""Time-resolved load metrics, reconstructed from request clocks, not SSE tokens."""
import math

from .report import quantile


def distribution(values):
    return dict(n=len(values), p50=quantile(values, .5), p95=quantile(values, .95),
                p99=quantile(values, .99), maximum=max(values) if values else None)


def meets_slo(row, case):
    if row['status'] != 'complete':
        return False
    for field, limit in (('first_text_after_scheduled_s', 'first_text_slo_s'),
                         ('completion_after_scheduled_s', 'completion_slo_s'),
                         ('max_text_chunk_gap_s', 'max_chunk_gap_slo_s')):
        if case.get(limit) is not None and (row.get(field) is None or row[field] > case[limit]):
            return False
    return True


def windows(rows, elapsed, case, width=5.0):
    """Arrival cohorts retain failures; completion counts use actual finish time.

    Latencies of a cohort include its eventual drain. Outstanding means client
    operations actually started but not finished, NOT the GPU batch/queue size.
    New-schema clocks are required; historical artifacts are not guessed.
    """
    if any('finished_s' not in r for r in rows):
        raise ValueError('request finish clocks required for time windows')
    result = []
    count = max(1, math.ceil(elapsed / width))
    for i in range(count):
        left, right = i * width, min((i + 1) * width, elapsed)
        duration = right - left
        cohort = [r for r in rows if left <= r['scheduled_s'] < right]
        complete = [r for r in cohort if r['status'] == 'complete']
        finished = [r for r in rows if left <= r['finished_s'] < right or
                    (i == count - 1 and r['finished_s'] == right)]
        good = sum(meets_slo(r, case) for r in cohort)
        checks = any(case.get(k) is not None for k in
                     ('first_text_slo_s', 'completion_slo_s', 'max_chunk_gap_slo_s'))
        result.append(dict(
            start_s=left, end_s=right, duration_s=duration,
            offered=len(cohort), completed_arrival_cohort=len(complete),
            finished_operations=len(finished), completed_in_window=sum(r['status'] == 'complete' for r in finished),
            offered_per_s=len(cohort)/duration if duration else None,
            completed_per_s=sum(r['status'] == 'complete' for r in finished)/duration if duration else None,
            client_outstanding_at_end=sum(r.get('dispatch_s') is not None and
                                          r['dispatch_s'] <= right < r['finished_s'] for r in rows),
            cohort_status_counts={s: sum(r['status'] == s for r in cohort)
                                  for s in sorted({r['status'] for r in cohort})},
            cohort_first_text_s=distribution([r['first_text_after_scheduled_s'] for r in complete
                                             if r.get('first_text_after_scheduled_s') is not None]),
            cohort_gateway_queue_s=distribution([r['gateway_queue_s'] for r in complete
                                                if r.get('gateway_queue_s') is not None]),
            cohort_slo_attainment=good/len(cohort) if checks and cohort else None))
    return dict(window_s=width, windows=result,
                semantics='Arrival-cohort latency includes eventual drain; finish rates use finish time. '
                          'Client outstanding is not gateway pending or engine running. '
                          'No stationarity/capacity claim is inferred automatically.')
