import pytest

from app.config import Settings
from app.prompts import CRITIC_SYSTEM_PROMPT, INVESTIGATOR_SYSTEM_PROMPT
from app.schemas import FailureInjection
from app.services.ai import CriticService, StructuredModelClient
from app.services.failures import failure_controller


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


def test_live_role_prompts_keep_roles_and_backend_boundary_explicit():
    assert "not a confirmed finding" in INVESTIGATOR_SYSTEM_PROMPT
    assert "You MUST NOT" in INVESTIGATOR_SYSTEM_PROMPT
    assert "backend enforces scope" in INVESTIGATOR_SYSTEM_PROMPT
    assert "independent, conservative evidence reviewer" in CRITIC_SYSTEM_PROMPT
    assert "final validation invariant" in CRITIC_SYSTEM_PROMPT
    yield
    failure_controller.configure(FailureInjection(kind="none", enabled=False))
