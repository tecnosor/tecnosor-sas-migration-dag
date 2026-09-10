# Evidence and provenance

SASsessment follows an evidence-first doctrine: every claim in the assessment
must trace back to registered evidence. Fabricated references are rejected
before they enter the state.

## Evidence-first doctrine

The system enforces three rules:

1. **Every finding must cite evidence.** Findings registered via
   `NodeContext.register_finding()` accept an `evidence_ids` list. The quality
   gate checks that all cited evidence ids exist in the `evidence` table.
2. **Every decision must cite evidence.** Decisions recorded via
   `NodeContext.record_decision()` include `evidence_ids`. The audit trail
   stores these references for traceability.
3. **No evidence id is invented.** The envelope validation in
   `src/sassessment/opencode_adapter/envelope.py` rejects any result that
   references evidence ids not present in state.

## Confidence levels

Every evidence item and finding carries a confidence level:

| Level | Meaning |
|-------|---------|
| `CONFIRMED` | directly observed in source material (file hash match, explicit statement) |
| `INFERRED` | derived from analysis (regex pattern match, statistical correlation) |
| `UNKNOWN` | confidence not yet assessed |

The `evidence.confidence` column defaults to `CONFIRMED` for items registered
from file intake. Findings default to `INFERRED` when produced by analysis
nodes.

## Finding versioning and supersession

Findings support versioning through the `version` and `superseded_by` columns
in the `findings` table:

- When a new analysis contradicts or refines an existing finding, the old
  finding's status changes to `SUPERSEDED` and `superseded_by` points to the
  new finding id.
- The `supersede_finding()` method in `Repository` handles this atomically
  within a transaction.
- Finding statuses: `ACTIVE`, `SUPERSEDED`, `CONTRADICTED`, `RETIRED`.

This ensures the assessment maintains a complete history of how conclusions
evolved over time.

## Anti-hallucination guard

The `build_result_from_envelope()` function in
`src/sassessment/opencode_adapter/envelope.py` validates agent output:

```python
unknown_refs = [
    ev for ev in envelope.evidence_used if not context.repo.get_evidence(ev)
]
if unknown_refs:
    raise ResultValidationError(
        "evidence references not found in state (possible hallucination)",
        details={"unknown": unknown_refs})
```

This check runs before any finding or decision from the agent is persisted.
If the agent claims to have used evidence that does not exist in the state,
the entire envelope is rejected with a `ResultValidationError`.

The guard prevents:

- Agents inventing evidence ids to make findings appear grounded.
- Stale evidence references from previous sessions.
- Typographical errors in evidence id formatting.

## Raw immutability in intake

Files placed in `intake/raw/<source-batch-id>/` are treated as immutable
raw evidence:

- The `intake.register` node hashes every file (SHA-256) and records the
  digest in `source_artifacts.sha256`.
- The batch manifest at `intake/manifests/<BAT-id>.yaml` includes an
  `integrity_hash` computed over all file paths and digests.
- The registration code in `src/sassessment/intake/registration.py` verifies
  that the batch directory lives directly under `intake/raw/` and rejects
  batches elsewhere.
- Once registered, the batch directory is never modified by the system.
  Humans may add files to a request destination batch
  (`intake/raw/req-<id>/`), but source batches are read-only.

This immutability guarantee ensures that evidence can be re-verified at any
time by re-hashing the raw files and comparing against the manifest.

## Evidence registration flow

```
file placed in intake/raw/<batch>/
       |
       v
intake.register node:
  - hash file (SHA-256)
  - detect duplicates by hash
  - write YAML manifest
  - persist source_batches + source_artifacts rows
  - register evidence item (kind="batch", title="batch BAT-... registered")
       |
       v
analysis nodes reference evidence:
  - evidence_used: ["EV-..."] in NodeResult
  - findings cite evidence_ids: ["EV-..."]
  - decisions cite evidence_ids: ["EV-..."]
       |
       v
quality.gate validates:
  - all evidence_used ids exist in evidence table
  - all finding evidence_ids exist
  - no orphan references
```

## Provenance chain

Every piece of data in the assessment has a provenance chain:

1. **Raw file** at `intake/raw/<batch>/<path>` with SHA-256 in
   `source_artifacts.sha256`.
2. **Evidence item** in `evidence` table with `artifact_id` linking to the
   source artifact.
3. **Finding** in `findings` table with `evidence_ids` JSON array linking to
   evidence items.
4. **Decision** in `decisions` table with `evidence_ids` linking to evidence.
5. **Audit event** in `audit_events` table with `evidence_ids` recording
   when evidence was registered or referenced.

The chain is queryable through the SQLite database and human-readable through
the JSONL audit trail and workspace sidecars.
