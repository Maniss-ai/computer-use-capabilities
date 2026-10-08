import asyncio
import json

import pytest
from conftest import events, wait_owner

from capabilities.contracts import Click, Target
from capabilities.engine import ReplayEngine
from capabilities.errors import ExecutionError

pytestmark = pytest.mark.browser


async def test_replay_returns_new_inputs_without_a_model(
    browser_factory, artifact, inputs, monkeypatch
):
    import anthropic

    monkeypatch.setattr(
        anthropic, "AsyncAnthropic", lambda **kw: pytest.fail("Replay initialized a model")
    )
    async with browser_factory() as (surface, control, evidence, executor):
        result = await ReplayEngine(executor).run(artifact, inputs)
        assert result.status == "success", result
        assert result.outputs == {**inputs, "review_ready": True}
        assert result.model_calls == 0
        assert await surface.screen() == "Review sub-account"
        log = (evidence.root / "events.jsonl").read_text()
        assert inputs["member_id"] not in log and inputs["nickname"] not in log
        assert (
            json.loads((evidence.root / "result.json").read_text())["outputs"]["nickname"]
            == "[REDACTED]"
        )


@pytest.mark.parametrize(
    "scenario,status,code",
    [
        ("slow", "success", None),
        ("interstitial", "success", None),
        ("permission_denied", "failure", "permission_denied"),
        ("app_error", "failure", "app_unavailable"),
        ("validation", "business_outcome", "validation_error"),
        ("unexpected_dialog", "failure", "intervention_required"),
        ("session_expired", "failure", "intervention_required"),
        ("visual_missing", "failure", "intervention_required"),
        ("ambiguous", "failure", "intervention_required"),
        ("prompt_injection", "success", None),
    ],
)
async def test_runtime_scenarios(browser_factory, artifact, inputs, scenario, status, code):
    async with browser_factory(scenario) as (_, _, evidence, executor):
        result = await ReplayEngine(executor).run(artifact, inputs)
        assert result.status == status, result
        if status == "failure":
            assert result.error.code == code
            assert (evidence.root / result.error.evidence).is_file()
        if status == "business_outcome":
            assert result.outcome == code
        if scenario == "interstitial":
            assert any(x["event"] == "recovery_performed" for x in events(evidence))


async def test_not_found_is_a_business_outcome(browser_factory, artifact, inputs):
    async with browser_factory() as (_, _, _, executor):
        result = await ReplayEngine(executor).run(artifact, {**inputs, "member_id": "99999"})
        assert result.status == "business_outcome"
        assert result.outcome == "member_not_found"
        assert result.error is None


@pytest.mark.parametrize(
    "scenario,button",
    [("session_expired", "Restore session"), ("unexpected_dialog", "Acknowledge notice")],
)
async def test_same_session_handoff(browser_factory, artifact, inputs, scenario, button):
    async with browser_factory(scenario, interactive=True) as (
        surface,
        control,
        evidence,
        executor,
    ):
        page = surface.page
        context = surface.context
        task = asyncio.create_task(ReplayEngine(executor).run(artifact, inputs))
        await wait_owner(control, "waiting")
        await control.claim(control.epoch)
        with pytest.raises(ExecutionError, match="session_not_owned"):
            async with control.automation():
                pass
        # Test actor simulates the operator using the SAME live browser. Clearly labelled in evidence.
        evidence.event("operator_simulation", source="test_fixture")
        await surface.workspace.get_by_role("button", name=button, exact=True).click()
        await control.resume(control.epoch)
        result = await task
        assert result.status == "success", result
        assert result.human_interventions == 1
        assert surface.page is page and surface.context is context
        assert any(x["event"] == "human_action" for x in events(evidence))
        assert any(
            x["event"] == "control_transferred" and x["owner"] == "automation"
            for x in events(evidence)
        )


async def test_resume_rejected_until_state_is_repaired(browser_factory, artifact, inputs):
    async with browser_factory("session_expired", interactive=True) as (
        surface,
        control,
        _,
        executor,
    ):
        task = asyncio.create_task(ReplayEngine(executor).run(artifact, inputs))
        await wait_owner(control, "waiting")
        await control.claim(control.epoch)
        await control.resume(control.epoch)
        await wait_owner(control, "waiting")
        assert not task.done()
        await control.claim(control.epoch)
        await surface.workspace.get_by_role("button", name="Restore session").click()
        await control.resume(control.epoch)
        assert (await task).status == "success"


async def test_intervention_timeout(browser_factory, artifact, inputs):
    async with browser_factory("session_expired", interactive=True, intervention_timeout=1) as (
        _,
        _,
        _,
        executor,
    ):
        result = await ReplayEngine(executor).run(artifact, inputs)
        assert result.error.code == "intervention_timeout"


async def test_final_commit_and_external_navigation_blocked(browser_factory, artifact, inputs):
    async with browser_factory() as (surface, _, evidence, executor):
        assert (await ReplayEngine(executor).run(artifact, inputs)).status == "success"
        with pytest.raises(ExecutionError, match="action_blocked"):
            executor.policy.authorize(
                "Review sub-account", Click(target=Target(kind="button", name="Create account"))
            )
        # Network policy also protects the browser when a human clicks a forbidden final action.
        async with surface.page.expect_request("**/workspace/commit"):
            await surface.workspace.get_by_role("button", name="Create account").click()
        async with asyncio.timeout(2):
            while not surface.blocked:  # noqa: ASYNC110
                await asyncio.sleep(0.01)
        assert surface.blocked
        assert any(x["event"] == "navigation_blocked" for x in events(evidence))


async def test_failure_screenshot_masks_sensitive_input(browser_factory, artifact, inputs):
    from PIL import Image

    async with browser_factory() as (surface, _, evidence, executor):
        await executor.act(artifact.steps[0].action, inputs, "Find a member")
        image_name = await surface.failure_evidence()
        input_box = await surface.workspace.get_by_label("Member ID").bounding_box()
        image = Image.open(evidence.root / image_name).convert("RGB")
        center = (
            int(input_box["x"] + input_box["width"] / 2),
            int(input_box["y"] + input_box["height"] / 2),
        )
        assert image.getpixel(center) == (37, 55, 70)


async def test_modified_success_check_fails(browser_factory, artifact, inputs):
    from capabilities.contracts import Check, Constant

    checks = artifact.goal.checks + (
        Check(target=Target(kind="field", name="Status"), equals=Constant(value="Account created")),
    )
    changed = artifact.model_copy(
        update={"goal": artifact.goal.model_copy(update={"checks": checks})}
    )
    async with browser_factory() as (_, _, _, executor):
        result = await ReplayEngine(executor).run(changed, inputs)
        assert result.error.code == "success_check_failed"


async def test_unknown_profile_is_rejected_before_acting(browser_factory, artifact, inputs):
    changed = artifact.model_copy(update={"profile": "different-vendor/v2"})
    async with browser_factory() as (_, _, evidence, executor):
        result = await ReplayEngine(executor).run(changed, inputs)
        assert result.status == "failure" and result.error.code == "profile_incompatible"
        assert not any(x["event"] == "action_started" for x in events(evidence))


async def test_policy_rejects_tampered_artifact_before_acting(browser_factory, artifact, inputs):
    changed = artifact.model_copy(
        update={
            "steps": (
                artifact.steps[0].model_copy(
                    update={
                        "action": Click(target=Target(kind="button", name="Create account")),
                    }
                ),
            )
        }
    )
    async with browser_factory() as (_, _, evidence, executor):
        result = await ReplayEngine(executor).run(changed, inputs)
        assert result.error.code == "action_blocked"
        assert not any(x["event"] == "action_started" for x in events(evidence))


async def test_ambiguous_extraction_is_rejected(browser_factory, artifact, inputs):
    async with browser_factory() as (surface, _, _, executor):
        assert (await ReplayEngine(executor).run(artifact, inputs)).status == "success"
        # Introduce a duplicate visible row; never silently select the first result.
        await surface.workspace.locator("table.data").evaluate(
            "(table) => table.append(table.rows[0].cloneNode(true))"
        )
        with pytest.raises(ExecutionError, match="target_ambiguous"):
            await surface.read(Target(kind="field", name="Member reference"))


async def test_privacy_classification_cannot_be_weakened(browser_factory, artifact, inputs):
    outputs = {
        **artifact.goal.outputs,
        "member_id": artifact.goal.outputs["member_id"].model_copy(update={"sensitive": False}),
    }
    changed = artifact.model_copy(
        update={"goal": artifact.goal.model_copy(update={"outputs": outputs})}
    )
    async with browser_factory() as (_, _, evidence, executor):
        result = await ReplayEngine(executor).run(changed, inputs)
        assert result.error.code == "privacy_contract_rejected"
        assert not any(x["event"] == "action_started" for x in events(evidence))


async def test_native_dialog_is_cancelled_and_fails_closed(browser_factory):
    async with browser_factory() as (surface, _, evidence, executor):
        assert not await surface.page.evaluate('confirm("Sensitive message must never be logged")')
        with pytest.raises(ExecutionError, match="native_dialog_cancelled"):
            await executor.guard()
        assert "Sensitive message" not in (evidence.root / "events.jsonl").read_text()


async def test_operator_webpage_controls_the_live_session(browser_factory, artifact, inputs):
    from scripts.offline_evidence import simulated_operator

    async with browser_factory("session_expired", interactive=True) as (
        surface,
        control,
        evidence,
        executor,
    ):
        page_id = surface.page
        operator = asyncio.create_task(simulated_operator(surface, control, "Restore session"))
        result = await ReplayEngine(executor).run(artifact, inputs)
        await operator
        assert result.status == "success", result
        assert surface.page is page_id
        assert (evidence.root / "operator-console.png").exists()
        assert any(e.get("manual_control") == "Restore session" for e in events(evidence))
