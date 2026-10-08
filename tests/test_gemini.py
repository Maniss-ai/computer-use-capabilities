"""Gemini transport tests are fixtures, not evidence of a live model run."""

import json
from contextlib import asynccontextmanager

import httpx
import pytest

from capabilities.errors import ExecutionError
from capabilities.evidence import Evidence
from capabilities.gemini import GeminiPlanner


def response_body(decision):
    return {
        "responseId": "gemini-response-test",
        "usageMetadata": {
            "promptTokenCount": 100,
            "candidatesTokenCount": 30,
            "thoughtsTokenCount": 20,
        },
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {"parts": [{"text": json.dumps(decision)}]},
            }
        ],
    }


@asynccontextmanager
async def planner_with_response(tmp_path, body, *, status=200):
    captured = []

    def respond(request):
        captured.append(request)
        return httpx.Response(status, json=body)

    evidence = Evidence(tmp_path, "gemini", ["private-test-key"])
    planner = GeminiPlanner("private-test-key", "gemini-3.8-flash", evidence, interval_seconds=0)
    await planner.client.aclose()
    planner.client = httpx.AsyncClient(
        base_url="https://generativelanguage.googleapis.com/v1beta/",
        headers={"x-goog-api-key": "private-test-key"},
        transport=httpx.MockTransport(respond),
    )
    try:
        yield planner, captured, evidence
    finally:
        await planner.close()


async def test_gemini_reads_masked_image_and_counts_thinking_usage(tmp_path, artifact):
    body = response_body({"finish": True, "reason": "verify_goal"})
    body["candidates"][0]["content"]["parts"].insert(
        0, {"thought": True, "text": "private-reasoning-marker"}
    )
    async with planner_with_response(tmp_path, body) as (planner, captured, evidence):
        decision = await planner.decide(
            "Prepare the requested review",
            artifact.goal,
            {"screen": "Review sub-account", "image_base64": "masked-image-marker"},
        )
        assert decision.finish
        assert planner.calls == 1 and planner.tokens == 150
        request = captured[0]
        assert request.url.host == "generativelanguage.googleapis.com"
        assert not request.url.query
        assert request.headers["x-goog-api-key"] == "private-test-key"
        payload = json.loads(request.content)
        assert payload["contents"][0]["parts"][1]["inlineData"]["data"] == "masked-image-marker"
        assert "responseJsonSchema" in payload["generationConfig"]
        persisted = (evidence.root / "events.jsonl").read_text()
        assert "gemini-response-test" in persisted
        assert all(
            marker not in persisted
            for marker in ("private-test-key", "private-reasoning-marker", "masked-image-marker")
        )


async def test_gemini_schema_preserves_observed_visual_target(tmp_path, artifact):
    visual = artifact.steps[2].action
    body = response_body({"action": visual.model_dump(mode="json"), "reason": "advance"})
    control = {"op": "click", "target": visual.target.model_dump(), "input": None}
    async with planner_with_response(tmp_path, body) as (planner, captured, _):
        decision = await planner.decide(
            "Prepare a review",
            artifact.goal,
            {"screen": "Member details", "controls": [control]},
        )
        assert decision.action.target.kind == "visual"
        schema = json.loads(captured[0].content)["generationConfig"]["responseJsonSchema"]
        choices = schema["properties"]["action"]["anyOf"]
        assert len(choices) == 2  # The single visible control, or no action when stopping.
        target = choices[0]["properties"]["target"]["properties"]
        assert target["kind"]["enum"] == ["visual"]
        assert target["name"]["enum"] == ["New sub-account"]
        assert target["scope"]["enum"] == ["workspace"]


@pytest.mark.parametrize(
    "decision",
    [
        {"finish": True, "request_human": True, "reason": "blocked"},
        {"action": {"op": "shell", "command": "bad"}, "reason": "advance"},
        {"finish": True, "reason": "verify_goal", "unexpected": "field"},
    ],
)
async def test_gemini_rejects_unsafe_or_incoherent_decisions(tmp_path, artifact, decision):
    async with planner_with_response(tmp_path, response_body(decision)) as (planner, _, _):
        with pytest.raises(ExecutionError, match="model_protocol_error"):
            await planner.decide("Prepare a review", artifact.goal, {"screen": "Find a member"})


@pytest.mark.parametrize(
    "status,expected",
    [
        (400, "model_request_invalid"),
        (401, "model_authentication_failed"),
        (403, "model_permission_denied"),
        (404, "model_not_found"),
        (429, "model_rate_limited"),
        (503, "model_service_unavailable"),
    ],
)
async def test_gemini_http_errors_never_retry_or_log_response(tmp_path, artifact, status, expected):
    body = {"error": {"message": "private-response-marker"}}
    async with planner_with_response(tmp_path, body, status=status) as (
        planner,
        captured,
        evidence,
    ):
        with pytest.raises(ExecutionError, match=expected):
            await planner.decide("Prepare a review", artifact.goal, {"screen": "Find a member"})
        assert len(captured) == 1
        assert "private-response-marker" not in (evidence.root / "events.jsonl").read_text()


async def test_gemini_truncation_cannot_be_treated_as_success(tmp_path, artifact):
    body = response_body({"finish": True, "reason": "verify_goal"})
    body["candidates"][0]["finishReason"] = "MAX_TOKENS"
    async with planner_with_response(tmp_path, body) as (planner, _, _):
        with pytest.raises(ExecutionError, match="model_incomplete_response"):
            await planner.decide("Prepare a review", artifact.goal, {"screen": "Find a member"})


def test_gemini_model_cannot_redirect_credentials(tmp_path):
    with pytest.raises(ValueError):
        GeminiPlanner("test-key", "https://other.example/", Evidence(tmp_path, "invalid-model"))
