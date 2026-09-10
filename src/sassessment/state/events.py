from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from sassessment.errors import StateError
from sassessment.ids import event_id, utc_now_iso_precise
from sassessment.state.database import Database


class Redactor:
    """Applies configurable regex patterns to redact secrets from persisted text."""

    _SENSITIVE_KEYS = re.compile(r"(?i)(password|passwd|pwd|secret|token|credential|api[_-]?key|apikey)")

    def __init__(self, patterns: Sequence[str]) -> None:
        self._compiled = [re.compile(p, re.MULTILINE) for p in patterns]

    def redact(self, value: Any) -> Any:
        if isinstance(value, str):
            text = value
            for pattern in self._compiled:
                text = pattern.sub("[REDACTED]", text)
            return text
        if isinstance(value, dict):
            result = {}
            for k, v in value.items():
                if isinstance(k, str) and self._SENSITIVE_KEYS.search(k):
                    result[k] = "[REDACTED]"
                else:
                    result[k] = self.redact(v)
            return result
        if isinstance(value, list):
            return [self.redact(v) for v in value]
        return value


class AuditEmitter:
    """Append-only audit trail: JSONL file (durable, human-readable) + SQLite index (queryable).

    The JSONL file is the authoritative sequence; SQLite is an index. Both writes occur
    before the method returns. Duplicate ``event_id`` values are ignored idempotently.
    """

    def __init__(self, db: Database, log_path: Path, redactor: Redactor) -> None:
        self.db = db
        self.log_path = Path(log_path)
        self.redactor = redactor
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(
        self,
        *,
        action: str,
        actor_type: str,
        actor_id: str = "",
        assessment_id: Optional[str] = None,
        session_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        node_id: Optional[str] = None,
        previous_state: Optional[str] = None,
        new_state: Optional[str] = None,
        rationale: str = "",
        evidence_ids: Optional[List[str]] = None,
        prompt_hash: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        result_status: Optional[str] = None,
        error: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        eid = event_id()
        ts = utc_now_iso_precise()
        record = {
            "event_id": eid,
            "ts": ts,
            "assessment_id": assessment_id,
            "session_id": session_id,
            "execution_id": execution_id,
            "node_id": node_id,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "action": action,
            "previous_state": previous_state,
            "new_state": new_state,
            "rationale": rationale,
            "evidence_ids": evidence_ids or [],
            "prompt_hash": prompt_hash,
            "model": model,
            "provider": provider,
            "details": details or {},
            "result_status": result_status,
            "error": error,
        }
        clean = self.redactor.redact(record)
        line = json.dumps(clean, ensure_ascii=False, default=str)
        self._append_line(line)
        self.db.execute(
            "INSERT OR IGNORE INTO audit_events (event_id, ts, assessment_id, session_id, execution_id,"
            " node_id, actor_type, actor_id, action, previous_state, new_state, rationale, evidence_ids,"
            " prompt_hash, model, provider, details_json, result_status, error)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (eid, ts, assessment_id, session_id, execution_id, node_id, actor_type, actor_id, action,
             previous_state, new_state, rationale,
             json.dumps(evidence_ids or []), prompt_hash, model, provider, json.dumps(clean.get("details", {})),
             result_status, error),
        )
        return eid

    def _append_line(self, line: str) -> None:
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()

    def read_events(self, assessment_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if assessment_id:
            rows = self.db.query(
                "SELECT details_json, * FROM audit_events WHERE assessment_id = ? ORDER BY seq",
                (assessment_id,))
        else:
            rows = self.db.query("SELECT details_json, * FROM audit_events ORDER BY seq")
        events: List[Dict[str, Any]] = []
        for row in rows:
            detail = json.loads(row["details_json"]) if row["details_json"] else {}
            events.append(_row_to_dict(row, detail))
        return events

    def export(self, destination: Path, assessment_id: Optional[str] = None) -> Dict[str, Any]:
        events = self.read_events(assessment_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8") as fh:
            for event in events:
                fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        return {
            "destination": str(destination),
            "event_count": len(events),
            "assessment_id": assessment_id,
        }


def _row_to_dict(row: Any, detail: Dict[str, Any]) -> Dict[str, Any]:
    base = {k: row[k] for k in row.keys() if k != "details_json"}
    base["details"] = detail
    record = {
        "event_id": base["event_id"], "ts": base["ts"],
        "assessment_id": base["assessment_id"], "session_id": base["session_id"],
        "execution_id": base["execution_id"], "node_id": base["node_id"],
        "actor_type": base["actor_type"], "actor_id": base["actor_id"],
        "action": base["action"], "previous_state": base["previous_state"],
        "new_state": base["new_state"], "rationale": base["rationale"],
        "evidence_ids": json.loads(base["evidence_ids"]) if base["evidence_ids"] else [],
        "prompt_hash": base["prompt_hash"], "model": base["model"], "provider": base["provider"],
        "details": base["details"], "result_status": base["result_status"], "error": base["error"],
    }
    return record
