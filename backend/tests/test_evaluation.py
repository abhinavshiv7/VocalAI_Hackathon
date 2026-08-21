import pytest

from app.config import Settings
from app.services.evaluation import run_evaluation


@pytest.mark.asyncio
async def test_evaluation_suite_is_deterministic():
    summary = await run_evaluation(Settings(ai_mode="deterministic"))
    assert summary.scenarios == 10
    assert summary.success_rate == 100
    assert summary.false_positives == 0
    assert summary.graceful_failure_rate == 100

