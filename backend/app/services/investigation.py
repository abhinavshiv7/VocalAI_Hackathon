from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..database import AuditEvent, Evidence, Finding, Hypothesis, Investigation, Target, ToolExecution
from ..schemas import CriticOutput, HypothesisStatus, InvestigationStatus, TargetCreate, ToolRequest
from .ai import CriticService, InvestigatorService, ModelFailure, StructuredModelClient
from .knowledge import retrieve_target_knowledge
from .policy import PolicyEngine, PolicyViolation
from .tools import ToolResult, tool_registry


def now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def add_event(session: Session, investigation_id: str, event_type: str, message: str, detail: dict | None = None) -> None:
    session.add(
        AuditEvent(
            investigation_id=investigation_id,
            event_type=event_type,
            message=message,
            detail=detail or {},
        )
    )


class InvestigationManager:
    def __init__(self, session: Session, settings: Settings):
        self.session = session
        self.settings = settings
        client = StructuredModelClient(settings)
        self.investigator = InvestigatorService(client)
        self.critic = CriticService(client)
        self.policy = PolicyEngine()

    def list_targets(self) -> list[Target]:
        return list(self.session.scalars(select(Target).order_by(Target.id)))

    def register_target(self, payload: TargetCreate) -> Target:
        parsed = urlsplit(payload.base_url)
        approved_hosts = {host.strip().lower() for host in self.settings.authorized_target_hosts.split(",") if host.strip()}
        if self.settings.target_registration_mode == "allowlisted" and (parsed.hostname is None or parsed.hostname.lower() not in approved_hosts):
            raise PolicyViolation("TARGET_HOST_NOT_APPROVED: ask an administrator to add this lab host to AUTHORIZED_TARGET_HOSTS")
        target = Target(
            id=new_id("TGT"),
            name=payload.name,
            environment=payload.environment,
            host=parsed.hostname,
            port=parsed.port or (443 if parsed.scheme == "https" else 80),
            base_url=payload.base_url,
            authorized=True,
            allowed_tools=["network_discovery", "web_inspection"],
            approved_paths=payload.approved_paths,
        )
        self.session.add(target)
        self.session.commit()
        return target

    def create(self, target_id: str) -> Investigation:
        target = self.session.get(Target, target_id)
        if target is None or not target.authorized:
            raise PolicyViolation("UNAUTHORIZED_TARGET: select an explicitly allowlisted target")
        investigation = Investigation(id=new_id("INV"), target_id=target_id, status=InvestigationStatus.CREATED)
        self.session.add(investigation)
        self.session.flush()
        add_event(self.session, investigation.id, "INVESTIGATION_CREATED", "Investigation created for an authorized target")
        self.session.commit()
        return investigation

    def get(self, investigation_id: str) -> Investigation | None:
        return self.session.get(Investigation, investigation_id)

    def list(self, limit: int = 20) -> list[Investigation]:
        statement = select(Investigation).order_by(Investigation.created_at.desc()).limit(limit)
        return list(self.session.scalars(statement))

    async def start(self, investigation_id: str) -> Investigation:
        investigation = self.session.get(Investigation, investigation_id)
        if not investigation:
            raise KeyError(investigation_id)
        if investigation.status != InvestigationStatus.CREATED:
            return investigation
        target = investigation.target
        investigation.started_at = now()
        self._transition(investigation, InvestigationStatus.DISCOVERING, "Authorized discovery started")

        discovery_request = ToolRequest(
            tool="network_discovery",
            target_id=target.id,
            path="/",
            reason="Establish whether the declared lab service is reachable before forming hypotheses.",
        )
        discovery_evidence = await self._run_tool(investigation, target, discovery_request, None)

        try:
            if investigation.model_calls >= self.settings.max_investigator_calls:
                raise ModelFailure("MODEL_BUDGET_EXCEEDED", "Investigator call budget exhausted")
            retrieved_knowledge = retrieve_target_knowledge(target.id, target.approved_paths)
            investigator_run = await self.investigator.generate(
                target.id,
                [evidence_to_dict(e) for e in discovery_evidence],
                retrieved_knowledge,
            )
            investigation.model_calls += investigator_run.attempts
            investigation.estimated_cost_usd += investigator_run.estimated_cost_usd
            drafts = investigator_run.output.hypotheses
            add_event(
                self.session,
                investigation.id,
                "INVESTIGATOR_COMPLETED",
                investigator_run.output.reasoning_summary,
                {
                    "latency_ms": investigator_run.latency_ms,
                    "hypotheses": len(drafts),
                    "retrieved_knowledge_chunks": len(retrieved_knowledge),
                },
            )
        except ModelFailure as exc:
            investigation.model_calls += 2 if exc.event_type == "MODEL_INVALID_OUTPUT" else 1
            self._degrade(investigation, exc.event_type, str(exc))
            fallback = Hypothesis(
                id=new_id("H"),
                investigation_id=investigation.id,
                title="Investigation requires human triage",
                description="The Investigator model did not return a usable, schema-valid plan.",
                reason=str(exc),
                confidence=0.0,
                status=HypothesisStatus.NEEDS_HUMAN_REVIEW,
                required_evidence=["schema-valid Investigator output"],
            )
            self.session.add(fallback)
            self._human_finding(investigation, fallback, [], "AI planning unavailable; no automated conclusion was made.")
            self._finish(investigation)
            return investigation

        self._transition(investigation, InvestigationStatus.HYPOTHESIS_GENERATED, f"Generated {len(drafts)} structured hypotheses")

        for draft in drafts:
            hypothesis = Hypothesis(
                id=new_id("H"),
                investigation_id=investigation.id,
                title=draft.title,
                description=draft.description,
                reason=draft.reason,
                confidence=draft.confidence,
                status=HypothesisStatus.UNDER_INVESTIGATION,
                required_evidence=draft.required_evidence,
            )
            self.session.add(hypothesis)
            self.session.flush()
            self._transition(investigation, InvestigationStatus.INVESTIGATING, f"Testing hypothesis {hypothesis.id}")
            evidence = await self._run_tool(investigation, target, draft.tool_request, hypothesis.id)
            self._transition(investigation, InvestigationStatus.CRITIC_REVIEW, f"Critic reviewing {hypothesis.id}")

            try:
                if investigation.model_calls >= self.settings.max_investigator_calls + self.settings.max_critic_calls:
                    raise ModelFailure("MODEL_BUDGET_EXCEEDED", "Critic call budget exhausted")
                critic_run = await self.critic.review(hypothesis_to_dict(hypothesis), [evidence_to_dict(item) for item in evidence])
                investigation.model_calls += critic_run.attempts
                investigation.estimated_cost_usd += critic_run.estimated_cost_usd
                decision: CriticOutput = critic_run.output  # type: ignore[assignment]
                hypothesis.critic_decision = decision.model_dump()
                hypothesis.confidence = decision.confidence
                add_event(
                    self.session,
                    investigation.id,
                    "CRITIC_COMPLETED",
                    decision.reason,
                    {"hypothesis_id": hypothesis.id, "decision": decision.decision, "latency_ms": critic_run.latency_ms},
                )
                if decision.decision == "needs_more_evidence" and draft.follow_up_tool_request:
                    self._transition(
                        investigation,
                        InvestigationStatus.INVESTIGATING,
                        f"Collecting preplanned follow-up evidence for {hypothesis.id}",
                    )
                    follow_up_evidence = await self._run_tool(
                        investigation,
                        target,
                        draft.follow_up_tool_request,
                        hypothesis.id,
                    )
                    evidence.extend(follow_up_evidence)
                    self._transition(investigation, InvestigationStatus.CRITIC_REVIEW, f"Critic re-reviewing {hypothesis.id}")
                    follow_up_run = await self.critic.review(
                        hypothesis_to_dict(hypothesis),
                        [evidence_to_dict(item) for item in evidence],
                    )
                    investigation.model_calls += follow_up_run.attempts
                    investigation.estimated_cost_usd += follow_up_run.estimated_cost_usd
                    decision = follow_up_run.output  # type: ignore[assignment]
                    hypothesis.critic_decision = decision.model_dump()
                    hypothesis.confidence = decision.confidence
                    add_event(
                        self.session,
                        investigation.id,
                        "CRITIC_FOLLOW_UP_COMPLETED",
                        decision.reason,
                        {"hypothesis_id": hypothesis.id, "decision": decision.decision, "latency_ms": follow_up_run.latency_ms},
                    )
                self._apply_critic_decision(investigation, hypothesis, evidence, decision)
            except ModelFailure as exc:
                investigation.model_calls += 2 if exc.event_type == "MODEL_INVALID_OUTPUT" else 1
                self._degrade(investigation, exc.event_type, str(exc))
                hypothesis.status = HypothesisStatus.NEEDS_HUMAN_REVIEW
                self._human_finding(investigation, hypothesis, evidence, "Critic unavailable; VALIDATED state is prohibited.")

        self._finish(investigation)
        return investigation

    async def _run_tool(
        self,
        investigation: Investigation,
        target: Target,
        request: ToolRequest,
        hypothesis_id: str | None,
    ) -> list[Evidence]:
        try:
            decision = self.policy.authorize(request, target, investigation, self.settings.max_tool_calls)
            add_event(self.session, investigation.id, "POLICY_APPROVED", decision.reason, request.model_dump())
        except PolicyViolation as exc:
            self._degrade(investigation, "POLICY_REJECTED", str(exc))
            return [self._failure_evidence(investigation, hypothesis_id, request.tool, "POLICY_REJECTED", str(exc))]

        execution = ToolExecution(
            id=new_id("T"),
            investigation_id=investigation.id,
            hypothesis_id=hypothesis_id,
            tool=request.tool,
            status="RUNNING",
            input_summary=f"{request.operation} {request.path} on {target.id}",
        )
        self.session.add(execution)
        self.session.flush()
        investigation.tool_calls += 1
        result = await tool_registry.get(request.tool).execute(request, target, self.settings.tool_timeout_seconds)
        execution.status = result.status
        execution.result_summary = result.summary
        execution.latency_ms = result.latency_ms
        execution.completed_at = now()
        records: list[Evidence] = []
        for item in result.evidence:
            record = Evidence(
                id=new_id("E"),
                investigation_id=investigation.id,
                hypothesis_id=hypothesis_id,
                source=item.source,
                target=target.id,
                observation=item.observation,
                severity=item.severity,
                kind=item.kind,
                raw=item.raw,
            )
            self.session.add(record)
            records.append(record)
        event_type = "TOOL_COMPLETED" if result.status == "SUCCEEDED" else (result.error_type or "TOOL_FAILED")
        add_event(
            self.session,
            investigation.id,
            event_type,
            result.summary,
            {"tool": request.tool, "hypothesis_id": hypothesis_id, "latency_ms": result.latency_ms},
        )
        if result.status != "SUCCEEDED":
            investigation.degraded_mode = True
        self.session.flush()
        return records

    def _apply_critic_decision(
        self,
        investigation: Investigation,
        hypothesis: Hypothesis,
        evidence: list[Evidence],
        decision: CriticOutput,
    ) -> None:
        evidence_failed = any(
            item.kind in {"TOOL_FAILED", "TOOL_TIMEOUT", "TOOL_UNAVAILABLE", "POLICY_REJECTED"}
            for item in evidence
        )
        if decision.decision == "validated" and not evidence_failed:
            hypothesis.status = HypothesisStatus.VALIDATED
            severity = strongest_severity(evidence)
            self.session.add(
                Finding(
                    id=new_id("F"),
                    investigation_id=investigation.id,
                    hypothesis_id=hypothesis.id,
                    title=hypothesis.title,
                    severity=severity,
                    confidence=decision.confidence,
                    status="VALIDATED",
                    evidence_refs=[item.id for item in evidence],
                    recommendation=recommendation_for(evidence),
                )
            )
        elif decision.decision == "rejected":
            hypothesis.status = HypothesisStatus.REJECTED
        else:
            hypothesis.status = HypothesisStatus.NEEDS_HUMAN_REVIEW
            self._human_finding(investigation, hypothesis, evidence, decision.reason)

    def _human_finding(
        self,
        investigation: Investigation,
        hypothesis: Hypothesis,
        evidence: list[Evidence],
        reason: str,
    ) -> None:
        self.session.add(
            Finding(
                id=new_id("F"),
                investigation_id=investigation.id,
                hypothesis_id=hypothesis.id,
                title=hypothesis.title,
                severity="unknown",
                confidence=hypothesis.confidence,
                status="NEEDS_HUMAN_REVIEW",
                evidence_refs=[item.id for item in evidence],
                recommendation=f"Collect missing evidence manually. Automated rationale: {reason}",
            )
        )

    def _failure_evidence(
        self,
        investigation: Investigation,
        hypothesis_id: str | None,
        source: str,
        kind: str,
        message: str,
    ) -> Evidence:
        record = Evidence(
            id=new_id("E"),
            investigation_id=investigation.id,
            hypothesis_id=hypothesis_id,
            source=source,
            target=investigation.target_id,
            observation=message,
            severity="info",
            kind=kind,
            raw={"error": kind},
        )
        self.session.add(record)
        self.session.flush()
        return record

    def _degrade(self, investigation: Investigation, event_type: str, message: str) -> None:
        investigation.degraded_mode = True
        investigation.status = InvestigationStatus.HUMAN_REVIEW
        add_event(self.session, investigation.id, event_type, message)

    def _transition(self, investigation: Investigation, status: InvestigationStatus, message: str) -> None:
        investigation.status = status
        add_event(self.session, investigation.id, "STATE_CHANGED", message, {"status": status})
        self.session.flush()

    def _finish(self, investigation: Investigation) -> None:
        self.session.flush()
        findings = list(self.session.scalars(select(Finding).where(Finding.investigation_id == investigation.id)))
        validated = sum(item.status == "VALIDATED" for item in findings)
        review = sum(item.status == "NEEDS_HUMAN_REVIEW" for item in findings)
        rejected = sum(item.status == HypothesisStatus.REJECTED for item in investigation.hypotheses)
        investigation.status = InvestigationStatus.HUMAN_REVIEW if review else InvestigationStatus.COMPLETED
        investigation.completed_at = now()
        investigation.summary = f"{validated} validated, {review} human review, {rejected} rejected"
        add_event(
            self.session,
            investigation.id,
            "INVESTIGATION_COMPLETED",
            investigation.summary,
            {"degraded_mode": investigation.degraded_mode},
        )
        self.session.commit()


def strongest_severity(evidence: list[Evidence]) -> str:
    weights = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    return max((item.severity for item in evidence), key=lambda item: weights.get(item, 0), default="unknown")


def recommendation_for(evidence: list[Evidence]) -> str:
    kinds = {item.kind for item in evidence}
    if "ADMIN_EXPOSURE" in kinds:
        return "Require authenticated, authorized access to /admin and avoid returning sensitive account metadata."
    if "MISSING_SECURITY_HEADERS" in kinds:
        return "Add CSP, X-Frame-Options, and X-Content-Type-Options at the application or reverse-proxy layer."
    return "Review the supporting evidence and apply the least-privilege configuration change."


def evidence_to_dict(item: Evidence) -> dict:
    return {
        "id": item.id,
        "hypothesis_id": item.hypothesis_id,
        "source": item.source,
        "target": item.target,
        "observation": item.observation,
        "severity": item.severity,
        "kind": item.kind,
        "raw": item.raw,
        "created_at": item.created_at.isoformat(),
    }


def hypothesis_to_dict(item: Hypothesis) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "reason": item.reason,
        "confidence": item.confidence,
        "status": item.status,
        "required_evidence": item.required_evidence,
        "critic_decision": item.critic_decision,
        "created_at": item.created_at.isoformat(),
    }


def investigation_to_dict(item: Investigation) -> dict:
    return {
        "id": item.id,
        "target_id": item.target_id,
        "target": target_to_dict(item.target),
        "status": item.status,
        "degraded_mode": item.degraded_mode,
        "summary": item.summary,
        "estimated_cost_usd": round(item.estimated_cost_usd, 6),
        "model_calls": item.model_calls,
        "tool_calls": item.tool_calls,
        "started_at": item.started_at.isoformat() if item.started_at else None,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        "created_at": item.created_at.isoformat(),
        "hypotheses": [hypothesis_to_dict(value) for value in sorted(item.hypotheses, key=lambda x: x.created_at.isoformat())],
        "evidence": [evidence_to_dict(value) for value in sorted(item.evidence, key=lambda x: x.created_at.isoformat())],
        "tool_executions": [
            {
                "id": value.id,
                "hypothesis_id": value.hypothesis_id,
                "tool": value.tool,
                "status": value.status,
                "input_summary": value.input_summary,
                "result_summary": value.result_summary,
                "latency_ms": value.latency_ms,
                "started_at": value.started_at.isoformat(),
                "completed_at": value.completed_at.isoformat() if value.completed_at else None,
            }
            for value in sorted(item.tool_executions, key=lambda x: x.started_at.isoformat())
        ],
        "findings": [
            {
                "id": value.id,
                "hypothesis_id": value.hypothesis_id,
                "title": value.title,
                "severity": value.severity,
                "confidence": value.confidence,
                "status": value.status,
                "evidence_refs": value.evidence_refs,
                "recommendation": value.recommendation,
                "created_at": value.created_at.isoformat(),
            }
            for value in sorted(item.findings, key=lambda x: x.created_at.isoformat())
        ],
        "events": [
            {
                "id": value.id,
                "event_type": value.event_type,
                "message": value.message,
                "detail": value.detail,
                "created_at": value.created_at.isoformat(),
            }
            for value in sorted(item.events, key=lambda x: x.created_at.isoformat())
        ],
    }


def target_to_dict(item: Target) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "environment": item.environment,
        "host": item.host,
        "port": item.port,
        "base_url": item.base_url,
        "authorized": item.authorized,
        "allowed_tools": item.allowed_tools,
        "approved_paths": item.approved_paths,
    }
