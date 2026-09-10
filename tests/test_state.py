from pathlib import Path
import json

import pytest
import yaml

from sassessment.config import load_config
from sassessment.errors import ConfigError
from sassessment.ids import new_id, session_id, evidence_id
from sassessment.state.database import Database, Migrator
from sassessment.state.events import AuditEmitter, Redactor
from sassessment.state.checkpoints import CheckpointManager
from sassessment.state.repository import Repository
from sassessment.workspace.layout import ensure_workspace, find_repo_root

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MIGRATIONS_DIR = _REPO_ROOT / "src" / "sassessment" / "state" / "migrations"
MIGRATIONS = tuple(
    (
        int(p.name.split("__")[0][1:]),
        p.name.split("__", 1)[1].replace(".sql", ""),
        p.read_text(encoding="utf-8"),
    )
    for p in sorted(_MIGRATIONS_DIR.glob("V*.sql"))
)


def build_db(tmp_path: Path):
    db = Database(tmp_path / "state.db")
    repo = Repository(db)
    Migrator(db, MIGRATIONS).apply_all()
    return db, repo


class TestMigrations:
    def test_apply_all_creates_tables(self, tmp_path):
        db, repo = build_db(tmp_path)
        tables = set(db.table_names())
        expected = {
            "assessments", "source_batches", "source_artifacts", "evidence", "sessions",
            "node_states", "executions", "human_requests", "findings", "decisions",
            "assumptions", "risks", "gaps", "checkpoints", "audit_events", "data_objects",
            "lineage_edges", "meta", "schema_migrations",
        }
        assert expected.issubset(tables)
        db.close()

    def test_idempotent_reapply(self, tmp_path):
        db, repo = build_db(tmp_path)
        migrator = Migrator(db, MIGRATIONS)
        migrator.apply_all()
        assert migrator.apply_all() == []
        assert migrator.current_version() >= 1
        db.close()


class TestRepository:
    def test_assessment_roundtrip(self, tmp_path):
        db, repo = build_db(tmp_path)
        aid = "ASMT-20260910-test0001"
        repo.create_assessment(aid, "Sub A", "subsidiary-a")
        row = repo.get_assessment(aid)
        assert row is not None
        assert row["status"] == "CREATED"
        assert row["current_phase"] == "phase0"
        repo.update_assessment(aid, status="RUNNING", current_phase="phase2")
        assert repo.get_assessment(aid)["status"] == "RUNNING"
        db.close()

    def test_node_state_roundtrip(self, tmp_path):
        db, repo = build_db(tmp_path)
        aid = "ASMT-1"
        repo.create_assessment(aid, "n", "s")
        repo.upsert_node_state(aid, "intake.register", status="SUCCEEDED", attempts=1)
        repo.upsert_node_state(aid, "intake.register", status="WAITING_FOR_INPUT", attempts=2)
        state = repo.get_node_state(aid, "intake.register")
        assert state["status"] == "WAITING_FOR_INPUT"
        assert state["attempts"] == 2
        db.close()

    def test_duplicate_request_not_created(self, tmp_path):
        db, repo = build_db(tmp_path)
        aid = "ASMT-1"
        repo.create_assessment(aid, "n", "s")
        first = repo.create_request(
            "REQ-1", aid, node_id="lineage.dba_wait", phase="phase4", priority="BLOCKING",
            title="t", missing_info="dba_dependencies", reason="r", expected_provider="DBA",
            retrieval_attempted="", accepted_formats="csv", destination_batch="intake/raw/x",
            security_notes="", resume_node="lineage.ingest_dba", query_pack_path="",
            request_doc_path="")
        second = repo.create_request(
            "REQ-2", aid, node_id="lineage.dba_wait", phase="phase4", priority="BLOCKING",
            title="t", missing_info="dba_dependencies", reason="r", expected_provider="DBA",
            retrieval_attempted="", accepted_formats="csv", destination_batch="intake/raw/x",
            security_notes="", resume_node="lineage.ingest_dba", query_pack_path="",
            request_doc_path="")
        assert first is True
        assert second is False
        assert len(repo.list_requests(aid)) == 1
        db.close()

    def test_transaction_rollback_on_error(self, tmp_path):
        db, repo = build_db(tmp_path)
        with __import__("pytest").raises(ValueError):
            with db.transaction() as conn:
                conn.execute("INSERT INTO meta (key, value) VALUES ('k', 'v')")
                raise ValueError("boom")
        assert repo.get_meta("k") is None
        db.close()

    def test_finding_supersede(self, tmp_path):
        db, repo = build_db(tmp_path)
        aid = "ASMT-1"
        repo.create_assessment(aid, "n", "s")
        repo.create_finding("FND-1", aid, statement="P1 has no runtime", category="runtime",
                            confidence="INFERRED", evidence_ids=["EV-1"])
        repo.create_finding("FND-2", aid, statement="P1 confirmed active", category="runtime",
                            confidence="CONFIRMED", evidence_ids=["EV-2"])
        assert repo.supersede_finding("FND-1", "FND-2", "runtime evidence arrived") is True
        assert repo.supersede_finding("FND-1", "FND-2", "again") is False
        active = repo.list_findings(aid)
        assert [f["id"] for f in active] == ["FND-2"]
        all_f = repo.list_findings(aid, include_inactive=True)
        assert len(all_f) == 2
        assert all_f[0]["status"] == "SUPERSEDED"
        db.close()

    def test_data_object_and_lineage_upsert(self, tmp_path):
        db, repo = build_db(tmp_path)
        aid = "ASMT-1"
        repo.create_assessment(aid, "n", "s")
        assert repo.upsert_data_object("DO-1", aid, "table", "CUSTOMER_ADDRESSES") is True
        assert repo.upsert_data_object("DO-2", aid, "table", "CUSTOMER_ADDRESSES") is False
        assert repo.create_lineage_edge("LE-1", aid, source_node="sas:proc:cli_list",
                                        target_node="db:oracle:cust.cust_dq", relationship="reads",
                                        extraction_method="sas-static-analysis",
                                        evidence_ids=["EV-1"], confidence="CONFIRMED") is True
        dup = repo.create_lineage_edge("DO-2", aid, source_node="sas:proc:cli_list",
                                       target_node="db:oracle:cust.cust_dq", relationship="reads",
                                       extraction_method="sas-static-analysis",
                                       evidence_ids=["EV-1"], confidence="CONFIRMED",
                                       validation_status="VALIDATED")
        assert dup is False
        db.close()


class TestEvents:
    def _emitter(self, tmp_path):
        db, repo = build_db(tmp_path)
        redactor = Redactor([r"(?i)password\s*[=:]\s*\S+", r"(?i)secret\s*[=:]\s*\S+"])
        emitter = AuditEmitter(db, tmp_path / "audit" / "events.jsonl", redactor)
        return db, repo, emitter

    def test_emit_creates_jsonl_and_db(self, tmp_path):
        db, repo, emitter = self._emitter(tmp_path)
        eid = emitter.emit(action="test.event", actor_type="human", assessment_id="ASMT-1",
                           previous_state="A", new_state="B", rationale="r")
        assert eid.startswith("EVT-")
        rows = emitter.read_events()
        assert len(rows) == 1
        assert rows[0]["action"] == "test.event"
        lines = (tmp_path / "audit" / "events.jsonl").read_text().strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["event_id"] == eid
        db.close()

    def test_secret_redaction(self, tmp_path):
        db, repo, emitter = self._emitter(tmp_path)
        emitter.emit(action="login", actor_type="human", details={"password": "hunter2", "secret": "abc"},)
        events = emitter.read_events()
        assert events[0]["details"]["password"] == "[REDACTED]"
        assert events[0]["details"]["secret"] == "[REDACTED]"
        raw = (tmp_path / "audit" / "events.jsonl").read_text()
        assert "hunter2" not in raw
        db.close()

    def test_export_consistent(self, tmp_path):
        db, repo, emitter = self._emitter(tmp_path)
        for i in range(3):
            emitter.emit(action=f"ev{i}", actor_type="system", assessment_id="ASMT-1")
        dest = tmp_path / "export" / "audit.jsonl"
        summary = emitter.export(dest)
        assert summary["event_count"] == 3
        reloaded = [json.loads(l) for l in dest.read_text().strip().splitlines()]
        assert [e["action"] for e in reloaded] == ["ev0", "ev1", "ev2"]
        db.close()


class TestCheckpoints:
    def test_create_verify_cycle(self, tmp_path):
        db, repo = build_db(tmp_path)
        layout = ensure_workspace(tmp_path)
        aid = "ASMT-1"
        repo.create_assessment(aid, "Demo", "sub")
        mgr = CheckpointManager(db, repo, layout)
        ckp = mgr.create(aid, "after intake")
        assert ckp.startswith("CKP-")
        assert mgr.verify(ckp) == []
        db.close()

    def test_restore_roundtrip(self, tmp_path):
        db, repo = build_db(tmp_path)
        layout = ensure_workspace(tmp_path)
        aid = "ASMT-1"
        repo.create_assessment(aid, "Demo", "s")
        mgr = CheckpointManager(db, repo, layout)
        ckp = mgr.create(aid, "pre")
        repo.set_meta("will_be_lost", "yes")
        assert repo.get_meta("will_be_lost") == "yes"
        mgr.restore(ckp)
        assert repo.get_meta("will_be_lost") is None
        db.close()

    def test_tampered_manifest_detected(self, tmp_path):
        db, repo = build_db(tmp_path)
        layout = ensure_workspace(tmp_path)
        aid = "ASMT-1"
        repo.create_assessment(aid, "Demo", "s")
        mgr = CheckpointManager(db, repo, layout)
        ckp = mgr.create(aid, "t")
        row = repo.get_checkpoint(ckp)
        manifest_path = Path(row["manifest_path"])
        manifest = yaml.safe_load(manifest_path.read_text())
        manifest["label"] = "tampered"
        manifest_path.write_text(yaml.safe_dump(manifest))
        with __import__("pytest").raises(__import__("sassessment").errors.CheckpointError):
            mgr.verify(ckp)
        db.close()


class TestConfig:
    def test_load_from_repo_root(self, tmp_path):
        cfg = load_config(repo_root=Path(__file__).resolve().parents[1])
        assert cfg.opencode.executable == "opencode"
        assert cfg.limits.max_graph_cycles >= 1

    def test_env_override(self, tmp_path):
        cfg = load_config(repo_root=Path(__file__).resolve().parents[1],
                          env={"SASSESSMENT_MAX_RETRIES": "7", "SASSESSMENT_OPENCODE_MODEL": "x/y"})
        assert cfg.limits.max_retries == 7
        assert cfg.opencode.default_model == "x/y"

    def test_invalid_rejection(self, tmp_path):
        with __import__("pytest").raises(ConfigError):
            load_config(repo_root=Path(__file__).resolve().parents[1],
                        overrides={"max_graph_cycles": 0})


def test_ids_format():
    sid = session_id()
    ev = evidence_id()
    generic = new_id("XX")
    assert sid.startswith("SES-")
    assert ev.startswith("EV-")
    assert generic.startswith("XX-")
    assert len(generic.split("-")) == 3
