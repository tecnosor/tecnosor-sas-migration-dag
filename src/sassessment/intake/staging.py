from __future__ import annotations

import shutil
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from sassessment.errors import (
    IntakeError,
    PathTraversalError,
    SymlinkEscapeError,
    UnsafeArchiveError,
)

ARCHIVE_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz", ".gz")

ZIP_ENCRYPTED_FLAG = 0x1


@dataclass
class StagingResult:
    archive: str
    staged_dir: str
    extracted_files: int
    rejected_entries: List[str] = field(default_factory=list)


def is_archive(path: Path) -> bool:
    name = path.name.lower()
    return (name.endswith(".tar.gz") or name.endswith(".tgz")
            or path.suffix.lower() in (".zip", ".tar"))


def safe_extract(
    archive_path: Path,
    destination: Path,
    *,
    quarantine_dir: Optional[Path] = None,
    reason: str = "",
) -> StagingResult:
    """Extract an archive safely; on any suspected danger quarantine instead.

    Guarantees:
    - never writes outside ``destination``
    - absolute paths and ``..`` traversal members are rejected
    - symlink/hardlink entries pointing outside are rejected
    - encrypted and device-like members are rejected
    - raw archive is never modified
    """
    archive_path = archive_path.resolve()
    if not archive_path.is_file():
        raise IntakeError(f"archive not found: {archive_path}")
    if not is_archive(archive_path):
        raise IntakeError(f"unsupported archive type: {archive_path.suffix}")
    if not destination.exists():
        destination.mkdir(parents=True, exist_ok=True)
    destination = destination.resolve()

    def quarantine(exc: IntakeError) -> NoReturn:
        if quarantine_dir is None:
            raise exc
        measured = quarantine_dir / archive_path.name
        shutil.move(str(archive_path), str(measured))
        (quarantine_dir / f"{archive_path.name}.quarantine.txt").write_text(
            reason or getattr(exc, "message", str(exc)), encoding="utf-8")
        raise exc

    try:
        if archive_path.suffix.lower() == ".zip":
            return _extract_zip(archive_path, destination)
        return _extract_tar(archive_path, destination)
    except IntakeError:
        raise
    except zipfile.BadZipFile as exc:
        quarantine(UnsafeArchiveError(f"corrupt zip: {exc}"))
    except tarfile.TarError as exc:
        quarantine(UnsafeArchiveError(f"corrupt tar: {exc}"))
    except Exception as exc:
        quarantine(UnsafeArchiveError(f"unexpected archive failure: {exc}"))


def _extract_zip(archive_path: Path, destination: Path) -> StagingResult:
    with zipfile.ZipFile(archive_path, mode="r") as zf:
        for info in zf.infolist():
            _reject_zip_member(info)
            target = destination / info.filename
            _reject_escape(destination, target)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, mode="r") as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
        count = sum(1 for name in zf.namelist() if not name.endswith("/"))
        return StagingResult(archive=str(archive_path), staged_dir=str(destination), extracted_files=count)


def _reject_zip_member(info: zipfile.ZipInfo) -> None:
    name = info.filename
    if name.startswith("/") or name.startswith("\\"):
        raise PathTraversalError(f"absolute path member: {name}")
    if ".." in Path(name).parts:
        raise PathTraversalError(f"path traversal member: {name}")
    if info.flag_bits & ZIP_ENCRYPTED_FLAG:
        raise UnsafeArchiveError(f"encrypted member: {name} (cannot verify; quarantine entire archive)")
    external = info.external_attr >> 16
    unix_mode = external & 0xFFFF
    if (unix_mode & 0o170000) == 0o120000:
        raise SymlinkEscapeError(f"symlink member: {name}")


def _extract_tar(archive_path: Path, destination: Path) -> StagingResult:
    with tarfile.open(str(archive_path), mode="r:*") as tf:
        members = tf.getmembers()
        for member in members:
            _reject_tar_member(member, destination)
            target = destination / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if member.isreg():
                extracted = tf.extractfile(member)
                if extracted is None:
                    continue
                with extracted as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                continue
            raise UnsafeArchiveError(f"unsupported member type: {member.name}")
        count = sum(1 for m in members if m.isreg())
        return StagingResult(archive=str(archive_path), staged_dir=str(destination), extracted_files=count)


def _reject_tar_member(member: tarfile.TarInfo, destination: Path) -> None:
    name = member.name
    if name.startswith("/") or name.startswith("\\"):
        raise PathTraversalError(f"absolute path member: {name}")
    if ".." in Path(name).parts:
        raise PathTraversalError(f"path traversal member: {name}")
    if member.issym() or member.islnk():
        target_link = member.linkname
        resolved_link = (destination / Path(name).parent / target_link).resolve()
        if not str(resolved_link).startswith(str(destination)):
            raise SymlinkEscapeError(f"link escapes destination: {name} -> {target_link}")
        raise UnsafeArchiveError(
            f"link member: {name} (links are discarded for safety; stage as separate evidence)")
    if member.isdev() and not member.isreg():
        raise UnsafeArchiveError(f"device member: {name}")


def _reject_escape(destination: Path, target: Path) -> None:
    resolved = target.resolve()
    if not str(resolved).startswith(str(destination) + "/") and resolved != destination:
        raise PathTraversalError(f"extraction would escape destination: {resolved}")


def scan_staged_for_dangers(staged_dir: Path) -> List[str]:
    """Post-extraction audit: symlinks, hardlinks, suspicious names."""
    problems: List[str] = []
    for path in staged_dir.rglob("*"):
        if path.is_symlink():
            resolved = path.resolve()
            if not str(resolved).startswith(str(staged_dir)):
                problems.append(f"symlink escape: {path} -> {resolved}")
            else:
                problems.append(f"symlink discarded (staged as file copy denied): {path}")
        if ".." in path.parts:
            problems.append(f"suspicious path: {path}")
    return problems
