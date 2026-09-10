---
name: db-object-normalization
description: Normalize database object names (tables, views, procedures) into a canonical form for cross-referencing.
---

# DB Object Normalization

Normalize database object names into a canonical form for consistent cross-referencing across SAS analysis, DBA exports, and data dictionaries.

## Purpose

Ensure that table names from different sources (SAS libname references, Oracle ALL_DEPENDENCIES, data dictionaries) resolve to the same canonical identifier.

## Inputs

- Raw table names from SAS static analysis (e.g., `SCHEMA.TABLE_NAME`).
- Raw names from DBA exports (owner, name pairs).
- Raw names from data dictionaries (object_name column).

## Outputs

- Domain objects in `data_objects` table with `normalized_name` field.
- Consistent cross-references across lineage edges.

## Steps

1. Collect all raw object names from upstream analysis.
2. Normalize: uppercase, strip whitespace, resolve schema prefix.
3. Upsert into `data_objects` via `context.upsert_domain_object()` with normalized_name.
4. Handle aliases: if the same table appears with different names across sources, record both and note the alias relationship.
5. Register findings for normalization conflicts.

## Artifacts

- Domain objects in `data_objects` table.
- Normalization log in `analysis/normalized/`.

## References

- Implementation: `src/sassessment/demo/nodes.py` `_schema_of()` helper.
- Repository: `src/sassessment/state/repository.py` `upsert_data_object()`.
