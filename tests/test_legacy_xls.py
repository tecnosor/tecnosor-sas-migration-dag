import zipfile
from pathlib import Path

import pytest

from sassessment.errors import IntakeError
from sassessment.intake.legacy_xls import convert_xls_to_xlsx
from sassessment.intake.xlsx_reader import read_xlsx

_REPO_ROOT = Path(__file__).resolve().parents[1]

OLE_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512

STAGED_SHEET_NAME = "Tables"

FAKE_SOFFICE_TEMPLATE = """#!/bin/sh
python3 - "$@" <<'PYEOF'
import os
import shutil
import sys
args = sys.argv
outdir = args[5]
src = args[6]
name = os.path.basename(src).rsplit(".", 1)[0] + ".xlsx"
shutil.copy(os.environ["STAGED_XLSX"], os.path.join(outdir, name))
PYEOF
"""


def build_prebuilt_xlsx(path: Path) -> None:
    import tests.test_inventory as inventory_helpers
    inventory_helpers.build_xlsx(
        path, STAGED_SHEET_NAME,
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>',
        '<row r="2"><c t="s"><v>2</v></c><c t="s"><v>3</v></c></row>')


def test_is_legacy_xls(tmp_path):
    from sassessment.intake.legacy_xls import is_legacy_xls
    legacy = tmp_path / "legacy.xls"
    legacy.write_bytes(OLE_HEADER)
    assert is_legacy_xls(legacy) is True
    modern = tmp_path / "modern.xlsx"
    modern.write_bytes(b"PK\x03\x04 not an xls")
    assert is_legacy_xls(modern) is False


def test_convert_raises_without_converter(tmp_path, monkeypatch):
    import sassessment.intake.legacy_xls as legacy_xls_module
    monkeypatch.setattr(legacy_xls_module, "find_converter", lambda: None)
    legacy = tmp_path / "report.xls"
    legacy.write_bytes(OLE_HEADER)
    with pytest.raises(IntakeError):
        convert_xls_to_xlsx(legacy, tmp_path / "out")


def test_convert_fails_cleanly_when_tool_produces_no_file(tmp_path, monkeypatch):
    import sassessment.intake.legacy_xls as legacy_xls_module
    failing = tmp_path / "failing-converter.sh"
    failing.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    failing.chmod(0o755)
    monkeypatch.setattr(legacy_xls_module, "find_converter", lambda: str(failing))
    legacy = tmp_path / "report.xls"
    legacy.write_bytes(OLE_HEADER)
    with pytest.raises(IntakeError):
        convert_xls_to_xlsx(legacy, tmp_path / "out")


def test_convert_via_fake_soffice(tmp_path, monkeypatch):
    import sassessment.intake.legacy_xls as legacy_xls_module
    staged = tmp_path / "staged.xlsx"
    build_prebuilt_xlsx(staged)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    script = tmp_path / "fake-soffice.sh"
    script.write_text(FAKE_SOFFICE_TEMPLATE, encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("STAGED_XLSX", str(staged))
    monkeypatch.setattr(legacy_xls_module, "find_converter", lambda: str(script))
    legacy = tmp_path / "report.xls"
    legacy.write_bytes(OLE_HEADER)
    produced = legacy_xls_module.convert_xls_to_xlsx(legacy, out_dir)
    assert produced.name == "report.xlsx"
    sheets = read_xlsx(produced)
    assert sheets


def test_full_node_flow_converts_legacy_xls(tmp_path, monkeypatch):
    import sassessment.intake.legacy_xls as legacy_xls_module
    from tests.test_inventory import build_engine
    engine = build_engine(tmp_path, with_batch=False)
    audit = engine.audit
    repo = engine.repo
    from sassessment.intake.registration import register_batch
    layout = engine.layout
    batch_dir = layout.intake_raw / "BAT-legacy"
    batch_dir.mkdir()
    staged_xlsx = tmp_path / "staged.xlsx"
    build_prebuilt_xlsx(staged_xlsx)
    legacy_file = batch_dir / "inventario-legacy.xls"
    legacy_file.write_bytes(OLE_HEADER)
    register_batch(layout.repo_root, batch_dir, repo, audit, batch_id="BAT-legacy")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    script = tmp_path / "fake-soffice.sh"
    script.write_text(FAKE_SOFFICE_TEMPLATE, encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("STAGED_XLSX", str(staged_xlsx))
    monkeypatch.setattr(legacy_xls_module, "find_converter", lambda: str(script))
    outcome = engine.run_node("inventory.extract")
    assert outcome.status == "SUCCEEDED"
    edges = repo.list_lineage_edges(engine.assessment_id)
    assert edges, "ownership edges expected from the converted inventory"
