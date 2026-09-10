from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sassessment.errors import GraphValidationError, UnknownNodeError

NODE_TYPES = (
    "system", "human", "deterministic", "opencode", "validation", "checkpoint", "composite",
)


class Condition:
    def __init__(self, name: str, args: Optional[Dict[str, Any]] = None) -> None:
        self.name = name
        self.args = dict(args or {})

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "args": self.args}


@dataclass
class EdgeDef:
    source: str
    target: str
    condition: Optional[Condition] = None
    priority: int = 100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source, "target": self.target,
            "condition": self.condition.to_dict() if self.condition else None,
            "priority": self.priority,
        }


@dataclass
class NodeDef:
    id: str
    type: str
    phase: str = ""
    title: str = ""
    handler: str = ""
    agent: str = ""
    phase_gate: bool = False
    requires: List[str] = field(default_factory=list)
    join: str = "all"
    optional: bool = False
    max_attempts: int = 5
    condition_registry_names: List[str] = field(default_factory=list)
    composite: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "type": self.type, "phase": self.phase, "title": self.title,
            "handler": self.handler, "agent": self.agent, "phase_gate": self.phase_gate,
            "requires": list(self.requires), "max_attempts": self.max_attempts,
            "composite": self.composite,
        }


@dataclass
class GraphDef:
    graph_id: str
    version: str
    entry: str
    nodes: Dict[str, NodeDef]
    edges: List[EdgeDef]
    phases: List[str] = field(default_factory=list)
    max_cycles: int = 25

    def node(self, node_id: str) -> NodeDef:
        if node_id not in self.nodes:
            raise UnknownNodeError(f"unknown node: {node_id}")
        return self.nodes[node_id]

    def outgoing(self, node_id: str) -> List[EdgeDef]:
        edges = [(e.priority, e) for e in self.edges if e.source == node_id]
        return [e for _, e in sorted(edges, key=lambda pair: pair[0])]

    def validate(self) -> None:
        problems: List[str] = []
        if not self.node_ids_valid():
            problems.append("node ids must be unique and non-empty")
        if len(self.nodes) == 0:
            problems.append("graph has no nodes")
        if self.entry not in self.nodes:
            problems.append(f"entry node missing: {self.entry}")
        for edge in self.edges:
            if edge.source not in self.nodes:
                problems.append(f"edge references unknown source: {edge.source}")
            if edge.target not in self.nodes:
                problems.append(f"edge references unknown target: {edge.target}")
            if edge.source == edge.target:
                problems.append(f"self-loop forbidden at {edge.source}")
        for node_id, node in self.nodes.items():
            if node.type not in NODE_TYPES:
                problems.append(f"node {node_id} illegal type {node.type!r}")
            if node.type in ("deterministic", "opencode") and not node.handler:
                problems.append(f"node {node_id} type {node.type} requires handler")
        reachable = set(self.reachable_nodes())
        unreachable = set(self.nodes) - reachable
        if unreachable:
            problems.append(f"unreachable nodes: {sorted(unreachable)}")
        if problems:
            raise GraphValidationError("graph validation failed", details={"problems": problems})

    def node_ids_valid(self) -> bool:
        if "" in self.nodes:
            return False
        return len(self.nodes) == len(set(self.nodes))

    def reachable_nodes(self) -> List[str]:
        seen: set = set()
        frontier = [self.entry]
        while frontier:
            current = frontier.pop()
            if current in seen:
                continue
            seen.add(current)
            for edge in self.outgoing(current):
                if edge.target not in seen:
                    frontier.append(edge.target)
        return sorted(seen)

    def is_terminal(self, node: NodeDef) -> bool:
        return not bool(self.outgoing(node.id))


def graph_from_json(document: Dict[str, Any]) -> GraphDef:
    if not isinstance(document, dict):
        raise GraphValidationError("graph document must be a JSON object")
    graph_id = str(document.get("id", "unnamed-graph"))
    version = str(document.get("version", "0"))
    entry = str(document.get("entry", ""))
    nodes_raw = document.get("nodes", [])
    edges_raw = document.get("edges", [])
    if not isinstance(nodes_raw, list) or not isinstance(edges_raw, list):
        raise GraphValidationError("'nodes' and 'edges' must be arrays")

    nodes: Dict[str, NodeDef] = {}
    for raw in nodes_raw:
        if not isinstance(raw, dict) or "id" not in raw:
            raise GraphValidationError("each node needs an 'id'")
        node_id = str(raw["id"])
        if node_id in nodes:
            raise GraphValidationError(f"duplicate node id: {node_id}")
        nodes[node_id] = NodeDef(
            id=node_id,
            type=str(raw.get("type", "deterministic")),
            phase=str(raw.get("phase", "")),
            title=str(raw.get("title", "")),
            handler=str(raw.get("handler", "")),
            agent=str(raw.get("agent", "")),
            phase_gate=bool(raw.get("phase_gate", False)),
            requires=[str(req) for req in raw.get("requires", [])],
            join=str(raw.get("join", "all")),
            optional=bool(raw.get("optional", False)),
            max_attempts=int(raw.get("max_attempts", 5)),
            composite=raw.get("composite"),
        )
    doc_id = graph_id

    edges: List[EdgeDef] = []
    for raw in edges_raw:
        if not isinstance(raw, dict) or "source" not in raw or "target" not in raw:
            raise GraphValidationError("edge requires 'source' and 'target'")
        condition_raw = raw.get("condition")
        condition = None
        if isinstance(condition_raw, dict):
            condition = Condition(name=str(condition_raw.get("name", "always")),
                                  args=condition_raw.get("args"))
        edges.append(EdgeDef(
            source=str(raw["source"]), target=str(raw["target"]),
            condition=condition, priority=int(raw.get("priority", 100))))

    graph = GraphDef(
        graph_id=doc_id, version=version, entry=entry, nodes=nodes, edges=edges,
        phases=[str(p) for p in document.get("phases", [])],
        max_cycles=int(document.get("max_cycles", 25)))
    del doc_id
    graph.validate()
    return graph
