from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import uvicorn

from capabilities.cli import load_policy
from capabilities.contracts import Capability
from capabilities.engine import Executor
from capabilities.evidence import Evidence
from capabilities.session import SessionController
from capabilities.surface import BrowserSurface


@pytest.fixture
def artifact():
    return Capability.model_validate_json(Path("examples/authored-capability.json").read_text())


@pytest.fixture
def inputs():
    return {"member_id": "10042", "product": "Checking", "nickname": "Travel Fund"}


@pytest.fixture(scope="session")
def sandbox_url():
    from capabilities.sandbox.app import app

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    import time

    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("Sandbox did not start")
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)
    sock.close()


@pytest.fixture
def browser_factory(tmp_path, sandbox_url, inputs):
    counter = 0

    @asynccontextmanager
    async def factory(scenario="normal", interactive=False, intervention_timeout=10):
        nonlocal counter
        counter += 1
        evidence = Evidence(tmp_path, f"test-{counter}", [inputs["member_id"], inputs["nickname"]])
        policy = load_policy(sandbox_url)
        controller = SessionController(
            evidence, timeout=intervention_timeout, interactive=interactive
        )
        surface = BrowserSurface(
            policy, evidence, controller, channel=os.getenv("CAPABILITIES_BROWSER_CHANNEL")
        )
        try:
            await surface.start(f"{sandbox_url}/?scenario={scenario}")
            yield surface, controller, evidence, Executor(surface, policy, controller, evidence)
        finally:
            await surface.close()

    return factory


async def wait_owner(controller, owner):
    async with asyncio.timeout(10):
        while controller.owner != owner:  # noqa: ASYNC110 - observe public state as an operator does
            await asyncio.sleep(0.02)


def events(evidence):
    path = evidence.root / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
