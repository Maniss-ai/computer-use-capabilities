"""Operator-authored goals and example inputs, never ordered action sequences.

This module contains no banking records and does not import the target application.
Examples are for the operator form; the planner receives only the goal contract.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field

from capabilities.contracts import Contract, GoalContract


class Workflow(Contract):
    id: str
    title: str
    department: str
    description: str
    goal: str
    contract: GoalContract
    labels: dict[str, str]
    examples: tuple[dict[str, str], ...] = Field(min_length=2)


def workflows() -> dict[str, Workflow]:
    path = Path(__file__).parent / "profiles/workflows.json"
    return {item["id"]: Workflow.model_validate(item) for item in json.loads(path.read_text())}


def workflow_for_goal(goal: GoalContract) -> Workflow:
    for workflow in workflows().values():
        if workflow.contract == goal:
            return workflow
    raise ValueError("The goal contract is not a qualified Harbor workflow")
