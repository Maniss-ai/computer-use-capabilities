from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

ROOT = Path(__file__).parent
app = FastAPI(title="Harbor Ledger — synthetic banking sandbox", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")
SCENARIOS = {
    "normal",
    "slow",
    "interstitial",
    "session_expired",
    "unexpected_dialog",
    "permission_denied",
    "app_error",
    "ambiguous",
    "validation",
    "prompt_injection",
    "offsite",
    "visual_missing",
}
MEMBERS = {"10023": "Jordan Ellis", "10042": "Morgan Chen", "10077": "Avery Patel"}


@dataclass
class Session:
    scenario: str = "normal"
    member: str = ""
    restored: bool = False
    acknowledged: bool = False


sessions: dict[str, Session] = {}


def session(request: Request) -> Session:
    sid = request.cookies.get("sandbox_session", "")
    return sessions.setdefault(sid, Session())


def render(request: Request, screen: str, **values: object) -> HTMLResponse:
    state = session(request)
    return templates.TemplateResponse(
        request=request,
        name="workspace.html",
        context={
            "screen": screen,
            "state": state,
            "member_name": MEMBERS.get(state.member, ""),
            **values,
        },
    )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, scenario: str = "normal") -> HTMLResponse:
    scenario = scenario if scenario in SCENARIOS else "normal"
    sid = secrets.token_urlsafe(20)
    sessions[sid] = Session(scenario=scenario)
    # This disposable fixture has bounded memory, not production session persistence.
    if len(sessions) > 2000:
        del sessions[next(iter(sessions))]
    response = templates.TemplateResponse(
        request=request, name="shell.html", context={"scenario": scenario}
    )
    response.set_cookie("sandbox_session", sid, httponly=True, samesite="strict")
    return response


@app.get("/workspace/search", response_class=HTMLResponse)
async def search_page(request: Request) -> HTMLResponse:
    return render(request, "Find a member")


@app.post("/workspace/search", response_model=None)
async def search(
    request: Request, member_id: Annotated[str, Form()]
) -> HTMLResponse | RedirectResponse:
    state = session(request)
    if not member_id.isdigit() or len(member_id) != 5:
        return render(request, "Validation error")
    if member_id not in MEMBERS:
        return render(request, "Member not found")
    state.member = member_id
    return RedirectResponse("/workspace/member", status_code=303)


@app.get("/workspace/member", response_class=HTMLResponse)
async def member(request: Request) -> HTMLResponse:
    state = session(request)
    if not state.member:
        return render(request, "Find a member")
    if state.scenario == "slow":
        await asyncio.sleep(0.45)
    if state.scenario == "permission_denied":
        return render(request, "Permission denied")
    if state.scenario == "app_error":
        return render(request, "Application unavailable")
    if state.scenario == "session_expired" and not state.restored:
        return render(request, "Session expired")
    return render(request, "Member details")


@app.get("/workspace/restore")
async def restore(request: Request) -> RedirectResponse:
    session(request).restored = True
    return RedirectResponse("/workspace/member", status_code=303)


@app.get("/workspace/acknowledge")
async def acknowledge(request: Request) -> RedirectResponse:
    session(request).acknowledged = True
    return RedirectResponse("/workspace/member", status_code=303)


@app.get("/workspace/new", response_class=HTMLResponse)
async def new_account(request: Request) -> HTMLResponse:
    return render(request, "Prepare sub-account")


@app.post("/workspace/review", response_class=HTMLResponse)
async def review(
    request: Request, nickname: Annotated[str, Form()], product: Annotated[str, Form()]
) -> HTMLResponse:
    if not nickname.strip() or len(nickname) > 80 or product not in {"Savings", "Checking"}:
        return render(request, "Validation error")
    if session(request).scenario == "validation":
        return render(request, "Validation error")
    return render(request, "Review sub-account", nickname=nickname, product=product)


@app.post("/workspace/commit", response_class=HTMLResponse)
async def commit(request: Request) -> HTMLResponse:
    # Deliberately outside the automation allowlist. No real financial effect.
    return render(request, "Account created — synthetic fixture only")
