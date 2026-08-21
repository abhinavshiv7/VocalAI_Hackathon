from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from ..config import Settings
from ..prompts import CRITIC_SYSTEM_PROMPT, INVESTIGATOR_SYSTEM_PROMPT
from ..schemas import CriticOutput, HypothesisDraft, InvestigatorOutput, ToolRequest
from .failures import failure_controller


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class ModelFailure(RuntimeError):
    def __init__(self, event_type: str, message: str):
        super().__init__(message)
        self.event_type = event_type


@dataclass
class ModelRun:
    output: BaseModel
    latency_ms: int
    estimated_cost_usd: float
    attempts: int


class StructuredModelClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def call(
        self,
        *,
        role: str,
        schema: type[SchemaT],
        system_prompt: str,
        payload: dict[str, Any],
    ) -> ModelRun:
        started = time.perf_counter()
        if failure_controller.matches("model", role):
            raise ModelFailure("MODEL_TIMEOUT", f"Injected {role} model outage")

        if self.settings.ai_mode == "deterministic":
            output = self._deterministic(role, payload)
            if failure_controller.matches("malformed_output", role):
                raise ModelFailure("MODEL_INVALID_OUTPUT", f"Injected malformed {role} output failed both schema attempts")
            return ModelRun(
                output=schema.model_validate(output),
                latency_ms=int((time.perf_counter() - started) * 1000),
                estimated_cost_usd=0.0,
                attempts=1,
            )

        config = self._provider_config(role)
        if not config["api_key"]:
            raise ModelFailure("MODEL_UNAVAILABLE", f"No API key configured for {role}")

        last_error = ""
        for attempt in range(1, 3):
            try:
                content = await self._chat_completion(
                    base_url=config["base_url"],
                    api_key=config["api_key"],
                    model=config["model"],
                    system_prompt=system_prompt,
                    payload=payload,
                    schema=schema,
                    correction=last_error if attempt == 2 else "",
                )
                if failure_controller.matches("malformed_output", role):
                    content = "{not valid json"
                validated = schema.model_validate(json.loads(content))
                return ModelRun(
                    output=validated,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    estimated_cost_usd=0.002,
                    attempts=attempt,
                )
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = f"Your last output did not match the schema: {exc}"
            except httpx.TimeoutException as exc:
                last_error = f"Model timeout: {exc}"
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                last_error = f"Model request failed: {exc}"
        event = "MODEL_INVALID_OUTPUT" if "schema" in last_error or "valid" in last_error else "MODEL_UNAVAILABLE"
        raise ModelFailure(event, last_error or f"{role} model failed")

    def _provider_config(self, role: str) -> dict[str, str]:
        if role == "investigator":
            return {
                "base_url": self.settings.investigator_base_url,
                "api_key": self.settings.investigator_api_key,
                "model": self.settings.investigator_model,
            }
        return {
            "base_url": self.settings.critic_base_url,
            "api_key": self.settings.critic_api_key,
            "model": self.settings.critic_model,
        }

    async def _chat_completion(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        system_prompt: str,
        payload: dict[str, Any],
        schema: type[BaseModel],
        correction: str,
    ) -> str:
        user_message = {
            "task": payload,
            "response_schema": schema.model_json_schema(),
            "correction": correction or None,
        }
        async with httpx.AsyncClient(timeout=self.settings.model_timeout_seconds) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "temperature": 0.1,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(user_message)},
                    ],
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

    def _deterministic(self, role: str, payload: dict[str, Any]) -> dict[str, Any]:
        if role == "investigator":
            target_id = payload["target_id"]
            return InvestigatorOutput(
                reasoning_summary=(
                    "Service discovery justifies focused, read-only HTTP checks. "
                    "The endpoint name alone is not evidence, so each hypothesis remains provisional."
                ),
                hypotheses=[
                    HypothesisDraft(
                        title="Potentially exposed administrative interface",
                        description="The lab may expose administrative data without an authentication challenge.",
                        reason="The controlled target declares an administrative route that requires evidence-based validation.",
                        confidence=0.62,
                        required_evidence=["HTTP reachability", "authentication behavior"],
                        tool_request=ToolRequest(
                            tool="web_inspection",
                            target_id=target_id,
                            path="/admin",
                            reason="Verify status and authentication challenge on the authorized admin route.",
                        ),
                    ),
                    HypothesisDraft(
                        title="Response security headers may be incomplete",
                        description="The public status route may omit baseline browser security controls.",
                        reason="A focused header inspection can prove or reject the configuration weakness.",
                        confidence=0.55,
                        required_evidence=["response header inventory"],
                        tool_request=ToolRequest(
                            tool="web_inspection",
                            target_id=target_id,
                            path="/api/status",
                            reason="Inspect security headers returned by the authorized status route.",
                        ),
                    ),
                    HypothesisDraft(
                        title="Debug endpoint may expose sensitive behavior",
                        description="A debug-named route could be reachable without authorization.",
                        reason="The route name is suspicious but is insufficient evidence on its own.",
                        confidence=0.38,
                        required_evidence=["access-control response"],
                        tool_request=ToolRequest(
                            tool="web_inspection",
                            target_id=target_id,
                            path="/api/debug",
                            reason="Test whether the authorized debug route enforces access control.",
                        ),
                    ),
                ],
            ).model_dump()

        evidence = payload.get("evidence", [])
        kinds = {item.get("kind") for item in evidence}
        observations = " ".join(item.get("observation", "") for item in evidence)
        if "ADMIN_EXPOSURE" in kinds and "AUTH_CONTROL_OBSERVED" in kinds:
            return CriticOutput(
                decision="needs_more_evidence",
                confidence=0.4,
                missing_evidence=["repeatable authentication behavior under controlled conditions"],
                contradictions=["The supplied probes disagree about access control."],
                reason="Contradictory authentication observations prohibit validation.",
            ).model_dump()
        if any(kind in {"TOOL_FAILED", "TOOL_TIMEOUT", "TOOL_UNAVAILABLE"} for kind in kinds):
            return CriticOutput(
                decision="human_review",
                confidence=0.2,
                missing_evidence=["successful tool observation"],
                reason="The tool boundary failed, so the hypothesis cannot be validated safely.",
            ).model_dump()
        if "ADMIN_EXPOSURE" in kinds:
            return CriticOutput(
                decision="validated",
                confidence=0.91,
                reason="The evidence directly shows HTTP 200 without an authentication challenge on the admin route.",
            ).model_dump()
        if "AUTH_CONTROL_OBSERVED" in kinds or "HTTP 403" in observations:
            return CriticOutput(
                decision="rejected",
                confidence=0.88,
                contradictions=["The endpoint denied the unauthenticated request."],
                reason="A suspicious route name does not outweigh the observed access-control response.",
            ).model_dump()
        if "MISSING_SECURITY_HEADERS" in kinds:
            return CriticOutput(
                decision="validated",
                confidence=0.86,
                reason="The normalized header inventory directly lists the missing baseline controls.",
            ).model_dump()
        return CriticOutput(
            decision="needs_more_evidence",
            confidence=0.35,
            missing_evidence=["direct observation satisfying the required evidence"],
            reason="Current evidence does not directly prove the hypothesis.",
        ).model_dump()


class InvestigatorService:
    def __init__(self, client: StructuredModelClient):
        self.client = client

    async def generate(self, target_id: str, discovery_evidence: list[dict[str, Any]]) -> ModelRun:
        return await self.client.call(
            role="investigator",
            schema=InvestigatorOutput,
            system_prompt=INVESTIGATOR_SYSTEM_PROMPT,
            payload={
                "target_id": target_id,
                "authorized": True,
                "available_tools": ["network_discovery", "web_inspection"],
                "discovery_evidence": discovery_evidence,
            },
        )


class CriticService:
    def __init__(self, client: StructuredModelClient):
        self.client = client

    async def review(self, hypothesis: dict[str, Any], evidence: list[dict[str, Any]]) -> ModelRun:
        return await self.client.call(
            role="critic",
            schema=CriticOutput,
            system_prompt=CRITIC_SYSTEM_PROMPT,
            payload={"hypothesis": hypothesis, "evidence": evidence},
        )
