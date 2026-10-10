"""Exercise web orchestration against real browsers, including same-session takeover."""

import asyncio
import json
import re
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from playwright.async_api import async_playwright, expect

from capabilities.contracts import Decision
from capabilities.dashboard import codespaces_origins, create_dashboard_app
from capabilities.errors import ExecutionError
from tests.test_discovery import FixturePlanner


@pytest.fixture
async def studio(tmp_path, sandbox_url):
    origin = "http://127.0.0.1:8766"
    app = create_dashboard_app(origin, sandbox_url, tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        html = (await client.get("/")).text
        csrf = re.search(r'name="studio-csrf" content="([^"]+)"', html).group(1)
        client.headers.update({"X-Studio-CSRF": csrf, "Origin": origin})
        catalog = (await client.get("/api/catalog")).json()
        body = {
            "capability_id": catalog["capabilities"][0]["id"],
            "inputs": {
                "member_id": "10077",
                "product": "Checking",
                "nickname": "Web private nickname",
            },
        }
        yield client, app.state.manager, body
    await app.state.manager.close()


async def wait_run(manager, run_id, *, owner=None):
    run = manager.runs[run_id]
    async with asyncio.timeout(25):
        while run.control.owner != owner if owner else not run.task.done():  # noqa: ASYNC110 - poll public state
            await asyncio.sleep(0.04)
    return run


async def test_web_api_rejects_cross_origin_stale_catalog_and_invalid_inputs(studio, monkeypatch):
    client, manager, body = studio
    expired = await client.post("/api/runs", json=body, headers={"X-Studio-CSRF": "wrong"})
    assert expired.status_code == 403
    assert expired.headers["x-studio-error"] == "stale-session"
    for token in ["wrong", client.headers["X-Studio-CSRF"]]:
        cross_origin = await client.post(
            "/api/runs",
            json=body,
            headers={"Origin": "https://evil.test", "X-Studio-CSRF": token},
        )
        assert cross_origin.status_code == 403
        assert "x-studio-error" not in cross_origin.headers
    assert (await client.get("/", headers={"Host": "evil.test"})).status_code == 400
    assert (
        await client.post("/api/runs", json={**body, "capability_id": "0" * 64})
    ).status_code == 404
    invalid = {**body, "inputs": {**body["inputs"], "member_id": "123"}}
    response = await client.post("/api/runs", json=invalid)
    assert response.status_code == 422
    assert "Web private nickname" not in response.text
    response = await client.post("/api/runs", json={**body, "scenario": "../../.env"})
    assert response.status_code == 422 and "../../.env" not in response.text
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert (await client.post("/api/runs", json={**body, "mode": "discover"})).status_code == 422
    assert not manager.runs


@pytest.mark.browser
async def test_stale_dashboard_recovers_and_starts_exactly_one_run(studio_url):
    origin, manager, _ = studio_url
    async with async_playwright() as runtime:
        browser = await runtime.chromium.launch()
        page = await browser.new_page()
        documents = 0
        posts = 0

        async def stale_document(route):
            nonlocal documents
            documents += 1
            response = await route.fetch()
            html = await response.text()
            if documents == 1:
                html = re.sub(
                    r'name="studio-csrf" content="[^"]+"',
                    'name="studio-csrf" content="expired"',
                    html,
                )
            await route.fulfill(response=response, body=html)

        async def expire_start(route):
            nonlocal posts
            if route.request.method == "POST":
                posts += 1
                if posts == 1:
                    # Exercise the real authorization rejection, before the handler runs.
                    await route.continue_(
                        headers={**route.request.headers, "x-studio-csrf": "expired-again"}
                    )
                    return
            await route.continue_()

        try:
            await page.route(origin + "/", stale_document)
            await page.route(origin + "/api/runs", expire_start)
            await page.goto(origin)
            await expect(page.locator(".workflow-card")).to_have_count(6)
            assert documents == 2
            await page.get_by_label("Member ID", exact=True).fill("10042")
            await page.get_by_label("Account nickname").fill("Preserved after reconnect")
            await page.get_by_role("button", name="Run capability", exact=False).click()
            await expect(page.locator("#run-status")).to_have_text("Success", timeout=20000)
            await expect(page.locator("#outputs")).to_contain_text("Preserved after reconnect")
            await expect(page.get_by_label("Member ID", exact=True)).to_have_value("10042")
            await expect(page.locator("#form-error")).to_be_empty()
            await expect(page.locator("#browser-image")).to_be_visible()
            assert documents == 3 and posts == 2 and len(manager.runs) == 1
            assert next(iter(manager.runs.values())).result.model_calls == 0
        finally:
            await browser.close()


@pytest.mark.browser
async def test_dashboard_clears_missing_run_without_losing_workflow_inputs(studio_url):
    origin, manager, server_loop = studio_url
    async with async_playwright() as runtime:
        browser = await runtime.chromium.launch()
        page = await browser.new_page()
        try:
            await page.goto(origin)
            await page.get_by_role("button", name="Run capability", exact=False).click()
            await expect(page.locator("#run-status")).to_have_text("Success", timeout=20000)
            await page.get_by_label("Banking workflow", exact=True).select_option(
                "card-replacement"
            )
            await page.get_by_role("button", name="Member 10042", exact=True).click()

            async def discard_session():
                await manager.close()
                manager.runs.clear()

            await asyncio.wrap_future(
                asyncio.run_coroutine_threadsafe(discard_session(), server_loop)
            )
            await expect(page.locator("#run-status")).to_have_text("Ready", timeout=10000)
            await expect(page.get_by_role("heading", name="Dashboard reconnected")).to_be_visible()
            await expect(page.locator("#history-list button")).to_have_count(0)
            await expect(page.locator("#browser-image")).to_be_hidden()
            await expect(page.locator("#stop")).to_be_hidden()
            await expect(page.locator("#result-content")).to_be_hidden()
            await expect(page.get_by_label("Card reference", exact=True)).to_have_value(
                "CARD-10042"
            )
            await expect(page.get_by_label("Banking workflow", exact=True)).to_have_value(
                "card-replacement"
            )
            await expect(
                page.get_by_role("button", name="Discover and save", exact=False)
            ).to_be_enabled()
            await expect(page.locator("#form-error")).to_be_empty()
        finally:
            await browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("failure", ["forbidden", "invalid", "network", "expired"])
async def test_start_failure_is_visible_and_never_retried_unsafely(studio_url, failure):
    origin, manager, _ = studio_url
    async with async_playwright() as runtime:
        browser = await runtime.chromium.launch()
        page = await browser.new_page()
        posts = 0
        documents = []
        page.on(
            "request",
            lambda request: documents.append(request.url) if request.url == origin + "/" else None,
        )

        async def reject_start(route):
            nonlocal posts
            if route.request.method != "POST":
                await route.continue_()
                return
            posts += 1
            if failure == "network":
                await route.abort("failed")
            elif failure == "expired":
                await route.continue_(headers={**route.request.headers, "x-studio-csrf": "expired"})
            else:
                await route.fulfill(
                    status=403 if failure == "forbidden" else 422,
                    json={"detail": "Start rejected for testing"},
                )

        try:
            await page.route(origin + "/api/runs", reject_start)
            await page.goto(origin)
            await page.get_by_label("Account nickname").fill("Keep this input")
            await page.get_by_role("button", name="Run capability", exact=False).click()
            await expect(page.locator("#run-status")).to_have_text(
                "Connection lost" if failure == "network" else "Not started"
            )
            await expect(page.locator("#empty-state h2")).to_have_text(
                "Could not confirm a new run"
            )
            await expect(page.locator("#form-error")).not_to_be_empty()
            await expect(
                page.get_by_role("button", name="Run capability", exact=False)
            ).to_be_enabled()
            await expect(page.get_by_label("Account nickname")).to_have_value("Keep this input")
            assert not manager.runs
            assert posts == (2 if failure == "expired" else 1)
            assert len(documents) == (2 if failure == "expired" else 1)
        finally:
            await browser.close()


async def test_workflow_catalog_has_goals_without_fake_capabilities(studio):
    client, manager, body = studio
    data = (await client.get("/api/catalog")).json()
    assert len(data["workflows"]) == 6
    assert {cap["workflow_id"] for cap in data["capabilities"]} == {"subaccount"}
    assert all("steps" not in item["contract"] for item in data["workflows"])
    assert (
        await client.post("/api/runs", json={**body, "workflow_id": "card-replacement"})
    ).status_code == 422
    assert (
        await client.post("/api/runs", json={"workflow_id": "card-replacement", "inputs": {}})
    ).status_code == 422
    assert (
        await client.post("/api/runs", json={**body, "workflow_id": "unknown"})
    ).status_code == 404
    assert not manager.runs


@pytest.mark.browser
async def test_web_replay_outputs_preview_redaction_and_single_writer(studio, monkeypatch):
    client, manager, body = studio

    def forbidden(*args, **kwargs):
        raise AssertionError("Replay must not initialize any model")

    monkeypatch.setattr("capabilities.gemini.GeminiPlanner.__init__", forbidden)
    monkeypatch.setattr("capabilities.discovery.AnthropicPlanner.__init__", forbidden)
    response = await client.post("/api/runs", json=body)
    assert response.status_code == 202
    run_id = response.json()["id"]
    assert (await client.post("/api/runs", json=body)).status_code == 409
    assert (
        await client.post(f"/api/runs/{run_id}/pointer", json={"epoch": 0, "x": 10, "y": 10})
    ).status_code == 409
    run = await wait_run(manager, run_id)
    state = (await client.get(f"/api/runs/{run_id}")).json()
    assert state["result"]["status"] == "success"
    assert state["result"]["outputs"] == {**body["inputs"], "review_ready": True}
    assert state["model_calls"] == 0 and state["completed_actions"] == 6
    assert state["screen"] == "Review sub-account"
    image = await client.get(f"/api/runs/{run_id}/preview")
    assert image.headers["content-type"] == "image/jpeg" and image.content[:2] == b"\xff\xd8"
    assert image.headers["cache-control"] == "no-store"
    assert run.surface.browser.is_connected() is False
    for path in run.evidence.root.glob("*.json*"):
        assert body["inputs"]["nickname"] not in path.read_text()
        assert body["inputs"]["member_id"] not in path.read_text()
    assert list(run.evidence.root.glob("checkpoint-*.png"))
    again = await client.post(
        "/api/runs", json={**body, "inputs": {**body["inputs"], "member_id": "99999"}}
    )
    second = await wait_run(manager, again.json()["id"])
    assert second.result.outcome == "member_not_found"
    assert second.surface.page is not run.surface.page


@pytest.mark.browser
async def test_web_handoff_pointer_restores_same_session_and_rejects_stale_input(studio):
    client, manager, body = studio
    start = await client.post("/api/runs", json={**body, "scenario": "session_expired"})
    run_id = start.json()["id"]
    run = await wait_run(manager, run_id, owner="waiting")
    page, context = run.surface.page, run.surface.context
    epoch = run.control.epoch
    assert (
        await client.post(f"/api/runs/{run_id}/control/claim", json={"epoch": epoch})
    ).status_code == 200
    assert (
        await client.post(f"/api/runs/{run_id}/pointer", json={"epoch": epoch, "x": 10, "y": 10})
    ).status_code == 409
    # Premature handback must fail, preserving the same browser for another claim.
    await client.post(f"/api/runs/{run_id}/control/resume", json={"epoch": run.control.epoch})
    await wait_run(manager, run_id, owner="waiting")
    assert run.control.reason == "resume_checkpoint_mismatch"
    await client.post(f"/api/runs/{run_id}/control/claim", json={"epoch": run.control.epoch})
    box = await run.surface.workspace.get_by_role("button", name="Restore session").bounding_box()
    response = await client.post(
        f"/api/runs/{run_id}/pointer",
        json={
            "epoch": run.control.epoch,
            "x": box["x"] + box["width"] / 2,
            "y": box["y"] + box["height"] / 2,
        },
    )
    assert response.status_code == 200
    await run.surface.wait_screen("Member details")
    assert run.surface.page is page and run.surface.context is context
    await client.post(f"/api/runs/{run_id}/control/resume", json={"epoch": run.control.epoch})
    await wait_run(manager, run_id)
    assert run.result.status == "success" and run.result.human_interventions == 1
    assert any(
        e["event"] == "human_action" and e.get("manual_control") == "Restore session"
        for e in run.events()
    )
    assert (
        await client.post(
            f"/api/runs/{run_id}/text", json={"epoch": run.control.epoch, "text": "forbidden"}
        )
    ).status_code == 409


@pytest.mark.browser
async def test_web_stop_closes_session_and_reports_failure(studio):
    client, manager, body = studio
    response = await client.post("/api/runs", json={**body, "scenario": "session_expired"})
    run_id = response.json()["id"]
    run = await wait_run(manager, run_id, owner="waiting")
    response = await client.post(f"/api/runs/{run_id}/stop", json={})
    assert response.json()["result"]["error"]["code"] == "operator_cancelled"
    assert run.control.owner == "closed" and not run.surface.browser.is_connected()
    assert not (run.evidence.root / "capability.json").exists()


@pytest.mark.browser
async def test_web_discovery_compiles_catalog_entry_without_faking_live_provenance(
    studio, monkeypatch
):
    client, manager, body = studio
    seed = manager.catalog()[body["capability_id"]]

    class WebFixturePlanner(FixturePlanner):
        def __init__(self, *args, **kwargs):
            super().__init__(
                [
                    *(Decision(action=s.action, reason="advance") for s in seed.steps),
                    Decision(finish=True, reason="verify_goal"),
                ]
            )

        async def close(self):
            pass

    monkeypatch.setenv("GEMINI_API_KEY", "test-fixture-key")
    monkeypatch.setattr("capabilities.gemini.GeminiPlanner", WebFixturePlanner)
    start = await client.post("/api/runs", json={**body, "mode": "discover"})
    run = await wait_run(manager, start.json()["id"])
    assert run.result.status == "success"
    catalog = (await client.get("/api/catalog")).json()["capabilities"]
    saved = next(c for c in catalog if c["provenance"]["run_id"] == run.evidence.run_id)
    assert saved["provenance"]["source"] == "test_fixture"
    replay = await client.post(
        "/api/runs",
        json={
            **body,
            "capability_id": saved["id"],
            "inputs": {**body["inputs"], "member_id": "10023"},
        },
    )
    result = await wait_run(manager, replay.json()["id"])
    assert result.result.outputs["member_id"] == "10023" and result.result.model_calls == 0
    assert "test-fixture-key" not in json.dumps(catalog)


@pytest.fixture
def studio_url(tmp_path, sandbox_url):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
    app = create_dashboard_app(origin, sandbox_url, tmp_path)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    state = {}

    async def serve():
        state["loop"] = asyncio.get_running_loop()
        await server.serve(sockets=[sock])

    thread = threading.Thread(target=lambda: asyncio.run(serve()), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("Dashboard did not start")
        time.sleep(0.02)
    yield origin, app.state.manager, state["loop"]
    server.should_exit = True
    thread.join(timeout=10)
    sock.close()


@pytest.mark.browser
async def test_dashboard_browser_controls_replay_and_handoff(studio_url):
    origin, manager, server_loop = studio_url
    async with async_playwright() as runtime:
        browser = await runtime.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1100})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            await page.goto(origin)
            await expect(page.locator("#capability-meta")).to_contain_text("AI-discovered")
            await page.get_by_label("Member ID", exact=True).fill("10042")
            await page.get_by_label("Account nickname").fill("Browser demo")
            await page.get_by_role("button", name="Run capability", exact=False).click()
            await expect(page.locator("#run-status")).to_have_text("Success", timeout=20000)
            await expect(page.locator("#outputs")).to_contain_text("Browser demo")
            await expect(page.locator("#model-count")).to_have_text("0")
            await expect(page.locator("#browser-image")).to_be_visible()
            await page.get_by_label("Test scenario").select_option("session_expired")
            await page.get_by_role("button", name="Run capability", exact=False).click()
            await expect(page.get_by_role("button", name="Claim session")).to_be_visible(
                timeout=15000
            )
            await page.get_by_role("button", name="Claim session").click()
            await expect(page.locator("#human-tools")).to_be_visible()
            # Locate the test target in the server-owned browser, then interact only
            # through the real scaled preview and its pointer endpoint.
            run = list(manager.runs.values())[-1]
            future = asyncio.run_coroutine_threadsafe(
                run.surface.workspace.get_by_role("button", name="Restore session").bounding_box(),
                server_loop,
            )
            target = await asyncio.wrap_future(future)
            image = page.locator("#browser-image")
            box = await image.bounding_box()
            await image.click(
                position={
                    "x": (target["x"] + target["width"] / 2) / 1280 * box["width"],
                    "y": (target["y"] + target["height"] / 2) / 900 * box["height"],
                }
            )
            await expect(page.locator("#screen-name")).to_have_text("Member details", timeout=10000)
            await page.get_by_role("button", name="Return to automation").click()
            await expect(page.locator("#run-status")).to_have_text("Success", timeout=20000)
            assert not errors
            await page.set_viewport_size({"width": 390, "height": 844})
            assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        finally:
            await browser.close()


@pytest.mark.browser
async def test_new_workflow_web_discovery_then_matching_replay(studio_url, monkeypatch):
    from capabilities.workflows import workflows
    from tests.test_workflows import fixture_decisions

    workflow = workflows()["transaction-dispute"]

    class WebFixturePlanner(FixturePlanner):
        def __init__(self, *args, **kwargs):
            super().__init__(fixture_decisions(workflow))

        async def close(self):
            pass

    monkeypatch.setenv("GEMINI_API_KEY", "test-fixture-key")
    monkeypatch.setattr("capabilities.gemini.GeminiPlanner", WebFixturePlanner)
    origin, manager, _ = studio_url
    async with async_playwright() as runtime:
        browser = await runtime.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1100})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            await page.goto(origin)
            await expect(page.locator(".workflow-card")).to_have_count(6)
            await page.get_by_label("Banking workflow", exact=True).select_option(workflow.id)
            await expect(page.locator("#discover-mode")).to_have_attribute("aria-pressed", "true")
            await expect(page.get_by_label("Transaction reference", exact=True)).to_have_value(
                "TXN-10023"
            )
            await page.get_by_role("button", name="Discover and save", exact=False).click()
            await expect(page.locator("#run-status")).to_have_text("Success", timeout=30000)
            discovery = list(manager.runs.values())[-1]
            assert discovery.workflow.id == workflow.id
            assert discovery.capability is None  # Discovery did not need an existing sequence.
            await page.get_by_role("button", name="Use this capability with new inputs").click()
            await expect(page.locator("#capability")).to_contain_text(
                discovery.evidence.run_id[-6:]
            )
            await page.get_by_role("button", name="Member 10042", exact=True).click()
            await expect(page.get_by_label("Transaction reference", exact=True)).to_have_value(
                "TXN-10042"
            )
            await page.get_by_role("button", name="Run capability", exact=False).click()
            await expect(page.locator("#run-status")).to_have_text("Running", timeout=10000)
            await expect(page.locator("#run-status")).to_have_text("Success", timeout=30000)
            await expect(page.locator("#outputs")).to_contain_text("USD 126.50")
            await expect(page.locator("#model-count")).to_have_text("0")
            await page.set_viewport_size({"width": 390, "height": 844})
            assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert not errors
        finally:
            await browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("recovers", [True, False])
async def test_dashboard_shows_model_retry_and_actionable_timeout(
    studio_url, monkeypatch, artifact, recovers
):
    class TimeoutFixturePlanner(FixturePlanner):
        def __init__(self, *args, **kwargs):
            super().__init__(
                [
                    *(Decision(action=s.action, reason="advance") for s in artifact.steps),
                    Decision(finish=True, reason="verify_goal"),
                ]
            )

        async def decide(self, goal, contract, observation):
            if self.calls == 2 or (not recovers and self.calls == 3):
                self.calls += 1
                raise ExecutionError("model_timeout")
            return await super().decide(goal, contract, observation)

        async def close(self):
            pass

    monkeypatch.setenv("GEMINI_API_KEY", "test-fixture-key")
    monkeypatch.setattr("capabilities.gemini.GeminiPlanner", TimeoutFixturePlanner)
    origin, manager, _ = studio_url
    async with async_playwright() as runtime:
        browser = await runtime.chromium.launch()
        page = await browser.new_page()
        try:
            await page.goto(origin)
            await page.get_by_role("button", name="Discover with AI", exact=True).click()
            await page.get_by_role("button", name="Discover and save", exact=False).click()
            await expect(page.locator("#run-status")).to_have_text(
                "Success" if recovers else "Stopped", timeout=20000
            )
            if not recovers:
                await expect(page.locator("#result-message")).to_contain_text(
                    "The model did not respond in time"
                )
                await expect(page.locator("#result-message")).to_contain_text(
                    "No capability was saved"
                )
            await page.get_by_role("button", name="Activity", exact=True).click()
            await expect(page.locator("#events")).to_contain_text(
                "Temporary model failure · retrying decision"
            )
            run = next(iter(manager.runs.values()))
            assert run.planner.calls == (8 if recovers else 4)
            assert sum(e["event"] == "action_completed" for e in run.events()) == (
                6 if recovers else 2
            )
            assert (run.evidence.root / "capability.json").exists() is recovers
        finally:
            await browser.close()


@pytest.mark.parametrize(
    "variable,value,port",
    [
        ("CODESPACES", "false", 8766),
        ("CODESPACE_NAME", "demo.evil.test/path", 8766),
        ("CODESPACE_NAME", "demo\r\nHost: evil.test", 8766),
        ("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "evil.test", 8766),
        ("CODESPACES", "true", 0),
    ],
)
def test_codespaces_rejects_invalid_forwarding_configuration(monkeypatch, variable, value, port):
    monkeypatch.setenv("CODESPACES", "true")
    monkeypatch.setenv("CODESPACE_NAME", "reviewer-demo-abc123")
    monkeypatch.setenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev")
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValueError):
        codespaces_origins(port, 8767)


@pytest.mark.browser
async def test_private_forwarding_preserves_csrf_and_internal_browser_replay(
    monkeypatch, tmp_path, sandbox_url
):
    monkeypatch.setenv("CODESPACES", "true")
    monkeypatch.setenv("CODESPACE_NAME", "reviewer-demo-abc123")
    monkeypatch.setenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev")
    origin, public_bank = codespaces_origins(8766, 8767)
    app = create_dashboard_app(origin, sandbox_url, tmp_path, bank_public_origin=public_bank)
    manager = app.state.manager
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        try:
            html = (await client.get("/")).text
            csrf = re.search(r'name="studio-csrf" content="([^"]+)"', html).group(1)
            assert (await client.get("/api/catalog")).status_code == 403
            client.headers.update({"Origin": origin, "X-Studio-CSRF": csrf})
            catalog = (await client.get("/api/catalog")).json()
            assert catalog["bank_origin"] == public_bank
            assert manager.bank_origin == sandbox_url
            body = {
                "capability_id": catalog["capabilities"][0]["id"],
                "inputs": {"member_id": "10042", "product": "Checking", "nickname": "Cloud demo"},
            }
            assert (
                await client.post("/api/runs", json=body, headers={"Origin": "https://evil.test"})
            ).status_code == 403
            assert (
                await client.get("/", headers={"Host": "another-8766.app.github.dev"})
            ).status_code == 400
            forged = await client.post(
                "/api/runs",
                json=body,
                headers={"Origin": "https://evil.test", "X-Forwarded-Host": origin.split("//")[1]},
            )
            assert forged.status_code == 403 and not manager.runs
            response = await client.post("/api/runs", json=body)
            assert response.status_code == 202
            run = await wait_run(manager, response.json()["id"])
            assert run.result.status == "success" and run.result.model_calls == 0
            assert run.result.outputs["member_id"] == "10042"
            assert run.result.outputs["nickname"] == "Cloud demo"
            assert run.surface.policy.origin == sandbox_url
        finally:
            await manager.close()
