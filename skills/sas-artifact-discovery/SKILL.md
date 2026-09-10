---
name: sas-artifact-discovery
description: Discover SAS source files in registered batches and extract static analysis patterns.
---

# SAS Artifact Discovery

Discover `.sas` source files from registered batch manifests and perform static pattern extraction.

## Purpose

Scan registered batches for SAS source files (media_type `sas-source`) and extract static patterns: includes, macros, data steps, SQL statements, table references.

## Inputs

- Registered batch manifests in `intake/manifests/*.yaml`.
- SAS source files referenced in manifests with media_type `sas-source`.

## Outputs

- Domain objects: `sas_process`, `table`, `macro`, `include`.
- Lineage edges: reads/writes relationships from SAS processes to tables.
- Evidence entries per discovered process.
- Findings with discovery summary.

## Steps

1. Iterate manifests in `intake/manifests/`.
2. For each manifest, find entries with media_type `sas-source`.
3. Resolve file paths relative to the manifest's `raw_dir`.
4. For each SAS file, apply static regex patterns (from `src/sassessment/demo/nodes.py`):
   - `INCLUDE_RE`: `%include` directives.
   - `MACRO_DEF_RE`: `%macro` definitions.
   - `DATA_STEP_RE`: `data` step targets.
   - `SET_MERGE_RE`: `set`, `merge`, `update` sources.
   - `CREATE_TABLE_RE`: `create table` targets.
   - `INSERT_INTO_RE`: `insert into` targets.
   - `FROM_RE`: `from` sources.
   - `JOIN_RE`: `join` sources.
5. Register domain objects via `context.upsert_domain_object()`.
6. Add lineage edges for qualified table names (containing a dot).
7. Register evidence and findings.

## Artifacts

- Domain objects in `data_objects` table.
- Lineage edges in `lineage_edges` table.
- Evidence entries in `evidence` table.

## References

- Implementation: `src/sassessment/demo/nodes.py` `node_sas_discover()`.
- Regex patterns: defined at module level in `demo/nodes.py`.
- Fixture: `examples/synthetic-fixture/sources/`.
