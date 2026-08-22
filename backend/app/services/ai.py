from __future__ import annotations

import json
import time
import asyncio
from dataclasses import dataclass
from typing import Any, TypeVar
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ValidationError

from ..config import Settings
from ..prompts import CRITIC_SYSTEM_PROMPT, INVESTIGATOR_SYSTEM_PROMPT
from ..schemas import CriticOutput, HypothesisDraft, InvestigatorOutput, ToolRequest, ValidationContract
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
        rate_limited = False
        for attempt in range(1, self.settings.model_retry_attempts + 1):
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
            except httpx.HTTPStatusError as exc:
                rate_limited = exc.response.status_code == 429
                provider_detail = exc.response.text.strip().replace("\n", " ")[:500]
                last_error = f"Model request failed ({exc.response.status_code}): {provider_detail or exc}"
                if rate_limited and attempt < self.settings.model_retry_attempts:
                    await asyncio.sleep(self._retry_delay_seconds(exc, attempt))
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = f"Your last output did not match the schema: {exc}"
            except httpx.TimeoutException as exc:
                last_error = f"Model timeout: {exc}"
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                last_error = f"Model request failed: {exc}"
        event = "MODEL_INVALID_OUTPUT" if "schema" in last_error or "valid" in last_error else "MODEL_RATE_LIMITED" if rate_limited else "MODEL_UNAVAILABLE"
        raise ModelFailure(event, last_error or f"{role} model failed")

    def _retry_delay_seconds(self, error: httpx.HTTPStatusError, attempt: int) -> float:
        retry_after = error.response.headers.get("Retry-After")
        try:
            if retry_after is not None:
                return min(max(float(retry_after), 0.0), self.settings.model_retry_max_delay_seconds)
        except ValueError:
            pass
        return min(float(2 ** (attempt - 1)), self.settings.model_retry_max_delay_seconds)

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
            if self._is_anthropic_base_url(base_url):
                return await self._anthropic_message(
                    client=client,
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    system_prompt=system_prompt,
                    user_message=user_message,
                )
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

    @staticmethod
    def _is_anthropic_base_url(base_url: str) -> bool:
        return urlparse(base_url).hostname == "api.anthropic.com"

    async def _anthropic_message(
        self,
        *,
        client: httpx.AsyncClient,
        base_url: str,
        api_key: str,
        model: str,
        system_prompt: str,
        user_message: dict[str, Any],
    ) -> str:
        response = await client.post(
            f"{base_url.rstrip('/')}/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 1024,
                "temperature": 0.1,
                "system": system_prompt,
                "messages": [{"role": "user", "content": json.dumps(user_message)}],
            },
        )
        response.raise_for_status()
        text = "".join(
            block.get("text", "")
            for block in response.json().get("content", [])
            if block.get("type") == "text"
        )
        if not text:
            raise ValueError("Anthropic response did not contain a text content block")
        return text

    def _deterministic(self, role: str, payload: dict[str, Any]) -> dict[str, Any]:
        if role == "investigator":
            target_id = payload["target_id"]
            approved_paths = [chunk["path"] for chunk in payload.get("retrieved_target_knowledge", [])]
            if target_id != "lab-web-01":
                hypotheses = [
                    HypothesisDraft(
                        title=f"Approved route {path} requires evidence-based review",
                        description="The explicitly authorized route is inspected read-only; its name alone is not a finding.",
                        reason="A direct status, header, and authentication observation is required before any conclusion.",
                        confidence=0.4,
                        required_evidence=["HTTP status", "response header inventory", "authentication behavior"],
                        validation_contract=ValidationContract(
                            claim_type="route_observation",
                            validation_path=path,
                            proof_evidence_kinds=["RESPONSE_HEADERS_OBSERVED"],
                            rejection_evidence_kinds=["AUTH_CONTROL_OBSERVED"],
                        ),
                        tool_request=ToolRequest(
                            tool="web_inspection",
                            target_id=target_id,
                            path=path,
                            reason=f"Collect direct read-only evidence from the approved route {path}.",
                        ),
                    )
                    for path in approved_paths[:5]
                ]
                return InvestigatorOutput(
                    reasoning_summary="Only onboarding-approved routes are available for deterministic read-only review.",
                    hypotheses=hypotheses,
                ).model_dump()
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
                        validation_contract=ValidationContract(
                            claim_type="unauthenticated_admin_exposure",
                            validation_path="/admin",
                            proof_evidence_kinds=["ADMIN_EXPOSURE"],
                            rejection_evidence_kinds=["AUTH_CONTROL_OBSERVED"],
                        ),
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
                        validation_contract=ValidationContract(
                            claim_type="missing_security_headers",
                            validation_path="/api/status",
                            proof_evidence_kinds=["MISSING_SECURITY_HEADERS"],
                            rejection_evidence_kinds=["RESPONSE_HEADERS_OBSERVED"],
                        ),
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
                        validation_contract=ValidationContract(
                            claim_type="unauthenticated_route_access",
                            validation_path="/api/debug",
                            proof_evidence_kinds=["UNAUTHENTICATED_ROUTE_EXPOSURE"],
                            rejection_evidence_kinds=["AUTH_CONTROL_OBSERVED"],
                        ),
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

    async def generate(
        self,
        target_id: str,
        discovery_evidence: list[dict[str, Any]],
        retrieved_target_knowledge: list[dict[str, Any]],
    ) -> ModelRun:
        return await self.client.call(
            role="investigator",
            schema=InvestigatorOutput,
            system_prompt=INVESTIGATOR_SYSTEM_PROMPT,
            payload={
                "target_id": target_id,
                "authorized": True,
                "available_tools": ["network_discovery", "web_inspection"],
                "discovery_evidence": discovery_evidence,
                "retrieved_target_knowledge": retrieved_target_knowledge,
            },
        )


class CriticService:
    def __init__(self, client: StructuredModelClient):
        self.client = client

    async def review(self, hypothesis: dict[str, Any], evidence: list[dict[str, Any]]) -> ModelRun:
        assessment = assess_evidence_contract(hypothesis, evidence)
        run = await self.client.call(
            role="critic",
            schema=CriticOutput,
            system_prompt=CRITIC_SYSTEM_PROMPT,
            payload={"hypothesis": hypothesis, "evidence": evidence, "backend_evidence_assessment": assessment},
        )
        output: CriticOutput = run.output  # type: ignore[assignment]
        forced = assessment["decision"]
        if forced:
            reason = assessment["reason"]
            output = output.model_copy(
                update={
                    "decision": forced,
                    "confidence": assessment["confidence"],
                    "reason": reason,
                    "missing_evidence": assessment["missing_evidence"],
                    "contradictions": assessment["contradictions"],
                }
            )
        return ModelRun(output=output, latency_ms=run.latency_ms, estimated_cost_usd=run.estimated_cost_usd, attempts=run.attempts)


def assess_evidence_contract(hypothesis: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply narrow, auditable validation rules before an AI opinion can affect state."""
    contract_data = hypothesis.get("validation_contract") or {}
    try:
        contract = ValidationContract.model_validate(contract_data)
    except ValidationError:
        return {
            "decision": "human_review",
            "confidence": 0.0,
            "reason": "The hypothesis lacks a schema-valid validation contract.",
            "missing_evidence": ["schema-valid validation contract"],
            "contradictions": [],
        }

    kinds = {str(item.get("kind") or "HTTP_RESPONSE_OBSERVED") for item in evidence}
    failures = kinds & {"TOOL_FAILED", "TOOL_TIMEOUT", "TOOL_UNAVAILABLE", "POLICY_REJECTED"}
    if failures:
        return {
            "decision": "human_review",
            "confidence": 0.0,
            "reason": "A tool or policy boundary failed; automated validation is prohibited.",
            "missing_evidence": ["successful read-only observation"],
            "contradictions": [],
        }

    # Header inventories accompany both present and absent-header observations.
    # The explicit missing-header signal therefore takes precedence over the
    # inventory itself; this rule is enforced in code, not delegated to a model.
    if contract.claim_type == "missing_security_headers":
        if "MISSING_SECURITY_HEADERS" in kinds:
            return {
                "decision": "validated",
                "confidence": 0.9,
                "reason": "The normalized header inventory explicitly identifies missing required headers.",
                "missing_evidence": [],
                "contradictions": [],
            }
        if "RESPONSE_HEADERS_OBSERVED" in kinds:
            return {
                "decision": "rejected",
                "confidence": 0.9,
                "reason": "A header inventory was collected and contains no normalized missing-header observation.",
                "missing_evidence": [],
                "contradictions": [],
            }

    proof = set(contract.proof_evidence_kinds) & kinds
    rejection = set(contract.rejection_evidence_kinds) & kinds
    if proof and rejection:
        return {
            "decision": "needs_more_evidence",
            "confidence": 0.25,
            "reason": "The evidence contains both proof and rejection signals for this contract.",
            "missing_evidence": ["repeatable observation resolving the conflict"],
            "contradictions": sorted(proof | rejection),
        }
    if proof:
        return {
            "decision": "validated",
            "confidence": 0.9,
            "reason": f"Observed required proof evidence: {', '.join(sorted(proof))}.",
            "missing_evidence": [],
            "contradictions": [],
        }
    if rejection:
        return {
            "decision": "rejected",
            "confidence": 0.9,
            "reason": f"Observed rejection evidence: {', '.join(sorted(rejection))}.",
            "missing_evidence": [],
            "contradictions": [],
        }
    return {
        "decision": "needs_more_evidence",
        "confidence": 0.3,
        "reason": "The evidence did not satisfy this hypothesis's explicit proof or rejection conditions.",
        "missing_evidence": sorted(set(contract.proof_evidence_kinds) | set(contract.rejection_evidence_kinds)),
        "contradictions": [],
    }
