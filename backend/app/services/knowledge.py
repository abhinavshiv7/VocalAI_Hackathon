"""Small, target-scoped retrieval corpus for the controlled SentinelLoop lab.

This is intentionally a local allowlisted corpus rather than general web search.
It gives a hosted Investigator the same authorized project context as the
deterministic demo without granting it new targets, tools, or execution power.
"""

from typing import Any


_TARGET_KNOWLEDGE: dict[str, list[dict[str, Any]]] = {
    "lab-web-01": [
        {
            "id": "lab-admin-access-control",
            "title": "Administrative route verification",
            "path": "/admin",
            "purpose": "Verify whether the controlled administrative route returns an unauthenticated response.",
            "expected_evidence": ["HTTP status", "authentication-challenge behavior"],
            "safe_tool": "web_inspection",
            "note": "This is an authorized test path, not evidence of a vulnerability by itself.",
        },
        {
            "id": "lab-status-header-baseline",
            "title": "Response-header baseline",
            "path": "/api/status",
            "purpose": "Inspect the controlled status endpoint for baseline browser security headers.",
            "expected_evidence": ["normalized response header inventory"],
            "safe_tool": "web_inspection",
            "note": "Validate only from observed headers; do not infer missing controls from a route name.",
        },
        {
            "id": "lab-debug-false-positive-control",
            "title": "Potential debug-route exposure",
            "path": "/api/debug",
            "purpose": "Test the risk hypothesis that a suspiciously named debug route is reachable without access control.",
            "expected_evidence": ["HTTP status", "access-control response"],
            "safe_tool": "web_inspection",
            "note": "A debug-like name is not a finding. A 401 or 403 denial response rejects this potential-exposure hypothesis.",
        },
    ]
}


def retrieve_target_knowledge(target_id: str, approved_paths: list[str] | None = None) -> list[dict[str, Any]]:
    """Return only the pre-approved knowledge chunks for this allowlisted target."""
    if target_id in _TARGET_KNOWLEDGE:
        return _TARGET_KNOWLEDGE[target_id]
    return [
        {
            "id": f"{target_id}-{index}",
            "title": f"Authorized route {path}",
            "path": path,
            "purpose": "Collect direct, read-only HTTP evidence for the explicitly approved route.",
            "expected_evidence": ["HTTP status", "response headers", "authentication behavior"],
            "safe_tool": "web_inspection",
            "note": "This route was supplied during target onboarding and is not evidence of a vulnerability by itself.",
        }
        for index, path in enumerate(approved_paths or [])
    ]


def approved_web_paths(target_id: str) -> set[str]:
    return {chunk["path"] for chunk in retrieve_target_knowledge(target_id)}
