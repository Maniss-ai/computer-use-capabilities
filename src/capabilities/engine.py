"""Shared execution rules and the model-free replay path."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from capabilities.contracts import (
    Action,
    Capability,
    Failure,
    GoalContract,
    RunResult,
    Step,
    resolve,
)
from capabilities.errors import BusinessOutcome, ExecutionError
from capabilities.evidence import Evidence, capability_digest
from capabilities.policy import Policy
from capabilities.session import SessionController
from capabilities.surface import Surface


class Executor:
    def __init__(
        self, surface: Surface, policy: Policy, control: SessionController, evidence: Evidence
    ):
        self.surface, self.policy, self.control, self.evidence = surface, policy, control, evidence
        self.started = time.monotonic()
        self.paused = 0.0
        self.current_step: str | None = None

    def check_budget(self) -> None:
        if time.monotonic() - self.started - self.paused > self.policy.timeout_seconds:
            raise ExecutionError("run_timeout")

    async def handoff(self, reason: str, step: str, expected: str | None) -> None:
        await self.surface.failure_evidence()

        async def validate() -> None:
            # An operator can request resume while their navigation is still committing.
            # Wait for both the checkpoint and the absence of blocking conditions.
            deadline = asyncio.get_running_loop().time() + 3
            observed = "unknown"
            while asyncio.get_running_loop().time() < deadline:
                condition = await self.surface.condition()
                observed = await self.surface.screen()
                if condition is None and (expected is None or observed == expected):
                    return
                await asyncio.sleep(0.05)
            raise ExecutionError("resume_checkpoint_mismatch", expected=expected, observed=observed)

        started = time.monotonic()
        try:
            await self.control.handoff(reason, step, validate)
        finally:
            self.paused += time.monotonic() - started

    async def guard(self, expected: str | None = None) -> str:
        self.check_budget()
        for attempt in range(3):
            condition = await self.surface.condition()
            if condition is None:
                screen = await self.surface.screen()
                if expected is not None and screen != expected:
                    raise ExecutionError("checkpoint_mismatch", expected=expected, observed=screen)
                return screen
            self.evidence.event("condition_detected", code=condition, step=self.current_step)
            if condition in {"member_not_found", "validation_error"}:
                raise BusinessOutcome(condition)
            if condition in {"permission_denied", "app_unavailable", "native_dialog_cancelled"}:
                raise ExecutionError(condition)
            if condition == "known_notice":
                async with self.control.automation():
                    await self.surface.recover_notice()
                self.evidence.event("recovery_performed", code=condition, attempt=attempt + 1)
            else:
                await self.handoff(condition, self.current_step or "discovery", expected)
        raise ExecutionError("recovery_exhausted")

    async def act(self, action: Action, inputs: dict[str, str], before: str) -> None:
        async with self.control.automation():
            current = await self.surface.screen()
            if current != before:
                raise ExecutionError(
                    "state_changed_before_action", expected=before, observed=current
                )
            self.policy.authorize(current, action)
            self.evidence.event(
                "action_started",
                step=self.current_step,
                op=action.op,
                target_kind=action.target.kind,
                target=action.target.name,
                screen=current,
            )
            await self.surface.execute(action, inputs)
            self.evidence.event("action_completed", step=self.current_step, op=action.op)

    async def checkpoint(self, goal: GoalContract, inputs: dict[str, str]) -> dict[str, str | bool]:
        await self.guard(goal.success_screen)
        async with self.control.automation():
            for check in goal.checks:
                if await self.surface.read(check.target) != resolve(check.equals, inputs):
                    raise ExecutionError("success_check_failed")
            outputs: dict[str, str | bool] = {}
            for name, spec in goal.outputs.items():
                value = await self.surface.read(spec.target)
                if spec.type == "boolean":
                    if value != spec.true_when:
                        raise ExecutionError("output_validation_failed")
                    outputs[name] = True
                else:
                    outputs[name] = value
            self.evidence.event("success_verified")
            return outputs

    async def finish(self, work: Callable[[], Awaitable[dict[str, str | bool]]]) -> RunResult:
        try:
            outputs = await work()
            result = RunResult(
                status="success",
                run_id=self.evidence.run_id,
                outputs=outputs,
                human_interventions=self.control.interventions,
            )
        except BusinessOutcome as outcome:
            result = RunResult(
                status="business_outcome",
                run_id=self.evidence.run_id,
                outcome=outcome.code,
                human_interventions=self.control.interventions,
            )
        except ExecutionError as error:
            capture = await self.surface.failure_evidence()
            result = RunResult(
                status="failure",
                run_id=self.evidence.run_id,
                human_interventions=self.control.interventions,
                error=Failure(
                    code=error.code,
                    step=self.current_step,
                    expected=error.expected,
                    observed=error.observed,
                    evidence=capture,
                ),
            )
        except Exception as error:
            # Unknown library failures become a stable error. Raw exceptions can contain PII/URLs.
            capture = await self.surface.failure_evidence()
            result = RunResult(
                status="failure",
                run_id=self.evidence.run_id,
                error=Failure(
                    code="internal_error",
                    step=self.current_step,
                    observed=type(error).__name__,
                    evidence=capture,
                ),
                human_interventions=self.control.interventions,
            )
        return result


class ReplayEngine:
    """Has no provider dependency. Recovery is bounded and declarative in the trusted app profile."""

    def __init__(self, executor: Executor):
        self.executor = executor

    async def run(self, capability: Capability, supplied: dict[str, Any]) -> RunResult:
        ex = self.executor
        ex.evidence.event(
            "replay_started",
            source=capability.provenance.source,
            artifact_sha256=capability_digest(capability),
        )
        try:
            inputs = capability.goal.validate_inputs(supplied)
        except ValueError:
            result = RunResult(
                status="business_outcome", run_id=ex.evidence.run_id, outcome="invalid_invocation"
            )
            ex.evidence.result(result, capability.goal.outputs)
            return result

        async def work() -> dict[str, str | bool]:
            self._validate_profile(capability)
            if len(capability.steps) > ex.policy.max_steps:
                raise ExecutionError("step_budget_exceeded")
            for step in capability.steps:
                ex.current_step = step.id
                await ex.guard(step.before)
                await self._step(step, inputs)
                await ex.surface.wait_screen(step.after, step.timeout_ms)
                await ex.guard(step.after)
                ex.evidence.event("checkpoint_verified", step=step.id, screen=step.after)
            return await ex.checkpoint(capability.goal, inputs)

        result = await ex.finish(work)
        ex.evidence.event(
            "run_finished",
            status=result.status,
            model_calls=0,
            human_interventions=result.human_interventions,
        )
        ex.evidence.result(result, capability.goal.outputs)
        ex.control.owner = "closed"
        return result

    def _validate_profile(self, capability: Capability) -> None:
        # Reject a modified artifact before the first UI action, even if schema-valid.
        self.executor.policy.validate_goal(capability.goal)
        if capability.profile != self.executor.policy.profile:
            raise ExecutionError("profile_incompatible")
        for step in capability.steps:
            self.executor.policy.authorize(step.before, step.action)

    async def _step(self, step: Step, inputs: dict[str, str]) -> None:
        ex = self.executor
        try:
            await ex.act(step.action, inputs, step.before)
        except ExecutionError as error:
            if error.code not in {
                "target_missing",
                "target_ambiguous",
                "visual_anchor_missing",
                "visual_anchor_ambiguous",
                "action_timeout",
            }:
                raise
            # Ambiguous dispatch is never automatically retried. A human must restore the
            # PRE-action checkpoint; only profile-approved reversible operations can retry once.
            await ex.handoff(error.code, step.id, step.before)
            await ex.act(step.action, inputs, step.before)
