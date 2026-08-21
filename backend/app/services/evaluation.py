from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import Settings
from ..schemas import CriticOutput, EvaluationSummary, FailureInjection
from .ai import CriticService, ModelFailure, StructuredModelClient
from .failures import failure_controller


def _scenario_file() -> Path:
    candidates = [
        Path("evaluation/scenarios/scenarios.json"),
        Path("../evaluation/scenarios/scenarios.json"),
        Path("/workspace/evaluation/scenarios/scenarios.json"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("evaluation/scenarios/scenarios.json")


async def run_evaluation(settings: Settings) -> EvaluationSummary:
    scenarios: list[dict[str, Any]] = json.loads(_scenario_file().read_text(encoding="utf-8"))
    critic = CriticService(StructuredModelClient(settings.model_copy(update={"ai_mode": "deterministic"})))
    previous = failure_controller.snapshot()
    results: list[dict[str, Any]] = []
    try:
        for scenario in scenarios:
            injection = scenario.get("failure")
            failure_controller.configure(
                FailureInjection(
                    kind=injection or "none",
                    subject="critic" if injection else None,
                    enabled=bool(injection),
                )
            )
            try:
                run = await critic.review(scenario["hypothesis"], scenario["evidence"])
                decision: CriticOutput = run.output  # type: ignore[assignment]
                outcome = {
                    "validated": "VALIDATED",
                    "rejected": "REJECTED",
                    "needs_more_evidence": "NEEDS_HUMAN_REVIEW",
                    "human_review": "NEEDS_HUMAN_REVIEW",
                }[decision.decision]
                confidence = decision.confidence
            except ModelFailure:
                outcome = "NEEDS_HUMAN_REVIEW"
                confidence = 0.0
            expected = scenario["expected_status"]
            confidence_range = scenario.get("confidence_range", [0.0, 1.0])
            correct = outcome == expected
            confidence_ok = confidence_range[0] <= confidence <= confidence_range[1]
            results.append(
                {
                    "id": scenario["id"],
                    "name": scenario["name"],
                    "expected": expected,
                    "actual": outcome,
                    "confidence": confidence,
                    "correct": correct,
                    "confidence_ok": confidence_ok,
                    "failure_scenario": bool(injection or scenario.get("failure_scenario")),
                }
            )
    finally:
        failure_controller.configure(
            FailureInjection(kind=previous.kind, subject=previous.subject, enabled=previous.enabled)
        )

    correct = sum(item["correct"] for item in results)
    false_positives = sum(item["actual"] == "VALIDATED" and item["expected"] != "VALIDATED" for item in results)
    false_confidence = sum(not item["confidence_ok"] for item in results)
    failure_results = [item for item in results if item["failure_scenario"]]
    graceful = sum(item["actual"] == "NEEDS_HUMAN_REVIEW" for item in failure_results)
    return EvaluationSummary(
        scenarios=len(results),
        correct_conclusions=correct,
        false_positives=false_positives,
        false_confidence=false_confidence,
        graceful_failures=graceful,
        success_rate=round(correct / len(results) * 100, 1) if results else 0,
        graceful_failure_rate=round(graceful / len(failure_results) * 100, 1) if failure_results else 100,
        results=results,
    )

