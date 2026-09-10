from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sassessment.errors import (
    CycleLimitExceededError,
    GraphError,
    MissingPrerequisiteError,
    NodeExecutionError,
    UnknownNodeError,
)
from sassessment.graph.model import Condition, GraphDef, NodeDef
from sassessment.graph.predicates import ConditionOutcome, PredicateRegistry
from sassessment.ids import decision_id as _dec
from sassessment.nodes.base import NodeContext, NodeRegistry, NodeResult

PHASE_ORDER = ["phase0", "phase1", "phase2", "phase3", "phase4",
               "phase5", "phase6", "phase7", "phase8"]

BLOCKED_STATUSES = ("WAITING_FOR_INPUT", "WAITING_FOR_APPROVAL", "CANCELLED", "SKIPPED")


@dataclass
class RunOutcome:
    node_id: str
    execution_id: Optional[str]
    status: str
    summary: str = ""
    fired_edges: List[Tuple[str, str, str]] = field(default_factory=list)
    decision_ids: List[str] = field(default_factory=list)
    dry_run: bool = False
    skipped_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id, "execution_id": self.execution_id, "status": self.status,
            "summary": self.summary, "fired_edges": self.fired_edges,
            "decision_ids": self.decision_ids, "dry_run": self.dry_run,
            "skipped_reason": self.skipped_reason,
        }


class GraphEngine:
    """Executes the assessment graph deterministically.

    Guarantees:
    - a node never runs before its `requires` are SUCCEEDED
    - failures isolate: node goes FAILED, no downstream routing, checkpoint intact
    - waiting branches (WAITING_FOR_INPUT) block only themselves
    - transitions are audited and routed via named predicates only
    - attempts and cycles are hard-bounded
    """

    def __init__(self, config, graph: GraphDef, registry: NodeRegistry,
                 predicates: PredicateRegistry, repo, audit, layout: Path,
                 assessment_id: str, session_id: str) -> None:
        self.config = config
        self.graph = graph
        self.registry = registry
        self.predicates = predicates
        self.repo = repo
        self.audit = audit
        self.layout = layout
        self.assessment_id = assessment_id
        self.session_id = session_id
        self._transitions = 0

    # -- selection -------------------------------------------------------------

    def state_snapshot(self, extras: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        state = self.repo.project_state(self.assessment_id)
        batch_rows = self.repo.list_batches()
        state["batch_count"] = len(batch_rows)
        state["resolved_requests"] = [
            str(r["id"]) for r in self.repo.list_requests(self.assessment_id) if r["status"] == "RESOLVED"
        ]
        if extras:
            state.update(extras)
        return state

    def _prerequisites_met(self, node: NodeDef, state: Dict[str, Any]) -> Tuple[bool, List[str]]:
        missing: List[str] = []
        for req in node.requires:
            if state.get("nodes", {}).get(req, {}).get("status") != "SUCCEEDED":
                missing.append(req)
        return (len(missing) == 0, missing)

    def next_runnable(self, extras: Optional[Dict[str, Any]] = None) -> Optional[NodeDef]:
        state = self.state_snapshot(extras)
        candidates: List[Tuple[int, int, NodeDef]] = []
        for node in self.graph.nodes.values():
            if node.id == self.graph.entry and state.get("nodes", {}).get(node.id, {}).get("status") is None:
                candidates.append((0, 0, node))
                continue
            status = state.get("nodes", {}).get(node.id, {}).get("status")
            if status is None:
                status = "PENDING"
            if status in ("READY", "PENDING"):
                met, _missing = self._prerequisites_met(node, state)
                if met:
                    rank = 0 if status == "READY" else 1
                    phase_rank = PHASE_ORDER.index(node.phase) if node.phase in PHASE_ORDER else 99
                    candidates.append((rank, phase_rank, node))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1], item[2].id))
        return candidates[0][2]

    def blocked_summary(self, extras: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        state = self.state_snapshot(extras)
        blockers: List[Dict[str, Any]] = []
        for node in self.graph.nodes.values():
            status = state.get("nodes", {}).get(node.id, {}).get("status", "PENDING")
            if status == "PENDING":
                met, missing_reqs = self._prerequisites_met(node, state)
                runnable_soon = self._has_successful_runnable_prereq(missing_reqs, state)
                if not met and not runnable_soon:
                    blockers.append({
                        "node": node.id, "reason": "prerequisites-not-reachable",
                        "missing": missing_reqs,
                    })
        open_requests = self.repo.list_requests(self.assessment_id, status="OPEN")
        for request in open_requests:
            blockers.append({
                "node": str(request["node_id"]), "request_id": str(request["id"]),
                "priority": str(request["priority"]),
                "reason": f"waiting for human input: {request['title']}",
                "destination_batch": str(request["destination_batch"]),
            })
        return blockers

    def _has_successful_runnable_prereq(self, missing_reqs: List[str],
                                        state: Dict[str, Any]) -> bool:
        if not missing_reqs:
            return False
        runnable_ids = {node.id for node in [self.next_runnable()] if node}
        if runnable_ids:
            return True
        for req in missing_reqs:
            status = state.get("nodes", {}).get(req, {}).get("status")
            if status == "READY":
                return True
            if status is None and req in self.graph.nodes:
                req_node = self.graph.nodes[req]
                met, deeper = self._prerequisites_met(req_node, state)
                if met:
                    return True
                if self._has_successful_runnable_prereq(deeper, state):
                    return True
        return False

    # -- dry run ----------------------------------------------------------------

    def dry_run_next(self) -> List[Dict[str, Any]]:
        planned: List[Dict[str, Any]] = []
        node = self.next_runnable()
        if node is None:
            planned.append({"action": "none-runnable", "blockers": self.blocked_summary()})
            return planned
        state = self.state_snapshot()
        planned.append({
            "action": "execute-node",
            "node_id": node.id,
            "type": node.type,
            "phase": node.phase,
            "handler": node.handler,
            "agent": node.agent,
        })
        if node.type == "opencode":
            planned.append(self._dry_run_opencode_intent(node))
        consequences = self._dry_run_edges(node, state)
        planned.extend(consequences)
        return planned

    def _dry_run_opencode_intent(self, node: NodeDef) -> Dict[str, Any]:
        from sassessment.opencode_adapter.adapter import OpenCodeAdapter
        from sassessment.opencode_adapter.adapter import create_adapter
        adapter = create_adapter(self.config)
        executable = self.config.opencode.executable
        return {
            "action": "would-invoke-opencode",
            "executable": executable,
            "available": adapter.available(),
            "model": self.config.opencode.default_model,
            "agent": node.agent,
            "note": "argv-array invocation; capture stdout/stderr/exit/duration; subject to timeout "
                    f"{self.config.opencode.timeout_seconds}s",
        }

    def _dry_run_edges(self, node: NodeDef, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        consequences: List[Dict[str, Any]] = []
        for edge in self.graph.outgoing(node.id):
            outcome = self.predicates.evaluate(edge.condition, state)
            consequences.append({
                "action": "would-route" if outcome.result else "skipped-route",
                "edge": f"{edge.source}->{edge.target}",
                "condition": outcome.name,
                "predicate_args": outcome.args,
                "predicate_result": outcome.result,
            })
        if not self.graph.outgoing(node.id):
            consequences.append({"action": "terminal-stop", "node_id": node.id})
        return consequences

    # -- execution ----------------------------------------------------------------

    def run(self, dry_run: bool = False, max_steps: int = 64,
            extras: Optional[Dict[str, Any]] = None) -> List[RunOutcome]:
        outcomes: List[RunOutcome] = []
        for _ in range(max_steps):
            node = self.next_runnable(extras)
            if node is None:
                break
            if dry_run:
                outcomes.append(RunOutcome(node_id=node.id, execution_id=None, status="PLANNED",
                                           dry_run=True,
                                           summary=self._planned_summary(node)))
                return outcomes
            outcome = self.run_node(node.id, extras=extras)
            outcomes.append(outcome)
            self._transitions += 1
            bound = self.graph.max_cycles * max(len(self.graph.nodes), 1)
            if self._transitions >= bound:
                break
        if self._transitions >= self.graph.max_cycles * max(len(self.graph.nodes), 1):
            raise CycleLimitExceededError(
                "graph transition bound reached",
                details={"transitions": self._transitions, "node_count": len(self.graph.nodes)})
        return outcomes

    def _planned_summary(self, node: NodeDef) -> str:
        if node.type == "opencode":
            intent = self._dry_run_opencode_intent(node)
            mode = "available" if intent["available"] else "mock"
            return f"would invoke OpenCode ({mode}) agent={node.agent}"
        return f"would execute {node.type} handler={node.handler!r}"

    def run_node(self, node_id: str, *, extras: Optional[Dict[str, Any]] = None) -> RunOutcome:
        node = self.graph.node(node_id)
        state = self.state_snapshot(extras)
        existing = self.repo.get_node_state(self.assessment_id, node_id)
        status_now = str(existing["status"]) if existing else "PENDING"
        attempts = int(existing["attempts"]) if existing else 0
        if status_now in BLOCKED_STATUSES:
            return RunOutcome(node_id=node_id, execution_id=None, status=status_now,
                              skipped_reason="node currently blocked/waiting")
        if attempts >= min(node.max_attempts, self.config.limits.max_node_attempts):
            raise NodeExecutionError(
                f"node {node_id} reached max attempts ({attempts})",
                details={"node": node_id, "attempts": attempts})

        if status_now == "PENDING" and not self._prerequisites_met(node, state)[0]:
            raise MissingPrerequisiteError(
                f"node {node_id} prerequisites missing",
                details={"missing": self._prerequisites_met(node, state)[1]})

        attempt = attempts + 1
        self._active_agent_meta = {}
        execution_id = self._new_execution_id()
        started = time.monotonic()
        self.repo.create_execution(execution_id, self.session_id, self.assessment_id,
                                   node_id, attempt, status="RUNNING")
        self.repo.upsert_node_state(self.assessment_id, node_id, status="RUNNING",
                                    attempts=attempt)
        self.audit.emit(action="node.started", actor_type="engine", assessment_id=self.assessment_id,
                        session_id=self.session_id, execution_id=execution_id, node_id=node_id,
                        previous_state=status_now, new_state="RUNNING", details={"attempt": attempt})

        try:
            result = self._execute(node, execution_id, attempt)
        except Exception as exc:
            from sassessment.errors import AdapterQuotaLimitError
            if isinstance(exc, AdapterQuotaLimitError):
                duration_ms = int((time.monotonic() - started) * 1000)
                self.repo.finish_execution(execution_id, status="WAITING_FOR_APPROVAL",
                                           duration_ms=duration_ms, error=str(exc))
                self.repo.upsert_node_state(self.assessment_id, node_id,
                                            status="WAITING_FOR_APPROVAL",
                                            attempts=attempts,
                                            last_execution_id=execution_id,
                                            last_error=f"quota hold: {str(exc)[:120]}")
                self.audit.emit(action="node.quota_hold", actor_type="engine",
                                assessment_id=self.assessment_id,
                                session_id=self.session_id, execution_id=execution_id,
                                node_id=node_id, previous_state="RUNNING",
                                new_state="WAITING_FOR_APPROVAL", error=str(exc),
                                details={"attempts_preserved": attempts,
                                         "resume_command": f"sassessment unblock {node_id}"})
                return RunOutcome(node_id=node_id, execution_id=execution_id,
                                  status="WAITING_FOR_APPROVAL",
                                  summary="provider quota/rate limit reached; attempts preserved. "
                                          f"Run 'sassessment unblock {node_id}' once quota resets.")
            duration_ms = int((time.monotonic() - started) * 1000)
            self.repo.finish_execution(execution_id, status="FAILED", duration_ms=duration_ms,
                                       error=str(exc))
            self.repo.upsert_node_state(self.assessment_id, node_id, status="FAILED",
                                        attempts=attempt, last_execution_id=execution_id,
                                        last_error=str(exc))
            self.audit.emit(action="node.failed", actor_type="engine", assessment_id=self.assessment_id,
                            session_id=self.session_id, execution_id=execution_id,
                            node_id=node_id, previous_state="RUNNING", new_state="FAILED",
                            error=str(exc), details={"attempt": attempt})
            return RunOutcome(node_id=node_id, execution_id=execution_id, status="FAILED",
                              summary=str(exc))

        duration_ms = int((time.monotonic() - started) * 1000)
        violations = result.validate()
        if violations and result.status == "success":
            self.repo.finish_execution(execution_id, status="FAILED", duration_ms=duration_ms,
                                       error=json.dumps(violations))
            self.repo.upsert_node_state(self.assessment_id, node_id, status="FAILED",
                                        attempts=attempt, last_execution_id=execution_id,
                                        last_error="invalid result envelope")
            return RunOutcome(node_id=node_id, execution_id=execution_id, status="FAILED",
                              summary="result envelope rejected: " + "; ".join(violations))

        if result.status == "success":
            agent_meta = dict(getattr(self, "_active_agent_meta", {}) or {})
            self.repo.finish_execution(execution_id, status="SUCCEEDED", duration_ms=duration_ms,
                                       prompt_hash=agent_meta.get("prompt_hash"),
                                       model=agent_meta.get("model"),
                                       provider=agent_meta.get("provider"),
                                       opencode_session_id=agent_meta.get("opencode_session_id"),
                                       result_path=str(self.execution_dir(node_id, execution_id)))
            self.repo.upsert_node_state(self.assessment_id, node_id, status="SUCCEEDED",
                                        attempts=attempt, last_execution_id=execution_id)
            self.audit.emit(action="node.succeeded", actor_type="engine",
                            assessment_id=self.assessment_id, session_id=self.session_id,
                            execution_id=execution_id, node_id=node_id,
                            previous_state="RUNNING", new_state="SUCCEEDED",
                            evidence_ids=result.evidence_used, result_status="success",
                            details={"summary": result.summary, "metrics": result.metrics})
            fired, decision_ids = self._route_from(node, result)
            self._maybe_advance_phase(node)
            return RunOutcome(node_id=node_id, execution_id=execution_id, status="SUCCEEDED",
                              summary=result.summary, fired_edges=fired, decision_ids=decision_ids)

        persisted_status = {
            "waiting_for_input": "WAITING_FOR_INPUT",
            "waiting_for_approval": "WAITING_FOR_APPROVAL",
            "skipped": "SKIPPED",
        }.get(result.status, result.status.upper())
        self.repo.finish_execution(execution_id, status=persisted_status, duration_ms=duration_ms)
        self.repo.upsert_node_state(self.assessment_id, node_id, status=persisted_status,
                                    attempts=attempt, last_execution_id=execution_id)
        self.audit.emit(action="node." + persisted_status.lower(), actor_type="engine",
                        assessment_id=self.assessment_id, session_id=self.session_id,
                        execution_id=execution_id, node_id=node_id,
                        previous_state="RUNNING", new_state=persisted_status,
                        rationale=result.summary)
        return RunOutcome(node_id=node_id, execution_id=execution_id, status=persisted_status,
                          summary=result.summary)

    def _new_execution_id(self) -> str:
        from sassessment.ids import execution_id as _exe
        return _exe()

    def execution_dir(self, node_id: str, execution_id: str) -> Path:
        return self.layout.execution_dir(self.session_id, execution_id)

    def _execute(self, node: NodeDef, execution_id: str, attempt: int) -> NodeResult:
        state = self.state_snapshot()
        context = NodeContext(
            node_id=node.id, execution_id=execution_id, attempt=attempt,
            assessment_id=self.assessment_id, session_id=self.session_id,
            execution_dir=self.execution_dir(node.id, execution_id),
            state=state, repo=self.repo, audit=self.audit, layout=self.layout,
            config=self.config)
        if node.type == "opencode":
            return self._execute_opencode(node, context)
        handler = self.registry.get(node.handler or node.id)
        return handler(context)

    # -- agent nodes ----------------------------------------------------------------

    def _execute_opencode(self, node: NodeDef, context: NodeContext) -> NodeResult:
        from sassessment.opencode_adapter.adapter import create_adapter
        from sassessment.opencode_adapter.envelope import build_result_from_envelope
        from sassessment.prompts import render_prompt

        prompt = render_prompt(node, context)
        adapter = create_adapter(self.config)
        invocation = None
        last_invocation = None
        retry_budget = max(self.config.limits.max_retries, 1)
        for attempt_index in range(retry_budget):
            try:
                invocation = adapter.run(
                    message=prompt["message"],
                    system_prompt=prompt.get("system"),
                    agent_name=node.agent or self.config.opencode.agents.get("coordinator", ""),
                    model=self.config.opencode.default_model,
                    timeout_seconds=self.config.opencode.timeout_seconds,
                    cwd=str(self.config.repo_root),
                )
                context.execution_dir.mkdir(parents=True, exist_ok=True)
                (context.execution_dir / "stdout.log").write_text(invocation.stdout, encoding="utf-8")
                (context.execution_dir / "stderr.log").write_text(invocation.stderr, encoding="utf-8")
                (context.execution_dir / "invocation.json").write_text(
                    json.dumps(invocation.to_dict()), encoding="utf-8")
                context.prompt_hash = invocation.prompt_hash
                last_invocation = invocation
                if invocation.timed_out and attempt_index < retry_budget - 1:
                    time.sleep(min(2.0, 0.5 * (attempt_index + 1)))
                    continue
                break
            except Exception as invocation_error:
                from sassessment.errors import AdapterQuotaLimitError
                if isinstance(invocation_error, AdapterQuotaLimitError):
                    raise
                if attempt_index < retry_budget - 1:
                    time.sleep(min(2.0, 0.5 * (attempt_index + 1)))
                    continue
                raise

        if last_invocation is None:
            from sassessment.errors import AdapterError
            raise AdapterError(f"opencode invocation produced no result for node {node.id}")
        invocation = last_invocation

        try:
            result = build_result_from_envelope(invocation, context)
        except Exception as exc:
            self.repo.finish_execution(context.execution_id, status="FAILED", duration_ms=0,
                                       error=f"envelope validation failed: {exc}",
                                       prompt_hash=invocation.prompt_hash,
                                       model=invocation.model, provider=invocation.provider,
                                       opencode_session_id=invocation.session_id)
            raise NodeExecutionError(
                f"agent output rejected for {node.id}: {exc}") from exc
        if invocation.session_id:
            context.log(f"opencode session {invocation.session_id}")
        self._active_agent_meta = {
            "prompt_hash": invocation.prompt_hash,
            "model": invocation.model,
            "provider": invocation.provider,
            "opencode_session_id": invocation.session_id,
        }
        return result

    # -- routing ------------------------------------------------------------------------

    def _route_from(self, node: NodeDef, result: NodeResult) -> Tuple[List[Tuple[str, str, str]], List[str]]:
        state = self.state_snapshot()
        fired: List[Tuple[str, str, str]] = []
        decision_ids: List[str] = []
        for edge in self.graph.outgoing(node.id):
            outcome = self.predicates.evaluate(edge.condition, state)
            rationale = outcome.rationale()
            if outcome.result:
                fired.append((edge.source, edge.target, outcome.name))
                target_state = self.repo.get_node_state(self.assessment_id, edge.target)
                next_status = str(target_state["status"]) if target_state else None
                if next_status == "SUCCEEDED":
                    continue
                if next_status in BLOCKED_STATUSES:
                    continue
                self.repo.upsert_node_state(self.assessment_id, edge.target, status="READY")
            did = _dec()
            self.repo.create_decision(
                did, self.assessment_id, node_id=node.id, execution_id=None,
                inputs={"edge": edge.to_dict(), "state_nodes": state.get("nodes", {})},
                evidence_ids=result.evidence_used, selected_route=edge.target,
                rationale=rationale if outcome.result else f"not taken: {rationale}",
                confidence="CONFIRMED")
            decision_ids.append(did)
        self.audit.emit(action="routing.decided", actor_type="engine",
                        assessment_id=self.assessment_id, session_id=self.session_id,
                        node_id=node.id,
                        previous_state=node.id, new_state=json.dumps([f"{s}->{t}" for s, t, _ in fired]),
                        rationale="deterministic predicate evaluation",
                        details={"fired": fired})
        return fired, decision_ids

    def _maybe_advance_phase(self, node: NodeDef) -> None:
        if not node.phase_gate or node.phase not in PHASE_ORDER:
            return
        index = PHASE_ORDER.index(node.phase)
        if index + 1 < len(PHASE_ORDER):
            self.repo.update_assessment(self.assessment_id, current_phase=PHASE_ORDER[index + 1])
            self.audit.emit(action="phase.advanced", actor_type="engine",
                            assessment_id=self.assessment_id, node_id=node.id,
                            previous_state=node.phase, new_state=PHASE_ORDER[index + 1])

    def recover_stale_running(self) -> List[str]:
        """Normalize nodes left RUNNING after a crash/VM restart.

        Called on engine startup: RUNNING nodes get their state reset to READY
        (attempt not consumed) and their executions are marked CANCELLED so the
        operator is not punished for a VM relaunch.
        """
        rows = self.repo.list_node_states(self.assessment_id)
        recovered: List[str] = []
        for row in rows:
            if str(row["status"]) != "RUNNING":
                continue
            node_id = str(row["node_id"])
            self.repo.upsert_node_state(self.assessment_id, node_id, status="READY",
                                        attempts=int(row["attempts"]),
                                        cycles=int(row["cycles"]),
                                        last_execution_id=None,
                                        last_error=None)
            execution_row = self.repo.get_execution(str(row["last_execution_id"]))
            if execution_row is not None and str(execution_row["status"]) == "RUNNING":
                self.repo.finish_execution(str(row["last_execution_id"]),
                                           status="CANCELLED", duration_ms=None)
            self.audit.emit(action="node.recovered", actor_type="engine",
                            assessment_id=self.assessment_id, node_id=node_id,
                            previous_state="RUNNING", new_state="READY",
                            rationale="stale RUNNING state after restart/crash")
            recovered.append(node_id)
        return recovered

    def is_final(self) -> bool:
        state = self.state_snapshot()
        for node in self.graph.nodes.values():
            if self.graph.is_terminal(node):
                continue
            status = state.get("nodes", {}).get(node.id, {}).get("status", "PENDING")
            if status not in ("SUCCEEDED", "SKIPPED", "CANCELLED"):
                if self._prerequisites_met(node, state)[0]:
                    return False
        return True

    def register_extra_state(self, extras: Dict[str, Any]) -> None:
        self._extras = dict(getattr(self, "_extras", {}) or {})
        self._extras.update(extras)
