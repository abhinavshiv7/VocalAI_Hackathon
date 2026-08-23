from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .database import SessionLocal, init_db
from .schemas import EvaluationSummary, FailureInjection, HealthView, InvestigationCreate, TargetCreate, TargetView
from .services.evaluation import run_evaluation
from .services.failures import failure_controller
from .services.investigation import InvestigationManager, add_event, investigation_to_dict, target_to_dict
from .services.policy import PolicyViolation
from .services.tools import tool_registry


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


settings = get_settings()
configured_origins = [origin.strip() for origin in settings.frontend_origin.split(",") if origin.strip()]
cors_options = {"allow_origins": configured_origins} if configured_origins else {
    # The dashboard can be opened through a VM IP, DNS name, or a proxy. This
    # fallback keeps the pre-built image portable; set FRONTEND_ORIGIN in a
    # production deployment to restrict access to known dashboard origins.
    "allow_origin_regex": r"^https?://[^/]+$"
}
app = FastAPI(
    title="SentinelLoop API",
    version="0.1.0",
    description="Evidence-backed AI security validation for explicitly authorized lab targets.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    **cors_options,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def manager(session: Session = Depends(get_db), config: Settings = Depends(get_settings)) -> InvestigationManager:
    return InvestigationManager(session, config)


@app.get("/api/health", response_model=HealthView)
def health(session: Session = Depends(get_db), config: Settings = Depends(get_settings)) -> HealthView:
    session.execute(text("SELECT 1"))
    return HealthView(status="ok", database="connected", ai_mode=config.ai_mode, timestamp=datetime.now(UTC))


@app.get("/api/targets", response_model=list[TargetView])
def targets(service: InvestigationManager = Depends(manager)):
    return [target_to_dict(item) for item in service.list_targets()]


@app.post("/api/targets", response_model=TargetView, status_code=201)
def register_target(payload: TargetCreate, service: InvestigationManager = Depends(manager)):
    try:
        return target_to_dict(service.register_target(payload))
    except PolicyViolation as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/api/tools")
def tools():
    return tool_registry.describe()


@app.post("/api/investigations", status_code=201)
def create_investigation(payload: InvestigationCreate, service: InvestigationManager = Depends(manager)):
    try:
        return investigation_to_dict(service.create(payload.target_id))
    except PolicyViolation as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/api/investigations")
def list_investigations(service: InvestigationManager = Depends(manager)):
    return [investigation_to_dict(item) for item in service.list()]


@app.get("/api/investigations/{investigation_id}")
def get_investigation(investigation_id: str, service: InvestigationManager = Depends(manager)):
    item = service.get(investigation_id)
    if not item:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return investigation_to_dict(item)


@app.post("/api/investigations/{investigation_id}/start")
async def start_investigation(investigation_id: str, service: InvestigationManager = Depends(manager)):
    try:
        return investigation_to_dict(await service.start(investigation_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Investigation not found") from exc


@app.get("/api/investigations/{investigation_id}/hypotheses")
def hypotheses(investigation_id: str, service: InvestigationManager = Depends(manager)):
    item = service.get(investigation_id)
    if not item:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return investigation_to_dict(item)["hypotheses"]


@app.get("/api/investigations/{investigation_id}/evidence")
def evidence(investigation_id: str, service: InvestigationManager = Depends(manager)):
    item = service.get(investigation_id)
    if not item:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return investigation_to_dict(item)["evidence"]


@app.get("/api/investigations/{investigation_id}/findings")
def findings(investigation_id: str, service: InvestigationManager = Depends(manager)):
    item = service.get(investigation_id)
    if not item:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return investigation_to_dict(item)["findings"]


@app.post("/api/investigations/{investigation_id}/approve")
def approve_human_review(investigation_id: str, service: InvestigationManager = Depends(manager)):
    item = service.get(investigation_id)
    if not item:
        raise HTTPException(status_code=404, detail="Investigation not found")
    if item.status != "HUMAN_REVIEW":
        raise HTTPException(status_code=409, detail="Investigation is not awaiting human review")
    item.status = "COMPLETED"
    item.summary = f"{item.summary}; human review acknowledged"
    add_event(service.session, item.id, "HUMAN_REVIEW_ACKNOWLEDGED", "A human acknowledged the review handoff")
    service.session.commit()
    return investigation_to_dict(item)


@app.get("/api/evaluations", response_model=EvaluationSummary)
async def evaluations(config: Settings = Depends(get_settings)) -> EvaluationSummary:
    return await run_evaluation(config)


@app.post("/api/debug/inject-failure")
def inject_failure(payload: FailureInjection, config: Settings = Depends(get_settings)):
    if not config.debug_failures_enabled:
        raise HTTPException(status_code=404, detail="Failure injection is disabled")
    state = failure_controller.configure(payload)
    return state.__dict__


@app.get("/api/debug/inject-failure")
def get_failure_state(config: Settings = Depends(get_settings)):
    if not config.debug_failures_enabled:
        raise HTTPException(status_code=404, detail="Failure injection is disabled")
    return failure_controller.snapshot().__dict__
