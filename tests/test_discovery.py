import pytest

from capabilities.contracts import Decision
from capabilities.discovery import DiscoveryEngine
from capabilities.engine import ReplayEngine


class FixturePlanner:
    """Test double only. Never describe its output as genuine model discovery."""

    source = "test_fixture"
    model = "scripted-test-double"
    calls = 0
    tokens = 0

    def __init__(self, decisions):
        self.decisions = iter(decisions)

    async def decide(self, goal, contract, observation):
        self.calls += 1
        return next(self.decisions)


@pytest.mark.browser
async def test_discovery_compiler_then_replay_real_browser(browser_factory, artifact, inputs):
    decisions = [Decision(action=s.action, reason="advance") for s in artifact.steps]
    decisions.append(Decision(finish=True, reason="verify_goal"))
    async with browser_factory() as (_, _, evidence, executor):
        engine = DiscoveryEngine(executor, FixturePlanner(decisions))
        result = await engine.run("Prepare a sub-account review", artifact.goal, inputs)
        assert result.status == "success", result
        assert engine.artifact.provenance.source == "test_fixture"
        assert (evidence.root / "capability.json").exists()
        compiled = engine.artifact
    async with browser_factory() as (_, _, _, executor):
        result = await ReplayEngine(executor).run(
            compiled, {**inputs, "member_id": "10077", "nickname": "Emergency Fund"}
        )
        assert result.status == "success"
        assert result.outputs["member_id"] == "10077"


@pytest.mark.browser
async def test_model_cannot_declare_false_success(browser_factory, artifact, inputs):
    async with browser_factory() as (_, _, evidence, executor):
        engine = DiscoveryEngine(
            executor, FixturePlanner([Decision(finish=True, reason="verify_goal")])
        )
        result = await engine.run("Prepare a sub-account", artifact.goal, inputs)
        assert result.status == "failure"
        assert result.error.code == "checkpoint_mismatch"
        assert not (evidence.root / "capability.json").exists()


@pytest.mark.browser
async def test_discovery_stops_on_no_progress(browser_factory, artifact, inputs):
    decision = Decision(action=artifact.steps[0].action, reason="enter_input")
    async with browser_factory() as (_, _, _, executor):
        result = await DiscoveryEngine(executor, FixturePlanner([decision] * 3)).run(
            "Prepare a sub-account", artifact.goal, inputs
        )
        assert result.error.code == "intervention_required"
        assert result.error.expected == "discovery_no_progress"


@pytest.mark.browser
async def test_exhausted_budget_stops_without_useless_handoff(browser_factory, artifact, inputs):
    decision = Decision(action=artifact.steps[0].action, reason="enter_input")
    async with browser_factory(interactive=True) as (_, control, _, executor):
        executor.policy = executor.policy.model_copy(update={"max_steps": 1})
        result = await DiscoveryEngine(executor, FixturePlanner([decision])).run(
            "Prepare a sub-account", artifact.goal, inputs
        )
        assert result.error.code == "step_budget_exceeded"
        assert result.human_interventions == 0
        assert control.owner == "closed"


@pytest.mark.browser
async def test_rejected_model_target_is_not_copied_into_evidence(browser_factory, artifact, inputs):
    action = artifact.steps[0].action
    private_target = "private-model-invented-label"
    action = action.model_copy(
        update={"target": action.target.model_copy(update={"name": private_target})}
    )
    async with browser_factory() as (_, _, evidence, executor):
        result = await DiscoveryEngine(
            executor, FixturePlanner([Decision(action=action, reason="enter_input")])
        ).run("Prepare a review", artifact.goal, inputs)
        assert result.error.code == "action_blocked"
        assert result.error.observed == "no_matching_permission"
        events = (evidence.root / "events.jsonl").read_text()
        assert "[UNRECOGNIZED]" in events
        assert private_target not in events
        assert "action_started" not in events
