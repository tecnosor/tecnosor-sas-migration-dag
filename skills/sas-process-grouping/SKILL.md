---
name: sas-process-grouping
description: Group discovered SAS artifacts into candidate business processes with identity heuristics.
---

# SAS Process Grouping

Group discovered SAS artifacts into candidate business processes. Source file identity is initial; final identity requires runtime correlation.

## Purpose

Take the raw output of SAS artifact discovery and group files into candidate processes based on naming conventions, include chains, macro dependencies, and scheduler hints.

## Inputs

- Domain objects of type `sas_process` from the discovery phase.
- Include chains and macro dependency data.
- Optional: scheduler export data for process name hints.

## Outputs

- Grouped process candidates with member file lists.
- Confidence annotations (INFERRED from static analysis).
- Findings documenting grouping rationale.

## Steps

1. Start with one candidate per source file (stem-based identity from discovery).
2. Merge candidates that share `%include` references.
3. Merge candidates that call the same macros.
4. Annotate each group with member files, include depth, macro count.
5. Register findings with confidence INFERRED and explicit rationale.
6. Note that final process identity requires runtime/scheduler correlation.

## Artifacts

- Grouped process records in `analysis/inventory/`.
- Findings in the repository.

## References

- Discovery implementation: `src/sassessment/demo/nodes.py` `node_sas_discover()`.
- Limitation: source code alone does not guarantee business-process identity.
