---
name: powerpoint-contract
description: Contract for generating PowerPoint (PPTX) assessment presentations. Fixture-referenced template, not a production generator.
---

# PowerPoint Contract

Define the contract for generating PowerPoint (PPTX) assessment presentations from assessment state. This is a CONTRACT with template references, not a production generator.

## Purpose

Specify the structure, slides, and data requirements for a PowerPoint assessment deck. The foundation defines the contract; implementation is a separate concern.

## Inputs

- Assessment state: findings, lineage edges, metrics, gaps, risks.
- Presentation template (PPTX) from `templates/`.
- Scoring and recommendation data from `analysis/`.

## Outputs (Contract Specification)

A conformant presentation generator must produce a PPTX file with:

1. Title slide: assessment name, subsidiary, date.
2. Agenda slide.
3. Executive summary slide: key metrics, confidence distribution.
4. SAS estate overview slide: process/table/application counts.
5. Lineage visualization slide: simplified graph or key paths.
6. Migration roadmap slide: phased timeline with wave assignments.
7. Risk summary slide: top risks with severity.
8. Next steps slide: open requests, decisions needed.

## Contract Requirements

1. Every metric on a slide must trace to an evidence ID.
2. Confidence levels visible on finding slides.
3. Limitations noted on every analytical slide.
4. Generated from state data only (no fabricated content).
5. Template must be validated against fixture data.

## Fixture Validation

- Template location: `templates/` directory.
- Fixture data: `examples/synthetic-fixture/`.
- A conformant generator must produce a valid PPTX from fixture data.

## Artifacts

- PPTX presentation in `deliverables/draft/` or `deliverables/validated/`.

## References

- Templates: `templates/` directory.
- This is a CONTRACT. Implementation is out of scope for the foundation graph.
