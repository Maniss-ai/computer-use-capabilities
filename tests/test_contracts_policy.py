import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from capabilities.cli import load_policy
from capabilities.contracts import Capability, Click, Constant, Decision, Fill, Target
from capabilities.errors import ExecutionError
from capabilities.evidence import Evidence


def test_contract_round_trip(artifact):
    assert Capability.model_validate_json(artifact.model_dump_json()) == artifact


@pytest.mark.parametrize(
    "change", ["unknown_version", "extra_code", "duplicate_step", "unknown_input"]
)
def test_reject_invalid_artifacts(artifact, change):
    raw = artifact.model_dump(mode="json")
    if change == "unknown_version":
        raw["schema_version"] = "999"
    if change == "extra_code":
        raw["steps"][0]["action"]["script"] = 'fetch("secret")'
    if change == "duplicate_step":
        raw["steps"][1]["id"] = raw["steps"][0]["id"]
    if change == "unknown_input":
        raw["steps"][0]["action"]["value"]["name"] = "undeclared"
    with pytest.raises(ValidationError):
        Capability.model_validate(raw)


@pytest.mark.parametrize("value", [10042, "", "abcde", "123456", "1234", "123\n4"])
def test_reject_bad_member_inputs(artifact, inputs, value):
    with pytest.raises(ValueError):
        artifact.goal.validate_inputs({**inputs, "member_id": value})


def test_reject_extra_inputs(artifact, inputs):
    with pytest.raises(ValueError):
        artifact.goal.validate_inputs({**inputs, "secret": "x"})


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8765/",
        "http://127.0.0.1:8765.evil.test/",
        "http://127.0.0.1:8765@evil.test/",
        "http://127.0.0.1:8765/workspace/commit",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://127.0.0.1:8765/workspace/%2e%2e/commit",
    ],
)
def test_origin_and_route_allowlist(url):
    assert not load_policy("http://127.0.0.1:8765").allows_url(url)


def test_irreversible_action_blocked():
    with pytest.raises(ExecutionError, match="action_blocked"):
        load_policy("http://127.0.0.1:8765").authorize(
            "Review sub-account", Click(target=Target(kind="button", name="Create account"))
        )


def test_model_cannot_type_a_literal():
    with pytest.raises(ExecutionError, match="input_binding_blocked"):
        load_policy("http://127.0.0.1:8765").authorize(
            "Find a member",
            Fill(target=Target(kind="label", name="Member ID"), value=Constant(value="10042")),
        )


def test_decision_requires_exactly_one_operation():
    with pytest.raises(ValidationError):
        Decision(finish=True, request_human=True, reason="blocked")


def test_secret_values_cannot_enter_artifacts(tmp_path, artifact):
    evidence = Evidence(tmp_path, "redaction", ["authored-example"])
    with pytest.raises(ValueError, match="Sensitive"):
        evidence.artifact(artifact)


def test_log_redaction_and_allowlist(tmp_path):
    evidence = Evidence(tmp_path, "redaction", ["PRIVATE-NAME"])
    evidence.event("test", code="PRIVATE-NAME someone@example.com sk-ant-secretstuff")
    text = (evidence.root / "events.jsonl").read_text()
    assert (
        "PRIVATE-NAME" not in text
        and "someone@example.com" not in text
        and "sk-ant-secretstuff" not in text
    )
    with pytest.raises(ValueError):
        evidence.event("test", raw_page="bad")


def test_schema_is_current():
    assert (
        json.loads(Path("schemas/capability.schema.json").read_text())
        == Capability.model_json_schema()
    )


def test_env_file_is_data_never_shell_code(tmp_path, monkeypatch):
    from capabilities.config import load_local_env

    monkeypatch.delenv("CAPABILITIES_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "existing-key")
    path = tmp_path / ".env"
    path.write_text(
        'ANTHROPIC_API_KEY=do-not-override\nCAPABILITIES_MODEL="test-model"\nGEMINI_API_KEY="local-gemini-key"\nHOME=/bad\nexport X=$(touch /tmp/bad)\n'
    )
    load_local_env(path)
    import os

    assert os.environ["CAPABILITIES_MODEL"] == "test-model"
    assert os.environ["ANTHROPIC_API_KEY"] == "existing-key"
    assert os.environ["GEMINI_API_KEY"] == "local-gemini-key"
    assert os.environ["HOME"] != "/bad"


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "failure", "run_id": "r"},
        {"status": "business_outcome", "run_id": "r"},
        {"status": "success", "run_id": "r", "outcome": "member_not_found"},
    ],
)
def test_result_contract_rejects_contradictions(payload):
    from capabilities.contracts import RunResult

    with pytest.raises(ValidationError):
        RunResult.model_validate(payload)
