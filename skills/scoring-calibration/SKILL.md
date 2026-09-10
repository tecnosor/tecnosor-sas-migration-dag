---
name: scoring-calibration
description: Calibrate migration scoring weights based on assessment findings and stakeholder input.
---

# Scoring Calibration

Calibrate the weights and thresholds used in migration prioritization scoring.

## Purpose

Define how complexity, business criticality, risk, and effort combine into a migration priority score. Calibration is adjustable per assessment.

## Inputs

- Complexity measurements from `analysis/scoring/`.
- Business criticality data (from data dictionaries or human input).
- Risk register from `workspace/risks/`.
- Stakeholder preferences (via human requests if needed).

## Outputs

- Scoring configuration in `analysis/scoring/calibration.yaml`.
- Calibrated scores per process in `analysis/scoring/`.
- Findings documenting calibration rationale.

## Steps

1. Define scoring dimensions: complexity, criticality, risk, effort, dependency_count.
2. Assign weights per dimension (default equal weights).
3. Define thresholds: high/medium/low priority bands.
4. Apply scoring formula to each process.
5. Validate score distribution (no all-high or all-low).
6. Record calibration decisions with rationale.

## Artifacts

- `analysis/scoring/calibration.yaml`
- Scored process list in `analysis/scoring/`.

## References

- Complexity input: `analysis/scoring/<process>.yaml` from complexity-measurement skill.
- Risk input: `workspace/risks/` directory.
