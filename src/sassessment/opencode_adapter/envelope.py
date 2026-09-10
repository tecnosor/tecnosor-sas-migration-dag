from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sassessment.errors import ResultValidationError

REQUIRED_FIELDS = ("status", "summary")

VALID_STATUSES = ("success", "failed", "waiting_for_input", "waiting_for_approval", "skipped")
VALID_CONFIDENCE = ("CONFIRMED", "INFERRED", "UNKNOWN")


@dataclass
class ResultEnvelope:
    node_id: str = ""
    execution_id: str = ""
    status: str = "success"
    summary: str = ""
    artifacts: List[str] = field(default_factory=list)
    evidence_used: List[str] = field(default_factory=list)
    findings: List[Dict[str, Any]] = field(default_factory=list)
    gaps: List[Dict[str, Any]] = field(default_factory=list)
    requests: List[Dict[str, Any]] = field(default_factory=list)
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    recommended_next_nodes: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    confidence: str = "UNKNOWN"

    def problems(self) -> List[str]:
        found: List[str] = []
        if self.status not in VALID_STATUSES:
            found.append(f"illegal status: {self.status!r}")
        if self.confidence not in VALID_CONFIDENCE:
            found.append(f"illegal confidence: {self.confidence!r}")
        if not self.summary:
            found.append("empty summary")
        if not isinstance(self.artifacts, list) or not isinstance(self.evidence_used, list):
            found.append("artifacts and evidence_used must be arrays")
        for ev in self.evidence_used:
            if not isinstance(ev, str) or not ev.strip():
                found.append(f"invalid evidence ref: {ev!r}")
        return found


def extract_envelope(stdout: str) -> ResultEnvelope:
    """Extract a JSON result envelope from raw agent stdout.

    Tries fenced ```json blocks first, then the largest brace-balanced object.
    """
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stdout, re.DOTALL)
    candidates: List[str] = []
    if fenced:
        candidates.append(fenced.group(1))
    deepest = _largest_brace_block(stdout)
    if deepest:
        candidates.append(deepest)
    for text in candidates:
        try:
            document = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(document, dict):
            continue
        envelope = ResultEnvelope(
            node_id=str(document.get("node_id", "")),
            execution_id=str(document.get("execution_id", "")),
            status=str(document.get("status", "success")),
            summary=str(document.get("summary", "")),
            artifacts=list(document.get("artifacts", [])),
            evidence_used=list(document.get("evidence_used", [])),
            findings=list(document.get("findings", [])),
            gaps=list(document.get("gaps", [])),
            requests=list(document.get("requests", [])),
            decisions=list(document.get("decisions", [])),
            metrics=dict(document.get("metrics", {})),
            recommended_next_nodes=list(document.get("recommended_next_nodes", [])),
            limitations=list(document.get("limitations", [])),
            confidence=str(document.get("confidence", "UNKNOWN")),
        )
        return envelope
    raise ResultValidationError(
        "no parseable result envelope in agent output",
        details={"stdout_sha256_len": len(stdout)})


def _largest_brace_block(text: str) -> Optional[str]:
    best: Optional[str] = None
    best_len = 0
    for start in [index for index, ch in enumerate(text) if ch == "{"]:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            ch = text[index]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    block = text[start:index + 1]
                    if len(block) > best_len and '"status"' in block:
                        best = block
                        best_len = len(block)
                    break
    return best


def build_result_from_envelope(invocation, context) -> "NodeResult":
    """Validate an invocation's output envelope and produce a NodeResult.

    Anti-hallucination guard: reported evidence ids must exist in the store,
    otherwise the envelope is rejected rather than silently trusted.
    """
    from sassessment.nodes.base import NodeResult

    if invocation.exit_code not in (0, None) and "```" not in invocation.stdout:
        raise ResultValidationError(
            f"non-zero exit ({invocation.exit_code}) and no structured result")
    envelope = extract_envelope(invocation.stdout or "")
    problems = envelope.problems()
    if problems:
        raise ResultValidationError("envelope invalid", details={"problems": problems})
    unknown_refs = [
        ev for ev in envelope.evidence_used if not context.repo.get_evidence(ev)
    ]
    if unknown_refs:
        raise ResultValidationError(
            "evidence references not found in state (possible hallucination)",
            details={"unknown": unknown_refs})
    result = NodeResult(
        status="success" if envelope.status == "success" else envelope.status,
        summary=envelope.summary,
        artifacts=list(envelope.artifacts),
        evidence_used=list(envelope.evidence_used),
        findings=list(envelope.findings),
        gaps=list(envelope.gaps),
        requests=[_spec_from_dict(req) for req in envelope.requests],
        metrics=dict(envelope.metrics),
        limitations=list(envelope.limitations),
        confidence=envelope.confidence,
    )
    result.validate()
    return result


def _spec_from_dict(document: Dict[str, Any]):
    from sassessment.nodes.base import HumanRequestSpec
    return HumanRequestSpec(
        title=str(document.get("title", "agent request")),
        missing_info=str(document.get("missing_info", "")),
        reason=str(document.get("reason", "")),
        priority=str(document.get("priority", "REQUIRED_FOR_CONFIDENCE")),
        expected_provider=str(document.get("expected_provider", "")),
        accepted_formats=str(document.get("accepted_formats", "csv, text")),
        security_notes=str(document.get("security_notes", "")),
        resume_node=str(document.get("resume_node", "")),
        query_pack=document.get("query_pack"),
    )
