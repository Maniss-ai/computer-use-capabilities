"""Transport-level provider tests use a fake HTTP response, never live model access."""

import json

import httpx
import pytest
from anthropic import AsyncAnthropic

from capabilities.discovery import AnthropicPlanner
from capabilities.errors import ExecutionError
from capabilities.evidence import Evidence


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"finish": True, "reason": "verify_goal"}, None),
        ({"finish": True, "request_human": True, "reason": "blocked"}, "model_protocol_error"),
        (
            {"action": {"op": "shell", "command": "rm -rf /"}, "reason": "advance"},
            "model_protocol_error",
        ),
    ],
)
async def test_provider_validates_decision_contract(tmp_path, artifact, payload, expected):
    captured = []

    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "msg_test_123",
                "type": "message",
                "role": "assistant",
                "model": "test-model",
                "content": [
                    {"type": "tool_use", "id": "tool_1", "name": "next_action", "input": payload}
                ],
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": {"input_tokens": 40, "output_tokens": 15},
            },
        )

    evidence = Evidence(tmp_path, "provider", ["never-log-this"])
    planner = AnthropicPlanner("never-log-this", "claude-sonnet-5-5", evidence)
    await planner.client.close()
    planner.client = AsyncAnthropic(
        api_key="never-log-this",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    try:
        if expected:
            with pytest.raises(ExecutionError, match=expected):
                await planner.decide(
                    "Prepare a review",
                    artifact.goal,
                    {"screen": "Review sub-account", "controls": []},
                )
        else:
            decision = await planner.decide(
                "Prepare a review", artifact.goal, {"screen": "Review sub-account", "controls": []}
            )
            assert decision.finish
        assert planner.calls == 1 and planner.tokens == 55
        assert captured[0]["tool_choice"]["disable_parallel_tool_use"]
        assert captured[0]["tool_choice"]["type"] == "auto"
        assert captured[0]["thinking"] == {"type": "between_tools"}
        assert "never-log-this" not in (evidence.root / "events.jsonl").read_text()
    finally:
        await planner.close()


@pytest.mark.parametrize(
    "status,message,expected",
    [
        (400, "Your credit balance is too low", "model_billing_required"),
        (400, "Invalid tool schema", "model_request_invalid"),
        (401, "Invalid x-api-key", "model_authentication_failed"),
        (403, "Not permitted", "model_permission_denied"),
        (404, "Model not found", "model_not_found"),
        (429, "Rate limit", "model_rate_limited"),
        (503, "Temporarily unavailable", "model_service_unavailable"),
    ],
)
async def test_provider_failure_is_actionable_without_leaking_body(
    tmp_path, artifact, status, message, expected
):
    sensitive_marker = "private-provider-response-marker"

    def respond(request):
        return httpx.Response(
            status,
            json={
                "type": "error",
                "error": {"type": "api_error", "message": f"{message}: {sensitive_marker}"},
            },
        )

    evidence = Evidence(tmp_path, "provider-failure")
    planner = AnthropicPlanner("test-key", "test-model", evidence)
    await planner.client.close()
    planner.client = AsyncAnthropic(
        api_key="test-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    try:
        with pytest.raises(ExecutionError) as caught:
            await planner.decide("Prepare a review", artifact.goal, {"screen": "Find a member"})
        assert caught.value.code == expected
        assert caught.value.observed == f"http_status_{status}"
        assert planner.calls == 1 and planner.tokens == 0
        events = (evidence.root / "events.jsonl").read_text()
        assert expected in events
        assert sensitive_marker not in events
        assert "test-key" not in events
    finally:
        await planner.close()
