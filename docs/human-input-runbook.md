# Human input runbook

SASsessment is file-first and offline-capable. Most human input takes the
form of placing files into designated directories. The system generates
structured requests when it needs material it cannot find.

## Placing files into intake

To add source material to the assessment:

1. Create a batch directory under `intake/raw/<source-batch-id>/`.
   The batch id is a human-readable label (e.g., `BAT-sas-export-2026Q1`).
2. Place files directly in the batch directory. Subdirectories are supported.
3. Run `sassessment scan-inputs` to see discovered batches.
4. Run `sassessment start` to register and process the batch.

### Accepted formats

The `media_type_of()` function in `src/sassessment/intake/registration.py`
recognizes these extensions:

| Extension | Media type |
|-----------|------------|
| `.sas` | sas-source |
| `.log` | log-text |
| `.txt` | text |
| `.md` | markdown |
| `.csv` | csv |
| `.tsv` | tsv |
| `.sql` | sql-plsql |
| `.json` | json |
| `.yaml`, `.yml` | yaml |
| `.docx` | office-word |
| `.doc` | office-word-legacy |
| `.xlsx` | office-excel |
| `.xls` | office-excel-legacy |
| `.pptx` | office-powerpoint |
| `.pdf` | pdf |
| `.zip` | archive-zip |
| `.tar` | archive-tar |
| `.gz`, `.tar.gz`, `.tgz` | archive (compressed) |
| `.dtsx` | datastage-export |
| `.job` | datastage-job |

Archives are extracted safely by `src/sassessment/intake/staging.py` with
protection against path traversal, symlink escapes, and encrypted entries.

### Using add-input

For convenience, `sassessment add-input <path>` copies a file or directory
into a new batch under `intake/raw/BAT-manual-<slug>/`:

```bash
sassessment add-input /path/to/export.csv
# staged into intake/raw/BAT-manual-export/ (run start to register)
```

## Human request flow

When the system needs material it cannot find, it creates a human request:

1. A node handler calls `context.request_human_input(spec)` with a
   `HumanRequestSpec` describing what is missing.
2. The system creates a destination batch at `intake/raw/req-<request-id>/`.
3. A `REQUEST.md` file is written to the destination with details about
   what is needed, accepted formats, and the expected provider.
4. If the spec includes a `query_pack`, a `query-pack.sql` file is also
   written with the SQL or query the human should run.
5. The node status flips to `WAITING_FOR_INPUT`.
6. The request is persisted in the `human_requests` table with status `OPEN`.

### Answering a request

To answer an open request:

1. Place the requested files in the destination batch directory:
   `intake/raw/req-<request-id>/`.
   Do not modify or delete `REQUEST.md` or `query-pack.sql`.
2. Run `sassessment answer <request-id>`.

The `answer_request()` function in `src/sassessment/cli/main.py`:

- Verifies the request exists and is OPEN.
- Checks that material files exist in the destination batch (files other
  than `REQUEST.md` and `query-pack.sql`).
- Registers the destination as a new batch with id `BAT-res-<request-suffix>`.
- Moves the request status to RESOLVED.
- Moves the waiting node status to SUCCEEDED.
- Moves the resume node (specified in the request) to READY.
- Emits an audit event.

### Example: DBA request

The foundation graph's `lineage.dba_request` node creates a request for
Oracle `all_dependencies` export:

```
request REQ-20260910-abcdef12
  title: Oracle all_dependencies export not supplied
  destination: intake/raw/req-20260910-abcdef12/
  resume node: lineage.ingest_dba
```

To answer:

```bash
# Place the DBA export in the destination
cp all_dependencies_export.csv intake/raw/req-20260910-abcdef12/

# Answer the request
sassessment answer REQ-20260910-abcdef12
# request REQ-20260910-abcdef12 resolved; resume branch ready at lineage.ingest_dba

# Resume the graph
sassessment start
```

## Branch independence

The foundation graph demonstrates branch independence. After `sas.discover`,
two branches run in parallel:

- **Main branch**: `runtime.correlate` -> `doc.map_apps` -> `quality.gate` ->
  `audit.export`. This branch does not wait for human input.
- **DBA lineage branch**: `lineage.dba_request` -> `lineage.ingest_dba`.
  This branch pauses at `lineage.dba_request` waiting for the DBA export.

The main branch completes even while the DBA branch is waiting. When the
human answers the DBA request, the `lineage.ingest_dba` node becomes READY
and the next `sassessment start` runs it.

## Checking open requests

```bash
sassessment status
# open requests:
#   - REQ-20260910-abcdef12 [REQUIRED_FOR_CONFIDENCE] Oracle all_dependencies export not supplied
#       destination: intake/raw/req-20260910-abcdef12

sassessment show requests
# REQ-20260910-abcdef12 [OPEN/REQUIRED_FOR_CONFIDENCE] Oracle all_dependencies export not supplied
#   destination batch: intake/raw/req-20260910-abcdef12
#   resume node: lineage.ingest_dba
```

## Request priorities

| Priority | Meaning |
|----------|---------|
| `BLOCKING` | graph cannot proceed without this input |
| `REQUIRED_FOR_CONFIDENCE` | assessment quality degrades significantly without this |
| `OPTIONAL_ENRICHMENT` | nice to have, assessment can proceed without it |

The priority is set by the node handler in the `HumanRequestSpec` and
displayed in status output.
