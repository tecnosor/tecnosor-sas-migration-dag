# Risk Register

Identified risks with likelihood, impact, and mitigation status. Risks are reviewed at each slice boundary.

---

## RSK-001: Hallucinated Evidence References

| Field | Value |
|-------|-------|
| ID | RSK-001 |
| Category | Data Integrity |
| Likelihood | Medium |
| Impact | High |
| Status | Mitigated |

**Description.** An LLM agent may reference evidence IDs that do not exist in the state database, fabricating a chain of custody that never occurred.

**Mitigation.** The envelope validation layer checks that `evidence_used` entries are non-empty strings. The quality gate node (phase8) performs evidence traceability verification, rejecting findings that reference nonexistent evidence. The system prompt explicitly instructs agents: "Never invent evidence ids; only reference ids that exist in state."

**Residual risk.** The quality gate is a deterministic node, but its implementation in `demo/nodes.py` uses regex-based checks. A sophisticated hallucination that passes regex checks but references semantically wrong evidence would not be caught.

---

## RSK-002: Path Traversal in Archive Extraction

| Field | Value |
|-------|-------|
| ID | RSK-002 |
| Category | Security |
| Likelihood | Medium |
| Impact | High |
| Status | Mitigated |

**Description.** Malicious archives (zip, tar) could contain entries with paths like `../../etc/passwd` that escape the staging directory and overwrite system files.

**Mitigation.** `src/sassessment/intake/staging.py` implements `safe_extract()` which validates every archive entry against the target directory. Entries that resolve outside the target are rejected with `PathTraversalError`. Symlink escapes are rejected with `SymlinkEscapeError`. Tests in `tests/test_intake.py` verify both attack vectors.

**Residual risk.** Encrypted archives and exotic archive formats are not supported and are quarantined. If a new archive library is introduced, the traversal checks must be ported.

---

## RSK-003: SQLite Concurrent Write Contention

| Field | Value |
|-------|-------|
| ID | RSK-003 |
| Category | Performance |
| Likelihood | Low |
| Impact | Medium |
| Status | Partially Mitigated |

**Description.** SQLite with WAL mode handles concurrent readers well, but concurrent writers can still contend. If multiple processes attempt to write simultaneously, some will receive `SQLITE_BUSY` errors.

**Mitigation.** The Database class uses BEGIN IMMEDIATE transactions, which acquire the write lock at transaction start rather than at first write. This reduces the window for contention. The POC is designed for single-assessment, single-user operation (ASM-006).

**Residual risk.** Heavy concurrency (multiple assessments, parallel agent invocations writing to the same database) remains untested. If this becomes a requirement, migration to PostgreSQL or a write-queue mechanism would be needed.

---

## RSK-004: LLM Over-Claiming Confidence

| Field | Value |
|-------|-------|
| ID | RSK-004 |
| Category | Data Integrity |
| Likelihood | Medium |
| Impact | Medium |
| Status | Mitigated |

**Description.** An LLM agent may report confidence level "CONFIRMED" for findings that are actually inferred or speculative, leading to overconfident migration recommendations.

**Mitigation.** The envelope validation accepts confidence values (CONFIRMED, INFERRED, UNKNOWN) but does not verify them against evidence strength. The quality gate node checks that findings reference evidence, but does not assess whether the evidence actually supports the claim. The system prompt instructs agents to use confidence levels honestly.

**Residual risk.** Automated verification of claim-evidence alignment is not implemented. Human review (the assessment-reviewer agent role) is the intended backstop, but that agent is not yet defined (Slice H).

---

## RSK-005: OpenCode CLI Changes Breaking Adapter

| Field | Value |
|-------|-------|
| ID | RSK-005 |
| Category | Integration |
| Likelihood | Medium |
| Impact | High |
| Status | Mitigated |

**Description.** The OpenCode CLI may change flag names, add required parameters, or alter output format in future versions, breaking the adapter.

**Mitigation.** The adapter performs capability discovery at startup via `--version` and `--help` probes. The `capabilities()` method reports which flags and subcommands are available. Tests verify that the adapter detects the real CLI and reports its capabilities. The MockAdapter provides a fallback for testing when the CLI is unavailable.

**Residual risk.** If the CLI changes in a way that breaks the adapter's assumptions (e.g., changes the envelope format in stdout), the capability discovery will not detect it. Integration tests against a specific CLI version would provide stronger guarantees.

---

## RSK-006: Parsers Pending Real SAS Samples

| Field | Value |
|-------|-------|
| ID | RSK-006 |
| Category | Functional |
| Likelihood | High |
| Impact | High |
| Status | Not Mitigated |

**Description.** The current SAS discovery implementation (`demo/nodes.py`) uses regex-based static analysis. It handles basic patterns (DATA steps, PROC SQL, %INCLUDE, %MACRO, SET/MERGE, CREATE TABLE, INSERT INTO, FROM, JOIN). Real SAS estates may use features not covered by these patterns (SAS/STAT procedures, macro variable resolution, indirect data step I/O, SCL, AF, stored processes).

**Mitigation.** None yet. Production parsers require real SAS samples from a subsidiary. The synthetic fixture exercises the regex patterns but does not represent the full complexity of real SAS code.

**Residual risk.** High. Until real samples are available and production parsers are implemented, the discovery results will be incomplete. The system is designed to flag missing evidence (via human requests) rather than silently produce wrong results.

---

## RSK-007: Demo State Pollution

| Field | Value |
|-------|-------|
| ID | RSK-007 |
| Category | Operational |
| Likelihood | Medium |
| Impact | Low |
| Status | Mitigated |

**Description.** Running the demo multiple times without cleaning state can produce incorrect results. Previous assessment data, staged fixtures, and manifests can interfere with subsequent runs.

**Mitigation.** The clean-state procedure is documented in HANDOFF-001 and AGENTS.md:

```bash
rm -f workspace/database/sassessment.db*
rm -rf intake/raw/BAT-demo-fixture intake/raw/req-*
rm -f intake/manifests/*.yaml
PYTHONPATH=src python3 -m sassessment demo
```

The demo runner checks if the fixture is already staged and skips re-copying.

**Residual risk.** If the cleanup procedure is incomplete or if state leaks into other directories, demo runs may fail. The procedure must be followed exactly.

---

## RSK-008: No CI Pipeline

| Field | Value |
|-------|-------|
| ID | RSK-008 |
| Category | Operational |
| Likelihood | High |
| Impact | Medium |
| Status | Not Mitigated |

**Description.** There is no continuous integration pipeline. Tests are run manually. Regressions may not be caught until a human runs the test suite.

**Mitigation.** None yet. The test suite is comprehensive (80 tests) and fast (seconds), so manual execution is feasible for now.

**Residual risk.** Medium. Without CI, a broken main branch can persist undetected. A GitHub Actions workflow should be added as part of Slice H.

---

## RSK-009: No Real SAS Estate Data Ingested

| Field | Value |
|-------|-------|
| ID | RSK-009 |
| Category | Functional |
| Likelihood | High |
| Impact | High |
| Status | Accepted |

**Description.** The system has not been tested against real SAS estate data. All evidence is synthetic. The foundation is complete, but the actual assessment capability is unproven.

**Mitigation.** This is by design. The repository deliberately does not perform a real assessment yet (see README.md). The foundation must be solid before real data is introduced.

**Residual risk.** High. The first real assessment will likely reveal gaps in parsers, intake handling, and agent prompts. The system is designed to be extensible, but the unknowns are significant.
