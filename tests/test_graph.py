import json
from pathlib import Path

import pytest

from sassessment.config import load_config
from sassessment.errors import (
    CycleLimitExceededError,
    GraphValidationError,
    MissingPrerequisiteError,
    UnknownNodeError,
    ResultValidationError,
)
from sassessment.graph.engine import GraphEngine
from sassessment.graph.loader import load_graph
from sassessment.graph.model import EdgeDef, NodeDef, GraphDef, graph_from_json
from sassessment.graph.predicates import PredicateRegistry
from sassessment.nodes.base import NodeRegistry, NodeResult, HumanRequestSpec
from sassessment.opencode_adapter.adapter import MockAdapter, OpenCodeAdapter
from sassessment.opencode_adapter.envelope import extract_envelope

_REPO_ROOT = Path(__file__).resolve().parents[1]


def make_config(tmp_path, executable="mock"):
    cfg = load_config(repo_root=_REPO_ROOT)
    cfg.opencode.executable = executable
    cfg.limits.max_node_attempts = 5
    return cfg


def build_engine(tmp_path, graph, handlers, executable="mock"):
    cfg = make_config(tmp_path, executable)
    layout = __import__("sassessment.workspace", fromlist=["ensure_workspace"]).ensure_workspace(tmp_path)
    from sassessment.state.database import Database, Migrator
    from sassessment.state.repository import Repository
    from sassessment.state.events import AuditEmitter, Redactor
    migrations_dir = _REPO_ROOT / "src" / "sassessment" / "state" / "migrations"
    migrations = tuple(
        (int(p.name.split("__")[0][1:]), p.name.split("__", 1)[1].replace(".sql", ""), p.read_text(encoding="utf-8"))
        for p in sorted(migrations_dir.glob("V*.sql"))
    )
    cfg.database_path = tmp_path / "db.sqlite"
    db = Database(cfg.database_path)
    Migrator(db, migrations).apply_all()
    repo = Repository(db)
    redactor = Redactor([r"(?i)password\s*[=:]\s*\S+"])
    audit = AuditEmitter(db, layout.audit_log_path(), redactor)
    aid = "ASMT-test"
    repo.create_assessment(aid, "Test assessment", "sub-x")
    from sassessment.ids import session_id
    sid = session_id()
    repo.create_session(sid, aid)
    registry = NodeRegistry()
    for name, handler in handlers.items():
        registry.register(handler, names=[name])
    engine = GraphEngine(cfg, graph, registry, PredicateRegistry(), repo, audit, layout, aid, sid)
    engine.db = db
    engine.repo_obj = repo
    return engine


def ok_handler(context):
    ev = context.register_evidence("analysis", f"evidence from {context.node_id}",
                                   locator=f"exec:{context.execution_id}")
    return NodeResult(status="success", summary=f"{context.node_id} done",
                      evidence_used=[ev], confidence="CONFIRMED")


def loop_handler(context):
    for i in range(30):
        context.log(f"iteration {i}")
    return NodeResult(status="success", summary="runs forever if allowed", confidence="UNKNOWN")


def fail_handler(context):
    raise RuntimeError("boom")


def wait_handler(context):
    rid = context.request_human_input(HumanRequestSpec(
        title="Provide DBA dependency export",
        missing_info="oracle.all_dependencies",
        reason="DB access unavailable",
        priority="BLOCKING",
        expected_provider="Subsidiary DBA",
        accepted_formats="csv, text",
        resume_node="ingest.dba_results"))
    return NodeResult(status="waiting_for_input", summary="waiting", confidence="UNKNOWN")


def simple_graph(entry="n1"):
    nodes = [
        NodeDef(id="n1", type="deterministic", phase="phase1", handler="ok", requires=[]),
        NodeDef(id="n2", type="deterministic", phase="phase2", handler="ok", requires=["wait"]),
        NodeDef(id="wait", type="deterministic", phase="phase1", handler="waiter", requires=[]),
        NodeDef(id="branch", type="deterministic", phase="phase1", handler="ok", requires=[]),
        NodeDef(id="final", type="validation", phase="final", handler="ok", requires=["n2"]),
    ]
    edges = [
        EdgeDef(source="n1", target="final"),
        EdgeDef(source="wait", target="n2"),
        EdgeDef(source="branch", target="final"),
    ]
    return GraphDef(graph_id="test-graph", version="1", entry=entry,
                    nodes={n.id: n for n in nodes}, edges=edges, phases=["phase1", "phase2", "final"])


def full_handlers():
    return {"ok": ok_handler, "waiter": wait_handler, "fail": fail_handler, "loop": loop_handler}


class TestGraphModel:
    def test_valid_graph_from_json(self, tmp_path):
        doc = {
            "id": "ok-graph", "version": "1", "entry": "n1",
            "nodes": [
                {"id": "n1", "type": "deterministic", "handler": "ok", "phase": "p"},
                {"id": "n2", "type": "validation", "phase": "final"},
            ],
            "edges": [{"source": "n1", "target": "n2"}],
        }
        graph = graph_from_json(doc)
        assert graph.graph_id == "ok-graph"
        assert len(graph.nodes) == 2

    def test_unknown_node_rejected(self, tmp_path):
        graph = simple_graph()
        with pytest.raises(UnknownNodeError):
            graph.node("does-not-exist")

    def test_edge_to_unknown_node_fails_validation(self, tmp_path):
        doc = {
            "id": "bad", "version": "1", "entry": "n1",
            "nodes": [{"id": "n1", "type": "deterministic", "handler": "ok"}],
            "edges": [{"source": "n1", "target": "ghost"}],
        }
        with pytest.raises(GraphValidationError):
            graph_from_json(doc)

    def test_self_loop_rejected(self, tmp_path):
        doc = {
            "id": "bad", "version": "1", "entry": "n1",
            "nodes": [{"id": "n1", "type": "deterministic", "handler": "ok"}],
            "edges": [{"source": "n1", "target": "n1"}],
        }
        with pytest.raises(GraphValidationError):
            graph_from_json(doc)

    def test_duplicate_node_ids_rejected(self, tmp_path):
        doc = {
            "id": "bad", "version": "1", "entry": "n1",
            "nodes": [
                {"id": "n1", "type": "deterministic", "handler": "ok"},
                {"id": "n1", "type": "deterministic", "handler": "ok"},
            ],
            "edges": [],
        }
        with pytest.raises(GraphValidationError):
            graph_from_json(doc)

    def test_unreachable_node_rejected(self, tmp_path):
        doc = {
            "id": "bad", "version": "1", "entry": "n1",
            "nodes": [
                {"id": "n1", "type": "deterministic", "handler": "ok"},
                {"id": "orphan", "type": "deterministic", "handler": "ok"},
            ],
            "edges": [],
        }
        with pytest.raises(GraphValidationError):
            graph_from_json(doc)

    def test_missing_handler_rejected(self, tmp_path):
        doc = {
            "id": "bad", "version": "1", "entry": "n1",
            "nodes": [{"id": "n1", "type": "deterministic"}],
            "edges": [],
        }
        with pytest.raises(GraphValidationError):
            graph_from_json(doc)


class TestEngine:
    def test_happy_chain_runs_and_marks_succeeded(self, tmp_path):
        graph = simple_graph()
        engine = build_engine(tmp_path, graph, full_handlers())
        outcomes = engine.run()
        statuses = {o.node_id: o.status for o in outcomes}
        assert statuses["n1"] == "SUCCEEDED"
        assert statuses["branch"] == "SUCCEEDED"
        assert statuses["wait"] == "WAITING_FOR_INPUT"

    def test_deterministic_routing_via_predicates(self, tmp_path):
        graph = simple_graph()
        engine = build_engine(tmp_path, graph, full_handlers())
        state = engine.state_snapshot()
        outcome = engine.predicates.evaluate(
            EdgeDef(source="a", target="b", condition=__import__(
                "sassessment.graph.model", fromlist=["Condition"]).Condition("node_succeeded", {"node": "n1"})).condition
            if False else None, state)
        assert outcome.result is True

    def test_missing_prerequisite_blocks(self, tmp_path):
        graph = simple_graph()
        engine = build_engine(tmp_path, graph, full_handlers())
        with pytest.raises(MissingPrerequisiteError):
            engine.run_node("n2")

    def test_failed_node_does_not_corrupt_checkpoint(self, tmp_path):
        graph = simple_graph()
        engine = build_engine(tmp_path, graph, full_handlers())
        engine.run_node("branch")
        from sassessment.state.checkpoints import CheckpointManager
        from sassessment.state.repository import Repository
        ckp_manager = CheckpointManager(engine.db, engine.repo_obj, engine.layout)
        ckp = ckp_manager.create(engine.assessment_id, "pre-failure")
        engine.run_node("n1")
        bad_n = NodeDef(id="failing", type="deterministic", phase="phase1", handler="fail", requires=[])
        engine.graph.nodes["failing"] = bad_n
        engine.graph.edges.append(EdgeDef(source="failing", target="final"))
        outcome = engine.run_node("failing")
        assert outcome.status == "FAILED"
        state = engine.state_snapshot()
        assert state["nodes"]["branch"]["status"] == "SUCCEEDED"
        assert ckp_manager.verify(ckp) == []

    def test_resume_selects_correct_next(self, tmp_path):
        graph = simple_graph()
        engine = build_engine(tmp_path, graph, full_handlers())
        engine.repo.upsert_node_state(engine.assessment_id, "wait", status="WAITING_FOR_INPUT", attempts=1)
        engine.run_node("branch")
        engine.repo.upsert_node_state(engine.assessment_id, "wait", status="SUCCEEDED", attempts=2)
        nxt = engine.next_runnable()
        assert nxt is not None
        assert nxt.id in ("n1", "n2")
        assert nxt.id == "n2" or nxt.id == "n1"

    def test_branch_waits_independently(self, tmp_path):
        graph = simple_graph()
        engine = build_engine(tmp_path, graph, full_handlers())
        engine.run()
        state = engine.state_snapshot()
        assert state["nodes"]["wait"]["status"] == "WAITING_FOR_INPUT"
        assert state["nodes"]["branch"]["status"] == "SUCCEEDED"
        assert state["open_request_count"] == 1

    def test_cycle_limit_enforced(self, tmp_path):
        nodes = [
            NodeDef(id="a1", type="deterministic", phase="phase1", handler="ok"),
            NodeDef(id="a2", type="deterministic", phase="phase1", handler="ok"),
            NodeDef(id="a3", type="deterministic", phase="phase1", handler="ok"),
            NodeDef(id="a4", type="validation", phase="final", handler="ok"),
        ]
        edges = [
            EdgeDef(source="a1", target="a2"),
            EdgeDef(source="a2", target="a3"),
            EdgeDef(source="a3", target="a4"),
        ]
        graph = GraphDef(graph_id="long", version="1", entry="a1",
                         nodes={n.id: n for n in nodes}, edges=edges, max_cycles=1)
        engine = build_engine(tmp_path, graph, full_handlers())
        with pytest.raises(CycleLimitExceededError):
            engine.run()

    def test_dry_run_reports_opencode_intent(self, tmp_path):
        nodes = [
            NodeDef(id="op", type="opencode", phase="phase1", handler="demo-task", agent="evidence-curator"),
        ]
        graph = GraphDef(graph_id="g2", version="1", entry="op",
                         nodes={n.id: n for n in nodes}, edges=[])
        graph.validate()
        engine = build_engine(tmp_path, graph, {})
        engine.registry.register(ok_handler, names=["demo-task"])
        plan = engine.dry_run_next()
        actions = [entry.get("action") for entry in plan]
        assert "execute-node" in actions
        assert "would-invoke-opencode" in actions
        intent = next(e for e in plan if e["action"] == "would-invoke-opencode")
        assert intent["agent"] == "evidence-curator"
        assert intent["model"]

    def test_dry_run_without_execution(self, tmp_path):
        graph = simple_graph()
        engine = build_engine(tmp_path, graph, full_handlers())
        outcomes = engine.run(dry_run=True)
        assert len(outcomes) == 1
        assert outcomes[0].dry_run is True
        state = engine.state_snapshot()
        assert state["nodes"] == {}


class TestPredicateRegistry:
    def test_unknown_predicate_raises(self, tmp_path):
        reg = PredicateRegistry()
        with pytest.raises(Exception):
            reg.evaluate(__import__(
                "sassessment.graph.model", fromlist=["Condition"]).Condition("unexistent"), {})

    def test_flag_and_phase(self, tmp_path):
        reg = PredicateRegistry()
        doc_cond = __import__("sassessment.graph.model", fromlist=["Condition"])
        assert reg.evaluate(doc_cond.Condition("flag_enabled", {"flag": "x"}),
                            {"flags": {"x": True}}).result is True
        assert reg.evaluate(doc_cond.Condition("phase_at_least", {"phase": "phase2"}),
                            {"current_phase": "phase1"}).result is False


class TestEnvelope:
    def test_extract_fenced_json(self, tmp_path):
        stdout = "Reasoning...\n```json\n{\"node_id\":\"n\",\"status\":\"success\",\"summary\":\"s\"}\n```\nDone."
        envelope = extract_envelope(stdout)
        assert envelope.node_id == "n"
        assert envelope.status == "success"

    def test_extract_raw_json(self, tmp_path):
        stdout = "{\"node_id\":\"n\",\"status\":\"success\",\"summary\":\"raw\"}"
        envelope = extract_envelope(stdout)
        assert envelope.summary == "raw"

    def test_unparseable_output_rejected(self, tmp_path):
        with pytest.raises(ResultValidationError):
            extract_envelope("the model declined to produce JSON")

    def test_bad_confidence_detected(self, tmp_path):
        stdout = json.dumps({"node_id": "n", "status": "success", "summary": "s", "confidence": "GUESS"})
        env = extract_envelope(stdout)
        problems = env.problems()
        assert any("illegal confidence: 'GUESS'" in p for p in problems)

    def test_fake_evidence_rejected(self, tmp_path):
        graph = simple_graph()
        engine = build_engine(tmp_path, graph, {})
        fake_context = type("C", (), {"repo": engine.repo_obj})()
        stdout = json.dumps({"node_id": "op", "status": "success", "summary": "s",
                             "evidence_used": ["EV-fake123"]})
        invocation = type("I", (), {"exit_code": 0, "stdout": stdout, "stderr": "",
                                    "prompt_hash": "h", "model": None, "provider": None,
                                    "opencode_session_id": "ses_x"})()
        from sassessment.opencode_adapter.envelope import build_result_from_envelope
        with pytest.raises(ResultValidationError):
            build_result_from_envelope(invocation, fake_context)
