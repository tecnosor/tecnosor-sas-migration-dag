from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from sassessment.errors import ConditionError


@dataclass
class ConditionOutcome:
    name: str
    args: Dict[str, Any]
    result: bool

    def rationale(self) -> str:
        return f"predicate {self.name!r} args={self.args} -> {self.result}"


class PredicateRegistry:
    """Deterministic named predicates evaluated against structured state.

    Graph JSON references predicates by name; the LLM never decides routing.
    Handlers may record their own semantic judgements as decisions/findings,
    but transition evaluation stays deterministic here.
    """

    def __init__(self) -> None:
        self._predicates: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], bool]] = {}
        for name, fn in _BUILTIN_PREDICATES.items():
            self._predicates[name] = fn

    def register(self, name: str, fn: Callable[[Dict[str, Any], Dict[str, Any]], bool]) -> None:
        if name in self._predicates:
            raise ConditionError(f"duplicate predicate: {name!r}")
        self._predicates[name] = fn

    def available(self) -> List[str]:
        return sorted(self._predicates)

    def evaluate(self, condition: Optional[Any], state: Dict[str, Any],
                 extras: Optional[Dict[str, Any]] = None) -> ConditionOutcome:
        if condition is None:
            return ConditionOutcome(name="always", args={}, result=True)
        name = getattr(condition, "name", "always")
        args = dict(getattr(condition, "args", {}) or {})
        fn = self._predicates.get(name)
        if fn is None:
            raise ConditionError(f"unknown predicate: {name!r}")
        try:
            result = bool(fn(state, dict(args, **(extras or {}))))
        except Exception as exc:
            raise ConditionError(
                f"predicate {name!r} raised", details={"predicate": name, "error": str(exc)}) from exc
        return ConditionOutcome(name=name, args=args, result=result)


def _node_status(state: Dict[str, Any], node_id: str) -> Optional[str]:
    node = state.get("nodes", {}).get(node_id)
    return node.get("status") if node else None


def _always(state: Dict[str, Any], args: Dict[str, Any]) -> bool:
    return True


def _never(state: Dict[str, Any], args: Dict[str, Any]) -> bool:
    return False


def _node_succeeded(state: Dict[str, Any], args: Dict[str, Any]) -> bool:
    node_id = str(args.get("node", ""))
    return _node_status(state, node_id) == "SUCCEEDED"


def _node_failed(state: Dict[str, Any], args: Dict[str, Any]) -> bool:
    return _node_status(state, str(args.get("node", ""))) == "FAILED"


def _node_waiting(state: Dict[str, Any], args: Dict[str, Any]) -> bool:
    return _node_status(state, str(args.get("node", ""))) in ("WAITING_FOR_INPUT", "WAITING_FOR_APPROVAL")


def _has_batches(state: Dict[str, Any], args: Dict[str, Any]) -> bool:
    return int(state.get("data_object_count", 0) if False else state.get("batch_count", 0)) > 0


def _phase_at_least(state: Dict[str, Any], args: Dict[str, Any]) -> bool:
    target = str(args.get("phase", ""))
    current = str(state.get("current_phase") or "")
    order = list(args.get("order", ["phase0", "phase1", "phase2", "phase3", "phase4",
                                    "phase5", "phase6", "phase7", "phase8"]))
    if target not in order or current not in order:
        return current == target
    return order.index(current) >= order.index(target)


def _has_open_requests(state: Dict[str, Any], args: Dict[str, Any]) -> bool:
    return int(state.get("open_request_count", 0)) > 0


def _request_resolved(state: Dict[str, Any], args: Dict[str, Any]) -> bool:
    request_id = str(args.get("request", ""))
    resolved = state.get("resolved_requests", [])
    return request_id in resolved


def _flag_enabled(state: Dict[str, Any], args: Dict[str, Any]) -> bool:
    return bool(state.get("flags", {}).get(str(args.get("flag", "")), False))


_BUILTIN_PREDICATES: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], bool]] = {
    "always": _always,
    "never": _never,
    "node_succeeded": _node_succeeded,
    "node_failed": _node_failed,
    "node_waiting": _node_waiting,
    "has_batches": _has_batches,
    "phase_at_least": _phase_at_least,
    "has_open_requests": _has_open_requests,
    "request_resolved": _request_resolved,
    "flag_enabled": _flag_enabled,
}
