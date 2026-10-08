"""Allowlisted events and atomic artifact storage. No raw model/browser exception strings."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from capabilities.contracts import Capability, OutputField, RunResult

FIELDS = {
    "step",
    "op",
    "target_kind",
    "screen",
    "reason",
    "code",
    "owner",
    "epoch",
    "model",
    "response_id",
    "input_tokens",
    "output_tokens",
    "artifact_sha256",
    "source",
    "event_count",
    "manual_kind",
    "target_tag",
    "target",
    "manual_control",
    "parameter",
    "attempt",
    "status",
    "model_calls",
    "human_interventions",
    "evidence",
    "duration_ms",
}


class Evidence:
    def __init__(self, root: Path, run_id: str, secrets: list[str] | None = None):
        self.root = root / run_id
        self.root.mkdir(parents=True, exist_ok=False)
        self.run_id = run_id
        self.secrets = sorted((x for x in (secrets or []) if x), key=len, reverse=True)
        self.sequence = 0

    def sanitize(self, value: str) -> str:
        for secret in self.secrets:
            value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL]", value)
        value = re.sub(r"\b(?:sk-ant-|sk-)[A-Za-z0-9_-]+", "[SECRET]", value)
        value = re.sub(r"(?i)(bearer\s+)\S+", r"\1[SECRET]", value)
        return value[:500]

    def event(self, event: str, **fields: Any) -> None:
        if not set(fields).issubset(FIELDS):
            raise ValueError("Unknown evidence field")
        self.sequence += 1
        payload = {
            "seq": self.sequence,
            "at": datetime.now(UTC).isoformat(),
            "run_id": self.run_id,
            "event": event,
            **{k: self.sanitize(v) if isinstance(v, str) else v for k, v in fields.items()},
        }
        with (self.root / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True) + "\n")

    def artifact(self, artifact: Capability) -> Path:
        raw = artifact.model_dump_json(indent=2)
        # Values declared sensitive must never accidentally become artifact literals.
        if any(secret in raw for secret in self.secrets):
            raise ValueError("Sensitive value found in artifact")
        path = self.root / "capability.json"
        atomic_write(path, raw)
        self.event("artifact_saved", artifact_sha256=hashlib.sha256(raw.encode()).hexdigest())
        return path

    def result(self, result: RunResult, outputs: dict[str, OutputField] | None = None) -> None:
        # Raw declared outputs go only to the live caller. Persistent result is redacted.
        payload = result.model_dump(mode="json")
        payload["outputs"] = {
            key: value
            if outputs and key in outputs and not outputs[key].sensitive
            else "[REDACTED]"
            for key, value in result.outputs.items()
        }
        if payload.get("error"):
            for key, value in payload["error"].items():
                if isinstance(value, str):
                    payload["error"][key] = self.sanitize(value)
        atomic_write(self.root / "result.json", json.dumps(payload, indent=2))


def atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value + "\n", encoding="utf-8")
    os.replace(temporary, path)


def capability_digest(capability: Capability) -> str:
    return hashlib.sha256(capability.model_dump_json(indent=2).encode()).hexdigest()
