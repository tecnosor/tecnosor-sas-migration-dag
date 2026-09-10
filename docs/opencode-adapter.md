# OpenCode adapter

The adapter in `src/sassessment/opencode_adapter/` invokes the OpenCode CLI
headlessly to run specialist agent nodes. It captures stdout, stderr, exit
code, duration, and the OpenCode session id.

## Verified OpenCode 1.14.30 behavior

The adapter constructs argv arrays for the `opencode run` command:

```
opencode run [message..] --agent <name> --model <provider/model>
```

Supported flags (verified against the installed CLI):

| Flag | Purpose |
|------|---------|
| `--agent` | select a specialist agent defined in `.opencode/agents/` |
| `--model` | override the model (provider/model format) |
| `-s` / `--session` | continue an existing session by id |
| `-c` / `--continue` | continue the most recent session |
| `--format json` | machine-readable output |
| `--file` | attach a file to the prompt |
| `--dir` | set the working directory |
| `--title` | set the session title |

Additional subcommands discovered:

| Subcommand | Purpose |
|------------|---------|
| `session` | list sessions |
| `export --sanitize` | export session history with redaction |
| `serve` | start the API server |
| `agent` | manage agents |

## argv-only invocation

All subprocess calls use `subprocess.run(argv, shell=False)`. No shell string
concatenation. This prevents command injection through prompt content.

```python
argv = [executable, "run", message]
if agent_name:
    argv.extend(["--agent", agent_name])
if model:
    argv.extend(["--model", model])
if continue_session and session_id:
    argv.extend(["--session", session_id])
proc = subprocess.run(argv, stdout=PIPE, stderr=PIPE,
                      timeout=timeout, check=False, shell=False, cwd=cwd)
```

## Timeouts

The default timeout is 600 seconds (configurable via
`opencode.timeout_seconds` or `SASSESSMENT_OPENCODE_TIMEOUT_SECONDS`).
On timeout, the adapter returns an `InvocationResult` with `timed_out=True`,
empty stdout, and a stderr message indicating the timeout duration.

## Output caps

Captured output is bounded by `opencode.max_output_bytes` (default 1 MiB).
The `InvocationResult` includes a `truncated` flag when output exceeds the
cap. The stdout and stderr SHA-256 hashes are always recorded for integrity.

## Prompt hashing

Every invocation records a SHA-256 hash of the message (first 16 hex chars)
in the `executions.prompt_hash` column and the audit event. This allows
correlating results with the exact prompt that produced them.

## Session capture

The adapter extracts the OpenCode session id from stdout using regex patterns:

```python
re.search(r"ses_[0-9a-zA-Z]+", stdout)
re.search(r"session[\"':=\s]+([0-9a-fA-F-]{16,64})", stdout)
```

The session id is stored in `executions.opencode_session_id` for later
continuation with `--session`.

## Mock adapter

`MockAdapter` in `src/sassessment/opencode_adapter/adapter.py` is an
always-available offline stand-in. It returns canned result envelopes without
invoking any external process. The mock is used when:

- OpenCode is not installed or not on PATH.
- Tests need deterministic results without LLM calls.
- The foundation demo runs in environments without network access.

The mock generates a deterministic session id from the message hash and
returns a valid envelope with `status: "success"`.

## Two execution strategies

1. **Isolated node execution** (default). Each node gets a fresh OpenCode
   session. The adapter invokes `opencode run <message> --agent <name>`
   without session continuation. This provides clean context per node.

2. **Continued specialist session**. When a node needs to continue a previous
   conversation (e.g., iterative refinement), the adapter passes
   `--session <id>` to resume the OpenCode session. The session id is
   captured from the previous invocation.

## Configuration knobs

All settings live under the `opencode` key in `config/default.yaml`:

| Key | Default | Description |
|-----|---------|-------------|
| `executable` | `opencode` | path to the OpenCode CLI binary |
| `default_model` | `opencode-go/glm-5.3-flash` | model for LLM-powered nodes |
| `agents` | (see below) | mapping of role names to agent identifiers |
| `timeout_seconds` | `600` | per-node invocation timeout |
| `max_output_bytes` | `1048576` | cap on captured output per stream |

### Agent mapping

```yaml
opencode:
  agents:
    coordinator: sassessment-coordinator
    evidence_curator: evidence-curator
    sas_analyst: sas-estate-analyst
    runtime_analyst: runtime-analyst
    lineage_analyst: lineage-analyst
    migration_architect: migration-architect
    reviewer: assessment-reviewer
```

These names are resolved in `.opencode/agents/` when the adapter constructs
the `--agent` flag.

## Result envelope

Agent output must contain a fenced JSON block with the result envelope.
The `extract_envelope()` function in
`src/sassessment/opencode_adapter/envelope.py` parses it:

```json
{
  "node_id": "...",
  "status": "success|failed|waiting_for_input|waiting_for_approval|skipped",
  "summary": "...",
  "artifacts": [],
  "evidence_used": [],
  "findings": [],
  "gaps": [],
  "requests": [],
  "decisions": [],
  "metrics": {},
  "recommended_next_nodes": [],
  "limitations": [],
  "confidence": "CONFIRMED|INFERRED|UNKNOWN"
}
```

The envelope is validated by `build_result_from_envelope()` which checks:

- Exit code is 0 or output contains a fenced block.
- All required fields are present and valid.
- Evidence references exist in state (anti-hallucination guard).
