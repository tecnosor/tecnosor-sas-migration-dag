import json
import subprocess
import sys
from pathlib import Path

import pytest

from sassessment.config import load_config
from sassessment.opencode_adapter.adapter import (
    InvocationResult,
    MockAdapter,
    OpenCodeAdapter,
    create_adapter,
)
from sassessment.opencode_adapter.envelope import extract_envelope, build_result_from_envelope

_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config():
    cfg = load_config(repo_root=_REPO_ROOT)
    return cfg


class TestCapabilityDiscovery:
    def test_real_cli_detected(self, config):
        adapter = OpenCodeAdapter(config)
        assert adapter.available() is True
        version = adapter.version()
        assert version
        parts = version.split(".")
        assert parts[0].isdigit()

    def test_capabilities_report(self, config):
        adapter = OpenCodeAdapter(config)
        caps = adapter.capabilities()
        assert caps["available"] is True
        assert "run" in caps["subcommands"]
        assert caps["supports_agent_flag"] is True
        assert caps["supports_session_continue"] is True


class TestArgvConstruction:
    def test_no_shell_injection_in_argv(self, config, monkeypatch):
        adapter = OpenCodeAdapter(config)
        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            return subprocess.CompletedProcess(argv, 0, stdout=b'{"node_id":"x","status":"success","summary":"ok"}', stderr=b"")

        monkeypatch.setattr(subprocess, "run", fake_run)
        hostile = 'hello"; rm -rf /; printf "pwned'
        adapter.run(message=hostile, agent_name="evidence-curator", model="p/m")
        argv = captured["argv"]
        assert argv[0] == config.opencode.executable
        assert argv[1] == "run"
        assert hostile in argv
        for part in argv:
            assert not part.startswith("--format") or part in ("--format", "json")
        assert "--agent" in argv
        assert "--model" in argv

    def test_session_continue_flags(self, config, monkeypatch):
        adapter = OpenCodeAdapter(config)
        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

        monkeypatch.setattr(subprocess, "run", fake_run)
        adapter.run(message="continue work", session_id="ses_test123", continue_session=True)
        argv = captured["argv"]
        assert "--session" in argv and "ses_test123" in argv


class TestTimeout:
    def test_timeout_produced(self, config, monkeypatch):
        def hanging(argv, **kwargs):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=0.1)

        monkeypatch.setattr(subprocess, "run", hanging)
        adapter = OpenCodeAdapter(config)
        result = adapter.run(message="slow", timeout_seconds=1)
        assert result.timed_out is True
        assert result.exit_code is None


class TestFailures:
    def test_nonzero_exit_captured(self, config, monkeypatch):
        def failer(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 2, stdout=b"", stderr=b"agent error")

        monkeypatch.setattr(subprocess, "run", failer)
        adapter = OpenCodeAdapter(config)
        result = adapter.run(message="whatever")
        assert result.exit_code == 2

    def test_malformed_envelope_rejected(self, config):
        invocation = InvocationResult(
            executable="opencode", argv=[], exit_code=0, stdout="not json at all",
            stderr="", duration_ms=1, session_id=None, prompt_hash="h",
            model=None, provider=None)
        with pytest.raises(Exception):
            extract_envelope(invocation.stdout)

    def test_missing_envelope_with_zero_exit(self, config, monkeypatch):
        def quiet(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout=b"just prose", stderr=b"")

        monkeypatch.setattr(subprocess, "run", quiet)
        adapter = OpenCodeAdapter(config)
        result = adapter.run(message="m")
        assert result.exit_code == 0
        with pytest.raises(Exception):
            extract_envelope(result.stdout)


class TestSessionCapture:
    def test_session_id_extracted(self, config, monkeypatch):
        session_stdout = b'created session ses_abc123XYZ. reply: {"status":"success","summary":"done"}'

        def responder(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout=session_stdout, stderr=b"")

        monkeypatch.setattr(subprocess, "run", responder)
        adapter = OpenCodeAdapter(config)
        result = adapter.run(message="m")
        assert result.session_id and result.session_id.startswith("ses_")


class TestMockAdapter:
    def test_mock_runs_without_cli(self, config):
        config.opencode.executable = "definitely-missing-opencode"
        adapter = create_adapter(config)
        assert adapter.available() is True

    def test_mock_envelope_structure(self, config):
        mock = MockAdapter(config)
        result = mock.run(message="task", agent_name="sas-estate-analyst", model="opencode-go/glm-5.3-flash")
        assert result.exit_code == 0
        envelope = extract_envelope(result.stdout)
        assert envelope.status == "success"
        assert envelope.limitations and "mock" in envelope.limitations[0]

    def test_forced_mock(self, config):
        adapter = create_adapter(config, force_mock=True)
        assert adapter.version() == "mock-0.1.0"


class TestEnvelopeBuilding:
    def _context(self, tmp_path):
        from sassessment.workspace.layout import ensure_workspace
        from sassessment.state.database import Database, Migrator
        from sassessment.state.repository import Repository
        from sassessment.state.events import AuditEmitter, Redactor
        migrations_dir = _REPO_ROOT / "src" / "sassessment" / "state" / "migrations"
        migrations = tuple(
            (int(p.name.split("__")[0][1:]), p.name.split("__", 1)[1].replace(".sql", ""), p.read_text(encoding="utf-8"))
            for p in sorted(migrations_dir.glob("V*.sql"))
        )
        db = Database(tmp_path / "env.db")
        Migrator(db, migrations).apply_all()
        repo = Repository(db)
        repo.create_assessment("ASMT-x", "env test", "s")
        repo.upsert_data_object("DO-x", "ASMT-x", "table", "T")
        return repo

    def test_valid_envelope_builds_node_result(self, tmp_path):
        repo = self._context(tmp_path)
        from sassessment.ids import evidence_id as _ev
        real_id = _ev()
        repo.create_evidence(real_id, "ASMT-x", "analysis", "test evidence")
        from sassessment.config import load_config as _lc
        ctx = type("C", (), {"repo": repo, "config": _lc(repo_root=_REPO_ROOT)})()
        stdout = json.dumps({
            "node_id": "sas.discover", "status": "success",
            "summary": "found processes", "evidence_used": [real_id],
            "confidence": "CONFIRMED",
        })
        invocation = type("I", (), {"exit_code": 0, "stdout": stdout, "stderr": "",
                                    "prompt_hash": "abc", "model": "m", "provider": "p",
                                    "opencode_session_id": "ses_1"})()
        result = build_result_from_envelope(invocation, ctx)
        assert result.summary == "found processes"
        assert result.status == "success"
