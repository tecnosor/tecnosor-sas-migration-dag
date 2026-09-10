---
name: orphan-candidate-classification
description: Classify processes without runtime evidence as orphan candidates. Absence of logs does not mean obsolete.
---

# Orphan Candidate Classification

Classify discovered processes that lack runtime evidence as orphan candidates, with explicit caveats.

## Purpose

Identify processes with zero runtime correlation and classify them as candidate-inactive. Never declare them obsolete without additional evidence.

## Inputs

- Discovered SAS processes from the discovery phase.
- Runtime correlation results (processes with log evidence).
- Coverage diff between discovered and correlated sets.

## Outputs

- Orphan candidate findings with confidence INFERRED.
- Explicit rationale: absence of logs is not proof of orphan status.
- Gap registrations for processes needing further investigation.

## Steps

1. Compute the set difference: discovered processes minus runtime-correlated processes.
2. For each uncorrelated process:
   - Register a finding with category `orphans`, confidence INFERRED.
   - Include rationale: only processes with zero activity AND documentation support may be declared orphan.
3. Register a global finding about the orphan classification methodology.
4. Optionally create human requests for processes needing owner confirmation.

## Artifacts

- Findings in `findings` table with category `orphans`.
- Optional human requests in `human_requests` table.

## Key Rule

Absence of logs does NOT equal obsolete. Always use INFERRED confidence. Always state the limitation explicitly.

## References

- Implementation: `src/sassessment/demo/nodes.py` `node_runtime_correlate()` (orphan finding section).
- Confidence: INFERRED (never CONFIRMED for absence-based claims).
