---
name: target-architecture-mapping
description: Map assessed SAS processes to approved PF target architecture components.
---

# Target Architecture Mapping

Map each assessed SAS process to a target technology in the approved Personal Finance architecture.

## Purpose

Produce a target mapping for each process: which target technology (or pattern) will replace it. Only approved PF standards are valid targets.

## Inputs

- Prioritized migration list from `analysis/recommendations/`.
- Approved PF target architecture documentation (templates or schemas).
- Lineage edges for dependency context.

## Outputs

- Target mapping per process in `analysis/recommendations/`.
- Migration option per process: rewrite, replatform, retire, replace-with-COTS.
- Findings with mapping rationale.

## Steps

1. Load the prioritized process list.
2. For each process, evaluate migration options:
   - Rewrite: complex custom logic with no COTS equivalent.
   - Replatform: straightforward logic that can run on target platform.
   - Retire: orphan candidates with no active runtime evidence.
   - Replace with COTS: standard process covered by existing PF products.
3. Assign target technology per approved PF standards.
4. Document rationale and evidence for each mapping.
5. Write target mapping to `analysis/recommendations/target-mapping.yaml`.

## Artifacts

- `analysis/recommendations/target-mapping.yaml`
- Findings in `findings` table.

## Boundaries

- Only approved PF target technologies. No invented targets.
- Confidence INFERRED (mapping is advisory).

## References

- Approved standards: defined in PF architecture documentation (external to this repo).
- Templates: `templates/` directory for mapping format.
