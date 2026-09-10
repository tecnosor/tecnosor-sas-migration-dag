from pathlib import Path

import pytest

from sassessment.config import load_config
from sassessment.errors import AdapterQuotaLimitError
from sassessment.opencode_adapter.adapter import _is_quota_error

_REPO_ROOT = Path(__file__).resolve().parents[1]


def make_config():
    cfg = load_config(repo_root=_REPO_ROOT)
    cfg.opencode.executable = "mock"
    return cfg


class TestQuotaDetection:
    def test_quota_patterns_detected(self):
        assert _is_quota_error("Error: 402 payment required: insufficient credits")
        assert _is_quota_error("daily limit reached, come back tomorrow")
        assert _is_quota_error("rate limit exceeded, please retry later")
        assert _is_quota_error("You've used your quota for this provider")
        assert _is_quota_error("credit balance is too low")

    def test_non_quota_output_not_flagged(self):
        assert not _is_quota_error("agent finished successfully with 4 records")
        assert not _is_quota_error("processed table cust.customer_ext")


def build_engine(tmp_path):
    from sassessment.workspace.layout import ensure_workspace
    from sassessment.state.database import Database, Migrator
    from sassessment.state.repository import Repository
    from sassessment.state.events import AuditEmitter, Redactor
    from sassessment.demo.nodes import build_registry
    from sassessment.graph.predicates import PredicateRegistry
    from sassessment.graph.engine import GraphEngine
    from sassessment.state.repository import Repository as Repo
    from sassessment.ids import session_id as new_session_id
    from sassessment.graph.model import GraphDef, NodeDef

    cfg = load_config(repo_root=_REPO_ROOT)
    cfg.database_path = tmp_path / "resilient.sqlite"
    layout = ensure_workspace(tmp_path)
    migrations = tuple(
        (int(p.name.split("__")[0][1:]), p.name.split("__", 1)[1].replace(".sql", ""), p.read_text(encoding="utf-8"))
        for p in sorted((_REPO_ROOT / "src" / "sassessment" / "state" / "migrations").glob("V*.sql"))
    )
    db = Database(cfg.database_path)
    Migrator(db, migrations).apply_all()
    repo = Repository(db)
    aid = "ASMT-resil"
    repo.create_assessment(aid, "resilience", "sub")
    audit = AuditEmitter(db, layout.audit_log_path(), Redactor([]))
    sid = new_session_id()
    repo.create_session(sid, aid)
    node = NodeDef(id="agent_node", type="opencode", phase="phase1", agent="runtime-analyst",
                   handler="legacy-log-interpret")
    graph = GraphDef(graph_id="g-resil", version="1", entry="agent_node",
                     nodes={node.id: node}, edges=[])
    graph.validate()
    engine = GraphEngine(cfg, graph, build_registry(), PredicateRegistry(),
                         repo, audit, layout, aid, sid)
    engine.db = db
    engine.repo_obj = repo
    return engine


def audit_events(engine):
    return engine.audit.read_events(engine.assessment_id)


class TestQuotaHoldLifecycle:
    def test_quota_error_holds_without_consuming_attempt(self, tmp_path, monkeypatch):
        engine = build_engine(tmp_path)
        import sassessment.opencode_adapter.adapter as adapter_module

        def run_quota(self, **kwargs):
            raise AdapterQuotaLimitError("429 daily limit reached")

        monkeypatch.setattr(adapter_module.OpenCodeAdapter, "run", run_quota)
        outcome = engine.run_node("agent_node")
        assert outcome.status == "WAITING_FOR_APPROVAL"
        state = engine.repo.get_node_state(engine.assessment_id, "agent_node")
        assert str(state["status"]) == "WAITING_FOR_APPROVAL"
        assert int(state["attempts"]) == 0
        events = audit_events(engine)
        assert any(event["action"] == "node.quota_hold" for event in events)

    def test_next_day_unblock_resumes_and_succeeds(self, tmp_path, monkeypatch):
        engine = build_engine(tmp_path)
        import sassessment.opencode_adapter.adapter as adapter_module

        calls = []

        def run_quota(self, **kwargs):
            calls.append("quota")
            raise AdapterQuotaLimitError("429 daily limit reached")

        monkeypatch.setattr(adapter_module.OpenCodeAdapter, "run", run_quota)
        engine.run_node("agent_node")
        assert calls == ["quota"]

        state = engine.repo.get_node_state(engine.assessment_id, "agent_node")
        engine.repo.upsert_node_state(engine.assessment_id, "agent_node", status="READY",
                                      attempts=int(state["attempts"]))
        engine.repo.db.execute(
            "INSERT OR IGNORE INTO audit_events (event_id, ts, actor_type, actor_id, action) "
            "VALUES (?, '2026-09-11T00:00:00Z', 'human', 'test', 'node.unblocked')",
            ("EVT-manual-1",))
        assert audit_events(engine) is not None

        def run_success(self, **kwargs):
            from sassessment.opencode_adapter.adapter import InvocationResult
            calls.append("success")
            envelope = (
                '{"node_id": "agent_node", "status": "success", "summary": "interpreted logs", '
                '"artifacts": [], "evidence_used": [], "findings": [], "gaps": [], "requests": [], '
                '"metrics": {}, "recommended_next_nodes": [], "limitations": ["interpretación legacy"], '
                '"confidence": "INFERRED"}')
            return adapter_module.InvocationResult(
                executable="opencode", argv=[], exit_code=0, stdout=envelope, stderr="",
                duration_ms=5, session_id="ses_daily2", prompt_hash="h",
                model="glm-5.3-flash", provider="opencode-go")

        monkeypatch.setattr(adapter_module.OpenCodeAdapter, "run", run_success)
        outcome = engine.run_node("agent_node")
        assert outcome.status == "SUCCEEDED"
        state = engine.repo.get_node_state(engine.assessment_id, "agent_node")
        assert str(state["status"]) == "SUCCEEDED"
        execution = engine.repo.get_execution(outcome.execution_id)
        assert execution is not None and execution["opencode_session_id"] == "ses_daily2" if execution else False


class TestRecoveryAfterCrash:
    def test_stale_running_recovered_as_ready_without_attempt_loss(self, tmp_path):
        engine = build_engine(tmp_path)
        from sassessment.ids import execution_id as new_execution_id
        execution_id = new_execution_id()
        engine.repo.create_execution(execution_id, engine.session_id, engine.assessment_id,
                                     "agent_node", attempt=3, status="RUNNING")
        engine.repo.upsert_node_state(engine.assessment_id, "agent_node", status="RUNNING",
                                      attempts=2, cycles=0, last_execution_id=execution_id)
        recovered = engine.recover_stale_running()
        assert recovered == ["agent_node"]
        state = engine.repo.get_node_state(engine.assessment_id, "agent_node")
        assert str(state["status"]) == "READY"
        assert int(state["attempts"]) == 2
        row = engine.repo.get_execution(execution_id)
        assert str(row["status"]) == "CANCELLED"
        events = audit_events(engine)
        assert any(event["action"] == "node.recovered" for event in events)

    def test_recovered_node_runs_normally_after_recover(self, tmp_path, monkeypatch):
        engine = build_engine(tmp_path)
        engine.repo.upsert_node_state(engine.assessment_id, "agent_node", status="RUNNING",
                                      attempts=1, cycles=0, last_execution_id=None)
        engine.recover_stale_running()
        import sassessment.opencode_adapter.adapter as adapter_module

        def run_success(self, **kwargs):
            envelope = ('{"node_id": "agent_node", "status": "success", "summary": "post-recovery", '
                        '"evidence_used": [], "confidence": "INFERRED"}')
            from sassessment.opencode_adapter.adapter import InvocationResult
            return InvocationResult(executable="opencode", argv=[], exit_code=0, stdout=envelope,
                                    stderr="", duration_ms=1, session_id=None,
                                    prompt_hash="h", model=None, provider=None)

        monkeypatch.setattr(adapter_module.OpenCodeAdapter, "run", run_success)
        outcome = engine.run_node("agent_node")
        assert outcome.status == "SUCCEEDED"


class TestTransientRetries:
    def test_timeout_retry_then_fail(self, tmp_path, monkeypatch):
        engine = build_engine(tmp_path)
        import sassessment.opencode_adapter.adapter as adapter_module
        from sassessment.opencode_adapter.adapter import InvocationResult

        call_count = []

        def hanging(self, **kwargs):
            call_count.append(1)
            return InvocationResult(
                executable="opencode", argv=[], exit_code=None, stdout="", stderr="timeout",
                duration_ms=1, session_id=None, prompt_hash="h", model=None, provider=None,
                timed_out=True)

        monkeypatch.setattr(adapter_module.OpenCodeAdapter, "run", hanging)
        outcome = engine.run_node("agent_node")
        assert outcome.status == "FAILED"
        assert len(call_count) == 2
        state = engine.repo.get_node_state(engine.assessment_id, "agent_node")
        assert str(state["status"]) == "FAILED"
