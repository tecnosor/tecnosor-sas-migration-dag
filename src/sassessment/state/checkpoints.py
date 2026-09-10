from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any, Dict, List

import yaml

from sassessment.errors import CheckpointError, CheckpointImmutableError
from sassessment.ids import checkpoint_id, utc_now_iso
from sassessment.state.database import Database
from sassessment.state.repository import Repository
from sassessment.workspace.layout import WorkspaceLayout


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class CheckpointManager:
    """Create, verify and restore immutable checkpoints.

    A checkpoint snapshots the SQLite state and the project-level sidecars into
    ``workspace/checkpoints/<CKP-id>/`` with a hash manifest. Restoring first
    verifies the manifest; any mismatch aborts without touching live state.
    """

    PROTECTED_MEMBERS = (
        "workspace/project",
        "workspace/decisions",
        "workspace/findings",
        "workspace/requests",
        "workspace/evidence",
        "workspace/assumptions",
        "workspace/risks",
        "workspace/gaps",
    )

    def __init__(self, db: Database, repository: Repository, layout: WorkspaceLayout,
                 audit: Any = None) -> None:
        self.db = db
        self.repo = repository
        self.layout = layout
        self.audit = audit

    def create(self, assessment_id: str, label: str) -> str:
        existing = self.repo.list_assessments()
        if not any(str(row["id"]) == assessment_id for row in existing):
            raise CheckpointError(f"unknown assessment: {assessment_id}")

        ckp_id = checkpoint_id()
        target_dir = self.layout.checkpoint_dir(ckp_id)
        target_dir.mkdir(parents=True, exist_ok=False)

        db_snapshot = target_dir / "state.db"
        self.db.backup_to(db_snapshot)

        members: List[Dict[str, Any]] = []
        for rel in self.PROTECTED_MEMBERS:
            member = self.layout.repo_root / rel
            if member.is_dir():
                for file_path in sorted(member.rglob("*")):
                    if file_path.is_file() and ".gitkeep" not in file_path.name:
                        digest = sha256_file(file_path)
                        members.append({
                            "path": str(file_path.relative_to(self.layout.repo_root)),
                            "sha256": digest,
                            "size": file_path.stat().st_size,
                        })

        manifest = {
            "checkpoint_id": ckp_id,
            "assessment_id": assessment_id,
            "label": label,
            "created_at": utc_now_iso(),
            "database": {"path": "state.db", "sha256": sha256_file(db_snapshot)},
            "members": members,
            "immutable": True,
        }
        manifest_path = target_dir / "manifest.yaml"
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
        manifest_sha = sha256_file(manifest_path)

        self.repo.create_checkpoint_record(
            ckp_id, assessment_id, label=label, manifest_path=str(manifest_path),
            db_snapshot_path=str(db_snapshot), manifest_sha256=manifest_sha)

        readme = target_dir / "README.md"
        readme.write_text(
            f"# Checkpoint {ckp_id}\n\n"
            f"- Label: {label}\n- Created: {manifest['created_at']}\n- Immutable: true\n\n"
            "Restoring replaces the live database after hash verification.\n",
            encoding="utf-8")

        if self.audit is not None:
            self.audit.emit(action="checkpoint.created", actor_type="system",
                            assessment_id=assessment_id, node_id=None,
                            new_state=ckp_id, rationale=label,
                            details={"members": len(members)})
        return ckp_id

    def verify(self, ckp_id: str) -> List[str]:
        row = self.repo.get_checkpoint(ckp_id)
        if row is None:
            raise CheckpointError(f"unknown checkpoint: {ckp_id}")
        manifest_path = Path(str(row["manifest_path"]))
        if not manifest_path.is_file():
            raise CheckpointError(f"checkpoint manifest missing: {manifest_path}")
        current_sha = sha256_file(manifest_path)
        if current_sha != str(row["manifest_sha256"]):
            raise CheckpointError("checkpoint manifest was modified after creation")
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        problems: List[str] = []
        db_hash = manifest["database"]["sha256"]
        db_path = manifest_path.parent / manifest["database"]["path"]
        if sha256_file(db_path) != db_hash:
            problems.append("database snapshot hash mismatch")
        for member in manifest.get("members", []):
            member_path = self.layout.repo_root / member["path"]
            if not member_path.is_file():
                problems.append(f"member missing: {member['path']}")
            elif sha256_file(member_path) != member["sha256"]:
                problems.append(f"member hash mismatch: {member['path']}")
        return problems

    def restore(self, ckp_id: str) -> None:
        problems = self.verify(ckp_id)
        if problems:
            raise CheckpointError(
                "checkpoint verification failed; live state untouched",
                details={"problems": problems})
        row = self.repo.get_checkpoint(ckp_id)
        assert row is not None
        snapshot = Path(str(row["db_snapshot_path"]))
        live = self.db.path
        self.db.close()
        shutil.copyfile(snapshot, live)
        for suffix in ("-wal", "-shm"):
            stale = Path(str(live) + suffix)
            if stale.exists():
                stale.unlink()
        self.db.connect()
        if self.audit is not None:
            self.audit.emit(action="checkpoint.restored", actor_type="system",
                            assessment_id=str(row["assessment_id"]), node_id=None,
                            previous_state=str(self.db.path.name), new_state=ckp_id)
