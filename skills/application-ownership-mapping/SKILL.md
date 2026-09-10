---
name: application-ownership-mapping
description: Map database tables to owning applications using data dictionaries (CSV/TSV).
---

# Application Ownership Mapping

Map database tables to their owning applications using data dictionaries provided as CSV or TSV files.

## Purpose

Correlate table names discovered through SAS analysis with application ownership data from data dictionaries. This enables migration prioritization by application.

## Inputs

- Data dictionary files (CSV/TSV) from registered batches.
- Expected columns: object_name, application (minimum).
- Domain objects of type `table` from prior analysis.

## Outputs

- Lineage edges: `app:{Application}` owns `db:{TABLE_NAME}`.
- Evidence entries per mapping.
- Findings with mapped/unmapped counts.
- Metrics: mapped count, unmapped count.

## Steps

1. Load data dictionary files from registered batch manifests.
2. Parse CSV/TSV with DictReader.
3. For each row:
   - Extract object_name (uppercase, stripped) and application.
   - Skip rows with empty object_name or application.
4. Look up the table in `data_objects` by normalized_name.
5. If found:
   - Register evidence (kind `data-dictionary`).
   - Create lineage edge: source `app:{application}`, target `db:{table_name}`, relationship `owns`.
   - Set confidence CONFIRMED, validation_status VALIDATED.
6. If not found: record as unmapped.
7. Register summary finding with mapped/unmapped counts.

## Artifacts

- Lineage edges in `lineage_edges` table.
- Evidence entries in `evidence` table.
- Findings in `findings` table.

## References

- Implementation: `src/sassessment/demo/nodes.py` `node_doc_mapping()`.
- Fixture: `examples/synthetic-fixture/dictionary/`.
- Limitation: dictionaries are partial; unmapped objects need owner confirmation.
