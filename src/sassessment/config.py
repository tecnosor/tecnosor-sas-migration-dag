from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from sassessment.errors import ConfigError


@dataclass
class OpenCodeSettings:
    executable: str = "opencode"
    default_model: str = "opencode-go/glm-5.3-flash"
    agents: Dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 600
    max_output_bytes: int = 1048576


@dataclass
class Limits:
    max_retries: int = 2
    max_graph_cycles: int = 25
    max_node_attempts: int = 5
    lineage_max_depth: int = 2
    lineage_max_iterations: int = 3
    evidence_max_bytes: int = 50 * 1024 * 1024
    subprocess_output_max_bytes: int = 1048576


@dataclass
class ConnectorSettings:
    enabled: Dict[str, bool] = field(default_factory=dict)
    approval_policy: str = "explicit"


@dataclass
class SassessmentConfig:
    repo_root: Path
    database_path: Path
    opencode: OpenCodeSettings
    limits: Limits
    connectors: ConnectorSettings
    redaction_patterns: List[str]
    active_assessment: Optional[str] = None
    dry_run: bool = False

    @property
    def graph_path(self) -> Path:
        return self.repo_root / "graphs" / "foundation-graph.json"


_DEFAULT_REDACTION_PATTERNS: List[str] = [
    r"(?i)(password|passwd|pwd)\s*[=:]\s*\S+",
    r"(?i)(api[_-]?key|apikey)\s*[=:]\s*\S+",
    r"(?i)(secret|token|credential)[a-z_]*\s*[=:]\s*\S+",
    r"(?i)bearer\s+[A-Za-z0-9._\-]+",
    r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
]


_ENV_MAP = {
    "SASSESSMENT_DATABASE_PATH": ("database_path", "path"),
    "SASSESSMENT_ACTIVE_ASSESSMENT": ("active_assessment", "str"),
    "SASSESSMENT_OPENCODE_EXECUTABLE": ("opencode.executable", "str"),
    "SASSESSMENT_OPENCODE_MODEL": ("opencode.default_model", "str"),
    "SASSESSMENT_OPENCODE_TIMEOUT_SECONDS": ("opencode.timeout_seconds", "int"),
    "SASSESSMENT_MAX_RETRIES": ("limits.max_retries", "int"),
    "SASSESSMENT_MAX_GRAPH_CYCLES": ("limits.max_graph_cycles", "int"),
    "SASSESSMENT_MAX_NODE_ATTEMPTS": ("limits.max_node_attempts", "int"),
    "SASSESSMENT_LINEAGE_MAX_DEPTH": ("limits.lineage_max_depth", "int"),
    "SASSESSMENT_LINEAGE_MAX_ITERATIONS": ("limits.lineage_max_iterations", "int"),
    "SASSESSMENT_EVIDENCE_MAX_BYTES": ("limits.evidence_max_bytes", "int"),
    "SASSESSMENT_APPROVAL_POLICY": ("connectors.approval_policy", "str"),
    "SASSESSMENT_DRY_RUN": ("dry_run", "bool"),
}


def _set_by_dotted_key(target: Dict[str, Any], key: str, value: Any) -> None:
    parts = key.split(".")
    cursor = target
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value


def _coerce(raw: str, kind: str) -> Any:
    if kind == "int":
        try:
            return int(raw)
        except ValueError as exc:
            raise ConfigError(f"environment value must be an integer: {raw!r}", details={"raw": raw}) from exc
    if kind == "bool":
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if kind == "path":
        return raw
    return raw


def load_config(
    repo_root: Optional[Path] = None,
    overrides: Optional[Dict[str, Any]] = None,
    env: Optional[Dict[str, str]] = None,
) -> SassessmentConfig:
    """Load configuration with precedence: defaults < YAML < env < explicit overrides."""
    root = (repo_root or Path.cwd()).resolve()
    if not (root / "pyproject.toml").is_file():
        parent = root.parent
        if (parent / "pyproject.toml").is_file():
            root = parent
        else:
            raise ConfigError(
                "not a SASsessment repository (no pyproject.toml); run 'sassessment init'",
                details={"cwd": str(root)},
            )

    default_doc = _defaults_document(root)
    env_doc: Dict[str, Any] = {}
    env_map = env if env is not None else dict(os.environ)
    for env_key, (key, kind) in _ENV_MAP.items():
        if env_map.get(env_key):
            _set_by_dotted_key(env_doc, key, _coerce(env_map[env_key], kind))

    merged = _deep_merge(default_doc, env_doc)
    if overrides:
        merged = _deep_merge(merged, _overrides_document(overrides))

    database_path = Path(merged.pop("database_path", "workspace/database/sassessment.db"))
    if not database_path.is_absolute():
        database_path = root / database_path

    config = SassessmentConfig(
        repo_root=root,
        database_path=database_path,
        opencode=OpenCodeSettings(**{k: v for k, v in merged.get("opencode", {}).items()}),
        limits=Limits(**{k: v for k, v in merged.get("limits", {}).items()}),
        connectors=ConnectorSettings(**{k: v for k, v in merged.get("connectors", {}).items()}),
        redaction_patterns=list(merged.get("redaction", {}).get("patterns", _DEFAULT_REDACTION_PATTERNS)),
        active_assessment=merged.get("active_assessment"),
        dry_run=bool(merged.get("dry_run", False)),
    )
    _validate(config)
    return config


def _overrides_document(overrides: Dict[str, Any]) -> Dict[str, Any]:
    doc: Dict[str, Any] = {}
    known = {
        "database_path": ("database_path", "raw"),
        "active_assessment": ("active_assessment", "raw"),
        "default_model": ("opencode.default_model", "raw"),
        "opencode_executable": ("opencode.executable", "raw"),
        "dry_run": ("dry_run", "raw"),
    }
    for key, value in overrides.items():
        if key in known:
            _set_by_dotted_key(doc, known[key][0], value)
        elif key in ("max_retries", "max_graph_cycles", "max_node_attempts", "timeout_seconds"):
            section = "limits" if key != "timeout_seconds" else "opencode"
            _set_by_dotted_key(doc, f"{section}.{key}", value)
        else:
            raise ConfigError(f"unknown configuration override: {key!r}", details={"key": key})
    return doc


def _defaults_document(root: Path) -> Dict[str, Any]:
    config_file = root / "config" / "default.yaml"
    if config_file.is_file():
        with config_file.open("r", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
        if not isinstance(doc, dict):
            raise ConfigError("config/default.yaml must be a mapping")
        return doc
    return {}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _validate(config: SassessmentConfig) -> None:
    problems = []
    if config.limits.max_retries < 0:
        problems.append("limits.max_retries must be >= 0")
    if config.limits.max_graph_cycles < 1:
        problems.append("limits.max_graph_cycles must be >= 1")
    if config.limits.max_node_attempts < 1:
        problems.append("limits.max_node_attempts must be >= 1")
    if config.opencode.timeout_seconds <= 0:
        problems.append("opencode.timeout_seconds must be > 0")
    if config.connectors.approval_policy not in ("explicit", "never"):
        problems.append("connectors.approval_policy must be 'explicit' or 'never'")
    if not config.redaction_patterns:
        problems.append("redaction.patterns must not be empty")
    if problems:
        raise ConfigError("invalid configuration", details={"problems": problems})
