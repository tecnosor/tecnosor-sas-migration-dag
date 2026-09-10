from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


def render_prompt(node, context) -> Dict[str, Optional[str]]:
    """Render an agent prompt for a node from templates or a built-in default.

    Look-up order: prompts/<node.handler>.md, prompts/<node.id>.md, built-in default.
    Placeholders: {{node_id}}, {{phase}}, {{title}}, {{state}}.
    """
    repo_root = context.config.repo_root
    template_name = node.handler or node.id
    candidates = [
        repo_root / "prompts" / f"{template_name}.md",
        repo_root / "prompts" / f"{node.id}.md",
    ]
    template = None
    for candidate in candidates:
        if candidate.is_file():
            template = candidate.read_text(encoding="utf-8")
            break
    if template is None:
        template = _DEFAULT_TEMPLATE

    state_json = json.dumps(_slim_state(context.state), sort_keys=True, ensure_ascii=False)
    message = (template
               .replace("{{node_id}}", node.id)
               .replace("{{phase}}", node.phase)
               .replace("{{title}}", node.title or node.id)
               .replace("{{state}}", state_json))
    system = (
        "You are a SASsessment specialist executing ONE bounded graph node.\n"
        "Rules you must follow:\n"
        "1. Ground every statement in the provided state or attached files.\n"
        "2. Never invent evidence ids; only reference ids that exist in state.\n"
        "3. End your reply with a single fenced JSON result envelope using fields:\n"
        "   node_id, status, summary, artifacts, evidence_used, findings, gaps, requests,\n"
        "   metrics, recommended_next_nodes, limitations, confidence.\n"
        "   status in: success|failed|waiting_for_input|waiting_for_approval|skipped\n"
        "   confidence in: CONFIRMED|INFERRED|UNKNOWN.\n"
        "4. You must not modify files outside the execution directory; you cannot advance the graph.\n"
    )
    return {"message": message, "system": system}


def _slim_state(state: Dict[str, Any]) -> Dict[str, Any]:
    slim = {}
    for key, value in state.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            slim[key] = value
        elif isinstance(value, dict):
            slim[key] = value
        elif isinstance(value, list) and len(value) <= 200:
            slim[key] = value
    return slim


_DEFAULT_TEMPLATE = """# Node task: {{node_id}} ({{title}})

Phase: {{phase}}

## Current structured state
```json
{{state}}
```

## Your task
Complete the bounded task described in the structured state and project conventions.
Register artifacts/evidence through the documented sidecar conventions, then produce the
final result envelope as instructed.
"""
