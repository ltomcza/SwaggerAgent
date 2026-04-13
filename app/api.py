import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session, selectinload

from app import crud, markdown
from app.database import get_db
from app.models import Service
from app.schemas import (
    ScanByNameResponse,
    ScanAllResponse,
    ScanStatusResponse,
    ScanTriggerResponse,
    ServiceCreate,
    ServiceListResponse,
    ServiceResponse,
    ServiceUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_scan_background(service_id: int, swagger_url: str, force: bool = False) -> None:
    """Runs the background scan — calls the agent and updates the service status.

    When force=False (default) and no endpoint changes are detected, the scan
    finishes early with status 'no_changes' instead of running the full pipeline.
    """
    from app import agent
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        log = crud.create_scan_log(db, service_id)
        result = agent.run_swagger_analysis(service_id, swagger_url, force=force)
        if result == "no_changes":
            crud.update_service(
                db,
                service_id,
                scan_status="completed",
                last_scanned_at=datetime.now(timezone.utc),
            )
            crud.finish_scan_log(
                db,
                log.id,
                status="no_changes",
                endpoints_found=_count_endpoints(db, service_id),
            )
            logger.info(f"Background scan found no changes for service {service_id}")
        else:
            crud.update_service(db, service_id, scan_status="completed")
            crud.finish_scan_log(
                db,
                log.id,
                status="completed",
                endpoints_found=_count_endpoints(db, service_id),
            )
            logger.info(f"Background scan completed for service {service_id}: {result[:100]}")
    except Exception as e:
        logger.error(f"Background scan failed for service {service_id}: {e}")
        try:
            crud.update_service(db, service_id, scan_status="error", scan_error=str(e))
            if "log" in locals():
                crud.finish_scan_log(db, log.id, status="error", error=str(e))
        except Exception:
            pass
    finally:
        db.close()


def _count_endpoints(db: Session, service_id: int) -> int:
    from app.models import Endpoint

    return db.query(Endpoint).filter(Endpoint.service_id == service_id).count()


def _run_analysis_background(service_id: int) -> None:
    """Re-runs LLM analysis on already-scanned service data (no re-fetch)."""
    from app.database import SessionLocal
    from app.tools import analyze_service_with_llm

    db = SessionLocal()
    try:
        service = (
            db.query(Service)
            .options(selectinload(Service.endpoints))
            .filter(Service.id == service_id)
            .first()
        )
        if service is None:
            return

        # Reconstruct parsed-doc dict from existing DB state
        parsed_doc = {
            "title": service.name,
            "description": service.description,
            "version": service.swagger_version,
            "base_url": service.base_url,
            "endpoints": [
                {
                    "path": ep.path,
                    "method": ep.method,
                    "summary": ep.summary,
                    "description": ep.description,
                    "tags": ep.tags,
                    "parameters_json": ep.parameters_json,
                    "request_body_json": ep.request_body_json,
                    "response_json": ep.response_json,
                    "deprecated": ep.deprecated,
                }
                for ep in service.endpoints
            ],
        }
        result = analyze_service_with_llm(service_id, parsed_doc)
        logger.info(f"On-demand analysis completed for service {service_id}: {result[:100]}")
    except Exception as e:
        logger.error(f"On-demand analysis failed for service {service_id}: {e}")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/services", response_model=ServiceResponse, status_code=201)
def create_service(payload: ServiceCreate, db: Session = Depends(get_db)):
    """Add a new service. Returns 409 if the URL already exists."""
    existing = crud.get_service_by_url(db, payload.swagger_url)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Service with this URL already exists")
    service = crud.create_service(db, name=payload.name, swagger_url=payload.swagger_url)
    db.refresh(service)
    return service


@router.get("/services/markdown/all")
def get_all_services_markdown(db: Session = Depends(get_db)):
    """Returns a Markdown report for all services."""
    services = db.query(Service).options(selectinload(Service.endpoints)).all()
    md = markdown.all_services_to_markdown(services)
    return Response(content=md, media_type="text/markdown; charset=utf-8")


@router.get("/services", response_model=list[ServiceListResponse])
def list_services(db: Session = Depends(get_db)):
    """List all services with endpoint counts."""
    services = db.query(Service).options(selectinload(Service.endpoints)).order_by(Service.id).all()
    result = []
    for service in services:
        item = ServiceListResponse.model_validate(service)
        item.endpoint_count = len(service.endpoints)
        result.append(item)
    return result


@router.get("/services/{service_id}", response_model=ServiceResponse)
def get_service(service_id: int, db: Session = Depends(get_db)):
    """Service details with endpoints."""
    service = (
        db.query(Service)
        .options(selectinload(Service.endpoints))
        .filter(Service.id == service_id)
        .first()
    )
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")
    return service


@router.put("/services/{service_id}", response_model=ServiceResponse)
def update_service(
    service_id: int, payload: ServiceUpdate, db: Session = Depends(get_db)
):
    """Edit a service."""
    service = crud.get_service(db, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")

    # Check uniqueness of the new URL if it changes
    if payload.swagger_url is not None and payload.swagger_url != str(service.swagger_url):
        existing = crud.get_service_by_url(db, payload.swagger_url)
        if existing is not None:
            raise HTTPException(status_code=409, detail="Service with this URL already exists")

    # Build dict of non-empty fields only
    update_fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    if update_fields:
        crud.update_service(db, service_id, **update_fields)

    # Return updated service with eager-loaded endpoints
    updated = (
        db.query(Service)
        .options(selectinload(Service.endpoints))
        .filter(Service.id == service_id)
        .first()
    )
    return updated


@router.delete("/services/{service_id}", status_code=200)
def delete_service(service_id: int, db: Session = Depends(get_db)):
    """Delete a service."""
    service = crud.get_service(db, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")
    crud.delete_service(db, service_id)
    return {"message": "Service deleted successfully"}


@router.post(
    "/services/{service_id}/scan",
    response_model=ScanTriggerResponse,
    status_code=202,
)
def trigger_scan(
    service_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Triggers a background Swagger scan for the service."""
    service = crud.get_service(db, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")

    crud.update_service(db, service_id, scan_status="scanning")
    background_tasks.add_task(
        _run_scan_background, service_id, str(service.swagger_url)
    )
    return ScanTriggerResponse(message="Scan started", service_id=service_id)


@router.post(
    "/services/{service_id}/scan/force",
    response_model=ScanTriggerResponse,
    status_code=202,
)
def trigger_force_scan(
    service_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Force a full scan for the service, bypassing the endpoint change check."""
    service = crud.get_service(db, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")

    crud.update_service(db, service_id, scan_status="scanning")
    background_tasks.add_task(
        _run_scan_background, service_id, str(service.swagger_url), True
    )
    return ScanTriggerResponse(message="Force scan started", service_id=service_id)


@router.post(
    "/services/by-name/{service_name}/scan",
    response_model=ScanByNameResponse,
    status_code=202,
)
def trigger_scan_by_name(
    service_name: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Triggers background Swagger scans for all services matching a name."""
    services = crud.get_services_by_name(db, service_name)
    if not services:
        raise HTTPException(status_code=404, detail="Service not found")

    for service in services:
        crud.update_service(db, service.id, scan_status="scanning")
        background_tasks.add_task(
            _run_scan_background, service.id, str(service.swagger_url)
        )

    return ScanByNameResponse(
        message=f"Scan triggered for {len(services)} service(s).",
        service_name=service_name,
        service_count=len(services),
        service_ids=[service.id for service in services],
    )


@router.post("/services/scan", response_model=ScanAllResponse, status_code=202)
def trigger_scan_all(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Triggers a background Swagger scan for all registered services."""
    services = crud.list_services(db)
    for service in services:
        crud.update_service(db, service.id, scan_status="scanning")
        background_tasks.add_task(
            _run_scan_background, service.id, str(service.swagger_url)
        )
    return ScanAllResponse(
        message=f"Scan triggered for {len(services)} service(s).",
        service_count=len(services),
    )


@router.post("/services/scan/force", response_model=ScanAllResponse, status_code=202)
def trigger_force_scan_all(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Force a full scan for all services, bypassing the endpoint change check."""
    services = crud.list_services(db)
    for service in services:
        crud.update_service(db, service.id, scan_status="scanning")
        background_tasks.add_task(
            _run_scan_background, service.id, str(service.swagger_url), True
        )
    return ScanAllResponse(
        message=f"Force scan triggered for {len(services)} service(s).",
        service_count=len(services),
    )


@router.get("/services/{service_id}/scan-status", response_model=ScanStatusResponse)
def get_scan_status(service_id: int, db: Session = Depends(get_db)):
    """Status of the last scan."""
    service = crud.get_service(db, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")
    return ScanStatusResponse(
        service_id=service.id,
        scan_status=service.scan_status,
        last_scanned_at=service.last_scanned_at,
        scan_error=service.scan_error,
    )


@router.post(
    "/services/{service_id}/analyze",
    status_code=202,
)
def trigger_analysis(
    service_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Triggers LLM analysis for a service that was already scanned.

    Requires scan_status='completed'. Runs analyze_service_with_llm in the
    background using existing DB endpoint data — no re-fetch of the Swagger URL.
    """
    service = crud.get_service(db, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")
    if service.scan_status != "completed":
        raise HTTPException(
            status_code=409,
            detail="Service must be fully scanned before analysis. Run /scan first.",
        )
    background_tasks.add_task(_run_analysis_background, service_id)
    return {"message": "Analysis started", "service_id": service_id}


@router.get("/services/{service_id}/analysis")
def get_service_analysis(service_id: int, db: Session = Depends(get_db)):
    """Returns the AI-generated analysis for a service."""
    service = (
        db.query(Service)
        .options(selectinload(Service.endpoints))
        .filter(Service.id == service_id)
        .first()
    )
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")

    endpoint_analyses = []
    for ep in service.endpoints:
        if any([ep.ai_summary, ep.ai_use_cases, ep.ai_notes, ep.ai_request_example, ep.ai_response_example]):
            endpoint_analyses.append({
                "id": ep.id,
                "path": ep.path,
                "method": ep.method,
                "ai_summary": ep.ai_summary,
                "ai_use_cases": ep.ai_use_cases,
                "ai_notes": ep.ai_notes,
                "ai_request_example": ep.ai_request_example,
                "ai_response_example": ep.ai_response_example,
            })

    return {
        "service_id": service_id,
        "ai_overview": service.ai_overview,
        "ai_use_cases": service.ai_use_cases,
        "ai_documentation_score": service.ai_documentation_score,
        "ai_documentation_notes": service.ai_documentation_notes,
        "auth_type": service.auth_type,
        "ai_design_score": service.ai_design_score,
        "ai_design_recommendations": service.ai_design_recommendations,
        "ai_analyzed_at": service.ai_analyzed_at,
        "endpoint_analyses": endpoint_analyses,
    }


@router.get("/services/{service_id}/markdown")
def get_service_markdown(service_id: int, db: Session = Depends(get_db)):
    """Markdown report for a single service."""
    service = (
        db.query(Service)
        .options(selectinload(Service.endpoints))
        .filter(Service.id == service_id)
        .first()
    )
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")
    md = markdown.service_to_markdown(service)
    return Response(content=md, media_type="text/markdown; charset=utf-8")
