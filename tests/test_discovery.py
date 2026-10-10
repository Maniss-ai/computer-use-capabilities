import asyncio
from unittest.mock import AsyncMock

import pytest

from capabilities.cli import load_policy
from capabilities.contracts import Decision
from capabilities.discovery import DiscoveryEngine
from capabilities.engine import Executor, ReplayEngine
from capabilities.errors import ExecutionError
from capabilities.evidence import Evidence
from capabilities.session import SessionController
from capabilities.surface import Surface
from tests.conftest import events


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


@pytest.mark.browser
@pytest.mark.parametrize(
    "code", ["model_timeout", "model_connection_failed", "model_service_unavailable"]
)
async def test_transient_failure_reobserves_same_browser_without_repeating_actions(
    browser_factory, artifact, inputs, code
):
    class InterruptedPlanner(FixturePlanner):
        def __init__(self):
            super().__init__(
                [
                    *(Decision(action=s.action, reason="advance") for s in artifact.steps),
                    Decision(finish=True, reason="verify_goal"),
                ]
            )
            self.observations = []

        async def decide(self, goal, contract, observation):
            self.observations.append(observation)
            if self.calls == 2:
                self.calls += 1
                raise ExecutionError(code)
            return await super().decide(goal, contract, observation)

    async with browser_factory() as (surface, _, evidence, executor):
        executor.policy = executor.policy.model_copy(update={"model_retry_delay_seconds": 0})
        page = surface.page
        planner = InterruptedPlanner()
        engine = DiscoveryEngine(executor, planner)
        result = await engine.run("Prepare a review", artifact.goal, inputs)
        assert result.status == "success", result
        assert surface.page is page
        assert len(engine.artifact.steps) == len(artifact.steps) == 6
        assert planner.calls == 8  # Six actions, a finish decision, and one failed request.
        assert planner.observations[2] is not planner.observations[3]
        assert (
            planner.observations[2]["screen"]
            == planner.observations[3]["screen"]
            == "Member details"
        )
        log = events(evidence)
        assert len([e for e in log if e["event"] == "action_completed"]) == 6
        retries = [e for e in log if e["event"] == "model_retry_scheduled"]
        assert len(retries) == 1 and retries[0]["step"] == "step_003"
        assert engine.artifact.provenance.source == "test_fixture"


@pytest.fixture
def retry_executor(tmp_path):
    """No browser required to test bounded waits, cancellation and retry eligibility."""
    evidence = Evidence(tmp_path, "retry-policy")
    policy = load_policy("http://127.0.0.1:8765").model_copy(
        update={"model_retry_delay_seconds": 0}
    )
    surface = AsyncMock(spec=Surface)
    surface.condition.return_value = None
    surface.screen.return_value = "Find a member"
    surface.observation.return_value = {"screen": "Find a member", "controls": []}
    surface.failure_evidence.return_value = "test-failure.png"
    return Executor(surface, policy, SessionController(evidence), evidence)


class FailingPlanner(FixturePlanner):
    def __init__(self, failures):
        super().__init__([])
        self.failures = iter(failures)

    async def decide(self, goal, contract, observation):
        self.calls += 1
        error = next(self.failures)
        if isinstance(error, Exception):
            raise error
        return error


@pytest.mark.parametrize(
    "code",
    [
        "model_authentication_failed",
        "model_permission_denied",
        "model_rate_limited",
        "model_request_invalid",
        "model_protocol_error",
    ],
)
async def test_terminal_model_errors_never_retry(retry_executor, artifact, inputs, code):
    planner = FailingPlanner([ExecutionError(code)])
    result = await DiscoveryEngine(retry_executor, planner).run(
        "Prepare a review", artifact.goal, inputs
    )
    assert result.error.code == code and planner.calls == 1
    retry_executor.surface.execute.assert_not_awaited()
    assert not any(e["event"] == "model_retry_scheduled" for e in events(retry_executor.evidence))


@pytest.mark.parametrize("retry_limit,calls", [(0, 1), (2, 2)])
async def test_repeated_timeout_is_bounded_and_withholds_artifact(
    retry_executor, artifact, inputs, retry_limit, calls
):
    retry_executor.policy = retry_executor.policy.model_copy(
        update={"max_model_retries": retry_limit}
    )
    planner = FailingPlanner([ExecutionError("model_timeout")] * 3)
    engine = DiscoveryEngine(retry_executor, planner)
    result = await engine.run("Prepare a review", artifact.goal, inputs)
    assert result.error.code == "model_timeout" and planner.calls == calls
    assert engine.artifact is None
    assert not (retry_executor.evidence.root / "capability.json").exists()
    retry_executor.surface.execute.assert_not_awaited()


async def test_retry_limit_applies_across_entire_discovery(retry_executor, artifact, inputs):
    action = Decision(action=artifact.steps[0].action, reason="enter_input")
    planner = FailingPlanner([ExecutionError("model_timeout"), action] * 3)
    result = await DiscoveryEngine(retry_executor, planner).run(
        "Prepare a review", artifact.goal, inputs
    )
    assert result.error.code == "model_timeout" and planner.calls == 5
    assert retry_executor.surface.execute.await_count == 2
    assert (
        len([e for e in events(retry_executor.evidence) if e["event"] == "model_retry_scheduled"])
        == 2
    )


class HangingPlanner(FixturePlanner):
    async def decide(self, goal, contract, observation):
        self.calls += 1
        await asyncio.sleep(60)
        raise AssertionError("The decision deadline must cancel this request")


async def test_decision_timeout_retries_once_then_stops(retry_executor, artifact, inputs):
    retry_executor.policy = retry_executor.policy.model_copy(
        update={"model_decision_timeout_seconds": 0.1}
    )
    planner = HangingPlanner([])
    result = await DiscoveryEngine(retry_executor, planner).run(
        "Prepare a review", artifact.goal, inputs
    )
    assert result.error.code == "model_timeout" and planner.calls == 2
    assert (
        len([e for e in events(retry_executor.evidence) if e["event"] == "model_request_failed"])
        == 2
    )
    retry_executor.surface.execute.assert_not_awaited()


async def test_remaining_run_budget_caps_model_wait(retry_executor, artifact, inputs):
    retry_executor.started -= retry_executor.policy.timeout_seconds - 0.1
    planner = HangingPlanner([])
    result = await DiscoveryEngine(retry_executor, planner).run(
        "Prepare a review", artifact.goal, inputs
    )
    assert result.error.code == "run_timeout" and planner.calls == 1
    assert not any(e["event"] == "model_retry_scheduled" for e in events(retry_executor.evidence))


async def test_cancel_during_model_wait_does_not_retry(retry_executor, artifact, inputs):
    planner = HangingPlanner([])
    engine = DiscoveryEngine(retry_executor, planner)
    task = asyncio.create_task(engine.run("Prepare a review", artifact.goal, inputs))
    async with asyncio.timeout(1):
        while planner.calls == 0:  # noqa: ASYNC110 - synchronize cancellation with request dispatch
            await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert planner.calls == 1 and engine.artifact is None
    assert not any(e["event"] == "model_retry_scheduled" for e in events(retry_executor.evidence))


async def test_changed_screen_prevents_retry(retry_executor, artifact, inputs):
    class ScreenChangedPlanner(FailingPlanner):
        async def decide(self, goal, contract, observation):
            retry_executor.surface.screen.return_value = "Member details"
            return await super().decide(goal, contract, observation)

    planner = ScreenChangedPlanner([ExecutionError("model_timeout")])
    result = await DiscoveryEngine(retry_executor, planner).run(
        "Prepare a review", artifact.goal, inputs
    )
    assert result.error.code == "checkpoint_mismatch" and planner.calls == 1
    retry_executor.surface.execute.assert_not_awaited()


async def test_token_budget_is_checked_before_retry(retry_executor, artifact, inputs):
    class SpentBudgetPlanner(FailingPlanner):
        async def decide(self, goal, contract, observation):
            self.tokens = retry_executor.policy.max_model_tokens
            return await super().decide(goal, contract, observation)

    planner = SpentBudgetPlanner([ExecutionError("model_timeout")])
    result = await DiscoveryEngine(retry_executor, planner).run(
        "Prepare a review", artifact.goal, inputs
    )
    assert result.error.code == "model_token_budget_exceeded" and planner.calls == 1
    retry_executor.surface.execute.assert_not_awaited()
