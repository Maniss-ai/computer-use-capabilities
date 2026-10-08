import asyncio
import re

import httpx
import pytest

from capabilities.errors import ExecutionError
from capabilities.evidence import Evidence
from capabilities.operator import create_operator_app
from capabilities.session import SessionController


async def test_control_transfer_fences_stale_requests(tmp_path):
    control = SessionController(Evidence(tmp_path, "control"), interactive=True)
    control.owner = "waiting"
    await control.claim(0)
    with pytest.raises(ExecutionError):
        await control.claim(0)
    with pytest.raises(ExecutionError):
        await control.resume(0)
    await control.resume(1)
    assert control.owner == "checking"


async def test_operator_origin_csrf_and_stale_epoch(tmp_path):
    control = SessionController(Evidence(tmp_path, "operator"), interactive=True)
    control.owner = "waiting"
    origin = "http://127.0.0.1:8766"
    transport = httpx.ASGITransport(app=create_operator_app(control, origin))
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        html = (await client.get("/")).text
        csrf = re.search("const csrf='([^']+)'", html).group(1)
        assert (await client.post("/api/claim", json={"epoch": 0})).status_code == 403
        assert (
            await client.post(
                "/api/claim",
                json={"epoch": 0},
                headers={"Origin": "https://evil.test", "X-Operator-CSRF": csrf},
            )
        ).status_code == 403
        headers = {"Origin": origin, "X-Operator-CSRF": csrf}
        assert (
            await client.post("/api/claim", json={"epoch": 0}, headers=headers)
        ).status_code == 200
        assert (
            await client.post("/api/claim", json={"epoch": 0}, headers=headers)
        ).status_code == 409
        assert (await client.get("/", headers={"Host": "evil.test"})).status_code == 400


async def test_claim_waits_for_inflight_action(tmp_path):
    control = SessionController(Evidence(tmp_path, "inflight"))
    async with control.automation():
        task = asyncio.create_task(control.claim(0))
        await asyncio.sleep(0.01)
        assert not task.done()
    with pytest.raises(ExecutionError):
        await task
