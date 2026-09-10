---
name: talend-parsing-contract
description: Contract for parsing Talend ETL export artifacts. Fixture-referenced, not a production parser.
---

# Talend Parsing Contract

Define the contract for parsing Talend ETL export artifacts. This is a CONTRACT with fixture references, not a production parser implementation.

## Purpose

Specify what a Talend parser must extract from Talend job export files, what evidence it produces, and what fixtures validate correct behavior.

## Inputs

- Talend export files from registered batch directories under `intake/raw/`.
- Expected formats: Talend job XML exports, item files.

## Outputs (Contract Specification)

A conformant Talend parser must produce:

- Domain objects: `talend_job`, `talend_component`, `talend_connection`.
- Lineage edges: source/target data store references per component.
- Evidence entries per parsed job.
- Findings with job count and component count.

## Contract Requirements

1. Parse job definitions: job name, version, purpose.
2. Parse components: component type (tInput, tOutput, tMap, tDBInput, tDBOutput), connected data stores.
3. Parse connections: component-to-component links with flow schemas.
4. Extract data store references (database tables, flat files, Salesforce, etc.).
5. Register all data store references as domain objects.
6. Create lineage edges with extraction_method `talend-contract`.
7. Set confidence INFERRED (contract-based parsing, not runtime verified).

## Fixture Validation

- Fixture location: `examples/synthetic-fixture/` (extend with Talend samples).
- A conformant parser must pass all fixture test cases.
- No fixture = no parser validation. Do not ship unvalidated parsers.

## Artifacts

- Domain objects in `data_objects` table.
- Lineage edges in `lineage_edges` table.

## References

- This is a CONTRACT. Implementation is out of scope for the foundation graph.
- Talend export format documentation required for parser implementation.
