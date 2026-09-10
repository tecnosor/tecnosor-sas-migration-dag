import json
from pathlib import Path

from sassessment.config import load_config
from sassessment.demo.nodes import build_registry
from sassessment.errors import AdapterQuotaLimitError
from sassessment.graph.predicates import PredicateRegistry
from sassessment.graph.engine import GraphEngine
from sassessment.opencode_adapter.adapter import MockAdapter, OpenCodeAdapter
from sassessment.state.database import Database, Migrator
from sassessment.state.events import AuditEmitter, Redactor
from sassessment.state.repository import Repository
from sassessment.workspace.layout import ensure_workspace
from sassessment.ids import session_id as new_session_id
from sassessment.graph.model import GraphDef, NodeDef

_REPO_ROOT = Path(__file__).resolve().parents[1]


def build_engine(tmp_path, *, force_mock: bool = True):
    cfg = load_config(repo_root=_REPO_ROOT)
    cfg.database_path = tmp_path / "db-integration.sqlite"
    cfg.opencode.executable = "opencode"
    cfg.opencode.force_mock = force_mock
    migrations = tuple(
        (int(p.name.split("__")[0][1:]), p.name.split("__", 1)[1].replace(".sql", ""),
         p.read_text(encoding="utf-8"))
        for p in sorted((_REPO_ROOT / "src" / "sassessment" / "state" / "migrations").glob("V*.sql"))
    )
    layout = ensure_workspace(tmp_path)
    db = Database(cfg.database_path)
    Migrator(db, migrations).apply_all()
    repo = Repository(db)
    aid = "ASMT-agent-int"
    repo.create_assessment(aid, "agent integration", "sub")
    audit = AuditEmitter(db, layout.audit_log_path(), Redactor([]))
    repo.create_session(new_session_id(), aid)
    node = NodeDef(id="probe_node", type="opencode", phase="phase1", agent="sas-estate-analyst",
                   handler="probe-task")
    graph = GraphDef(graph_id="g-agent-int", version="1", entry="probe_node",
                     nodes={node.id: node}, edges=[])
    graph.validate()
    engine = GraphEngine(cfg, graph, build_registry(), PredicateRegistry(),
                         repo, audit, layout, aid, repo.list_sessions(aid)[0]["id"])
    engine.db = db
    engine.repo_obj = repo
    return engine


class TestAdapterEngineIntegration:
    def test_complete_mock_adapter_to_engine_path(self, tmp_path):
        engine = build_engine(tmp_path)
        engine.config.opencode.force_mock = True
        outcome = engine.run_node("probe_node")
        assert outcome.status == "SUCCEEDED"
        row = engine.repo.get_execution(outcome.execution_id)
        assert row is not None
        assert row["status"] == "SUCCEEDED"
        assert row["opencode_session_id"] and row["opencode_session_id"].startswith("ses_mock")
        assert row["prompt_hash"]
        assert row["model"]
        assert row["exit_code"] == 0
        execution_dir = engine.execution_dir("probe_node", outcome.execution_id)
        invocation_json = Path(str(execution_dir)) / "invocation.json"
        assert invocation_json.is_file(), f"missing {invocation_json}"
        payload = json.loads(invocation_json.read_text())
        assert payload["prompt_hash"] == row["prompt_hash"]
        assert payload["exit_code"] == 0
        assert (Path(str(execution_dir)) / "stdout.log").is_file()
        assert (Path(str(execution_dir)) / "stderr.log").is_file()
        audit_events = engine.audit.read_events(engine.assessment_id)
        assert any(event["action"] == "node.succeeded" for event in audit_events)

    def test_system_prompt_reaches_adapter_argv(self, tmp_path, monkeypatch):
        cfg = build_engine(tmp_path).config
        adapter = OpenCodeAdapter(cfg)
        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            envelope = json.dumps({"node_id": "n", "status": "success", "summary": "s"})
            _ = envelope
            import subprocess as _subprocess
            return _subprocess.CompletedProcess(argv, 0,
                                                stdout='{"node_id":"n","status":"success","summary":"ok"}'.encode("utf-8"),
                                                stderr=b"")

        import subprocess
        monkeypatch.setattr(subprocess, "run", fake_run)
        result = adapter.run(message="do the thing",
                             system_prompt="You are a bounded SASsessment specialist.")
        assert (cfg.opencode.executable, "run") == (result.argv[0], result.argv[1])
        full_message = result.argv[2]
        assert full_message.startswith("You are a bounded SASsessment specialist.") is not None or \
            full_message.startswith("You are a bounded") or "SASsessment specialist" in full_message
        assert "###TASK###" in full_message
        assert "do the thing" in full_message
        assert result.prompt_hash

    def test_quota_reaches_engine_hold(self, tmp_path, monkeypatch):
        import sassessment.opencode_adapter.adapter as adapter_module

        def run_quota(self, **kwargs):
            raise AdapterQuotaLimitError("429 daily limit reached")

        monkeypatch.setattr(adapter_module.OpenCodeAdapter, "run", run_quota)
        engine = build_engine(tmp_path, force_mock=False)
        outcome = engine.run_node("probe_node")
        assert outcome.status == "WAITING_FOR_APPROVAL"


class TestRealOpenCodeSmoke:
    """Real CLI smoke, cheap and gated: set SASSESSMENT_REAL_OPENCODE_SMOKE=1."""

    def test_real_one_word_invocation(self):
        import os
        import pytest
        if os.environ.get("SASSESSMENT_REAL_OPENCODE_SMOKE", "") != "1":
            pytest.skip("real opencode smoke not enabled (SASSESSMENT_REAL_OPENCODE_SMOKE=1)")
        import tempfile
        engine = build_engine(Path(tempfile.mkdtemp()), force_mock=False)
        adapter = OpenCodeAdapter(engine.config)
        conclusion = adapter.run(
            message="Reply with the single word OK. Do nothing else.",
            system_prompt="You are being smoke-tested; reply only with one word.",
            model=engine.config.opencode.default_model,
            timeout_seconds=90,
        )
        assert conclusion.exit_code == 0
        assert conclusion.session_id and conclusion.session_id.startswith("ses_")
