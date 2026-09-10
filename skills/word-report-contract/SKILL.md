---
name: word-report-contract
description: Contract for generating Word (DOCX) assessment reports. Fixture-referenced template, not a production generator.
---

# Word Report Contract

Define the contract for generating Word (DOCX) assessment reports from assessment state. This is a CONTRACT with template references, not a production report generator.

## Purpose

Specify the structure, sections, and data requirements for a Word assessment report. The foundation defines the contract; implementation is a separate concern.

## Inputs

- Assessment state: findings, lineage edges, metrics, gaps, risks.
- Report template (DOCX) from `templates/`.
- Scoring and recommendation data from `analysis/`.

## Outputs (Contract Specification)

A conformant report generator must produce a DOCX file with:

1. Cover page: assessment name, subsidiary, date, classification.
2. Executive summary: key findings, confidence distribution, gap count.
3. SAS estate overview: process count, table count, application count.
4. Lineage summary: edge count, depth, coverage.
5. Migration recommendations: prioritized list with target mappings.
6. Risk register: open risks with severity.
7. Appendix: evidence index, audit trail summary.

## Contract Requirements

1. Every claim in the report must reference an evidence ID.
2. Confidence levels must be stated for every finding.
3. Limitations section must list all known gaps.
4. Report must be generated from state data only (no fabricated content).
5. Template must be validated against fixture data.

## Fixture Validation

- Template location: `templates/` directory.
- Fixture data: `examples/synthetic-fixture/`.
- A conformant generator must produce a valid DOCX from fixture data.

## Artifacts

- DOCX report in `deliverables/draft/` or `deliverables/validated/`.

## References

- Templates: `templates/` directory.
- This is a CONTRACT. Implementation is out of scope for the foundation graph.
