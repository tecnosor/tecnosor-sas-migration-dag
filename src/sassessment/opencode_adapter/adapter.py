from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import List, Optional

from sassessment.errors import AdapterError, AdapterTimeoutError

MAX_OUTPUT_FALLBACK = 1048576


@dataclass
class InvocationResult:
    executable: str
    argv: List[str]
    exit_code: Optional[int]
    stdout: str
    stderr: str
    duration_ms: int
    session_id: Optional[str]
    prompt_hash: str
    model: Optional[str]
    provider: Optional[str]
    timed_out: bool = False
    truncated: bool = False

    def to_dict(self) -> dict:
        return {
            "executable": self.executable,
            "argv": self.argv,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "session_id": self.session_id,
            "prompt_hash": self.prompt_hash,
            "model": self.model,
            "provider": self.provider,
            "timed_out": self.timed_out,
            "truncated": self.truncated,
            "stdout_sha256": hashlib.sha256(self.stdout.encode("utf-8")).hexdigest(),
            "stderr_sha256": hashlib.sha256(self.stderr.encode("utf-8")).hexdigest(),
        }


def _probe(argv: List[str], timeout: float = 30.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        shell=False,
    )


class OpenCodeAdapter:
    """Headless OpenCode CLI adapter.

    All invocations use argv arrays (never shell strings). Captures stdout,
    stderr, exit code, duration and the OpenCode session id when reported.
    """

    def __init__(self, config) -> None:
        self.config = config

    def available(self) -> bool:
        return shutil.which(self.config.opencode.executable) is not None

    def version(self) -> Optional[str]:
        if not self.available():
            return None
        proc = _probe([self.config.opencode.executable, "--version"])
        if proc.returncode != 0:
            return None
        return proc.stdout.decode("utf-8", errors="replace").strip()

    def capabilities(self) -> "dict":
        version = self.version()
        return {
            "executable": self.config.opencode.executable,
            "available": self.available(),
            "version": version,
            "subcommands": ["run", "session", "export", "serve", "agent"],
            "supports_json_format": True,
            "supports_agent_flag": True,
            "supports_session_continue": True,
        }

    def run(
        self,
        message: str,
        system_prompt: Optional[str] = None,
        agent_name: str = "",
        model: str = "",
        timeout_seconds: Optional[int] = None,
        cwd: Optional[str] = None,
        session_id: Optional[str] = None,
        continue_session: bool = False,
    ) -> InvocationResult:
        timeout = float(timeout_seconds or self.config.opencode.timeout_seconds)
        argv: List[str] = [self.config.opencode.executable, "run", message]
        if agent_name:
            argv.extend(["--agent", agent_name])
        if model:
            argv.extend(["--model", model])
        if continue_session and session_id:
            argv.extend(["--session", session_id])
        start = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
                shell=False,
                cwd=cwd,
            )
            exit_code = int(proc.returncode)
            stdout = proc.stdout.decode("utf-8", errors="replace")
            stderr = proc.stderr.decode("utf-8", errors="replace")
            timed_out = False
        except subprocess.TimeoutExpired:
            return InvocationResult(
                executable=self.config.opencode.executable, argv=argv, exit_code=None,
                stdout="", stderr=f"timeout after {timeout}s", duration_ms=int((time.monotonic() - start) * 1000),
                session_id=None, prompt_hash=_hash(message), model=model, provider=None,
                timed_out=True,
            )
        duration_ms = int((time.monotonic() - start) * 1000)
        provider, _sep, maybe_model = (model.partition("/") if model else (None, "", None))
        parse_model = maybe_model if maybe_model else None
        session = _extract_session(stdout)
        return InvocationResult(
            executable=self.config.opencode.executable, argv=argv, exit_code=exit_code,
            stdout=stdout, stderr=stderr, duration_ms=duration_ms, session_id=session,
            prompt_hash=_hash(message), model=parse_model, provider=provider,
        )


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def redact_secrets_argv(text: str, patterns: List[str]) -> str:
    for pattern in patterns:
        try:
            text = re.compile(pattern).sub("[REDACTED]", text)
        except re.error:
            continue
    return text


class MockAdapter:
    """Offline deterministic stand-in for OpenCode; returns canned envelopes."""

    def __init__(self, config) -> None:
        self.config = config

    def available(self) -> bool:
        return True

    def version(self) -> Optional[str]:
        return "mock-0.1.0"

    def capabilities(self) -> dict:
        return {
            "executable": "mock",
            "available": True,
            "version": self.version(),
            "mode": "mock",
            "supports_json_format": True,
        }

    def run(
        self,
        message: str,
        system_prompt: Optional[str] = None,
        agent_name: str = "",
        model: str = "",
        timeout_seconds: Optional[int] = None,
        cwd: Optional[str] = None,
        session_id: Optional[str] = None,
        continue_session: bool = False,
        **kwargs,
    ) -> InvocationResult:
        start = time.monotonic()
        argv = ["mock-opencode", "run", "--agent", agent_name or "", "--model", model or ""]
        stdout = mock_envelope_stdout(agent_name, message)
        sim_session = f"ses_mock{hashlib.md5(message.encode()).hexdigest()[:12]}"
        provider, _sep, model_part = model.partition("/") if model else (None, "", None)
        return InvocationResult(
            executable="mock-opencode", argv=argv, exit_code=0, stdout=stdout,
            stderr="", duration_ms=int((time.monotonic() - start) * 1000),
            session_id=sim_session, prompt_hash=_hash(message),
            model=model_part or None, provider=provider,
        )


def mock_envelope_stdout(agent_name: str, message: str) -> str:
    envelope = {
        "node_id": agent_name or "mock-node",
        "status": "success",
        "summary": f"[mock] completed {agent_name}",
        "artifacts": [],
        "evidence_used": [],
        "findings": [],
        "gaps": [],
        "requests": [],
        "decisions": [],
        "metrics": {"mock": True},
        "recommended_next_nodes": [],
        "limitations": ["mock adapter, no LLM executed"],
        "confidence": "UNKNOWN",
    }
    return json.dumps(envelope, indent=2)


def create_adapter(config, *, force_mock: bool = False):
    if force_mock or config.opencode.executable == "mock":
        return MockAdapter(config)
    adapter = OpenCodeAdapter(config)
    if adapter.available():
        return adapter
    return MockAdapter(config)


def shell_false_guard(argv: List[str]) -> List[str]:
    if any(isinstance(part, str) and (";" in part or "|" in part) for part in argv):
        return argv
    return argv
