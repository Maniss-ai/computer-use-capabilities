"""Gemini vision planner; the same executor validates every proposed action."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Literal

import httpx

from capabilities.contracts import Decision, GoalContract
from capabilities.discovery import SYSTEM
from capabilities.errors import ExecutionError
from capabilities.evidence import Evidence

GEMINI_SYSTEM = SYSTEM.replace(
    "Return exactly one next_action tool call per observation.",
    "Return exactly one JSON decision per observation, matching the response schema.",
)


def decision_schema(controls: list[dict[str, Any]]) -> dict[str, Any]:
    """Translate Pydantic annotations to Google's supported JSON Schema subset.

    Host-side Decision validation remains authoritative, including exactly_one
    and constraints the provider does not support.
    """

    def translate(value: Any) -> Any:
        if isinstance(value, list):
            return [translate(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {
            key: translate(item)
            for key, item in value.items()
            if key not in {"default", "discriminator", "pattern", "minLength", "maxLength"}
        }
        if "const" in result:
            result["enum"] = [result.pop("const")]
        if "oneOf" in result:
            result["anyOf"] = result.pop("oneOf")
        return result

    result: dict[str, Any] = translate(Decision.model_json_schema())
    # Limit syntax to controls in this observation, without supplying their order
    # or choosing the next action. The executor still checks policy at dispatch.
    actions = []
    for control in controls:
        target = control["target"]
        properties: dict[str, Any] = {
            "op": {"type": "string", "enum": [control["op"]]},
            "target": {
                "type": "object",
                "properties": {
                    key: {"type": "string", "enum": [target[key]]}
                    for key in ("kind", "name", "scope")
                },
                "required": ["kind", "name", "scope"],
                "additionalProperties": False,
            },
        }
        if control["op"] in {"fill", "select"}:
            properties["value"] = {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["input"]},
                    "name": {"type": "string", "enum": [control["input"]]},
                },
                "required": ["kind", "name"],
                "additionalProperties": False,
            }
        actions.append(
            {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            }
        )
    result["properties"]["action"] = {"anyOf": [*actions, {"type": "null"}]}
    result.pop("$defs", None)
    return result


class GeminiPlanner:
    source: Literal["llm_discovery"] = "llm_discovery"

    def __init__(
        self, api_key: str, model: str, evidence: Evidence, *, interval_seconds: float = 13.0
    ):
        if not re.fullmatch(r"gemini-[a-z0-9.-]+", model):
            raise ValueError("Expected a Gemini model ID")
        self.client = httpx.AsyncClient(
            base_url="https://generativelanguage.googleapis.com/v1beta/",
            headers={"x-goog-api-key": api_key},
            timeout=30.0,
            follow_redirects=False,
        )
        self.model, self.evidence = model, evidence
        self.calls, self.tokens = 0, 0
        self.history: list[dict[str, Any]] = []
        self.interval_seconds = interval_seconds
        self.last_request: float | None = None

    async def decide(
        self, goal: str, contract: GoalContract, observation: dict[str, Any]
    ) -> Decision:
        # Space requests for small free quotas. This is not a quota guarantee;
        # a rejection stops the run, with no retries or paid-provider fallback.
        if self.last_request is not None:
            await asyncio.sleep(
                max(0, self.interval_seconds - (time.monotonic() - self.last_request))
            )
        safe = {key: value for key, value in observation.items() if key != "image_base64"}
        parts: list[dict[str, Any]] = [
            {
                "text": json.dumps(
                    {
                        "goal": goal,
                        "contract": contract.model_dump(mode="json"),
                        "recent_decisions": self.history[-4:],
                        "observation": safe,
                    }
                )
            }
        ]
        if observation.get("image_base64"):
            parts.append(
                {"inlineData": {"mimeType": "image/png", "data": observation["image_base64"]}}
            )
        generation: dict[str, Any] = {
            "responseMimeType": "application/json",
            "responseJsonSchema": decision_schema(safe.get("controls", [])),
            "maxOutputTokens": 2048,
            "candidateCount": 1,
        }
        if self.model.startswith("gemini-3"):
            generation["thinkingConfig"] = {"thinkingLevel": "LOW", "includeThoughts": False}
        self.calls += 1
        self.last_request = time.monotonic()
        try:
            response = await self.client.post(
                f"models/{self.model}:generateContent",
                json={
                    "systemInstruction": {"parts": [{"text": GEMINI_SYSTEM}]},
                    "contents": [{"role": "user", "parts": parts}],
                    "generationConfig": generation,
                },
            )
        except httpx.TimeoutException as error:
            raise ExecutionError("model_timeout") from error
        except httpx.RequestError as error:
            raise ExecutionError("model_connection_failed") from error
        if response.status_code != 200:
            code = {
                400: "model_request_invalid",
                401: "model_authentication_failed",
                403: "model_permission_denied",
                404: "model_not_found",
                429: "model_rate_limited",
            }.get(response.status_code, "model_request_failed")
            if response.status_code >= 500:
                code = "model_service_unavailable"
            self.evidence.event("model_request_failed", code=code)
            raise ExecutionError(code, observed=f"http_status_{response.status_code}")
        try:
            body = response.json()
            usage = body["usageMetadata"]
            input_tokens = usage["promptTokenCount"]
            output_tokens = usage.get("candidatesTokenCount", 0) + usage.get(
                "thoughtsTokenCount", 0
            )
            response_id = body["responseId"]
            if not isinstance(response_id, str) or not response_id:
                raise ValueError("Missing response ID")
            if any(type(count) is not int or count < 0 for count in (input_tokens, output_tokens)):
                raise ValueError("Invalid usage")
            self.tokens += input_tokens + output_tokens
            self.evidence.event(
                "model_response",
                model=self.model,
                response_id=response_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            candidates = body.get("candidates", [])
            if body.get("promptFeedback", {}).get("blockReason"):
                raise ExecutionError("model_refused")
            if len(candidates) != 1:
                raise ValueError("Expected one candidate")
            candidate = candidates[0]
            if candidate.get("finishReason") != "STOP":
                raise ExecutionError("model_incomplete_response")
            text = "".join(
                part["text"]
                for part in candidate["content"]["parts"]
                if "text" in part and not part.get("thought", False)
            )
            decision = Decision.model_validate_json(text)
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise ExecutionError("model_protocol_error") from error
        self.history.append(
            {"screen": safe.get("screen"), "decision": decision.model_dump(mode="json")}
        )
        return decision

    async def close(self) -> None:
        await self.client.aclose()
