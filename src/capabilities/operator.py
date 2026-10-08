"""Local operator UI. OS-local user is the trust boundary; CSRF and DNS rebinding are blocked."""

from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from capabilities.errors import ExecutionError
from capabilities.session import SessionController


class ControlRequest(BaseModel):
    epoch: int


def create_operator_app(controller: SessionController, origin: str) -> FastAPI:
    app = FastAPI(title="Capability operator", docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1"])
    csrf = secrets.token_urlsafe(32)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        html = (Path(__file__).parent / "templates/operator.html").read_text()
        return HTMLResponse(
            html.replace("{{csrf}}", csrf),
            headers={
                "Cache-Control": "no-store",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "frame-ancestors 'none'; connect-src 'self'",
            },
        )

    @app.get("/api/state")
    async def state() -> dict[str, object]:
        return controller.state()

    @app.post("/api/{command}")
    async def command(command: str, body: ControlRequest, request: Request) -> dict[str, object]:
        if request.headers.get("origin") != origin or not secrets.compare_digest(
            request.headers.get("x-operator-csrf", ""), csrf
        ):
            raise HTTPException(403, "Local operator origin and CSRF token required")
        handlers = {
            "claim": controller.claim,
            "resume": controller.resume,
            "abort": controller.abort,
        }
        if command not in handlers:
            raise HTTPException(404)
        try:
            await handlers[command](body.epoch)
        except ExecutionError as error:
            raise HTTPException(409, error.code) from error
        return controller.state()

    return app
