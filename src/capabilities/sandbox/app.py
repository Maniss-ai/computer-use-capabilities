from __future__ import annotations

import asyncio
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from capabilities.sandbox.services import SERVICES, Service, record_for

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
    service: str = ""
    record: dict[str, str] = field(default_factory=dict)
    reference: str = ""


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
            "services": SERVICES.values(),
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
    state.member, state.service, state.reference = "", "", ""
    state.record.clear()
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


def service_context(request: Request, slug: str) -> tuple[Service, Session]:
    service = SERVICES.get(slug)
    if service is None:
        raise HTTPException(404, "Unknown service")
    state = session(request)
    if state.member not in MEMBERS:
        raise HTTPException(409, "Find a member before servicing a record")
    return service, state


@app.get("/workspace/services/{slug}", response_class=HTMLResponse)
async def service_home(request: Request, slug: str) -> HTMLResponse:
    service, state = service_context(request, slug)
    state.service, state.reference = slug, ""
    state.record = {} if service.lookup_name else record_for(service, state.member, "") or {}
    return render(
        request,
        service.title if service.lookup_name else service.detail_screen,
        service=service,
        stage="lookup" if service.lookup_name else "detail",
    )


@app.post("/workspace/services/{slug}/lookup", response_class=HTMLResponse)
async def service_lookup(request: Request, slug: str) -> HTMLResponse:
    service, state = service_context(request, slug)
    values = await request.form()
    reference = values.get(service.lookup_name)
    state.service, state.record, state.reference = slug, {}, ""
    if not isinstance(reference, str) or len(reference) > 80:
        return render(request, "Validation error")
    record = record_for(service, state.member, reference)
    if record is None:
        return render(request, "Service record not found")
    if reference.endswith("-HOLD"):
        return render(request, "Request not eligible", record=record)
    state.record, state.reference = record, reference
    return render(request, service.detail_screen, service=service, stage="detail")


@app.get("/workspace/services/{slug}/prepare", response_class=HTMLResponse)
async def service_prepare(request: Request, slug: str) -> HTMLResponse:
    service, state = service_context(request, slug)
    if state.service != slug or not state.record:
        return render(request, "Service record not found")
    return render(request, service.prepare_screen, service=service, stage="prepare")


@app.post("/workspace/services/{slug}/review", response_class=HTMLResponse)
async def service_review(request: Request, slug: str) -> HTMLResponse:
    service, state = service_context(request, slug)
    if state.service != slug or not state.record:
        return render(request, "Service record not found")
    form = await request.form()
    values: dict[str, str] = {}
    for item in service.fields:
        value = form.get(item.name)
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 80
            or any(ord(char) < 32 for char in value)
            or (item.choices and value not in item.choices)
        ):
            return render(request, "Validation error")
        values[item.name] = value
    if slug == "address-change" and (
        not re.fullmatch(r"[A-Z]{2}", values["region"])
        or not re.fullmatch(r"[0-9]{5}", values["postal_code"])
    ):
        return render(request, "Validation error")
    if state.scenario == "validation":
        return render(request, "Validation error")
    rows = {
        "Member reference": state.member,
        **state.record,
        **{item.label: values[item.name] for item in service.fields},
        "Status": "Ready for review",
    }
    return render(request, service.review_screen, service=service, stage="review", rows=rows)


@app.post("/workspace/services/{slug}/commit", response_class=HTMLResponse)
async def service_commit(request: Request, slug: str) -> HTMLResponse:
    service_context(request, slug)
    # Even manual exploration cannot produce a real or simulated financial mutation.
    return render(request, "Submission unavailable in training")
