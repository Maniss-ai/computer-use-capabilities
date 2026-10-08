"""Generate truthful offline evidence using real Chromium and an explicitly scripted planner.

No API key is read. The operator actor is simulated; it operates the same live browser.
A genuine model run is a separate, mandatory submission step.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import socket
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal

import uvicorn

from capabilities.cli import load_policy
from capabilities.contracts import Capability, Decision, GoalContract
from capabilities.discovery import DiscoveryEngine
from capabilities.engine import Executor, ReplayEngine
from capabilities.evidence import Evidence, atomic_write
from capabilities.operator import create_operator_app
from capabilities.sandbox.app import app
from capabilities.session import SessionController
from capabilities.surface import BrowserSurface


class ScriptedPlanner:
    source: Literal["test_fixture"] = "test_fixture"
    model = "scripted-test-double-not-an-llm"
    calls = 0
    tokens = 0

    def __init__(self, artifact: Capability):
        self.actions = iter(artifact.steps)

    async def decide(
        self, goal: str, contract: GoalContract, observation: dict[str, Any]
    ) -> Decision:
        self.calls += 1
        step = next(self.actions, None)
        return (
            Decision(action=step.action, reason="advance")
            if step
            else Decision(finish=True, reason="verify_goal")
        )


async def simulated_operator(
    surface: BrowserSurface, control: SessionController, button: str
) -> None:
    """Exercise the real operator webpage and HTTP control API, with an explicit test actor."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
    app = create_operator_app(control, origin)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    assert surface.browser is not None
    context = await surface.browser.new_context(viewport={"width": 1280, "height": 900})
    try:
        async with asyncio.timeout(20):
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError("Operator console did not start")
                await asyncio.sleep(0.02)
            while control.owner != "waiting":  # noqa: ASYNC110 - public operator state polling
                await asyncio.sleep(0.02)
            surface.evidence.event("operator_simulation", source="scripted_operator_not_a_human")
            page = await context.new_page()
            await page.goto(origin)
            await page.get_by_role("button", name="Claim session", exact=True).wait_for()
            await page.screenshot(path=surface.evidence.root / "operator-console.png")
            await page.get_by_role("button", name="Claim session", exact=True).click()
            while control.owner != "human":  # noqa: ASYNC110
                await asyncio.sleep(0.02)
            await surface.workspace.get_by_role("button", name=button, exact=True).click()
            await page.get_by_role("button", name="Return to automation", exact=True).click()
            while control.owner == "human":  # noqa: ASYNC110
                await asyncio.sleep(0.02)
    finally:
        await context.close()
        server.should_exit = True
        await task
        sock.close()


async def generate(out: Path, repetitions: int) -> None:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started:
        if task.done():
            await task
            raise RuntimeError("Sandbox startup failed")
        await asyncio.sleep(0.02)
    authored = Capability.model_validate_json(
        await asyncio.to_thread(Path("examples/authored-capability.json").read_text)
    )
    policy = load_policy(origin)
    manifest: dict[str, Any] = {
        "live_llm_discovery": False,
        "human_operator": False,
        "description": "Real UI execution; scripted planner and operator actors. Not live discovery evidence.",
        "python": platform.python_version(),
        "platform": platform.system(),
        "playwright": version("playwright"),
        "cases": [],
    }
    artifact = authored
    try:
        cases = [
            ("fixture-discovery", "normal", "10023", None),
            ("replay-success", "normal", "10042", None),
            ("replay-not-found", "normal", "99999", None),
            ("replay-validation", "validation", "10042", None),
            ("replay-permission-denied", "permission_denied", "10042", None),
            ("replay-slow", "slow", "10042", None),
            ("replay-known-notice", "interstitial", "10042", None),
            ("handoff-expired-session", "session_expired", "10042", "Restore session"),
            ("handoff-unknown-dialog", "unexpected_dialog", "10042", "Acknowledge notice"),
        ]
        cases.extend(
            (f"stability-{i + 1:02d}", "normal", "10077", None) for i in range(repetitions)
        )
        for name, scenario, member, button in cases:
            supplied = {"member_id": member, "product": "Savings", "nickname": "Emergency Fund"}
            evidence = Evidence(out, name, [member, supplied["nickname"]])
            control = SessionController(evidence, timeout=15, interactive=bool(button))
            surface = BrowserSurface(policy, evidence, control)
            started = time.monotonic()
            operator_task: asyncio.Task[None] | None = None
            try:
                await surface.start(f"{origin}/?scenario={scenario}")
                executor = Executor(surface, policy, control, evidence)
                if name == "fixture-discovery":
                    discovery = DiscoveryEngine(executor, ScriptedPlanner(authored))
                    result = await discovery.run(
                        "Prepare a sub-account review using the input parameters",
                        authored.goal,
                        supplied,
                    )
                    assert discovery.artifact is not None, result
                    artifact = discovery.artifact
                else:
                    if button:
                        operator_task = asyncio.create_task(
                            simulated_operator(surface, control, button)
                        )
                    result = await ReplayEngine(executor).run(artifact, supplied)
                    if operator_task:
                        await operator_task
                if result.status == "success":
                    await surface.capture()
                elapsed = round((time.monotonic() - started) * 1000)
                manifest["cases"].append(
                    {
                        "run": name,
                        "status": result.status,
                        "outcome": result.outcome,
                        "error": result.error.code if result.error else None,
                        "model_calls": result.model_calls,
                        "human_interventions": result.human_interventions,
                        "duration_ms": elapsed,
                    }
                )
                print(f"{name}: {result.status} ({elapsed} ms)")
            finally:
                if operator_task and not operator_task.done():
                    operator_task.cancel()
                await surface.close()
        stability = [case for case in manifest["cases"] if case["run"].startswith("stability-")]
        manifest["stability"] = {
            "runs": len(stability),
            "passed": sum(case["status"] == "success" for case in stability),
            "scope": "Same pinned browser and fixture; not a production reliability estimate",
        }
        atomic_write(out / "manifest.json", json.dumps(manifest, indent=2))
    finally:
        server.should_exit = True
        await task
        sock.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("evidence/offline"))
    parser.add_argument("--repetitions", type=int, default=10)
    args = parser.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        parser.error("Choose an empty output directory; existing evidence is never overwritten")
    if not 1 <= args.repetitions <= 30:
        parser.error("Repetitions must be between 1 and 30")
    asyncio.run(generate(args.out, args.repetitions))
