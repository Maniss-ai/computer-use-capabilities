"""Versioned wire contracts. Artifacts contain data, never executable code."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Parameter(Contract):
    type: Literal["string"] = "string"
    description: str = Field(max_length=240)
    format: Literal["text", "member_id"] = "text"
    choices: tuple[str, ...] = ()
    sensitive: bool = True
    max_length: int = Field(default=80, ge=1, le=200)

    def validate_value(self, value: object) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > self.max_length:
            raise ValueError("Expected a nonempty string within the declared length")
        if self.format == "member_id" and not re.fullmatch(r"[0-9]{5}", value):
            raise ValueError("Member ID must contain exactly five digits")
        if self.choices and value not in self.choices:
            raise ValueError("Value is not one of the declared choices")
        if any(ord(char) < 32 for char in value):
            raise ValueError("Control characters are not supported")
        return value


class InputRef(Contract):
    kind: Literal["input"] = "input"
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")


class Constant(Contract):
    kind: Literal["constant"] = "constant"
    value: str = Field(max_length=200)


Binding = Annotated[InputRef | Constant, Field(discriminator="kind")]


class Target(Contract):
    kind: Literal["label", "button", "link", "text", "field", "visual"]
    name: str = Field(min_length=1, max_length=100)
    scope: str = Field(default="workspace", pattern=r"^[a-z][a-z0-9_-]{0,39}$")


class Click(Contract):
    op: Literal["click"] = "click"
    target: Target


class Fill(Contract):
    op: Literal["fill"] = "fill"
    target: Target
    value: Binding


class Select(Contract):
    op: Literal["select"] = "select"
    target: Target
    value: Binding


Action = Annotated[Click | Fill | Select, Field(discriminator="op")]


class Check(Contract):
    target: Target
    equals: Binding


class OutputField(Contract):
    type: Literal["string", "boolean"] = "string"
    target: Target
    sensitive: bool = True
    true_when: str | None = None

    @model_validator(mode="after")
    def boolean_mapping(self) -> OutputField:
        if self.type == "boolean" and self.true_when is None:
            raise ValueError("Boolean extraction needs an explicit true_when value")
        return self


class GoalContract(Contract):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    inputs: dict[str, Parameter] = Field(min_length=1, max_length=20)
    outputs: dict[str, OutputField] = Field(min_length=1, max_length=20)
    success_screen: str = Field(min_length=1, max_length=100)
    checks: tuple[Check, ...] = Field(min_length=1, max_length=20)

    def validate_inputs(self, supplied: dict[str, object]) -> dict[str, str]:
        if set(supplied) != set(self.inputs):
            raise ValueError("Input names do not match the capability contract")
        return {key: spec.validate_value(supplied[key]) for key, spec in self.inputs.items()}


class Step(Contract):
    id: str = Field(pattern=r"^step_[0-9]{3}$")
    before: str = Field(max_length=100)
    action: Action
    after: str = Field(max_length=100)
    timeout_ms: int = Field(default=3000, ge=100, le=30000)


class Provenance(Contract):
    source: Literal["llm_discovery", "test_fixture", "authored_example"]
    run_id: str
    model: str | None = None
    # Provider response IDs and usage live in redacted evidence, never raw conversation dumps.


class Capability(Contract):
    schema_version: Literal["1.0"] = "1.0"
    capability_version: Literal["1.0.0"] = "1.0.0"
    profile: str = Field(default="harbor-ledger/v1", pattern=r"^[a-z][a-z0-9_-]+/v[0-9]+$")
    goal: GoalContract
    steps: tuple[Step, ...] = Field(min_length=1, max_length=80)
    provenance: Provenance

    @model_validator(mode="after")
    def validate_references(self) -> Capability:
        if len({step.id for step in self.steps}) != len(self.steps):
            raise ValueError("Step IDs must be unique")
        bindings: list[Binding] = [check.equals for check in self.goal.checks]
        bindings.extend(
            step.action.value for step in self.steps if isinstance(step.action, Fill | Select)
        )
        if any(
            isinstance(value, InputRef) and value.name not in self.goal.inputs for value in bindings
        ):
            raise ValueError("Undeclared input reference")
        return self


class Decision(Contract):
    action: Action | None = None
    finish: bool = False
    request_human: bool = False
    reason: Literal["advance", "enter_input", "verify_goal", "blocked"]

    @model_validator(mode="after")
    def exactly_one(self) -> Decision:
        if sum((self.action is not None, self.finish, self.request_human)) != 1:
            raise ValueError("Choose exactly one action, finish, or request_human")
        return self


class Failure(Contract):
    code: str
    step: str | None = None
    expected: str | None = None
    observed: str | None = None
    evidence: str | None = None


class RunResult(Contract):
    status: Literal["success", "business_outcome", "failure"]
    run_id: str
    outputs: dict[str, str | bool] = Field(default_factory=dict)
    outcome: str | None = None
    error: Failure | None = None
    model_calls: int = Field(default=0, ge=0)
    human_interventions: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def coherent_result(self) -> RunResult:
        if self.status == "success" and (self.error is not None or self.outcome is not None):
            raise ValueError("Success cannot carry an error or business outcome")
        if self.status == "business_outcome" and (
            not self.outcome or self.error is not None or self.outputs
        ):
            raise ValueError("Business outcomes require an outcome and no success outputs or error")
        if self.status == "failure" and (
            self.error is None or self.outcome is not None or self.outputs
        ):
            raise ValueError("Failure requires an error and no success outputs or business outcome")
        return self


def resolve(binding: Binding, inputs: dict[str, str]) -> str:
    return inputs[binding.name] if isinstance(binding, InputRef) else binding.value
