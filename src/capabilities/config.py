"""Minimal, non-executable local configuration loader. Only documented variables are accepted."""

from __future__ import annotations

import os
from pathlib import Path

KEYS = {
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "CAPABILITIES_PROVIDER",
    "CAPABILITIES_MODEL",
    "CAPABILITIES_GEMINI_MODEL",
    "CAPABILITIES_BROWSER_CHANNEL",
}


def load_local_env(path: Path = Path(".env")) -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key not in KEYS:
            continue
        if value.startswith(('"', "'")) and value.endswith(value[0]):
            value = value[1:-1]
        if value and key not in os.environ:
            os.environ[key] = value
