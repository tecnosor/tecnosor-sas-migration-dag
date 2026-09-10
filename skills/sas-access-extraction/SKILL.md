---
name: sas-access-extraction
description: Extract external database and file access patterns from SAS source code.
---

# SAS Access Extraction

Extract external database references and file access patterns from SAS source files.

## Purpose

Identify how SAS processes interact with external systems: Oracle/DB2 tables (via libname or SQL passthrough), flat files (via infile/file statements), and UTL_FILE-style directory objects.

## Inputs

- SAS source files from registered batches.
- Static analysis output from `sas-artifact-discovery`.

## Outputs

- Domain objects for external tables, filerefs, directory objects.
- Lineage edges: reads/writes to external systems.
- Findings with access pattern summary.

## Steps

1. Scan SAS source text for libname assignments (external database connections).
2. Scan for SQL passthrough blocks (`connect to`, `execute`).
3. Scan for `infile` and `file` statements (flat file I/O).
4. Scan for fileref assignments (`filename` statements).
5. Register qualified table names as domain objects (type `table`).
6. Register filerefs as domain objects (type `fileref`).
7. Add lineage edges with extraction_method `sas-access-extraction`.

## Artifacts

- Domain objects in `data_objects` table.
- Lineage edges in `lineage_edges` table.

## References

- Discovery patterns: `src/sassessment/demo/nodes.py` regex set.
- Qualified name convention: `schema.table` (dot-separated).
