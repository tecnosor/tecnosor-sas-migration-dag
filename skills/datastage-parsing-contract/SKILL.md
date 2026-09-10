---
name: datastage-parsing-contract
description: Contract for parsing IBM DataStage export artifacts (.dtsx, .job). Fixture-referenced, not a production parser.
---

# DataStage Parsing Contract

Define the contract for parsing IBM DataStage export artifacts. This is a CONTRACT with fixture references, not a production parser implementation.

## Purpose

Specify what a DataStage parser must extract from `.dtsx` and `.job` files, what evidence it produces, and what fixtures validate correct behavior.

## Inputs

- DataStage export files with media_type `datastage-export` (.dtsx) or `datastage-job` (.job).
- Files located in registered batch directories under `intake/raw/`.

## Outputs (Contract Specification)

A conformant DataStage parser must produce:

- Domain objects: `datastage_job`, `datastage_stage`, `datastage_link`.
- Lineage edges: source/target data store references per stage.
- Evidence entries per parsed job.
- Findings with job count and stage count.

## Contract Requirements

1. Parse job definitions: job name, container type (server/job/parallel).
2. Parse stages: stage name, stage type (input/output/transform), data store references.
3. Parse links: stage-to-stage connections with column mappings.
4. Extract data store references (Oracle tables, flat files, sequential files).
5. Register all data store references as domain objects.
6. Create lineage edges with extraction_method `datastage-contract`.
7. Set confidence INFERRED (contract-based parsing, not runtime verified).

## Fixture Validation

- Fixture location: `examples/synthetic-fixture/` (extend with DataStage samples).
- A conformant parser must pass all fixture test cases.
- No fixture = no parser validation. Do not ship unvalidated parsers.

## Artifacts

- Domain objects in `data_objects` table.
- Lineage edges in `lineage_edges` table.

## References

- Media types: `datastage-export`, `datastage-job` in `src/sassessment/intake/registration.py`.
- This is a CONTRACT. Implementation is out of scope for the foundation graph.
