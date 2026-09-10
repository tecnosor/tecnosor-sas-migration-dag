# Synthetic demo walkthrough (foundation-only; ALL DATA SYNTHETIC)

This demonstrates the operational foundation end to end. NO real subsidiary data
is used; the fixture lives in `examples/synthetic-fixture/` and every file is
labeled synthetic.

## The 14-step flow

| Step | Action | Where it happens |
|---|---|---|
| 1 | Initialize assessment | `sassessment init` (implicit in demo command) |
| 2 | Register fixture batch | node `intake.register` hashes `intake/raw/BAT-demo-fixture/`, writes manifest |
| 3 | Evidence discovery | node `intake.coverage` counts media types |
| 4 | SAS discovery placeholder | node `sas.discover` static regex analysis (3 processes) |
| 5 | Database object identification | same node registers `cust.*` tables as data objects |
| 6 | Persisted DBA request | node `lineage.dba_request` creates REQ + `query-pack.sql` (ALL_DEPENDENCIES) |
| 7 | Pause lineage branch | that node returns `waiting_for_input`; other branches continue |
| 8 | Documentation-mapping branch | node `doc.map_apps` maps 3 tables to applications from `dictionary/data_dictionary.csv` |
| 9 | Add synthetic DBA-result batch | `sassessment demo` writes `all_dependencies_export.csv` into the request destination |
| 10 | Resolve the request | `answer_request` marks REQ RESOLVED, waiting node SUCCEEDED, resume node READY |
| 11 | Resume lineage branch | node `lineage.ingest_dba` ingests the export: 3 CONFIRMED edges |
| 12 | Checkpoint | `CheckpointManager` snapshot + manifest (immutable) |
| 13 | Quality validation | node `quality.gate` verifies every finding/edge cites existing evidence |
| 14 | Audit export | `workspace/audit/export-<ASMT-id>.jsonl` |

## Exact commands (clean state)

```bash
rm -f workspace/database/sassessment.db* && rm -rf intake/raw/BAT-demo-fixture intake/raw/req-* intake/manifests/*.yaml
PYTHONPATH=src python3 -m sassessment init
PYTHONPATH=src python3 -m sassessment demo
PYTHONPATH=src python3 -m sassessment status
PYTHONPATH=src python3 -m sassessment review
```

## Expected highlights

- `intake.register: SUCCEEDED` with fixture batch (7 files incl. README).
- `quality.gate` initially FAILS only if a finding/edge lacks evidence (the demo
  phase 1 run may pass) — after the DBA resume the gate re-run passes.
- The DBA destination is `intake/raw/req-<request-id>/` — printed on creation.
- Audit export lands as `workspace/audit/export-<assessment-id>.jsonl`.

## Fail-safe notes

- Re-running the demo is idempotent-ish: already-registered batches are skipped,
  an already-resolved request is not duplicated (unique OPEN index).
- To hard-reset: the `rm` line above plus deleting `workspace/sessions/*/`.
