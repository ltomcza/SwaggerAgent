from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Endpoint, ScanLog, Service


# ============================================================
# Services
# ============================================================


def create_service(db: Session, name: str, swagger_url: str) -> Service:
    """Create a new service record.

    Raises sqlalchemy.exc.IntegrityError if swagger_url already exists.
    """
    service = Service(name=name, swagger_url=swagger_url)
    db.add(service)
    db.commit()
    db.refresh(service)
    return service


def get_service(db: Session, service_id: int) -> Service | None:
    """Return a service by primary key, or None if not found.

    Endpoints are available via lazy loading on the returned object.
    """
    return db.query(Service).filter(Service.id == service_id).first()


def get_service_by_url(db: Session, swagger_url: str) -> Service | None:
    """Return a service by its swagger_url, or None if not found."""
    return db.query(Service).filter(Service.swagger_url == swagger_url).first()


def get_services_by_name(db: Session, name: str) -> list[Service]:
    """Return services matching name (case-insensitive), ordered by id."""
    return (
        db.query(Service)
        .filter(func.lower(Service.name) == name.lower())
        .order_by(Service.id)
        .all()
    )


def list_services(db: Session) -> list[Service]:
    """Return all services ordered by id ascending."""
    return db.query(Service).order_by(Service.id).all()


def update_service(db: Session, service_id: int, **kwargs) -> Service | None:
    """Update selected fields of a service.

    - Only non-None kwargs are applied (None values are ignored).
    - The 'id' key is always skipped to prevent PK modification.
    - updated_at is always set to the current UTC time.
    - Returns None if the service does not exist.
    """
    service = get_service(db, service_id)
    if service is None:
        return None

    for key, value in kwargs.items():
        if key == 'id':
            continue
        if value is not None:
            setattr(service, key, value)

    service.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(service)
    return service


def delete_service(db: Session, service_id: int) -> bool:
    """Delete a service (cascades to endpoints and scan_logs).

    Returns False if the service was not found, True on success.
    """
    service = get_service(db, service_id)
    if service is None:
        return False

    db.delete(service)
    db.commit()
    return True


# ============================================================
# Endpoints
# ============================================================


def replace_endpoints(
    db: Session, service_id: int, endpoints_data: list[dict]
) -> list[Endpoint]:
    """Replace all endpoints for a service with a new set.

    Deletes existing endpoints for service_id, then bulk-inserts the
    new ones supplied in endpoints_data.  Each dict may contain:
        path, method, summary, description, parameters_json,
        request_body_json, response_json, tags, deprecated, auth_required.
    """
    # Remove existing endpoints for this service
    db.query(Endpoint).filter(Endpoint.service_id == service_id).delete()

    new_endpoints: list[Endpoint] = []
    for data in endpoints_data:
        endpoint = Endpoint(
            service_id=service_id,
            path=data.get('path', ''),
            method=data.get('method', ''),
            summary=data.get('summary'),
            description=data.get('description'),
            parameters_json=data.get('parameters_json'),
            request_body_json=data.get('request_body_json'),
            response_json=data.get('response_json'),
            tags=data.get('tags'),
            deprecated=data.get('deprecated', False),
            auth_required=data.get('auth_required'),
        )
        db.add(endpoint)
        new_endpoints.append(endpoint)

    db.commit()

    for endpoint in new_endpoints:
        db.refresh(endpoint)

    return new_endpoints


def update_service_ai(
    db: Session,
    service_id: int,
    ai_overview: str | None = None,
    ai_use_cases: str | None = None,
    ai_documentation_score: int | None = None,
    ai_documentation_notes: str | None = None,
    ai_design_score: int | None = None,
    ai_design_recommendations: str | None = None,
) -> Service | None:
    """Update only the LLM-generated fields on a service."""
    service = get_service(db, service_id)
    if service is None:
        return None
    if ai_overview is not None:
        service.ai_overview = ai_overview
    if ai_use_cases is not None:
        service.ai_use_cases = ai_use_cases
    if ai_documentation_score is not None:
        service.ai_documentation_score = ai_documentation_score
    if ai_documentation_notes is not None:
        service.ai_documentation_notes = ai_documentation_notes
    if ai_design_score is not None:
        service.ai_design_score = ai_design_score
    if ai_design_recommendations is not None:
        service.ai_design_recommendations = ai_design_recommendations
    service.ai_analyzed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(service)
    return service


def get_endpoint_by_path_method(
    db: Session, service_id: int, path: str, method: str
) -> Endpoint | None:
    """Return an endpoint by service_id, path and HTTP method."""
    return (
        db.query(Endpoint)
        .filter(
            Endpoint.service_id == service_id,
            Endpoint.path == path,
            Endpoint.method == method.upper(),
        )
        .first()
    )


def update_endpoint_ai(
    db: Session,
    endpoint_id: int,
    ai_summary: str | None = None,
    ai_request_example: str | None = None,
    ai_response_example: str | None = None,
    ai_use_cases: str | None = None,
    ai_notes: str | None = None,
) -> Endpoint | None:
    """Update only the LLM-generated fields on an endpoint."""
    endpoint = db.query(Endpoint).filter(Endpoint.id == endpoint_id).first()
    if endpoint is None:
        return None
    if ai_summary is not None:
        endpoint.ai_summary = ai_summary
    if ai_request_example is not None:
        endpoint.ai_request_example = ai_request_example
    if ai_response_example is not None:
        endpoint.ai_response_example = ai_response_example
    if ai_use_cases is not None:
        endpoint.ai_use_cases = ai_use_cases
    if ai_notes is not None:
        endpoint.ai_notes = ai_notes
    db.commit()
    db.refresh(endpoint)
    return endpoint


def get_endpoints(db: Session, service_id: int) -> list[Endpoint]:
    """Return all endpoints for a service ordered by path, method."""
    return (
        db.query(Endpoint)
        .filter(Endpoint.service_id == service_id)
        .order_by(Endpoint.path, Endpoint.method)
        .all()
    )


def endpoints_have_changed(existing: list[Endpoint], new_data: list[dict]) -> bool:
    """Return True if the endpoint set differs from what is stored in the DB.

    Compares all fields that describe an endpoint's contract: path, method,
    summary, description, parameters, request body, responses, tags, and
    deprecated flag.  Returns False (no change) when both sets are identical.
    """
    def _fp(path, method, summary, description, params, body, resp, tags, deprecated):
        return (
            path or "",
            method or "",
            summary or "",
            description or "",
            params or "",
            body or "",
            resp or "",
            tags or "",
            bool(deprecated),
        )

    existing_set = {
        _fp(
            ep.path, ep.method, ep.summary, ep.description,
            ep.parameters_json, ep.request_body_json, ep.response_json,
            ep.tags, ep.deprecated,
        )
        for ep in existing
    }
    new_set = {
        _fp(
            d.get("path", ""), d.get("method", ""), d.get("summary"), d.get("description"),
            d.get("parameters_json"), d.get("request_body_json"), d.get("response_json"),
            d.get("tags"), d.get("deprecated", False),
        )
        for d in new_data
    }
    return existing_set != new_set


# ============================================================
# Scan logs
# ============================================================


def create_scan_log(db: Session, service_id: int) -> ScanLog:
    """Create a new scan log entry with started_at set to now (UTC)."""
    log = ScanLog(
        service_id=service_id,
        started_at=datetime.now(timezone.utc),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def finish_scan_log(
    db: Session,
    log_id: int,
    status: str,
    endpoints_found: int = 0,
    error: str | None = None,
) -> ScanLog | None:
    """Finalise a scan log entry.

    Sets finished_at to now (UTC), updates status, endpoints_found and
    error_message.  Returns None if the log entry was not found.
    """
    log = db.query(ScanLog).filter(ScanLog.id == log_id).first()
    if log is None:
        return None

    log.finished_at = datetime.now(timezone.utc)
    log.status = status
    log.endpoints_found = endpoints_found
    log.error_message = error

    db.commit()
    db.refresh(log)
    return log
