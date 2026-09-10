from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from sassessment.errors import StateError
from sassessment.state.database import Database

EXECUTION_STATUSES = (
    "PENDING", "READY", "RUNNING", "WAITING_FOR_INPUT", "WAITING_FOR_APPROVAL",
    "SUCCEEDED", "FAILED", "CANCELLED", "SUPERSEDED", "SKIPPED",
)
NODE_STATUSES = (
    "PENDING", "READY", "RUNNING", "WAITING_FOR_INPUT", "WAITING_FOR_APPROVAL",
    "SUCCEEDED", "FAILED", "CANCELLED", "SUPERSEDED", "SKIPPED",
)
REQUEST_PRIORITIES = ("BLOCKING", "REQUIRED_FOR_CONFIDENCE", "OPTIONAL_ENRICHMENT")
REQUEST_STATUSES = ("OPEN", "ANSWERED", "RESOLVED", "CANCELLED", "EXPIRED")
CONFIDENCE_LEVELS = ("CONFIRMED", "INFERRED", "UNKNOWN")
FINDING_STATUSES = ("ACTIVE", "SUPERSEDED", "CONTRADICTED", "RETIRED")
ASSESSMENT_STATUSES = ("CREATED", "RUNNING", "PAUSED", "COMPLETED", "CANCELLED")


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


class Repository:
    """Transactional data access over the SASsessment SQLite schema.

    SQLite provides the queryable index; every mutation is mirrored to
    human-readable sidecars by callers. All multi-row changes run inside
    explicit transactions.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    # -- meta ---------------------------------------------------------------

    def get_meta(self, key: str) -> Optional[str]:
        row = self.db.query_one("SELECT value FROM meta WHERE key = ?", (key,))
        return str(row["value"]) if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    # -- assessments ---------------------------------------------------------

    def create_assessment(self, assessment_id: str, name: str, subsidiary: str) -> None:
        now = _dumps(utcnow_helper())
        self.db.execute(
            "INSERT INTO assessments (id, name, subsidiary, status, current_phase, created_at, updated_at)"
            " VALUES (?, ?, ?, 'CREATED', 'phase0', ?, ?)",
            (assessment_id, name, subsidiary, now, now),
        )

    def get_assessment(self, assessment_id: str) -> Optional[sqlite3.Row]:
        return self.db.query_one("SELECT * FROM assessments WHERE id = ?", (assessment_id,))

    def list_assessments(self) -> List[sqlite3.Row]:
        return self.db.query("SELECT * FROM assessments ORDER BY created_at")

    def update_assessment(self, assessment_id: str, *, status: Optional[str] = None,
                          current_phase: Optional[str] = None) -> None:
        sets, params = [], []
        if status is not None:
            sets.append("status = ?"); params.append(status)
        if current_phase is not None:
            sets.append("current_phase = ?"); params.append(current_phase)
        if not sets:
            return
        sets.append("updated_at = ?"); params.append(_dumps(utcnow_helper()))
        params.append(assessment_id)
        self.db.execute(f"UPDATE assessments SET {', '.join(sets)} WHERE id = ?", tuple(params))

    # -- sessions -------------------------------------------------------------

    def create_session(self, session_id: str, assessment_id: str) -> None:
        self.db.execute(
            "INSERT INTO sessions (id, assessment_id, status, started_at) VALUES (?, ?, 'OPEN', ?)",
            (session_id, assessment_id, _dumps(utcnow_helper())),
        )

    def get_session(self, session_id: str) -> Optional[sqlite3.Row]:
        return self.db.query_one("SELECT * FROM sessions WHERE id = ?", (session_id,))

    def list_sessions(self, assessment_id: Optional[str] = None, limit: int = 50) -> List[sqlite3.Row]:
        if assessment_id:
            return self.db.query(
                "SELECT * FROM sessions WHERE assessment_id = ? ORDER BY started_at DESC LIMIT ?",
                (assessment_id, limit),
            )
        return self.db.query("SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,))

    def close_session(self, session_id: str) -> None:
        self.db.execute(
            "UPDATE sessions SET status = 'CLOSED', closed_at = ? WHERE id = ? AND status = 'OPEN'",
            (_dumps(utcnow_helper()), session_id),
        )

    # -- node state -------------------------------------------------------------

    def upsert_node_state(self, assessment_id: str, node_id: str, *, status: str,
                          attempts: Optional[int] = None, cycles: Optional[int] = None,
                          last_execution_id: Optional[str] = None,
                          last_error: Optional[str] = None) -> None:
        existing = self.db.query_one(
            "SELECT * FROM node_states WHERE assessment_id = ? AND node_id = ?", (assessment_id, node_id))
        now = _dumps(utcnow_helper())
        if status not in NODE_STATUSES:
            raise StateError(f"illegal node status: {status}", details={"node": node_id})
        if existing is None:
            self.db.execute(
                "INSERT INTO node_states (assessment_id, node_id, status, attempts, cycles, last_execution_id,"
                " last_error, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (assessment_id, node_id, status, attempts or 0, cycles or 0, last_execution_id, last_error, now),
            )
            return
        new_attempts = existing["attempts"] if attempts is None else attempts
        new_cycles = existing["cycles"] if cycles is None else cycles
        self.db.execute(
            "UPDATE node_states SET status = ?, attempts = ?, cycles = ?, last_execution_id = ?,"
            " last_error = ?, updated_at = ? WHERE assessment_id = ? AND node_id = ?",
            (status, new_attempts, new_cycles, last_execution_id, last_error, now, assessment_id, node_id),
        )

    def get_node_state(self, assessment_id: str, node_id: str) -> Optional[sqlite3.Row]:
        return self.db.query_one(
            "SELECT * FROM node_states WHERE assessment_id = ? AND node_id = ?", (assessment_id, node_id))

    def list_node_states(self, assessment_id: str) -> List[sqlite3.Row]:
        return self.db.query(
            "SELECT * FROM node_states WHERE assessment_id = ? ORDER BY node_id", (assessment_id,))

    # -- executions ---------------------------------------------------------------

    def create_execution(self, execution_id: str, session_id: str, assessment_id: str,
                         node_id: str, attempt: int, status: str = "RUNNING") -> None:
        self.db.execute(
            "INSERT INTO executions (id, session_id, assessment_id, node_id, attempt, status, started_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (execution_id, session_id, assessment_id, node_id, attempt, status, _dumps(utcnow_helper())),
        )

    def finish_execution(self, execution_id: str, *, status: str, duration_ms: Optional[int],
                         exit_code: Optional[int] = None, error: Optional[str] = None,
                         prompt_hash: Optional[str] = None, model: Optional[str] = None,
                         provider: Optional[str] = None, opencode_session_id: Optional[str] = None,
                         result_path: Optional[str] = None) -> None:
        self.db.execute(
            "UPDATE executions SET status = ?, finished_at = ?, duration_ms = ?, exit_code = ?, error = ?,"
            " prompt_hash = ?, model = ?, provider = ?, opencode_session_id = ?, result_path = ?"
            " WHERE id = ?",
            (status, _dumps(utcnow_helper()), duration_ms, exit_code, error, prompt_hash, model, provider,
             opencode_session_id, result_path, execution_id),
        )

    def get_execution(self, execution_id: str) -> Optional[sqlite3.Row]:
        return self.db.query_one("SELECT * FROM executions WHERE id = ?", (execution_id,))

    def list_executions(self, assessment_id: Optional[str] = None, node_id: Optional[str] = None,
                        limit: int = 100) -> List[sqlite3.Row]:
        sql = "SELECT * FROM executions"
        clauses, params = [], []
        if assessment_id:
            clauses.append("assessment_id = ?"); params.append(assessment_id)
        if node_id:
            clauses.append("node_id = ?"); params.append(node_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        return self.db.query(sql, tuple(params))

    # -- batches / artifacts / evidence --------------------------------------------

    def create_batch(self, batch_id: str, batch_dir: str, *, provider: str, source_team: str,
                     environment: str, authority_level: str, confidentiality: str,
                     manifest_path: str, integrity_hash: str) -> None:
        self.db.execute(
            "INSERT INTO source_batches (id, provider, source_team, environment, authority_level,"
            " confidentiality, status, manifest_path, batch_dir, integrity_hash, registered_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 'REGISTERED', ?, ?, ?, ?)",
            (batch_id, provider, source_team, environment, authority_level, confidentiality,
             manifest_path, batch_dir, integrity_hash, _dumps(utcnow_helper())),
        )

    def get_batch(self, batch_id: str) -> Optional[sqlite3.Row]:
        return self.db.query_one("SELECT * FROM source_batches WHERE id = ?", (batch_id,))

    def update_batch_status(self, batch_id: str, status: str) -> None:
        self.db.execute("UPDATE source_batches SET status = ? WHERE id = ?", (status, batch_id))

    def list_batches(self, assessment_id: Optional[str] = None) -> List[sqlite3.Row]:
        del assessment_id
        return self.db.query("SELECT * FROM source_batches ORDER BY registered_at")

    def add_artifact(self, artifact_id: str, batch_id: str, relative_path: str, media_type: str,
                     size_bytes: int, sha256: str) -> bool:
        """Register an artifact. Returns True when new, False when a duplicate hash exists."""
        dup = self.db.query_one(
            "SELECT id FROM source_artifacts WHERE sha256 = ? AND id != ? LIMIT 1", (sha256, artifact_id))
        self.db.execute(
            "INSERT INTO source_artifacts (id, batch_id, relative_path, media_type, size_bytes, sha256,"
            " parser_status, duplicate_of, registered_at) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)",
            (artifact_id, batch_id, relative_path, media_type, size_bytes, sha256,
             dup["id"] if dup else None, _dumps(utcnow_helper())),
        )
        return dup is None

    def list_artifacts(self, batch_id: str) -> List[sqlite3.Row]:
        return self.db.query(
            "SELECT * FROM source_artifacts WHERE batch_id = ? ORDER BY relative_path", (batch_id,))

    def create_evidence(self, evidence_id: str, assessment_id: str, kind: str, title: str,
                        *, artifact_id: Optional[str] = None, locator: str = "", sha256: str = "",
                        confidence: str = "CONFIRMED") -> None:
        self.db.execute(
            "INSERT INTO evidence (id, assessment_id, artifact_id, kind, title, locator, sha256, confidence,"
            " registered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (evidence_id, assessment_id, artifact_id, kind, title, locator, sha256, confidence,
             _dumps(utcnow_helper())),
        )

    def get_evidence(self, evidence_id: str) -> Optional[sqlite3.Row]:
        return self.db.query_one("SELECT * FROM evidence WHERE id = ?", (evidence_id,))

    def list_evidence(self, assessment_id: str) -> List[sqlite3.Row]:
        return self.db.query(
            "SELECT * FROM evidence WHERE assessment_id = ? ORDER BY registered_at", (assessment_id,))

    # -- human requests ---------------------------------------------------------------

    def create_request(self, request_id: str, assessment_id: str, *, node_id: str, phase: str,
                       priority: str, title: str, missing_info: str, reason: str,
                       expected_provider: str, retrieval_attempted: str, accepted_formats: str,
                       destination_batch: str, security_notes: str, resume_node: str,
                       query_pack_path: str, request_doc_path: str) -> bool:
        """Create a request; idempotent per (assessment, node, missing_info) while OPEN."""
        existing = self.db.query_one(
            "SELECT id FROM human_requests WHERE assessment_id = ? AND node_id = ? AND missing_info = ?"
            " AND status = 'OPEN'",
            (assessment_id, node_id, missing_info))
        if existing is not None:
            return False
        self.db.execute(
            "INSERT INTO human_requests (id, assessment_id, node_id, phase, priority, status, title,"
            " missing_info, reason, expected_provider, retrieval_attempted, accepted_formats,"
            " destination_batch, security_notes, resume_node, query_pack_path, request_doc_path, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (request_id, assessment_id, node_id, phase, priority, title, missing_info, reason,
             expected_provider, retrieval_attempted, accepted_formats, destination_batch, security_notes,
             resume_node, query_pack_path, request_doc_path, _dumps(utcnow_helper())),
        )
        return True

    def get_request(self, request_id: str) -> Optional[sqlite3.Row]:
        return self.db.query_one("SELECT * FROM human_requests WHERE id = ?", (request_id,))

    def list_requests(self, assessment_id: str, status: Optional[str] = None) -> List[sqlite3.Row]:
        if status:
            return self.db.query(
                "SELECT * FROM human_requests WHERE assessment_id = ? AND status = ? ORDER BY created_at",
                (assessment_id, status))
        return self.db.query(
            "SELECT * FROM human_requests WHERE assessment_id = ? ORDER BY created_at", (assessment_id,))

    def resolve_request(self, request_id: str, *, status: str, resolution_batch_id: Optional[str]) -> bool:
        row = self.get_request(request_id)
        if row is None or row["status"] != "OPEN":
            return False
        self.db.execute(
            "UPDATE human_requests SET status = ?, resolved_at = ?, resolution_batch_id = ? WHERE id = ?",
            (status, _dumps(utcnow_helper()), resolution_batch_id, request_id),
        )
        return True

    # -- findings / decisions / registers ------------------------------------------------

    def create_finding(self, finding_id: str, assessment_id: str, *, statement: str, category: str,
                       confidence: str, evidence_ids: List[str], source_locators: Optional[List[str]] = None,
                       extraction_method: str = "", rationale: str = "", scope: str = "",
                       limitations: str = "") -> None:
        self.db.execute(
            "INSERT INTO findings (id, assessment_id, statement, category, status, confidence, evidence_ids,"
            " source_locators, extraction_method, rationale, scope, limitations, version, created_at)"
            " VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (finding_id, assessment_id, statement, category, confidence, _dumps(evidence_ids),
             _dumps(source_locators or []), extraction_method, rationale, scope, limitations,
             _dumps(utcnow_helper())),
        )

    def supersede_finding(self, original_id: str, new_finding_id: str, basis: str) -> bool:
        row = self.db.query_one(
            "SELECT id, status FROM findings WHERE id = ? AND status = 'ACTIVE'", (original_id,))
        if row is None:
            return False
        self.db.execute(
            "UPDATE findings SET status = 'SUPERSEDED', superseded_by = ? WHERE id = ?",
            (new_finding_id, original_id))
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE findings SET rationale = rationale || ? WHERE id = ?",
                (f" | supersede-basis: {basis}", new_finding_id))
        return True

    def list_findings(self, assessment_id: str, include_inactive: bool = False) -> List[sqlite3.Row]:
        if include_inactive:
            return self.db.query(
                "SELECT * FROM findings WHERE assessment_id = ? ORDER BY created_at, id", (assessment_id,))
        return self.db.query(
            "SELECT * FROM findings WHERE assessment_id = ? AND status = 'ACTIVE' ORDER BY created_at, id",
            (assessment_id,))

    def create_decision(self, decision_id: str, assessment_id: str, *, node_id: str,
                        execution_id: Optional[str], inputs: Dict[str, Any], evidence_ids: List[str],
                        selected_route: str, rationale: str, confidence: str) -> None:
        self.db.execute(
            "INSERT INTO decisions (id, assessment_id, node_id, execution_id, inputs, evidence_ids,"
            " selected_route, rationale, confidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (decision_id, assessment_id, node_id, execution_id, _dumps(inputs), _dumps(evidence_ids),
             selected_route, rationale, confidence, _dumps(utcnow_helper())),
        )

    def list_decisions(self, assessment_id: str, node_id: Optional[str] = None) -> List[sqlite3.Row]:
        if node_id:
            return self.db.query(
                "SELECT * FROM decisions WHERE assessment_id = ? AND node_id = ? ORDER BY created_at",
                (assessment_id, node_id))
        return self.db.query(
            "SELECT * FROM decisions WHERE assessment_id = ? ORDER BY created_at", (assessment_id,))

    def create_gap(self, gap_id: str, assessment_id: str, description: str, phase: str = "") -> None:
        self.db.execute(
            "INSERT INTO gaps (id, assessment_id, description, phase, status, created_at)"
            " VALUES (?, ?, ?, ?, 'OPEN', ?)",
            (gap_id, assessment_id, description, phase, _dumps(utcnow_helper())),
        )

    def create_assumption(self, assumption_id: str, assessment_id: str, statement: str, rationale: str = "") -> None:
        self.db.execute(
            "INSERT INTO assumptions (id, assessment_id, statement, rationale, status, created_at)"
            " VALUES (?, ?, ?, ?, 'ACTIVE', ?)",
            (assumption_id, assessment_id, statement, rationale, _dumps(utcnow_helper())),
        )

    def create_risk(self, risk_id: str, assessment_id: str, statement: str, severity: str = "MEDIUM",
                    mitigation: str = "") -> None:
        self.db.execute(
            "INSERT INTO risks (id, assessment_id, statement, severity, mitigation, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'OPEN', ?)",
            (risk_id, assessment_id, statement, severity, mitigation, _dumps(utcnow_helper())),
        )

    # -- data objects / lineage ------------------------------------------------

    def upsert_data_object(self, object_id: str, assessment_id: str, object_type: str, name: str,
                           *, schema_name: str = "", normalized_name: str = "",
                           first_seen_evidence: str = "") -> bool:
        normalized = normalized_name or name.lower()
        try:
            self.db.execute(
                "INSERT INTO data_objects (id, assessment_id, object_type, schema_name, name, normalized_name,"
                " first_seen_evidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (object_id, assessment_id, object_type, schema_name, name, normalized,
                 first_seen_evidence, _dumps(utcnow_helper())),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def list_data_objects(self, assessment_id: str) -> List[sqlite3.Row]:
        return self.db.query(
            "SELECT * FROM data_objects WHERE assessment_id = ? ORDER BY normalized_name", (assessment_id,))

    def create_lineage_edge(self, edge_id: str, assessment_id: str, *, source_node: str, target_node: str,
                            relationship: str, extraction_method: str, evidence_ids: List[str],
                            confidence: str = "UNKNOWN", validation_status: str = "UNVALIDATED",
                            depth: int = 0, limitations: str = "", direction: str = "DIRECTED") -> bool:
        try:
            self.db.execute(
                "INSERT INTO lineage_edges (id, assessment_id, source_node, target_node, relationship,"
                " direction, extraction_method, evidence_ids, confidence, validation_status, depth,"
                " limitations, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (edge_id, assessment_id, source_node, target_node, relationship, direction,
                 extraction_method, _dumps(evidence_ids), confidence, validation_status, depth,
                 limitations, _dumps(utcnow_helper())),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def list_lineage_edges(self, assessment_id: str) -> List[sqlite3.Row]:
        return self.db.query(
            "SELECT * FROM lineage_edges WHERE assessment_id = ? ORDER BY source_node, target_node",
            (assessment_id,))

    # -- checkpoints -----------------------------------------------------------

    def create_checkpoint_record(self, checkpoint_id: str, assessment_id: str, *, label: str,
                                 manifest_path: str, db_snapshot_path: str, manifest_sha256: str) -> None:
        self.db.execute(
            "INSERT INTO checkpoints (id, assessment_id, label, manifest_path, db_snapshot_path,"
            " manifest_sha256, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (checkpoint_id, assessment_id, label, manifest_path, db_snapshot_path, manifest_sha256,
             _dumps(utcnow_helper())),
        )

    def get_checkpoint(self, checkpoint_id: str) -> Optional[sqlite3.Row]:
        return self.db.query_one("SELECT * FROM checkpoints WHERE id = ?", (checkpoint_id,))

    def list_checkpoints(self, assessment_id: str) -> List[sqlite3.Row]:
        return self.db.query(
            "SELECT * FROM checkpoints WHERE assessment_id = ? ORDER BY created_at", (assessment_id,))

    # -- aggregated state -----------------------------------------------------------

    def project_state(self, assessment_id: str) -> Dict[str, Any]:
        """Aggregate state snapshot used by graph predicates and status rendering."""
        nodes = {
            str(r["node_id"]): {
                "status": str(r["status"]), "attempts": int(r["attempts"]), "cycles": int(r["cycles"]),
            }
            for r in self.list_node_states(assessment_id)
        }
        open_requests = self.list_requests(assessment_id, status="OPEN")
        evidence_count = len(self.list_evidence(assessment_id))
        findings = self.list_findings(assessment_id)
        assessment = self.get_assessment(assessment_id)
        return {
            "assessment_id": assessment_id,
            "assessment_status": str(assessment["status"]) if assessment else None,
            "current_phase": str(assessment["current_phase"]) if assessment else None,
            "nodes": nodes,
            "open_requests": [str(r["id"]) for r in open_requests],
            "open_request_count": len(open_requests),
            "evidence_count": evidence_count,
            "finding_count": len(findings),
            "lineage_edge_count": len(self.list_lineage_edges(assessment_id)),
            "data_object_count": len(self.list_data_objects(assessment_id)),
            "checkpoint_count": len(self.list_checkpoints(assessment_id)),
        }


def utcnow_helper() -> str:
    from sassessment.ids import utc_now_iso
    return utc_now_iso()
