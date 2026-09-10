# Assumptions Register

Assumptions underlying the current design and implementation. If any assumption proves false, the affected decisions and implementation must be revisited.

---

## ASM-001: SQLite Suffices for POC State Size

| Field | Value |
|-------|-------|
| ID | ASM-001 |
| Status | Active |
| Related | ADR-003 |

**Assumption.** The SASsessment POC will process a single subsidiary assessment at a time. The state database will contain at most thousands of rows across all tables. SQLite with WAL mode and BEGIN IMMEDIATE transactions handles this workload without contention.

**Impact if false.** If multiple assessments run concurrently against the same database, or if a single assessment generates millions of rows, SQLite write contention or file size limits could become problems. Migration to PostgreSQL or another RDBMS would be required.

---

## ASM-002: Corporate Runtime Is System Python

| Field | Value |
|-------|-------|
| ID | ASM-002 |
| Status | Active |
| Related | ADR-001 |

**Assumption.** The target execution environment provides system Python 3.9.6 at `/usr/bin/python3` with pytest and PyYAML preinstalled. No virtual environment or package manager setup is required.

**Impact if false.** If the corporate environment changes (different Python version, missing packages), the build and test pipeline will break. ADR-001 would need revision.

---

## ASM-003: OpenCode CLI Behavior Matches Verified Flags

| Field | Value |
|-------|-------|
| ID | ASM-003 |
| Status | Active |
| Related | ADR-008 |

**Assumption.** The OpenCode CLI (version 1.14.30 at `/opt/homebrew/bin/opencode`) supports the following flags and subcommands as verified:

**Run flags:**
- `--agent <name>` -- select agent
- `--model <provider/model>` -- select model
- `-s` / `--session <id>` -- specify session
- `-c` / `--continue` -- continue existing session
- `--format json` / `--format default` -- output format
- `--file <path>` -- attach file
- `--dir <path>` -- set working directory
- `--title <text>` -- set session title

**Extra subcommands:**
- `session list` -- list sessions
- `export <id> --sanitize` -- export session with redaction
- `agent list` -- list available agents
- `models` -- list available models

**Impact if false.** The adapter's capability discovery mechanism mitigates this. If flags change, the adapter will detect the discrepancy at startup. However, the demo and CLI commands that rely on specific flag behavior would need updating.

---

## ASM-004: Intake Is Human-Placed

| Field | Value |
|-------|-------|
| ID | ASM-004 |
| Status | Active |
| Related | Slice D |

**Assumption.** All files under `intake/raw/<batch-id>/` are placed by a human operator or a trusted external process. The system does not automatically fetch files from remote sources (network shares, APIs, email attachments). The scanner only discovers what is already on disk.

**Impact if false.** If automated connectors are required (e.g., pulling from a shared drive or API), the intake layer would need extension with connector implementations. The current design does not include this.

---

## ASM-005: No Real SAS Estate Data Ingested Yet

| Field | Value |
|-------|-------|
| ID | ASM-005 |
| Status | Active |
| Related | Slices D, G |

**Assumption.** The repository does not contain real SAS estate data. All evidence is synthetic (see `examples/synthetic-fixture/`). No subsidiary has provided actual SAS source code, runtime logs, or data dictionaries. The system has not been tested against real-world SAS artifacts.

**Impact if false.** If real SAS data is ingested before parsers are production-ready, the regex-based discovery in `demo/nodes.py` may produce incomplete or incorrect results. Production parsers (Slice H gap) would be needed.

---

## ASM-006: Single Assessment Per Workspace

| Field | Value |
|-------|-------|
| ID | ASM-006 |
| Status | Active |
| Related | ADR-003 |

**Assumption.** Each workspace directory hosts one active assessment at a time. The `meta` table tracks the `active_assessment` key. Multiple assessments in the same database are technically supported by the schema but not by the CLI workflow.

**Impact if false.** If multi-assessment support is needed, the CLI would need commands to switch between assessments and the workspace layout may need per-assessment subdirectories.

---

## ASM-007: LLM Output Is Bounded by Envelope Validation

| Field | Value |
|-------|-------|
| ID | ASM-007 |
| Status | Active |
| Related | ADR-011, ADR-010 |

**Assumption.** LLM agents will produce output that can be parsed into the ResultEnvelope format. The envelope validation (status, confidence, evidence references) catches malformed output. Routing decisions are never made by the LLM; they are made by deterministic predicates.

**Impact if false.** If agents consistently fail to produce valid envelopes, the system will reject their output and mark nodes as failed. The retry mechanism (max_attempts) provides some resilience, but persistent failures would block the graph.

---

## ASM-008: Demo State Is Cleanable

| Field | Value |
|-------|-------|
| ID | ASM-008 |
| Status | Active |
| Related | Slice G |

**Assumption.** The demo can be run repeatedly from a clean state by removing the database, staged fixture, and manifests. The clean-state procedure is:

```bash
rm -f workspace/database/sassessment.db*
rm -rf intake/raw/BAT-demo-fixture intake/raw/req-*
rm -f intake/manifests/*.yaml
PYTHONPATH=src python3 -m sassessment demo
```

**Impact if false.** If demo state leaks into other workspace directories or if the cleanup procedure is incomplete, subsequent demo runs may fail or produce incorrect results.
