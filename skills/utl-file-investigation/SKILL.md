---
name: utl-file-investigation
description: Investigate UTL_FILE directory objects and file I/O patterns in Oracle PL/SQL discovered during analysis.
---

# UTL_FILE Investigation

Track UTL_FILE directory objects and file I/O patterns found in Oracle PL/SQL code during lineage analysis.

## Purpose

Oracle PL/SQL uses UTL_FILE for server-side file I/O via DIRECTORY objects. These represent implicit data flows that must be captured in the lineage graph.

## Inputs

- PL/SQL source code or DBA export data referencing UTL_FILE calls.
- DIRECTORY object definitions from Oracle catalog.

## Outputs

- Domain objects of type `directory_object` for UTL_FILE directories.
- Domain objects of type `file_ref` for file paths used in UTL_FILE calls.
- Lineage edges connecting PL/SQL procedures to directory objects and file paths.
- Findings documenting UTL_FILE-based data flows.

## Steps

1. Scan PL/SQL source text (from DBA exports or provided code) for UTL_FILE patterns:
   - `UTL_FILE.FOPEN(directory_name, filename, mode)`
   - `UTL_FILE.PUT_LINE(file_handle, ...)`
   - `UTL_FILE.GET_LINE(file_handle, ...)`
2. Extract directory object names and file path patterns.
3. Register directory objects as domain objects.
4. Register file references as domain objects.
5. Create lineage edges from the PL/SQL procedure to the directory object (relationship: `writes_via_utl_file` or `reads_via_utl_file`).
6. Note limitations: UTL_FILE paths are server-side, not client-side; actual file content not available.

## Artifacts

- Domain objects in `data_objects` table.
- Lineage edges in `lineage_edges` table.
- Findings in `findings` table.

## References

- Oracle UTL_FILE documentation for DIRECTORY object semantics.
- Limitation: server-side file paths, not directly accessible from the assessment.
