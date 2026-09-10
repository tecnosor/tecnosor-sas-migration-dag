---
name: evidence-consistency-review
description: Verify that all findings and lineage edges reference existing evidence IDs. Detect unsupported claims.
---

# Evidence Consistency Review

Verify evidence traceability across all findings and lineage edges. Detect unsupported claims where evidence IDs are cited but do not exist.

## Purpose

Ensure the integrity of the evidence chain. Every finding and every lineage edge must reference evidence that actually exists in the repository.

## Inputs

- All active findings from `findings` table.
- All lineage edges from `lineage_edges` table.
- All evidence records from `evidence` table.

## Outputs

- Violation list: findings or edges citing missing evidence.
- Quality review report in `analysis/quality/`.
- Gap registrations for each violation.

## Steps

1. Load all active findings for the assessment.
2. For each finding, parse its evidence_ids list.
3. For each evidence ID, verify it exists in the `evidence` table.
4. If not found: record a violation (unsupported claim).
5. Load all lineage edges for the assessment.
6. For each edge, parse its evidence_ids list.
7. For each evidence ID, verify it exists.
8. If not found: record a violation.
9. Check supersession chains: every SUPERSEDED finding must have a valid superseded_by reference.
10. Write quality report to `analysis/quality/evidence-consistency.yaml`.

## Artifacts

- `analysis/quality/evidence-consistency.yaml`
- Gap registrations in `gaps` table.

## References

- Implementation pattern: `src/sassessment/demo/nodes.py` `node_quality_gate()`.
- This skill implements the same checks as the quality gate node but as a standalone review.
