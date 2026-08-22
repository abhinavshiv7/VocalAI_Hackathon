from types import SimpleNamespace

import pytest

from app.config import Settings
from app.prompts import CRITIC_SYSTEM_PROMPT, INVESTIGATOR_SYSTEM_PROMPT
from app.schemas import CriticOutput, FailureInjection, InvestigatorOutput, ToolRequest
from app.services.ai import CriticService, ModelFailure, StructuredModelClient
from app.services.failures import failure_controller
from app.services.tools import HttpxInspectionTool


@pytest.mark.asyncio
async def test_critic_rejects_protected_debug_route():
    critic = CriticService(StructuredModelClient(Settings(ai_mode="deterministic")))
    run = await critic.review(
        {"title": "Debug exposure"},
        [{"kind": "AUTH_CONTROL_OBSERVED", "observation": "HTTP 403"}],
    )
    assert run.output.decision == "rejected"


@pytest.mark.asyncio
async def test_critic_requests_review_on_conflict():
    critic = CriticService(StructuredModelClient(Settings(ai_mode="deterministic")))
    run = await critic.review(
        {"title": "Admin exposure"},
        [
            {"kind": "ADMIN_EXPOSURE", "observation": "HTTP 200"},
            {"kind": "AUTH_CONTROL_OBSERVED", "observation": "HTTP 403"},
        ],
    )
    assert run.output.decision == "needs_more_evidence"


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
