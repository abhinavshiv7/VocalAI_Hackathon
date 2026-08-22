from types import SimpleNamespace

import pytest

from app.schemas import ToolRequest
from app.services.policy import PolicyEngine, PolicyViolation


def investigation(calls: int = 0):
    return SimpleNamespace(tool_calls=calls)


def target(authorized: bool = True):
    return SimpleNamespace(
        id="lab-web-01",
        authorized=authorized,
        allowed_tools=["network_discovery", "web_inspection"],
        base_url="http://fake-target:3000",
        host="fake-target",
    )


def test_allows_read_only_request_for_allowlisted_target():
    request = ToolRequest(
        tool="web_inspection",
        target_id="lab-web-01",
        path="/admin",
        reason="Collect direct authentication evidence.",
    )
    assert PolicyEngine().authorize(request, target(), investigation(), 10).allowed


def test_rejects_unauthorized_target():
    request = ToolRequest(
        tool="web_inspection",
        target_id="lab-web-01",
        path="/admin",
        reason="Collect direct authentication evidence.",
    )
    with pytest.raises(PolicyViolation, match="UNAUTHORIZED_TARGET"):
        PolicyEngine().authorize(request, target(False), investigation(), 10)


def test_rejects_budget_exhaustion():
    request = ToolRequest(
        tool="network_discovery",
        target_id="lab-web-01",
        reason="Verify declared service reachability.",
    )
    with pytest.raises(PolicyViolation, match="TOOL_BUDGET_EXCEEDED"):
        PolicyEngine().authorize(request, target(), investigation(10), 10)


def test_rejects_web_path_outside_approved_target_knowledge():
    request = ToolRequest(
        tool="web_inspection",
        target_id="lab-web-01",
        path="/unapproved",
        reason="Attempt to inspect a route outside the approved playbook.",
    )
    with pytest.raises(PolicyViolation, match="PATH_NOT_ALLOWED"):
        PolicyEngine().authorize(request, target(), investigation(), 10)
