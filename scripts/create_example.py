"""Create an explicitly authored example. This is NOT model discovery evidence."""

from pathlib import Path

from capabilities.contracts import (
    Capability,
    Click,
    Fill,
    GoalContract,
    InputRef,
    Provenance,
    Select,
    Step,
    Target,
)

contract = GoalContract.model_validate_json(
    Path("examples/prepare-subaccount.goal.json").read_text()
)
steps = [
    (
        "Find a member",
        Fill(target=Target(kind="label", name="Member ID"), value=InputRef(name="member_id")),
        "Find a member",
    ),
    ("Find a member", Click(target=Target(kind="button", name="Search")), "Member details"),
    (
        "Member details",
        Click(target=Target(kind="visual", name="New sub-account")),
        "Prepare sub-account",
    ),
    (
        "Prepare sub-account",
        Select(target=Target(kind="label", name="Product"), value=InputRef(name="product")),
        "Prepare sub-account",
    ),
    (
        "Prepare sub-account",
        Fill(target=Target(kind="label", name="Nickname"), value=InputRef(name="nickname")),
        "Prepare sub-account",
    ),
    (
        "Prepare sub-account",
        Click(target=Target(kind="button", name="Review request")),
        "Review sub-account",
    ),
]
artifact = Capability(
    goal=contract,
    provenance=Provenance(source="authored_example", run_id="authored-example"),
    steps=tuple(
        Step(id=f"step_{i + 1:03d}", before=before, action=action, after=after)
        for i, (before, action, after) in enumerate(steps)
    ),
)
Path("examples/authored-capability.json").write_text(artifact.model_dump_json(indent=2) + "\n")
