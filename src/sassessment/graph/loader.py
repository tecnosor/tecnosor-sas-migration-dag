from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Union

from sassessment.errors import GraphValidationError
from sassessment.graph.model import graph_from_json


def load_graph(path: Union[str, Path]) -> "object":
    graph_path = Path(path)
    if not graph_path.is_file():
        raise GraphValidationError(f"graph file not found: {graph_path}")
    try:
        document = json.loads(graph_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GraphValidationError(
            f"graph is not valid JSON: {graph_path}", details={"error": str(exc)}) from exc
    return graph_from_json(document)
