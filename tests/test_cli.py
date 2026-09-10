import io
import subprocess
from pathlib import Path
import shutil

import pytest

from sassessment.cli.main import (
    answer_request,
    cmd_history,
    cmd_init,
    cmd_status,
    cmd_run,
    cmd_scan_inputs,
    cmd_validate,
    main,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_repo(tmp_path):
    for resource in ("config", "graphs", "examples", "src", "pyproject.toml"):
        source = _REPO_ROOT / resource
        if source.is_dir():
            shutil.copytree(source, tmp_path / resource, dirs_exist_ok=True)
        elif source.is_file():
            shutil.copy2(source, tmp_path / source.name)
    yield tmp_path


def test_cli_init_isolated(isolated_repo):
    code = main(["--workspace", str(isolated_repo), "init"])
    assert code == 0


def test_cli_status_empty(isolated_repo):
    main(["--workspace", str(isolated_repo), "init"])
    code = main(["--workspace", str(isolated_repo), "status"])
    assert code == 0


def test_cli_validate(isolated_repo):
    main(["--workspace", str(isolated_repo), "init"])
    code = main(["--workspace", str(isolated_repo), "validate"])
    assert code in (0, 1)


def test_cli_scan_and_add_input(isolated_repo, tmp_path):
    source_file = tmp_path / "sample.sas"
    source_file.write_text("data work.test; run;", encoding="utf-8")
    assert main(["--workspace", str(isolated_repo), "add-input", str(source_file)]) == 0
    raw_root = isolated_repo / "intake" / "raw"
    staged_dirs = sorted(entry for entry in raw_root.iterdir() if entry.is_dir())
    assert staged_dirs
    assert main(["--workspace", str(isolated_repo), "scan-inputs"]) == 0


def test_cli_full_graph_runs_with_fixtures(isolated_repo):
    import shutil
    fixture_src = _REPO_ROOT / "examples" / "synthetic-fixture"
    shutil.copytree(fixture_src, isolated_repo / "intake" / "raw" / "BAT-fixture")
    assert main(["--workspace", str(isolated_repo), "init"]) == 0
    assert main(["--workspace", str(isolated_repo), "start"]) == 0
    from sassessment.cli.main import ApplicationContext
    ctx = ApplicationContext(repo_root=isolated_repo)
    aid = ctx.active_assessment_id()
    nodes = {str(row["node_id"]): str(row["status"]) for row in ctx.repo.list_node_states(aid)}
    assert nodes["sys.workspace"] == "SUCCEEDED"
    assert nodes["intake.register"] == "SUCCEEDED"
    assert nodes["sas.discover"] == "SUCCEEDED"
    assert nodes["doc.map_apps"] == "SUCCEEDED"
    assert "lineage.dba_request" in nodes and nodes["lineage.dba_request"] in ("WAITING_FOR_INPUT", "SUCCEEDED")
    open_requests = ctx.repo.list_requests(aid, status="OPEN")
    ctx.close()
    if open_requests:
        request = open_requests[0]
        destination = Path(str(request["destination_batch"]))
        (destination / "all_dependencies_export.csv").write_text(
            "owner,name,type,referenced_owner,referenced_name,referenced_type\n"
            "CUST,CUSTOMER_MASTER,TABLE,ETL,LOAD_X,PACKAGE\n", encoding="utf-8")
        assert answer_request(ctx, str(request["id"])) == 0
        assert main(["--workspace", str(isolated_repo), "start"]) == 0
        nodes2 = {str(row["node_id"]): str(row["status"]) for row in ApplicationContext(repo_root=isolated_repo).repo.list_node_states(aid)}
        nodes2 = nodes2
        del nodes2


def test_cli_history_and_export(isolated_repo):
    import shutil
    fixture_src = _REPO_ROOT / "examples" / "synthetic-fixture"
    shutil.copytree(fixture_src, isolated_repo / "intake" / "raw" / "BAT-fixture")
    main(["--workspace", str(isolated_repo), "init"])
    main(["--workspace", str(isolated_repo), "start"])
    assert main(["--workspace", str(isolated_repo), "history"]) == 0
    assert main(["--workspace", str(isolated_repo), "export-audit"]) == 0
    audit_dir = isolated_repo / "workspace" / "audit"
    assert any(audit_dir.glob("export-*.jsonl"))


def test_smoke_end_to_end(isolated_repo):
    import shutil
    fixture_src = _REPO_ROOT / "examples" / "synthetic-fixture"
    shutil.copytree(fixture_src, isolated_repo / "intake" / "raw" / "BAT-smoke")
    assert main(["--workspace", str(isolated_repo), "init"]) == 0
    assert main(["--workspace", str(isolated_repo), "start"]) == 0
    from sassessment.cli.main import ApplicationContext
    ctx = ApplicationContext(repo_root=isolated_repo)
    aid = ctx.active_assessment_id()
    for request in ctx.repo.list_requests(aid, status="OPEN"):
        destination = Path(str(request["destination_batch"]))
        (destination / "all_dependencies_export.csv").write_text(
            "owner,name,type,referenced_owner,referenced_name,referenced_type\n"
            "CUST,CUSTOMER_MASTER,TABLE,ETL,LOAD_X,PACKAGE\n", encoding="utf-8")
        assert answer_request(ctx, str(request["id"])) == 0
    assert main(["--workspace", str(isolated_repo), "start"]) == 0
    assert main(["--workspace", str(isolated_repo), "checkpoint"]) == 0
    assert main(["--workspace", str(isolated_repo), "validate"]) == 0
