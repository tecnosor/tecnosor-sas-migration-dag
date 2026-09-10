---
name: runtime-scheduler-correlation
description: Correlate scheduler exports and execution logs with discovered SAS processes to derive frequency and last-run data.
---

# Runtime Scheduler Correlation

Correlate runtime evidence (scheduler exports, execution logs) with discovered SAS processes.

## Purpose

Match log events to discovered processes, derive execution metrics (count, frequency, duration, last observed), and produce CONFIRMED runtime findings.

## Inputs

- Log files from registered batches (media_type `log-text` or `text`).
- Discovered SAS processes from the discovery phase.

## Outputs

- Runtime evidence entries per correlated process.
- Findings with execution metrics.
- Metrics dict with correlated_processes and executions counts.

## Steps

1. Iterate manifests for entries with media_type `log-text` or `text`.
2. Parse each log file line-by-line using `LOG_EVENT_RE` pattern:
   - Timestamp, process name, event type (START/END/FINISHED), optional duration.
3. Group events by process name (case-insensitive).
4. For each process group:
   - Sort events by timestamp.
   - Count total executions (END/FINISHED events).
   - Compute day span for frequency.
   - Compute average duration from events with duration data.
   - Record last observed timestamp.
5. Register evidence (kind `runtime`) and findings (confidence CONFIRMED).

## Artifacts

- Evidence entries in `evidence` table.
- Findings in `findings` table.
- Runtime analysis data in `analysis/runtime/`.

## References

- Implementation: `src/sassessment/demo/nodes.py` `node_runtime_correlate()`.
- Log pattern: `LOG_EVENT_RE` regex in `demo/nodes.py`.
- Fixture: `examples/synthetic-fixture/runtime/`.
