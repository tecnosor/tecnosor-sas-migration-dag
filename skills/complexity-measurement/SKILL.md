---
name: complexity-measurement
description: Measure SAS process complexity using line counts, macro depth, SQL passthrough, and include chains.
---

# Complexity Measurement

Measure the complexity of discovered SAS processes using static metrics.

## Purpose

Produce quantitative complexity scores for each candidate SAS process to inform migration prioritization.

## Inputs

- SAS source files from registered batches.
- Static analysis output (macro count, data step count, SQL blocks, include depth).

## Outputs

- Complexity metrics per process in `analysis/scoring/`.
- Metrics include: line_count, macro_count, data_step_count, sql_passthrough_count, include_depth, table_count, external_ref_count.

## Steps

1. For each discovered SAS process, read the source file(s).
2. Count lines of code (excluding comments and blank lines).
3. Count macro definitions (`%macro` occurrences).
4. Count data steps (`data` statement occurrences).
5. Count SQL passthrough blocks (`connect to`, `execute` occurrences).
6. Measure include chain depth (recursive `%include` resolution).
7. Count distinct table references (qualified names).
8. Count external references (non-SAS data sources).
9. Write complexity report to `analysis/scoring/<process-name>.yaml`.

## Artifacts

- Complexity reports in `analysis/scoring/`.

## References

- Discovery patterns: `src/sassessment/demo/nodes.py` regex set.
- Configuration: `config/default.yaml` limits section.
