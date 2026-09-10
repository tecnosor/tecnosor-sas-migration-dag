---
name: oracle-dba-query-pack
description: Generate Oracle DBA query packs for offline lineage extraction. Offline first, no live database access.
---

# Oracle DBA Query Pack

Generate SQL query packs for Oracle DBA teams to execute offline. The foundation operates in offline mode only.

## Purpose

Create a query pack (typically ALL_DEPENDENCIES export) for identified Oracle database objects. The query pack is delivered to a human request destination batch for the DBA team to execute and return results.

## Inputs

- Database objects (tables, views) identified from SAS analysis and data dictionaries.
- Configuration: `connectors.enabled.database` (must be false for offline mode).

## Outputs

- `HumanRequestSpec` with query_pack SQL text.
- Request document at `intake/raw/req-<id>/REQUEST.md`.
- Query pack file at `intake/raw/req-<id>/query-pack.sql`.
- Node status: waiting_for_input.

## Steps

1. Count identified database objects (tables, views) from `data_objects`.
2. If no objects found, skip with status `skipped`.
3. If live database connector is enabled, register a gap and return `waiting_for_approval`.
4. Otherwise, create a `HumanRequestSpec`:
   - title: "Run ALL_DEPENDENCIES export for identified Oracle objects"
   - missing_info: "oracle.all_dependencies"
   - priority: BLOCKING
   - query_pack: SELECT from ALL_DEPENDENCIES excluding SYS/SYSTEM.
   - resume_node: "lineage.ingest_dba"
5. The request creates a destination batch at `intake/raw/req-<id>/`.
6. Return NodeResult with status `waiting_for_input`.

## Artifacts

- `intake/raw/req-<id>/REQUEST.md`
- `intake/raw/req-<id>/query-pack.sql`
- Human request record in `human_requests` table.

## References

- Implementation: `src/sassessment/demo/nodes.py` `node_dba_request()`.
- Query pack SQL: ALL_DEPENDENCIES with SYS/SYSTEM exclusion.
- Configuration: `config/default.yaml` connectors section.
