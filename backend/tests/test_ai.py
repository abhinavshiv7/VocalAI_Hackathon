from types import SimpleNamespace

import pytest

from app.config import Settings
from app.prompts import CRITIC_SYSTEM_PROMPT, INVESTIGATOR_SYSTEM_PROMPT
from app.schemas import CriticOutput, FailureInjection, InvestigatorOutput, ToolRequest
from app.services.ai import CriticService, ModelFailure, StructuredModelClient, assess_evidence_contract
from app.services.failures import failure_controller
from app.services.tools import HttpxInspectionTool


@pytest.mark.asyncio
async def test_critic_rejects_protected_debug_route():
    critic = CriticService(StructuredModelClient(Settings(ai_mode="deterministic")))
    run = await critic.review(
        {
            "title": "Debug exposure",
            "validation_contract": {
                "claim_type": "unauthenticated_route_access",
                "validation_path": "/api/debug",
                "proof_evidence_kinds": ["ADMIN_EXPOSURE"],
                "rejection_evidence_kinds": ["AUTH_CONTROL_OBSERVED"],
            },
        },
        [{"kind": "AUTH_CONTROL_OBSERVED", "observation": "HTTP 403"}],
    )
    assert run.output.decision == "rejected"


@pytest.mark.asyncio
async def test_critic_requests_review_on_conflict():
    critic = CriticService(StructuredModelClient(Settings(ai_mode="deterministic")))
    run = await critic.review(
        {
            "title": "Admin exposure",
            "validation_contract": {
                "claim_type": "unauthenticated_admin_exposure",
                "validation_path": "/admin",
                "proof_evidence_kinds": ["ADMIN_EXPOSURE"],
                "rejection_evidence_kinds": ["AUTH_CONTROL_OBSERVED"],
            },
        },
        [
            {"kind": "ADMIN_EXPOSURE", "observation": "HTTP 200"},
            {"kind": "AUTH_CONTROL_OBSERVED", "observation": "HTTP 403"},
        ],
    )
    assert run.output.decision == "needs_more_evidence"


def test_contract_assessment_validates_only_explicit_proof_evidence():
    result = assess_evidence_contract(
        {
            "validation_contract": {
                "claim_type": "missing_security_headers",
                "validation_path": "/status",
                "proof_evidence_kinds": ["MISSING_SECURITY_HEADERS"],
                "rejection_evidence_kinds": ["RESPONSE_HEADERS_OBSERVED"],
            }
        },
        [{"kind": "MISSING_SECURITY_HEADERS", "observation": "CSP missing"}],
    )
    assert result["decision"] == "validated"


def test_contract_assessment_rejects_when_access_control_is_observed():
    result = assess_evidence_contract(
        {
            "validation_contract": {
                "claim_type": "unauthenticated_admin_exposure",
                "validation_path": "/admin",
                "proof_evidence_kinds": ["ADMIN_EXPOSURE"],
                "rejection_evidence_kinds": ["AUTH_CONTROL_OBSERVED"],
            }
        },
        [{"kind": "AUTH_CONTROL_OBSERVED", "observation": "HTTP 403"}],
    )
    assert result["decision"] == "rejected"


@pytest.fixture(autouse=True)
def clear_failures():
    failure_controller.configure(FailureInjection(kind="none", enabled=False))
    yield
    failure_controller.configure(FailureInjection(kind="none", enabled=False))


def test_live_role_prompts_keep_roles_and_backend_boundary_explicit():
    assert "A hypothesis is provisional" in INVESTIGATOR_SYSTEM_PROMPT
    assert "YOU MUST NOT" in INVESTIGATOR_SYSTEM_PROMPT
    assert "backend enforces scope" in INVESTIGATOR_SYSTEM_PROMPT
    assert "independent, conservative evidence reviewer" in CRITIC_SYSTEM_PROMPT
    assert "final validation invariant" in CRITIC_SYSTEM_PROMPT


def test_detects_anthropic_messages_api_base_url():
    assert StructuredModelClient._is_anthropic_base_url("https://api.anthropic.com")
    assert not StructuredModelClient._is_anthropic_base_url("https://api.openai.com/v1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "schema", "payload"),
    [
        ("investigator", InvestigatorOutput, {"target_id": "lab-web-01"}),
        ("critic", CriticOutput, {"hypothesis": {}, "evidence": []}),
    ],
)
async def test_injected_model_outages_stop_the_selected_role(role, schema, payload):
    failure_controller.configure(FailureInjection(kind="model", subject=role, enabled=True))

    with pytest.raises(ModelFailure, match=f"Injected {role} model outage"):
        await StructuredModelClient(Settings(ai_mode="deterministic")).call(
            role=role,
            schema=schema,
            system_prompt="test",
            payload=payload,
        )


@pytest.mark.asyncio
async def test_injected_malformed_critic_output_is_handled_as_a_model_failure():
    failure_controller.configure(FailureInjection(kind="malformed_output", subject="critic", enabled=True))

    with pytest.raises(ModelFailure) as failure:
        await StructuredModelClient(Settings(ai_mode="deterministic")).call(
            role="critic",
            schema=CriticOutput,
            system_prompt="test",
            payload={"hypothesis": {}, "evidence": []},
        )
    assert failure.value.event_type == "MODEL_INVALID_OUTPUT"


@pytest.mark.asyncio
async def test_injected_web_tool_outage_returns_normalized_failure_evidence():
    failure_controller.configure(FailureInjection(kind="tool", subject="web_inspection", enabled=True))

    result = await HttpxInspectionTool().execute(
        ToolRequest(tool="web_inspection", target_id="lab-web-01", path="/admin", reason="Failure test request."),
        SimpleNamespace(),
        timeout=1,
    )

    assert result.status == "FAILED"
    assert result.error_type == "TOOL_UNAVAILABLE"
    assert result.evidence[0].kind == "TOOL_UNAVAILABLE"
