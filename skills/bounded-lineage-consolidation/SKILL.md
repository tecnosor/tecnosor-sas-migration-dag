---
name: bounded-lineage-consolidation
description: Consolidate lineage edges from multiple sources into a bounded, deduplicated lineage graph.
---

# Bounded Lineage Consolidation

Consolidate lineage edges from SAS analysis, DBA exports, data dictionaries, and ETL contracts into a single bounded lineage graph.

## Purpose

Merge lineage edges from multiple extraction methods, resolve duplicates, enforce depth bounds, and produce a consolidated lineage view.

## Inputs

- All lineage edges in `lineage_edges` table for the assessment.
- Configuration: `lineage_max_depth` (default 2), `lineage_max_iterations` (default 3).

## Outputs

- Consolidated lineage subgraph in `analysis/lineage/`.
- Deduplication report.
- Findings with coverage summary.

## Steps

1. Load all lineage edges for the assessment.
2. Group edges by (source_node, target_node) pair.
3. For duplicate pairs: merge evidence_ids, keep highest confidence, note multiple extraction methods.
4. Enforce depth bound: remove edges beyond `lineage_max_depth` from root objects.
5. Enforce iteration cap: limit subgraph expansion cycles to `lineage_max_iterations`.
6. Produce consolidated graph output (JSON or YAML) in `analysis/lineage/`.
7. Register findings with coverage metrics.

## Artifacts

- Consolidated lineage file in `analysis/lineage/`.
- Findings in `findings` table.

## References

- Configuration: `config/default.yaml` limits section.
- Repository: `src/sassessment/state/repository.py` `list_lineage_edges()`.
- Edge schema: source_node, target_node, relationship, extraction_method, evidence_ids, confidence, validation_status, depth, limitations.
