---
name: migration-prioritization
description: Prioritize SAS processes for migration based on calibrated scores, dependencies, and business value.
---

# Migration Prioritization

Rank SAS processes for migration sequencing based on complexity scores, dependency order, and business criticality.

## Purpose

Produce a prioritized migration list that respects dependency ordering and maximizes early value delivery.

## Inputs

- Calibrated scores from `analysis/scoring/`.
- Lineage edges from `analysis/lineage/` (dependency order).
- Application ownership from lineage edges (relationship `owns`).

## Outputs

- Prioritized migration list in `analysis/recommendations/`.
- Phase assignments (migration waves).
- Findings with prioritization rationale.

## Steps

1. Load calibrated scores for all processes.
2. Build dependency graph from lineage edges.
3. Topological sort respecting dependencies.
4. Within each dependency tier, sort by priority score (high first).
5. Assign migration waves (phase 1, 2, 3...).
6. Validate: no process scheduled before its dependencies.
7. Write prioritized list to `analysis/recommendations/migration-priority.yaml`.

## Artifacts

- `analysis/recommendations/migration-priority.yaml`
- Findings in `findings` table.

## References

- Scoring: `analysis/scoring/calibration.yaml`.
- Lineage: `analysis/lineage/` consolidated graph.
