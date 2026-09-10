---
name: oracle-query-result-ingestion
description: Ingest DBA query results (CSV/TSV exports) and create lineage edges from dependency data.
---

# Oracle Query Result Ingestion

Ingest DBA team exports (CSV/TSV from ALL_DEPENDENCIES) and create lineage edges for database object dependencies.

## Purpose

Parse the DBA team's response to the query pack, extract dependency relationships, and create `depends_on` lineage edges between Oracle objects.

## Inputs

- Resolved human request with resolution_batch_id.
- CSV/TSV files in the resolution batch directory.
- Expected columns: owner, name, type, referenced_owner, referenced_name, referenced_type.

## Outputs

- Lineage edges with relationship `depends_on` and extraction_method `all-dependencies-export`.
- Evidence entries per dependency row.
- Findings with edge count summary.

## Steps

1. Find the resolved DBA request (missing_info = "oracle.all_dependencies", status = RESOLVED).
2. Locate the resolution batch manifest.
3. For each CSV/TXT file in the batch:
   - Parse with csv.DictReader.
   - Extract owner, name, referenced_owner, referenced_name.
   - Skip rows with empty names.
4. For each valid row:
   - Register evidence (kind `dba-export`).
   - Create lineage edge: source `db:oracle:{owner}.{name}`, target `db:oracle:{referenced_owner}.{referenced_name}`, relationship `depends_on`.
   - Set confidence CONFIRMED, validation_status VALIDATED.
   - Set limitations: dependency views do not capture dynamic SQL, synonyms, database links.
5. Register summary finding.

## Artifacts

- Lineage edges in `lineage_edges` table.
- Evidence entries in `evidence` table.
- Findings in `findings` table.

## References

- Implementation: `src/sassessment/demo/nodes.py` `node_ingest_dba()`.
- Limitations: dynamic SQL, synonyms, database links not captured.
