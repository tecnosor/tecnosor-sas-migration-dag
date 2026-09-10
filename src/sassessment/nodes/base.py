from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from sassessment.errors import HumanRequestError, NodeExecutionError
from sassessment.ids import decision_id, request_id

if TYPE_CHECKING:
    from sassessment.config import SassessmentConfig
    from sassessment.state.repository import Repository
    from sassessment.state.events import AuditEmitter
    from sassessment.workspace.layout import WorkspaceLayout


@dataclass
class HumanRequestSpec:
    title: str
    missing_info: str
    reason: str
    priority: str = "REQUIRED_FOR_CONFIDENCE"
    expected_provider: str = ""
    retrieval_attempted: str = ""
    accepted_formats: str = ""
    security_notes: str = ""
    resume_node: str = ""
    query_pack: Optional[str] = None


@dataclass
class NodeResult:
    status: str = "success"
    summary: str = ""
    artifacts: List[str] = field(default_factory=list)
    evidence_used: List[str] = field(default_factory=list)
    findings: List[Dict[str, Any]] = field(default_factory=list)
    gaps: List[Dict[str, Any]] = field(default_factory=list)
    requests: List[HumanRequestSpec] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    limitations: List[str] = field(default_factory=list)
    recommended_next_nodes: List[str] = field(default_factory=list)
    confidence: str = "UNKNOWN"
    violations: List[str] = field(default_factory=list)

    VALID_STATUSES = ("success", "failed", "waiting_for_input", "waiting_for_approval", "skipped")

    def validate(self) -> List[str]:
        problems: List[str] = []
        if self.status not in self.VALID_STATUSES:
            problems.append(f"illegal status {self.status!r}")
        if self.confidence not in ("CONFIRMED", "INFERRED", "UNKNOWN"):
            problems.append(f"illegal confidence {self.confidence!r}")
        for ev in self.evidence_used:
            if not isinstance(ev, str) or not ev.strip():
                problems.append(f"invalid evidence reference: {ev!r}")
        return problems


class NodeContext:
    """Per-node execution environment handed to node handlers.

    Handlers may read project state, write analysis artifacts under the
    execution directory, register evidence/findings/decisions, create human
    requests, and record routing decisions. Handlers must never advance the
    graph themselves; they return a NodeResult.
    """

    def __init__(
        self,
        node_id: str,
        execution_id: str,
        attempt: int,
        assessment_id: str,
        session_id: str,
        execution_dir: Path,
        state: Dict[str, Any],
        repo: "Repository",
        audit: "AuditEmitter",
        layout: "WorkspaceLayout",
        config: "SassessmentConfig",
    ) -> None:
        self.node_id = node_id
        self.execution_id = execution_id
        self.attempt = attempt
        self.assessment_id = assessment_id
        self.session_id = session_id
        self.execution_dir = execution_dir
        self.state = state
        self.repo = repo
        self.audit = audit
        self.layout = layout
        self.log_lines: List[str] = []

    def log(self, message: str) -> None:
        self.log_lines.append(str(message))

    def write_artifact(self, name: str, content: str) -> str:
        self.execution_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(name).name
        target = self.execution_dir / safe_name
        target.write_text(content, encoding="utf-8")
        self.log(f"artifact: {safe_name}")
        return str(target)

    def register_evidence(self, kind: str, title: str, *, locator: str = "",
                          sha256: str = "", confidence: str = "CONFIRMED",
                          artifact_id: Optional[str] = None) -> str:
        from sassessment.ids import evidence_id as _ev
        ev = _ev()
        self.repo.create_evidence(ev, self.assessment_id, kind, title,
                                  artifact_id=artifact_id, locator=locator,
                                  sha256=sha256, confidence=confidence)
        self.audit.emit(action="evidence.registered", actor_type="node", actor_id=self.node_id,
                        assessment_id=self.assessment_id, session_id=self.session_id,
                        execution_id=self.execution_id, node_id=self.node_id,
                        evidence_ids=[ev], details={"kind": kind, "title": title})
        self.log(f"evidence {ev}: {title}")
        return ev

    def register_finding(self, statement: str, category: str, *, confidence: str = "INFERRED",
                         evidence_ids: Optional[List[str]] = None, source_locators: Optional[List[str]] = None,
                         extraction_method: str = "", rationale: str = "",
                         scope: str = "", limitations: str = "") -> str:
        from sassessment.ids import finding_id as _fnd
        fid = _fnd()
        self.repo.create_finding(fid, self.assessment_id, statement=statement, category=category,
                                 confidence=confidence, evidence_ids=evidence_ids or [],
                                 source_locators=source_locators, extraction_method=extraction_method,
                                 rationale=rationale, scope=scope, limitations=limitations)
        self.log(f"finding {fid}: {statement[:80]}")
        return fid

    def register_gap(self, description: str, phase: str = "") -> str:
        from sassessment.ids import gap_id as _gap
        gid = _gap()
        self.repo.create_gap(gid, self.assessment_id, description, phase or "")
        self.log(f"gap {gid}: {description[:60]}")
        return gid

    def request_human_input(self, spec: HumanRequestSpec) -> str:
        """Create a persisted human request and flip this node to WAITING_FOR_INPUT."""
        rid = request_id()
        dest_batch = self.layout.intake_raw / f"req-{rid.lower()}"
        dest_batch.mkdir(parents=True, exist_ok=True)
        query_pack_path = ""
        if spec.query_pack:
            qp = dest_batch / "query-pack.sql"
            qp.write_text(spec.query_pack, encoding="utf-8")
            query_pack_path = str(qp)
        request_doc = (
            f"# Request {rid}\n\n"
            f"- Title: {spec.title}\n"
            f"- Priority: {spec.priority}\n"
            f"- Node: {self.node_id}\n"
            f"- Missing information: {spec.missing_info}\n"
            f"- Reason: {spec.reason}\n"
            f"- Expected provider/team: {spec.expected_provider}\n"
            f"- Retrieval already attempted: {spec.retrieval_attempted or 'none'}\n"
            f"- Accepted formats: {spec.accepted_formats}\n"
            f"- Destination batch (place files here): {dest_batch}\n"
            f"- Security notes: {spec.security_notes or 'standard controls'}\n"
            f"- Resume node after resolution: {spec.resume_node}\n\n"
            f"## Deliver the result here\n\n"
            f"`{dest_batch}` as CSV or plain text exports.\n"
        )
        doc_path = dest_batch / "REQUEST.md"
        doc_path.write_text(request_doc, encoding="utf-8")
        created = self.repo.create_request(
            rid, self.assessment_id, node_id=self.node_id, phase=str(self.state.get("current_phase") or ""),
            priority=spec.priority, title=spec.title, missing_info=spec.missing_info,
            reason=spec.reason, expected_provider=spec.expected_provider,
            retrieval_attempted=spec.retrieval_attempted, accepted_formats=spec.accepted_formats,
            destination_batch=str(dest_batch), security_notes=spec.security_notes,
            resume_node=spec.resume_node or self.node_id, query_pack_path=query_pack_path,
            request_doc_path=str(doc_path))
        if not created:
            existing = self.repo.list_requests(self.assessment_id, status="OPEN")
            for row in existing:
                if row["node_id"] == self.node_id and row["missing_info"] == spec.missing_info:
                    return str(row["id"])
            raise HumanRequestError("request not created and no existing open request found")
        self.audit.emit(action="request.created", actor_type="node", actor_id=self.node_id,
                        assessment_id=self.assessment_id, session_id=self.session_id,
                        execution_id=self.execution_id, node_id=self.node_id,
                        new_state=rid, rationale=spec.title,
                        details={"priority": spec.priority, "destination": str(dest_batch)})
        self.log(f"request {rid}: {spec.title}")
        return rid

    def upsert_domain_object(self, object_type: str, name: str, *, schema_name: str = "",
                             evidence_id: str = "") -> str:
        from sassessment.ids import short_token
        normalized = name.strip().upper().replace(" ", "_")
        doc_id = f"DO-{short_token(10)}"
        self.repo.upsert_data_object(doc_id, self.assessment_id, object_type, name,
                                     schema_name=schema_name, normalized_name=normalized,
                                     first_seen_evidence=evidence_id)
        self.log(f"data-object {object_type}:{normalized}")
        return doc_id

    def add_lineage_edge(self, source: str, target: str, relationship: str, *,
                         extraction_method: str, evidence_ids: Optional[List[str]] = None,
                         confidence: str = "INFERRED", validation_status: str = "UNVALIDATED",
                         depth: int = 0, limitations: str = "") -> str:
        from sassessment.ids import short_token
        edge_id = f"LE-{short_token(10)}"
        self.repo.create_lineage_edge(edge_id, self.assessment_id, source_node=source,
                                      target_node=target, relationship=relationship,
                                      extraction_method=extraction_method,
                                      evidence_ids=evidence_ids or [], confidence=confidence,
                                      validation_status=validation_status, depth=depth,
                                      limitations=limitations)
        self.log(f"edge {source} -[{relationship}]-> {target}")
        return edge_id

    def prompt_hash(self, prompt: str) -> str:
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


NodeHandler = Callable[[NodeContext], NodeResult]


class NodeRegistry:
    def __init__(self) -> None:
        self._handlers: Dict[str, NodeHandler] = {}

    def register(self, handler: NodeHandler, names: Optional[List[str]] = None) -> None:
        if names is None:
            names = [getattr(handler, "node_name", handler.__name__.lower())]
        for name in names:
            if name in self._handlers:
                raise NodeExecutionError(f"duplicate handler registration: {name}")
            self._handlers[name] = handler

    def get(self, name: str) -> NodeHandler:
        if name not in self._handlers:
            raise NodeExecutionError(f"no handler registered for {name!r}")
        return self._handlers[name]

    def has(self, name: str) -> bool:
        return name in self._handlers
