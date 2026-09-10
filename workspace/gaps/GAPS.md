# Gap Register

Open gaps in the current implementation. Each gap has an owner hint and a next action. Gaps are distinct from risks: they represent missing functionality, not potential failures.

---

## GAP-001: Real SAS Parser

| Field | Value |
|-------|-------|
| ID | GAP-001 |
| Category | Functional |
| Priority | High |
| Owner Hint | sas-estate-analyst agent |
| Status | Open |

**Description.** The current SAS discovery implementation uses regex-based static analysis (`demo/nodes.py`). It handles basic patterns but does not cover the full SAS language: SAS/STAT procedures, macro variable resolution, indirect data step I/O, SCL, AF, stored processes, SAS/CONNECT, hash objects, dynamic SQL, PROC FCMP functions.

**Next Action.** Obtain real SAS samples from a subsidiary. Analyze the samples to identify patterns not covered by the current regex set. Implement production parsers as separate modules under `src/sassessment/parsers/`. Each parser should produce structured evidence (data objects, lineage edges, process metadata) that the discovery node can consume.

**Dependencies.** Real SAS estate data (blocked by subsidiary engagement).

---

## GAP-002: Word Document Generator

| Field | Value |
|-------|-------|
| ID | GAP-002 |
| Category | Output |
| Priority | Medium |
| Owner Hint | migration-architect agent |
| Status | Open |

**Description.** The assessment produces structured evidence, findings, and recommendations, but does not generate Word documents (.docx) for human consumption. Subsidiary stakeholders expect formatted reports.

**Next Action.** Implement a Word generator using `python-docx` (or a similar library). The generator should consume the assessment state (findings, decisions, lineage, recommendations) and produce a structured document with sections: executive summary, scope, methodology, findings, recommendations, appendix (evidence index). Add as a new node in the graph (phase8, after audit.export) or as a CLI command (`sassessment export-word`).

**Dependencies.** python-docx library (not in current dependency set). Decision on document template and branding.

---

## GAP-003: PowerPoint Generator

| Field | Value |
|-------|-------|
| ID | GAP-003 |
| Category | Output |
| Priority | Low |
| Owner Hint | migration-architect agent |
| Status | Open |

**Description.** Similar to GAP-002, but for PowerPoint presentations (.pptx). Executive stakeholders often prefer slide decks over lengthy documents.

**Next Action.** Implement after GAP-002. Use `python-pptx` library. Generate a slide deck with key findings, high-level lineage diagrams, and migration recommendations.

**Dependencies.** GAP-002 (reuse assessment state consumption logic). python-pptx library.

---

## GAP-004: Connectors for Automated Intake

| Field | Value |
|-------|-------|
| ID | GAP-004 |
| Category | Integration |
| Priority | Medium |
| Owner Hint | evidence-curator agent |
| Status | Open |

**Description.** The current intake layer assumes files are human-placed in `intake/raw/`. There are no connectors to automatically fetch files from network shares, APIs, email attachments, or version control systems.

**Next Action.** Define connector interfaces. Implement connectors for common sources: SMB/CIFS network shares, REST APIs, Git repositories. Each connector should produce batches in `intake/raw/<batch-id>/` with appropriate metadata. Add connector configuration to `config/default.yaml`.

**Dependencies.** Decision on which sources to support first. Access credentials and network configuration for target environments.

---

## GAP-005: ETL Platform Metadata Samples

| Field | Value |
|-------|-------|
| ID | GAP-005 |
| Category | Functional |
| Priority | High |
| Owner Hint | runtime-analyst agent |
| Status | Open |

**Description.** The runtime correlation node (`runtime.correlate`) processes scheduler export logs to identify which SAS processes actually execute. The current implementation handles a specific log format (regex-based). Real ETL platforms (Control-M, Airflow, DataStage, Informatica) have different metadata formats.

**Next Action.** Obtain sample metadata exports from the target ETL platforms. Analyze the formats. Implement platform-specific parsers that produce a common intermediate format (process name, schedule, dependencies, runtime statistics). Update the runtime correlation node to consume the intermediate format.

**Dependencies.** Access to ETL platform metadata. Sample exports from subsidiary environments.

---

## GAP-006: Deeper Workspace Validator

| Field | Value |
|-------|-------|
| ID | GAP-006 |
| Category | Quality |
| Priority | Low |
| Owner Hint | assessment-reviewer agent |
| Status | Open |

**Description.** The current workspace validator (`sassessment validate`) checks basic structural integrity: required directories exist, database is accessible, graph loads. It does not check: evidence consistency (all referenced evidence exists), lineage completeness (all data objects have lineage), finding-evidence alignment, checkpoint manifest integrity.

**Next Action.** Extend the validator with deeper checks. Add validation modes: `--quick` (current behavior), `--deep` (full consistency check), `--fix` (attempt to repair minor issues). Report violations as structured findings.

**Dependencies.** None. Can be implemented incrementally.

---

## GAP-007: Security Review Checklist

| Field | Value |
|-------|-------|
| ID | GAP-007 |
| Category | Security |
| Priority | Medium |
| Owner Hint | guardian agent |
| Status | Open |

**Description.** There is no formal security review checklist for the SASsessment application itself. The threat model (GAP-008) is also not yet written. Security considerations are addressed ad hoc (path traversal checks, secret redaction, argv-only subprocess invocation) but not systematically reviewed.

**Next Action.** Create a security review checklist covering: input validation (all intake paths), output encoding (all generated documents), authentication/authorization (if multi-user support is added), secret management (redaction coverage), dependency vulnerabilities (pip audit), subprocess invocation (argv-only enforcement), file system access (path traversal prevention). Document as `docs/security-review-checklist.md`.

**Dependencies.** None. Can be done as part of Slice H.

---

## GAP-008: Threat Model Document

| Field | Value |
|-------|-------|
| ID | GAP-008 |
| Category | Security |
| Priority | Medium |
| Owner Hint | guardian agent |
| Status | Open |

**Description.** No threat model document exists. The system interacts with multiple trust boundaries: human operators (intake), LLM agents (adapter), file system (workspace), database (state), external CLI (opencode). Each boundary has potential threats.

**Next Action.** Write `docs/threat-model.md` covering: threat actors (insider, external attacker, compromised LLM), attack surfaces (intake, adapter, database, file system), threat categories (data exfiltration, code execution, privilege escalation, evidence tampering), mitigations (current and planned), residual risks.

**Dependencies.** None. Can be done as part of Slice H.

---

## GAP-009: Agent and Skill Markdown Files

| Field | Value |
|-------|-------|
| ID | GAP-009 |
| Category | Operational |
| Priority | High |
| Owner Hint | coordinator agent |
| Status | Open |

**Description.** The node framework (Slice F) supports agent execution, but the actual agent markdown files (`.opencode/agents/*.md`) and skill files (`.opencode/skills/<name>/SKILL.md`) do not exist. The 7 agent roles (coordinator, evidence-curator, sas-estate-analyst, runtime-analyst, lineage-analyst, migration-architect, assessment-reviewer) are defined in STATE.md but not implemented as OpenCode-discoverable agents.

**Next Action.** Create agent markdown files in `.opencode/agents/` for each role. Each file should define: description, mode (subagent), model, temperature, permission, system prompt. Create skill files in `.opencode/skills/` for key capabilities (e.g., sas-discovery, runtime-correlation, lineage-analysis, quality-gate, audit-export). Test that OpenCode discovers and can invoke them.

**Dependencies.** None. Can be done as part of Slice H.

---

## GAP-010: CI Pipeline

| Field | Value |
|-------|-------|
| ID | GAP-010 |
| Category | Operational |
| Priority | Medium |
| Owner Hint | coordinator agent |
| Status | Open |

**Description.** No continuous integration pipeline exists. Tests are run manually. There is no automated linting, type checking, or deployment.

**Next Action.** Create a GitHub Actions workflow (`.github/workflows/ci.yml`) that runs on push and pull requests. Steps: checkout, setup Python 3.9, install dependencies (pip install -e .[dev]), run pytest, run sassessment validate, run sassessment demo (clean state). Add optional steps: lint (ruff or flake8), type check (mypy), security audit (pip-audit).

**Dependencies.** GitHub repository setup (if not already done). Decision on required vs. optional checks.
