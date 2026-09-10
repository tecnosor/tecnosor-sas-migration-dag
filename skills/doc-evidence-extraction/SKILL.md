---
name: doc-evidence-extraction
description: Extract structured evidence from office documents (DOCX, XLSX, PPTX, PDF) using contract-based parsers with fixture references.
---

# Document Evidence Extraction

Extract structured evidence from office documents using defined parser contracts. No speculative parsing.

## Purpose

Define the contract for extracting text, tables, and metadata from DOCX, XLSX, PPTX, and PDF files found in registered batches. Parsers are contracts with fixture references, not production implementations.

## Inputs

- Artifact path (under `intake/raw/<batch-id>/`) with media_type: office-word, office-excel, office-powerpoint, or pdf.
- Manifest entry with sha256 and size_bytes.

## Outputs

- Extracted text content (for Word, PDF).
- Extracted table data (for Excel).
- Extracted slide text and notes (for PowerPoint).
- Evidence entries registered via `context.register_evidence()`.

## Steps

1. Verify artifact exists and SHA-256 matches manifest entry.
2. Route by media_type to the appropriate parser contract.
3. For each parser contract:
   - DOCX: extract paragraphs, tables, headers/footers. Reference fixture at `examples/synthetic-fixture/`.
   - XLSX: extract sheet names, cell ranges, named tables. Reference fixture.
   - PPTX: extract slide text, notes, table content. Reference fixture.
   - PDF: extract text layers, table structures. Reference fixture.
4. Register each extracted item as evidence with kind matching the media type.
5. Record extraction limitations (e.g., scanned PDFs require OCR, not available in foundation).

## Artifacts

- Evidence entries in the repository.
- Extraction log in the execution directory.

## Parser Contracts

Each parser is a CONTRACT, not a production implementation. The foundation provides:
- Media type classification (via `registration.py` MEDIA_TYPES).
- Fixture references at `examples/synthetic-fixture/`.
- Evidence registration interface via `NodeContext.register_evidence()`.

Production parsers for DOCX/XLSX/PPTX/PDF are out of scope for the foundation graph. They must be implemented as separate skills with their own fixture validation.

## References

- Media types: `src/sassessment/intake/registration.py` MEDIA_TYPES dict.
- Fixture: `examples/synthetic-fixture/`.
- Evidence registration: `src/sassessment/nodes/base.py` `NodeContext.register_evidence()`.
