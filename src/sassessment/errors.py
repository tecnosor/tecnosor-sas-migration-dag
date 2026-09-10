"""Typed error hierarchy for SASsessment.

All errors carry a machine-readable ``code`` so CLI and audit trails can
classify failures deterministically.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class SASsessmentError(Exception):
    """Base class for all SASsessment errors."""

    code = "SASSESSMENT_ERROR"

    def __init__(self, message: str, *, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: Dict[str, Any] = dict(details or {})

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class ConfigError(SASsessmentError):
    code = "CONFIG_ERROR"


class WorkspaceError(SASsessmentError):
    code = "WORKSPACE_ERROR"


class StateError(SASsessmentError):
    code = "STATE_ERROR"


class GraphError(SASsessmentError):
    code = "GRAPH_ERROR"


class GraphValidationError(GraphError):
    code = "GRAPH_VALIDATION_ERROR"


class UnknownNodeError(GraphError):
    code = "UNKNOWN_NODE_ERROR"


class ConditionError(GraphError):
    code = "CONDITION_ERROR"


class CycleLimitExceededError(GraphError):
    code = "CYCLE_LIMIT_EXCEEDED"


class MissingPrerequisiteError(GraphError):
    code = "MISSING_PREREQUISITE"


class NodeExecutionError(SASsessmentError):
    code = "NODE_EXECUTION_ERROR"


class NodeRegistryError(SASsessmentError):
    code = "NODE_REGISTRY_ERROR"


class HumanRequestError(SASsessmentError):
    code = "HUMAN_REQUEST_ERROR"


class IntakeError(SASsessmentError):
    code = "INTAKE_ERROR"


class UnsafeArchiveError(IntakeError):
    code = "UNSAFE_ARCHIVE"


class PathTraversalError(UnsafeArchiveError):
    code = "PATH_TRAVERSAL"


class SymlinkEscapeError(UnsafeArchiveError):
    code = "SYMLINK_ESCAPE"


class AdapterError(SASsessmentError):
    code = "ADAPTER_ERROR"


class AdapterTimeoutError(AdapterError):
    code = "ADAPTER_TIMEOUT"


class AdapterQuotaLimitError(AdapterError):
    code = "ADAPTER_QUOTA_LIMIT"


class ResultValidationError(AdapterError):
    code = "RESULT_VALIDATION_ERROR"


class CheckpointError(SASsessmentError):
    code = "CHECKPOINT_ERROR"


class CheckpointImmutableError(CheckpointError):
    code = "CHECKPOINT_IMMUTABLE"
