"""Six independent goals exercised through the real UI, with explicit test planners."""

import json
from contextlib import asynccontextmanager

import httpx
import pytest

from capabilities.cli import load_policy
from capabilities.contracts import Click, Decision, Fill, InputRef, Select, Target
from capabilities.discovery import DiscoveryEngine
from capabilities.engine import Executor, ReplayEngine
from capabilities.evidence import Evidence
from capabilities.session import SessionController
from capabilities.surface import BrowserSurface
from capabilities.workflows import workflow_for_goal, workflows
from tests.test_discovery import FixturePlanner

WORKFLOWS = workflows()
SERVICES = {
    "card-replacement": ("Card services", "Prepare replacement", "card_reference"),
    "transaction-dispute": ("Transaction disputes", "Prepare dispute", "transaction_reference"),
    "address-change": ("Contact maintenance", "Prepare address change", None),
    "statement-request": (
        "Statements and documents",
        "Prepare statement request",
        "account_reference",
    ),
    "fee-adjustment": ("Fee servicing", "Prepare adjustment request", "fee_reference"),
}


async def test_switching_member_discards_previous_service_record():
    # Unit test of the target application's session boundary, not an engine shortcut.
    from capabilities.sandbox.app import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.get("/")
        await client.post("/workspace/search", data={"member_id": "10023"})
        await client.get("/workspace/services/card-replacement")
        found = await client.post(
            "/workspace/services/card-replacement/lookup", data={"card_reference": "CARD-10023"}
        )
        assert "Card details" in found.text
        await client.post("/workspace/search", data={"member_id": "10042"})
        result = await client.get("/workspace/services/card-replacement/prepare")
        assert "Service record not found" in result.text
        assert "CARD-10023" not in result.text


def fixture_decisions(workflow):
    """Authored test sequence. Production discovery never imports this helper."""

    def click(name, kind="button"):
        return Click(target=Target(kind=kind, name=name))

    def enter(name):
        spec = workflow.contract.inputs[name]
        cls = Select if spec.choices else Fill
        return cls(
            target=Target(kind="label", name=workflow.labels[name]), value=InputRef(name=name)
        )

    actions = [enter("member_id"), click("Search")]
    if workflow.id == "subaccount":
        actions.extend(
            [
                click("New sub-account", "visual"),
                enter("product"),
                Fill(target=Target(kind="label", name="Nickname"), value=InputRef(name="nickname")),
            ]
        )
    else:
        hub, prepare, reference = SERVICES[workflow.id]
        actions.append(click(hub))
        if reference:
            actions.extend([enter(reference), click("Find record")])
        actions.append(click(prepare))
        actions.extend(
            enter(name) for name in workflow.contract.inputs if name not in {"member_id", reference}
        )
    actions.append(click("Review request"))
    return [
        *(Decision(action=action, reason="advance") for action in actions),
        Decision(finish=True, reason="verify_goal"),
    ]


@asynccontextmanager
async def browser_run(root, origin, run_id, inputs, scenario="normal"):
    policy = load_policy(origin)
    evidence = Evidence(
        root, run_id, [inputs[name] for name in policy.sensitive_inputs if name in inputs]
    )
    control = SessionController(evidence, 5, interactive=False)
    surface = BrowserSurface(policy, evidence, control)
    try:
        await surface.start(f"{origin}/?scenario={scenario}")
        yield surface, evidence, Executor(surface, policy, control, evidence)
    finally:
        await surface.close()


@pytest.mark.browser
@pytest.mark.parametrize("workflow_id", WORKFLOWS)
async def test_each_goal_compiles_and_replays_with_new_member(
    tmp_path, sandbox_url, workflow_id, monkeypatch
):
    workflow = WORKFLOWS[workflow_id]
    first, second = workflow.examples
    async with browser_run(tmp_path, sandbox_url, "discovery", first) as (
        surface,
        evidence,
        executor,
    ):
        engine = DiscoveryEngine(executor, FixturePlanner(fixture_decisions(workflow)))
        result = await engine.run(workflow.goal, workflow.contract, first)
        assert result.status == "success", result
        artifact = engine.artifact
        assert artifact.provenance.source == "test_fixture"
        assert workflow_for_goal(artifact.goal) == workflow
        for name, value in first.items():
            assert result.outputs[name] == value
        assert result.outputs["review_ready"] is True
        assert all(
            value not in (evidence.root / "capability.json").read_text()
            for name, value in first.items()
            if workflow.contract.inputs[name].sensitive
        )
        # A compiled path must only target allowed controls, and final submit remains blocked.
        route = (
            "/workspace/commit"
            if workflow_id == "subaccount"
            else f"/workspace/services/{workflow_id}/commit"
        )
        assert not surface.policy.allows_url(sandbox_url + route)
        await surface.capture()

    def forbidden(*args, **kwargs):
        raise AssertionError("Replay attempted to initialize a model")

    monkeypatch.setattr("capabilities.gemini.GeminiPlanner.__init__", forbidden)
    monkeypatch.setattr("capabilities.discovery.AnthropicPlanner.__init__", forbidden)
    async with browser_run(tmp_path, sandbox_url, "replay", second) as (_, evidence, executor):
        result = await ReplayEngine(executor).run(artifact, second)
        assert result.status == "success", result
        assert result.model_calls == 0
        for name, value in second.items():
            assert result.outputs[name] == value
        if workflow_id == "transaction-dispute":
            assert result.outputs["transaction_amount"] == "USD 126.50"
        if workflow_id == "fee-adjustment":
            assert result.outputs["fee_amount"] == "USD 8.00"
        for path in evidence.root.glob("*.json*"):
            assert all(
                value not in path.read_text()
                for name, value in second.items()
                if workflow.contract.inputs[name].sensitive
            )


@pytest.mark.browser
@pytest.mark.parametrize("workflow_id", [key for key in SERVICES if key != "address-change"])
@pytest.mark.parametrize(
    "variant,outcome", [("wrong_member", "record_not_found"), ("hold", "request_not_eligible")]
)
async def test_member_scoped_records_and_ineligible_records_stop_without_artifact(
    tmp_path, sandbox_url, workflow_id, variant, outcome
):
    workflow = WORKFLOWS[workflow_id]
    inputs = dict(workflow.examples[0])
    reference = SERVICES[workflow_id][2]
    inputs[reference] = (
        workflow.examples[1][reference]
        if variant == "wrong_member"
        else inputs[reference] + "-HOLD"
    )
    async with browser_run(tmp_path, sandbox_url, "blocked", inputs) as (_, evidence, executor):
        engine = DiscoveryEngine(executor, FixturePlanner(fixture_decisions(workflow)))
        result = await engine.run(workflow.goal, workflow.contract, inputs)
        assert result.status == "business_outcome" and result.outcome == outcome, result
        assert not (evidence.root / "capability.json").exists()


@pytest.mark.browser
async def test_masked_form_progress_and_address_validation(tmp_path, sandbox_url):
    workflow = WORKFLOWS["address-change"]
    inputs = {**workflow.examples[0], "postal_code": "INVALID"}
    async with browser_run(tmp_path, sandbox_url, "address", inputs) as (
        surface,
        evidence,
        executor,
    ):
        decisions = fixture_decisions(workflow)
        before = await surface.observation()
        assert not before["controls"][0]["input_applied"]
        await executor.act(decisions[0].action, inputs, "Find a member")
        after = await surface.observation()
        assert after["controls"][0]["input_applied"]
        assert inputs["member_id"] not in json.dumps(
            {k: v for k, v in after.items() if k != "image_base64"}
        )
        await executor.act(decisions[1].action, inputs, "Find a member")
        assert not surface.applied_inputs
        engine = DiscoveryEngine(executor, FixturePlanner(decisions[2:]))
        result = await engine.run(workflow.goal, workflow.contract, inputs)
        assert result.status == "business_outcome" and result.outcome == "validation_error"
        assert not (evidence.root / "capability.json").exists()
