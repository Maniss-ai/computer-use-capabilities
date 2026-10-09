"""Local web control plane over the existing discovery, replay, and ownership engines."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import uvicorn
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from capabilities.cli import load_policy
from capabilities.contracts import Action, Capability, Contract, Failure, RunResult
from capabilities.engine import Executor, ReplayEngine
from capabilities.errors import ExecutionError
from capabilities.evidence import Evidence, capability_digest
from capabilities.session import SessionController
from capabilities.surface import SCREENS, BrowserSurface
from capabilities.workflows import Workflow, workflow_for_goal, workflows

PACKAGE = Path(__file__).parent
GOAL = "Find the supplied member, prepare the requested sub-account with the supplied nickname, and stop at the review screen."
Scenario = Literal[
    "normal",
    "slow",
    "interstitial",
    "validation",
    "permission_denied",
    "app_error",
    "session_expired",
    "unexpected_dialog",
    "ambiguous",
    "visual_missing",
    "prompt_injection",
]


class StartRun(Contract):
    mode: Literal["replay", "discover"] = "replay"
    capability_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    workflow_id: str | None = Field(default=None, pattern=r"^[a-z][a-z-]{0,40}$")
    inputs: dict[str, str]
    scenario: Scenario = "normal"
    provider: Literal["gemini", "anthropic"] = "gemini"


class Control(Contract):
    epoch: int = Field(ge=0)


class Pointer(Control):
    x: float = Field(ge=0, lt=1280, allow_inf_nan=False)
    y: float = Field(ge=0, lt=900, allow_inf_nan=False)


class Typing(Control):
    text: str = Field(min_length=1, max_length=80)


class Key(Control):
    key: Literal["Tab", "Enter", "Escape", "Backspace", "ArrowUp", "ArrowDown"]


class PreviewSurface(BrowserSurface):
    async def execute(self, action: Action, inputs: dict[str, str]) -> None:
        await super().execute(action, inputs)
        # A short presentation pause makes real actions visible in the web preview.
        # Target selection, checkpoints, and recovery still belong to the engine.
        await asyncio.sleep(0.6)


@dataclass
class WebRun:
    evidence: Evidence
    request: StartRun
    capability: Capability | None
    workflow: Workflow
    control: SessionController
    surface: BrowserSurface
    status: str = "starting"
    screen: str = "Starting browser"
    started: float = field(default_factory=time.monotonic)
    elapsed: float = 0
    result: RunResult | None = None
    planner: Any = None
    task: asyncio.Task[None] | None = None
    preview: asyncio.Task[None] | None = None
    image: bytes | None = None
    frame: int = 0

    def events(self) -> list[dict[str, Any]]:
        path = self.evidence.root / "events.jsonl"
        if not path.exists():
            return []
        # Only expose complete records; a refresh can coincide with the final write.
        return [json.loads(line) for line in path.read_text().splitlines() if line.endswith("}")][
            -300:
        ]

    def state(self) -> dict[str, Any]:
        events = self.events()
        return {
            "id": self.evidence.run_id,
            "mode": self.request.mode,
            "workflow_id": self.workflow.id,
            "workflow_title": self.workflow.title,
            "status": self.status,
            "screen": self.screen,
            "control": self.control.state(),
            "result": self.result.model_dump(mode="json") if self.result else None,
            "model_calls": self.result.model_calls
            if self.result
            else getattr(self.planner, "calls", 0),
            "completed_actions": sum(e["event"] == "action_completed" for e in events),
            "elapsed_seconds": round(
                self.elapsed if self.result else time.monotonic() - self.started, 1
            ),
            "frame": self.frame,
            "events": events,
            "artifact_available": (self.evidence.root / "capability.json").is_file(),
        }


class RunManager:
    """One active browser, bounded in-memory history; disk evidence stays redacted."""

    def __init__(self, bank_origin: str, root: Path):
        self.bank_origin, self.root = bank_origin, root
        self.runs: dict[str, WebRun] = {}
        self.lock = asyncio.Lock()

    def catalog(self) -> dict[str, Capability]:
        paths = [
            *sorted((PACKAGE / "catalog").glob("*.json")),
            *sorted(self.root.glob("*/capability.json")),
        ]
        catalog: dict[str, Capability] = {}
        for path in paths:
            try:
                artifact = Capability.model_validate_json(path.read_text())
                workflow_for_goal(artifact.goal)
                if artifact.profile == "harbor-ledger/v1":
                    catalog[capability_digest(artifact)] = artifact
            except (ValueError, OSError):
                continue  # Incomplete or incompatible local artifacts cannot become runnable.
        return catalog

    async def start(self, request: StartRun) -> WebRun:
        async with self.lock:
            if any(run.task and not run.task.done() for run in self.runs.values()):
                raise HTTPException(409, "A run is already active. Finish or stop it first.")
            capability = self.catalog().get(request.capability_id or "")
            if request.capability_id and capability is None:
                raise HTTPException(404, "Capability not found")
            workflow = (
                workflows().get(request.workflow_id)
                if request.workflow_id
                else workflow_for_goal(capability.goal)
                if capability
                else None
            )
            if workflow is None:
                raise HTTPException(404, "Workflow not found")
            if request.mode == "replay" and capability is None:
                raise HTTPException(422, "Discover this workflow before replaying it.")
            if capability and capability.goal != workflow.contract:
                raise HTTPException(422, "Capability does not belong to the selected workflow.")
            try:
                inputs = workflow.contract.validate_inputs(dict(request.inputs))
            except ValueError:
                raise HTTPException(
                    422,
                    "Check the workflow inputs: use a five-digit member ID and valid nonempty field values.",
                ) from None
            key = ""
            if request.mode == "discover":
                key = os.environ.get(
                    "GEMINI_API_KEY" if request.provider == "gemini" else "ANTHROPIC_API_KEY", ""
                )
                if not key:
                    raise HTTPException(
                        422,
                        "Configure the selected provider key in the local .env file, then restart the dashboard.",
                    )
            # Completed frames remain in memory; every invocation owns a new context.
            while len(self.runs) >= 20:
                del self.runs[next(iter(self.runs))]
            run_id = f"web-{request.mode}-{uuid.uuid4().hex[:12]}"
            evidence = Evidence(
                self.root,
                run_id,
                [
                    key,
                    *(inputs[k] for k, spec in workflow.contract.inputs.items() if spec.sensitive),
                ],
            )
            policy = load_policy(self.bank_origin)
            control = SessionController(evidence, policy.intervention_seconds, interactive=True)
            surface = PreviewSurface(
                policy, evidence, control, channel=os.getenv("CAPABILITIES_BROWSER_CHANNEL")
            )
            run = WebRun(evidence, request, capability, workflow, control, surface)
            self.runs[run_id] = run
            run.task = asyncio.create_task(self._execute(run, key))
            await asyncio.sleep(0)  # Enter its cleanup scope before accepting a stop request.
            return run

    async def _preview(self, run: WebRun) -> None:
        while True:
            try:
                await self._snapshot(run)
            except Exception:
                # Navigation can race a screenshot. Withhold stale pixels until next frame.
                run.image = None
                run.screen = "Preview unavailable"
                run.frame += 1
            await asyncio.sleep(0.4)

    async def _snapshot(self, run: WebRun) -> None:
        run.screen = await run.surface.screen()
        if run.screen in SCREENS and not run.surface.blocked and not run.surface.dialog:
            # Local live view only. Never persist these pixels or send them to a model.
            run.image = await run.surface.page.screenshot(
                type="jpeg", quality=75, animations="disabled"
            )
        else:
            run.image = None
        run.frame += 1

    async def _execute(self, run: WebRun, key: str) -> None:
        try:
            await run.surface.start(f"{self.bank_origin}/?scenario={run.request.scenario}")
            run.status = "running"
            run.preview = asyncio.create_task(self._preview(run))
            executor = Executor(run.surface, run.surface.policy, run.control, run.evidence)
            if run.request.mode == "replay":
                assert run.capability is not None
                run.result = await ReplayEngine(executor).run(run.capability, run.request.inputs)
            else:
                from capabilities.discovery import AnthropicPlanner, DiscoveryEngine
                from capabilities.gemini import GeminiPlanner

                if run.request.provider == "gemini":
                    run.planner = GeminiPlanner(
                        key,
                        os.getenv("CAPABILITIES_GEMINI_MODEL", "gemini-3.1-flash-lite"),
                        run.evidence,
                    )
                else:
                    run.planner = AnthropicPlanner(
                        key, os.getenv("CAPABILITIES_MODEL", "claude-sonnet-5-5"), run.evidence
                    )
                run.result = await DiscoveryEngine(executor, run.planner).run(
                    run.workflow.goal, run.workflow.contract, run.request.inputs
                )
            run.status = run.result.status
            if run.result.status == "success":
                await run.surface.capture()
        except asyncio.CancelledError:
            self._failure(run, "operator_cancelled")
        except Exception:
            self._failure(run, "startup_or_runtime_error")
        finally:
            if run.preview:
                run.preview.cancel()
                with suppress(asyncio.CancelledError):
                    await run.preview
            try:
                await self._snapshot(run)
            except Exception:
                run.image = None
                run.screen = "Preview unavailable"
                run.frame += 1
            run.elapsed = time.monotonic() - run.started
            run.control.owner = "closed"
            if run.planner:
                with suppress(Exception):
                    await run.planner.close()
            # Keep only the last frame; close all browser resources on completion.
            with suppress(Exception):
                await run.surface.close()

    def _failure(self, run: WebRun, code: str) -> None:
        run.status = "failure"
        run.result = RunResult(
            status="failure",
            run_id=run.evidence.run_id,
            error=Failure(code=code),
            model_calls=getattr(run.planner, "calls", 0),
            human_interventions=run.control.interventions,
        )
        run.evidence.event(
            "run_finished", status="failure", code=code, model_calls=run.result.model_calls
        )
        run.evidence.result(run.result)

    async def close(self) -> None:
        for run in self.runs.values():
            if run.task and not run.task.done():
                run.task.cancel()
                with suppress(asyncio.CancelledError):
                    await run.task


def create_dashboard_app(origin: str, bank_origin: str, root: Path) -> FastAPI:
    manager = RunManager(bank_origin, root)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await manager.close()

    app = FastAPI(title="Capability Studio", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.manager = manager
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1"])
    csrf = secrets.token_urlsafe(32)
    app.mount("/assets", StaticFiles(directory=PACKAGE / "web_static"), name="assets")

    @app.middleware("http")
    async def private_responses(request: Request, call_next: Any) -> Response:
        response: Response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'self'; img-src 'self' blob:; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            }
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {"detail": "Invalid request. Check the form fields and refresh the current session."},
            status_code=422,
        )

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return (PACKAGE / "web_static/index.html").read_text().replace("{{csrf}}", csrf)

    async def authorized(request: Request) -> None:
        if not secrets.compare_digest(request.headers.get("x-studio-csrf", ""), csrf):
            raise HTTPException(403, "Open the local dashboard to control this session.")
        if request.method != "GET" and request.headers.get("origin") != origin:
            raise HTTPException(403, "Dashboard origin required")
        if request.headers.get("origin") not in {None, origin}:
            raise HTTPException(403, "Dashboard origin required")

    api = APIRouter(prefix="/api", dependencies=[Depends(authorized)])

    def get_run(run_id: str) -> WebRun:
        if run_id not in manager.runs:
            raise HTTPException(404, "Run not found. The dashboard may have restarted.")
        return manager.runs[run_id]

    @api.get("/catalog")
    async def catalog() -> dict[str, Any]:
        return {
            "capabilities": [
                {
                    "id": key,
                    "workflow_id": workflow_for_goal(cap.goal).id,
                    "title": workflow_for_goal(cap.goal).title,
                    "name": cap.goal.name,
                    "version": cap.capability_version,
                    "steps": len(cap.steps),
                    "provenance": cap.provenance.model_dump(),
                    "artifact": cap.model_dump(mode="json"),
                }
                for key, cap in manager.catalog().items()
            ],
            "providers": {
                name: bool(os.getenv(key))
                for name, key in (("gemini", "GEMINI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY"))
            },
            "workflows": [workflow.model_dump(mode="json") for workflow in workflows().values()],
            "bank_origin": bank_origin,
        }

    @api.get("/runs")
    async def runs() -> list[dict[str, Any]]:
        return [
            {
                "id": r.evidence.run_id,
                "mode": r.request.mode,
                "status": r.status,
                "workflow_id": r.workflow.id,
                "workflow_title": r.workflow.title,
            }
            for r in reversed(list(manager.runs.values()))
        ]

    @api.post("/runs", status_code=202)
    async def start(body: StartRun) -> dict[str, Any]:
        return (await manager.start(body)).state()

    @api.get("/runs/{run_id}")
    async def state(run_id: str) -> dict[str, Any]:
        return get_run(run_id).state()

    @api.get("/runs/{run_id}/preview")
    async def preview(run_id: str) -> Response:
        image = get_run(run_id).image
        return Response(image, media_type="image/jpeg") if image else Response(status_code=204)

    @api.post("/runs/{run_id}/stop")
    async def stop(run_id: str) -> dict[str, Any]:
        run = get_run(run_id)
        if run.task and not run.task.done():
            run.task.cancel()
            await run.task
        return run.state()

    @api.post("/runs/{run_id}/control/{command}")
    async def control(
        run_id: str, command: Literal["claim", "resume", "abort"], body: Control
    ) -> dict[str, Any]:
        run = get_run(run_id)
        try:
            await getattr(run.control, command)(body.epoch)
        except ExecutionError as error:
            raise HTTPException(409, error.code) from None
        return run.state()

    async def human_input(run: WebRun, epoch: int, kind: str, value: Any) -> None:
        async with run.control.lock:
            if run.control.owner != "human" or run.control.epoch != epoch:
                raise HTTPException(
                    409, "Claim the current paused session before using browser controls."
                )
            try:
                if kind == "click":
                    await run.surface.page.mouse.click(value.x, value.y)
                elif kind == "text":
                    await run.surface.page.keyboard.insert_text(value)
                else:
                    await run.surface.page.keyboard.press(value)
            except Exception:
                raise HTTPException(409, "The browser could not accept that input.") from None

    @api.post("/runs/{run_id}/pointer")
    async def pointer(run_id: str, body: Pointer) -> dict[str, bool]:
        await human_input(get_run(run_id), body.epoch, "click", body)
        return {"accepted": True}

    @api.post("/runs/{run_id}/text")
    async def typing(run_id: str, body: Typing) -> dict[str, bool]:
        if any(ord(char) < 32 for char in body.text):
            raise HTTPException(422, "Use the keyboard buttons for control keys.")
        await human_input(get_run(run_id), body.epoch, "text", body.text)
        return {"accepted": True}

    @api.post("/runs/{run_id}/key")
    async def key(run_id: str, body: Key) -> dict[str, bool]:
        await human_input(get_run(run_id), body.epoch, "key", body.key)
        return {"accepted": True}

    app.include_router(api)
    return app


async def serve_dashboard(port: int, bank_port: int, root: Path) -> None:
    """Start both local surfaces together; fail immediately if either port is occupied."""
    from capabilities.sandbox.app import app as bank_app

    sockets: list[socket.socket] = []
    tasks: list[asyncio.Task[None]] = []
    servers: list[uvicorn.Server] = []
    try:
        for value in (bank_port, port):
            sock = socket.socket()
            sockets.append(sock)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", value))
            sock.setblocking(False)
        origin, bank_origin = f"http://127.0.0.1:{port}", f"http://127.0.0.1:{bank_port}"
        dashboard = create_dashboard_app(origin, bank_origin, root)
        for app, sock in zip((bank_app, dashboard), sockets, strict=True):
            server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="warning"))
            servers.append(server)
            tasks.append(asyncio.create_task(server.serve(sockets=[sock])))
        print(f"Capability Studio: {origin}\nSynthetic banking sandbox: {bank_origin}", flush=True)
        await asyncio.gather(*tasks)
    finally:
        for server in servers:
            server.should_exit = True
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for sock in sockets:
            sock.close()
