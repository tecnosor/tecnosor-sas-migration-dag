from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from sassessment.errors import IntakeError
from sassessment.ids import short_token, utc_now_iso
from sassessment.workspace import layout as layout_module

MEDIA_TYPES: Dict[str, str] = {
    ".sas": "sas-source",
    ".log": "log-text",
    ".txt": "text",
    ".md": "markdown",
    ".csv": "csv",
    ".tsv": "tsv",
    ".sql": "sql-plsql",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".docx": "office-word",
    ".doc": "office-word-legacy",
    ".xlsx": "office-excel",
    ".xls": "office-excel-legacy",
    ".pptx": "office-powerpoint",
    ".pdf": "pdf",
    ".zip": "archive-zip",
    ".tar": "archive-tar",
    ".gz": "archive-gzip",
    ".tgz": "archive-tar-gzip",
    ".tar.gz": "archive-tar-gzip",
    ".dtsx": "datastage-export",
    ".job": "datastage-job",
    ".zipfile": "unknown",
}


def media_type_of(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        return MEDIA_TYPES[".tar.gz"]
    return MEDIA_TYPES.get(path.suffix.lower(), "unknown")


@dataclass
class BatchRegistration:
    batch_id: str
    batch_dir: str
    manifest_path: str
    file_count: int
    duplicate_count: int
    integrity_hash: str


def compute_integrity_hash(entries: List[Dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: str(item["path"])):
        digest.update(str(entry["path"]).encode("utf-8"))
        digest.update(str(entry["sha256"]).encode("utf-8"))
    return digest.hexdigest()


def register_batch(
    repo_root: Path,
    batch_dir: Path,
    repository,
    audit,
    *,
    provider: str = "",
    source_team: str = "",
    environment: str = "",
    authority_level: str = "SUBSIDIARY",
    confidentiality: str = "INTERNAL",
    known_omissions: str = "",
    batch_id: Optional[str] = None,
) -> BatchRegistration:
    """Register a raw batch: hash files, detect duplicates, write manifest, persist."""
    from sassessment.ids import batch_id as new_batch_id

    resolved_root = Path(repo_root).resolve()
    resolved_batch = batch_dir.resolve()
    if resolved_batch != (resolved_root / layout_module.INTAKE_RAW / resolved_batch.name):
        raise IntakeError(
            f"batch must live directly under {layout_module.INTAKE_RAW}/",
            details={"given": str(batch_dir), "expected": str(resolved_root / layout_module.INTAKE_RAW)})

    by_dir = repository.db.query_one(
        "SELECT * FROM source_batches WHERE batch_dir = ?", (str(batch_dir),))
    if by_dir is not None and str(by_dir["integrity_hash"]):
        return BatchRegistration(
            batch_id=str(by_dir["id"]), batch_dir=str(batch_dir),
            manifest_path=str(by_dir["manifest_path"]),
            file_count=0, duplicate_count=0, integrity_hash=str(by_dir["integrity_hash"]))

    raw_files = [path for path in sorted(resolved_batch.rglob("*")) if path.is_file()]
    if not raw_files:
        raise IntakeError(f"batch is empty: {batch_dir}")

    if batch_id is None:
        bid = resolved_batch.name if resolved_batch.name.startswith("BAT-") else new_batch_id(provider or "batch")
    else:
        bid = batch_id

    audit.emit(action="batch.placing", actor_type="system", node_id=None, new_state=bid)
    repository.create_batch(
        bid, str(batch_dir), provider=provider, source_team=source_team,
        environment=environment, authority_level=authority_level,
        confidentiality=confidentiality, manifest_path="", integrity_hash="")

    files: List[Dict[str, object]] = []
    duplicate_count = 0
    for path in raw_files:
        relative = path.resolve().relative_to(resolved_batch)
        sha = _sha256_file(path)
        media = media_type_of(path)
        artifact_id = f"ART-{short_token(10)}"
        is_duplicate = not repository.add_artifact(artifact_id, bid, str(relative), media,
                                                    size_bytes=path.stat().st_size, sha256=sha)
        if is_duplicate:
            duplicate_count += 1
        files.append({
            "path": str(relative), "sha256": sha,
            "size": path.stat().st_size, "media_type": media,
            "artifact_id": artifact_id, "duplicate": is_duplicate,
        })

    integrity = compute_integrity_hash([
        {"path": f["path"], "sha256": f["sha256"]} for f in files
    ])

    manifest = {
        "batch_id": bid,
        "provider": provider,
        "source_team": source_team,
        "environment": environment,
        "delivery_date": utc_now_iso(),
        "authority_level": authority_level,
        "confidentiality": confidentiality,
        "raw_dir": str(batch_dir),
        "integrity_hash": integrity,
        "files": files,
        "duplicate_references": [f["artifact_id"] for f in files if f["duplicate"]],
        "known_omissions": known_omissions,
        "raw_immutable": True,
    }
    manifests_dir = resolved_root / layout_module.INTAKE_MANIFESTS
    manifests_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifests_dir / f"{bid}.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    repository.db.execute(
        "UPDATE source_batches SET manifest_path = ?, integrity_hash = ? WHERE id = ?",
        (str(manifest_path), integrity, bid))
    audit.emit(action="batch.registered", actor_type="system", assessment_id="",
               node_id=None, new_state=bid,
               details={"files": len(files), "duplicates": duplicate_count,
                        "integrity": integrity})
    return BatchRegistration(
        batch_id=bid, batch_dir=str(batch_dir), manifest_path=str(manifest_path),
        file_count=len(files), duplicate_count=duplicate_count, integrity_hash=integrity)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
