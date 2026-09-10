from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from sassessment.errors import WorkspaceError

INTAKE_RAW = "intake/raw"
INTAKE_STAGED = "intake/staged"
INTAKE_QUARANTINE = "intake/quarantine"
INTAKE_MANIFESTS = "intake/manifests"

WORKSPACE_SUBDIRS = (
    "project",
    "sessions",
    "executions",
    "checkpoints",
    "handoffs",
    "evidence",
    "findings",
    "requests",
    "decisions",
    "assumptions",
    "risks",
    "gaps",
    "backlog",
    "plans",
    "audit",
    "database",
)

ANALYSIS_SUBDIRS = (
    "normalized",
    "inventory",
    "runtime",
    "lineage",
    "scoring",
    "recommendations",
    "quality",
)

DELIVERABLES_SUBDIRS = ("draft", "review", "validated", "final")

TOP_LEVEL_DIRS = ("config", "graphs", "prompts", "templates", "schemas", "agents", "skills", "tools", "docs")


class WorkspaceLayout:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.intake_raw = repo_root / INTAKE_RAW
        self.intake_staged = repo_root / INTAKE_STAGED
        self.intake_quarantine = repo_root / INTAKE_QUARANTINE
        self.intake_manifests = repo_root / INTAKE_MANIFESTS
        self.workspace = repo_root / "workspace"
        self.workspace_project = self.workspace / "project"
        self.workspace_sessions = self.workspace / "sessions"
        self.workspace_executions = self.workspace / "executions"
        self.workspace_checkpoints = self.workspace / "checkpoints"
        self.workspace_handoffs = self.workspace / "handoffs"
        self.workspace_evidence = self.workspace / "evidence"
        self.workspace_findings = self.workspace / "findings"
        self.workspace_requests = self.workspace / "requests"
        self.workspace_decisions = self.workspace / "decisions"
        self.workspace_assumptions = self.workspace / "assumptions"
        self.workspace_risks = self.workspace / "risks"
        self.workspace_gaps = self.workspace / "gaps"
        self.workspace_backlog = self.workspace / "backlog"
        self.workspace_plans = self.workspace / "plans"
        self.workspace_audit = self.workspace / "audit"
        self.workspace_database = self.workspace / "database"
        self.analysis = repo_root / "analysis"
        self.deliverables = repo_root / "deliverables"

    def requested_subdirs(self) -> Dict[str, List[str]]:
        return {
            "intake": [str(self.intake_raw.parent)],
            "workspace": WORKSPACE_SUBDIRS,
            "analysis": list(ANALYSIS_SUBDIRS),
            "deliverables": list(DELIVERABLES_SUBDIRS),
            "top": list(TOP_LEVEL_DIRS),
        }

    def audit_log_path(self) -> Path:
        return self.workspace_audit / "events.jsonl"

    def database_dir(self) -> Path:
        return self.workspace_database

    def all_member_paths(self) -> List[Path]:
        intake = [self.intake_raw, self.intake_staged, self.intake_quarantine, self.intake_manifests]
        workspace = [self.workspace / name for name in WORKSPACE_SUBDIRS]
        analysis = [self.analysis / name for name in ANALYSIS_SUBDIRS]
        deliverables = [self.deliverables / name for name in DELIVERABLES_SUBDIRS]
        top = [self.repo_root / name for name in TOP_LEVEL_DIRS]
        return intake + workspace + analysis + deliverables + top

    def session_dir(self, session_id: str) -> Path:
        return self.workspace_sessions / session_id

    def execution_dir(self, session_id: str, execution_id: str) -> Path:
        return self.session_dir(session_id) / "executions" / execution_id

    def checkpoint_dir(self, checkpoint_id: str) -> Path:
        return self.workspace_checkpoints / checkpoint_id

    def handoff_path(self, name: str) -> Path:
        return self.workspace_handoffs / name

    def validate(self) -> List[str]:
        problems: List[str] = []
        if not self.repo_root.is_dir():
            problems.append(f"repo root missing: {self.repo_root}")
            return problems
        for path in self.all_member_paths():
            if not path.is_dir():
                problems.append(f"missing directory: {path.relative_to(self.repo_root)}")
        for path in [self.audit_log_path().parent]:
            if not path.is_dir():
                problems.append(f"missing directory: {path.relative_to(self.repo_root)}")
        return problems


def find_repo_root(start: Optional[Path] = None) -> Path:
    """Walk up from ``start`` (default cwd) to the directory containing pyproject.toml."""
    current = (start or Path.cwd()).resolve()
    for candidate in [current] + list(current.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise WorkspaceError(
        "could not locate SASsessment repository root (no pyproject.toml in ancestors)",
        details={"start": str(current)},
    )


def ensure_workspace(repo_root: Optional[Path] = None, create_gitkeeps: bool = True) -> WorkspaceLayout:
    """Create every required workspace directory; idempotent."""
    layout = WorkspaceLayout((repo_root or find_repo_root()).resolve())
    for path in layout.all_member_paths():
        path.mkdir(parents=True, exist_ok=True)
    if create_gitkeeps:
        for path in layout.all_member_paths():
            marker = path / ".gitkeep"
            if not marker.exists() and path.is_dir() and not any(path.iterdir()):
                marker.touch()
    return layout
