import hashlib
import io
import tarfile
import uuid
import zipfile
from pathlib import Path

import pytest
import yaml

from sassessment.errors import (
    IntakeError,
    PathTraversalError,
    SymlinkEscapeError,
    UnsafeArchiveError,
)
from sassessment.intake.registration import register_batch, BatchRegistration, media_type_of
from sassessment.intake.scanner import scan_batches, files_in_batch
from sassessment.intake.staging import safe_extract, is_archive, scan_staged_for_dangers

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _repo_fixture(tmp_path: Path):
    from sassessment.workspace.layout import ensure_workspace
    layout = ensure_workspace(tmp_path)
    from sassessment.state.database import Database, Migrator
    from sassessment.state.repository import Repository
    from sassessment.state.events import AuditEmitter, Redactor
    migrations_dir = _REPO_ROOT / "src" / "sassessment" / "state" / "migrations"
    migrations = tuple(
        (int(p.name.split("__")[0][1:]), p.name.split("__", 1)[1].replace(".sql", ""), p.read_text(encoding="utf-8"))
        for p in sorted(migrations_dir.glob("V*.sql"))
    )
    db = Database(tmp_path / "intake-db.sqlite")
    Migrator(db, migrations).apply_all()
    repo = Repository(db)
    audit = AuditEmitter(db, layout.audit_log_path(), Redactor([]))
    return layout, repo, audit, db


def _seed_batch(tmp_path: Path, layout):
    batch_dir = layout.intake_raw / "batch-alpha"
    (batch_dir / "nested").mkdir(parents=True, exist_ok=True)
    (batch_dir / "code.sas").write_text("data work.test; run;", encoding="utf-8")
    (batch_dir / "nested" / "notes.md").write_text("# notes", encoding="utf-8")
    return batch_dir


class TestScanner:
    def test_scan_finds_batches(self, tmp_path):
        layout, _repo, _audit, db = _repo_fixture(tmp_path)
        batch_dir = _seed_batch(tmp_path, layout)
        found = scan_batches(tmp_path)
        assert batch_dir in found
        assert files_in_batch(batch_dir)

    def test_scan_fails_without_raw_dir(self, tmp_path):
        (tmp_path / "empty").mkdir()
        with pytest.raises(IntakeError):
            scan_batches(tmp_path / "empty")


class TestRegistration:
    def test_register_batch_roundtrip(self, tmp_path):
        layout, repo, audit, db = _repo_fixture(tmp_path)
        batch_dir = _seed_batch(tmp_path, layout)
        result = register_batch(tmp_path, batch_dir, repo, audit)
        assert result.file_count == 2
        assert result.duplicate_count == 0
        manifest_path = layout.intake_manifests / f"{result.batch_id}.yaml"
        assert manifest_path.is_file()
        manifest = yaml.safe_load(manifest_path.read_text())
        sha = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
        assert sha["code.sas"] == hashlib.sha256(b"data work.test; run;").hexdigest()
        assert manifest["batch_id"] == result.batch_id
        assert manifest["integrity_hash"] == result.integrity_hash
        assert len(repo.list_artifacts(result.batch_id)) == 2

    def test_registration_without_hash_content_succeeds(self, tmp_path):
        layout, repo, audit, db = _repo_fixture(tmp_path)
        batch_dir = _seed_batch(tmp_path, layout)
        result = register_batch(tmp_path, batch_dir, repo, audit)
        assert result.integrity_hash

    def test_re_registration_is_idempotent(self, tmp_path):
        layout, repo, audit, db = _repo_fixture(tmp_path)
        batch_dir = _seed_batch(tmp_path, layout)
        first = register_batch(tmp_path, batch_dir, repo, audit)
        second = register_batch(tmp_path, batch_dir, repo, audit)
        assert first.batch_id == second.batch_id
        assert first.file_count == second.file_count or second.file_count == 0

    def test_raw_files_unchanged_after_registration(self, tmp_path):
        layout, repo, audit, db = _repo_fixture(tmp_path)
        batch_dir = _seed_batch(tmp_path, layout)
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in batch_dir.rglob("*") if p.is_file()}
        register_batch(tmp_path, batch_dir, repo, audit)
        after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in batch_dir.rglob("*") if p.is_file()}
        assert before == after

    def test_duplicate_content_detected(self, tmp_path):
        layout, repo, audit, db = _repo_fixture(tmp_path)
        a = layout.intake_raw / "dup-batch-a"
        b = layout.intake_raw / "dup-batch-b"
        a.mkdir(); b.mkdir()
        (a / "same.sas").write_text("same content", encoding="utf-8")
        (b / "copy.sas").write_text("same content", encoding="utf-8")
        first = register_batch(tmp_path, a, repo, audit,
                               batch_id="BAT-a")
        second = register_batch(tmp_path, b, repo, audit,
                                batch_id="BAT-b")
        reference_a = repo.db.query_one("SELECT * FROM source_artifacts WHERE batch_id = ?", (first.batch_id,))
        reference_b = repo.db.query_one("SELECT * FROM source_artifacts WHERE batch_id = ?", (second.batch_id,))
        assert str(reference_b["duplicate_of"]) == str(reference_a["id"])

    def test_empty_batch_rejected(self, tmp_path):
        layout, repo, audit, db = _repo_fixture(tmp_path)
        empty = layout.intake_raw / "empty-batch"
        empty.mkdir()
        with pytest.raises(IntakeError):
            register_batch(tmp_path, empty, repo, audit)

    def test_registration_refuses_outside_raw(self, tmp_path):
        layout, repo, audit, db = _repo_fixture(tmp_path)
        rogue = tmp_path / "outside"
        rogue.mkdir()
        (rogue / "f.txt").write_text("x", encoding="utf-8")
        with pytest.raises(IntakeError):
            register_batch(tmp_path, rogue, repo, audit)


class TestArchiveStaging:
    def test_zip_roundtrip(self, tmp_path):
        layout, repo, audit, db = _repo_fixture(tmp_path)
        archive = tmp_path / "example.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("dir/file.txt", "content")
            zf.writestr("dir/other.txt", "more")
        result = safe_extract(archive, layout.intake_staged / "example")
        assert result.extracted_files == 2
        assert (layout.intake_staged / "example" / "dir" / "file.txt").is_file()

    def test_zip_path_traversal_rejected(self, tmp_path):
        layout, repo, audit, db = _repo_fixture(tmp_path)
        evil_dir = tmp_path / "evil-raw"; evil_dir.mkdir()
        evil = evil_dir / "evil.zip"
        with zipfile.ZipFile(evil, "w") as zf:
            zf.writestr("../outside.txt", "escape attempt")
        with pytest.raises(PathTraversalError):
            safe_extract(evil, layout.intake_staged / "evil")
        assert not (tmp_path / "outside.txt").exists()

    def test_zip_absolute_member_rejected(self, tmp_path):
        layout, repo, audit, db = _repo_fixture(tmp_path)
        evil_dir = tmp_path / "absolute-raw"; evil_dir.mkdir()
        evil = evil_dir / "absolute.zip"
        dest_abs = layout.intake_staged / "abs"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            info = zipfile.ZipInfo("/tmp/target.txt")
            info.external_attr = (0o644 << 16)
            info.create_system = 3
            zf.writestr(info, "absolute")
        evil.write_bytes(buf.getvalue())
        with pytest.raises(PathTraversalError):
            safe_extract(evil, dest_abs)

    def test_zip_symlink_member_rejected(self, tmp_path):
        layout, repo, audit, db = _repo_fixture(tmp_path)
        evil_dir = tmp_path / "symlink-raw"; evil_dir.mkdir()
        evil = evil_dir / "symlink.zip"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            info = zipfile.ZipInfo("link.txt")
            info.external_attr = (0o120777 << 16)
            info.create_system = 3
            zf.writestr(info, "../../etc/passwd")
        evil.write_bytes(buf.getvalue())
        with pytest.raises(SymlinkEscapeError):
            safe_extract(evil, layout.intake_staged / "symlink")

    def test_encrypted_zip_rejected(self, tmp_path):
        from sassessment.intake.staging import _reject_zip_member, ZIP_ENCRYPTED_FLAG
        info = zipfile.ZipInfo("secret.txt")
        info.flag_bits |= ZIP_ENCRYPTED_FLAG
        with pytest.raises(UnsafeArchiveError):
            _reject_zip_member(info)

    def test_tar_path_traversal_rejected(self, tmp_path):
        layout, repo, audit, db = _repo_fixture(tmp_path)
        evil_dir = tmp_path / "tar-raw"; evil_dir.mkdir()
        evil = evil_dir / "evil.tar"
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            info = tarfile.TarInfo("../escape.txt")
            payload = b"xb"
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))
        evil.write_bytes(buf.getvalue())
        with pytest.raises(PathTraversalError):
            safe_extract(evil, layout.intake_staged / "tar-evil")
        assert not (tmp_path / "escape.txt").exists()

    def test_tar_symlink_rejected(self, tmp_path):
        layout, repo, audit, db = _repo_fixture(tmp_path)
        evil_dir = tmp_path / "tar-link-raw"; evil_dir.mkdir()
        evil = evil_dir / "with-link.tar"
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            info = tarfile.TarInfo("lnk")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tf.addfile(info)
        evil.write_bytes(buf.getvalue())
        with pytest.raises(SymlinkEscapeError):
            safe_extract(evil, layout.intake_staged / "tar-link")

    def test_corrupt_zip_quarantined(self, tmp_path):
        layout, repo, audit, db = _repo_fixture(tmp_path)
        evil_dir = tmp_path / "corrupt-raw"; evil_dir.mkdir()
        evil = evil_dir / "broken.zip"
        evil.write_bytes(b"PK\x03\x04this is not a zip payload")
        with pytest.raises(UnsafeArchiveError):
            safe_extract(evil, layout.intake_staged / "broken",
                         quarantine_dir=layout.intake_quarantine)
        quarantined = list(layout.intake_quarantine.glob("broken.zip*"))
        assert quarantined

    def test_non_archive_rejected(self, tmp_path):
        layout, repo, audit, db = _repo_fixture(tmp_path)
        plain = tmp_path / "doc.pdf"
        plain.write_bytes(b"%PDF-1.4")
        with pytest.raises(IntakeError):
            safe_extract(plain, layout.intake_staged / "not-arch")

    def test_is_archive(self, tmp_path):
        assert is_archive(Path("a.zip"))  is True
        assert is_archive(Path("b.tar.gz")) is True
        assert is_archive(Path("c.sas")) is False
