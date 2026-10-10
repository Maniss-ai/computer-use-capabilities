"""Policy belongs to the application operator, never to the model or artifact author."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field

from capabilities.contracts import Action, Contract, Fill, GoalContract, InputRef, Select
from capabilities.errors import ExecutionError


class Permission(Contract):
    screen: str
    op: str
    kind: str
    name: str
    input_name: str | None = None
    risk: Literal["reversible", "irreversible"] = "reversible"


class Policy(Contract):
    profile: str = "harbor-ledger/v1"
    origin: str
    routes: tuple[str, ...]
    actions: tuple[Permission, ...]
    sensitive_inputs: tuple[str, ...] = ("member_id", "nickname")
    sensitive_fields: tuple[str, ...] = ("Member reference", "Nickname")
    max_steps: int = Field(default=35, ge=1, le=80)
    timeout_seconds: int = Field(default=180, ge=1, le=600)
    max_model_tokens: int = Field(default=60000, ge=1000, le=200000)
    model_decision_timeout_seconds: float = Field(default=75, ge=0.1, le=120)
    max_model_retries: int = Field(default=2, ge=0, le=2)
    model_retry_delay_seconds: float = Field(default=2, ge=0, le=10)
    intervention_seconds: int = Field(default=300, ge=1, le=1800)

    def allows_url(self, url: str) -> bool:
        parsed, base = urlsplit(url), urlsplit(self.origin)
        return (
            parsed.scheme in {"http", "https"}
            and parsed.scheme == base.scheme
            and parsed.netloc == base.netloc
            and parsed.username is None
            and parsed.password is None
            and parsed.path in self.routes
            and not parsed.fragment
        )

    def check_url(self, url: str) -> None:
        if not self.allows_url(url):
            raise ExecutionError("navigation_blocked")

    def authorize(self, screen: str, action: Action) -> None:
        if action.target.scope != "workspace":
            raise ExecutionError("action_blocked", observed="scope_not_permitted")
        match = next(
            (
                rule
                for rule in self.actions
                if (rule.screen, rule.op, rule.kind, rule.name)
                == (screen, action.op, action.target.kind, action.target.name)
            ),
            None,
        )
        if match is None:
            raise ExecutionError("action_blocked", observed="no_matching_permission")
        if match.risk != "reversible":
            raise ExecutionError("irreversible_action_blocked")
        if isinstance(action, Fill | Select):
            if action.value.kind != "input" or action.value.name != match.input_name:
                raise ExecutionError("input_binding_blocked")

    def validate_goal(self, goal: GoalContract) -> None:
        for name in self.sensitive_inputs:
            if name in goal.inputs and not goal.inputs[name].sensitive:
                raise ExecutionError("privacy_contract_rejected")
        for output in goal.outputs.values():
            if output.target.name in self.sensitive_fields and not output.sensitive:
                raise ExecutionError("privacy_contract_rejected")
        for check in goal.checks:
            if check.target.name in self.sensitive_fields and not isinstance(
                check.equals, InputRef
            ):
                raise ExecutionError("privacy_contract_rejected")
