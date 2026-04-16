from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional, cast
from urllib.parse import urljoin, urlparse

import requests
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app import crud
from app.config import settings
from app.database import SessionLocal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured output schemas for LLM responses
# ---------------------------------------------------------------------------


class EndpointAnalysisItem(BaseModel):
    path: str
    method: str
    summary: str    # plain-English description, max 255 chars
    use_cases: str  # pipe-separated: "Use case A|Use case B"
    notes: str      # inferred caveats, or empty string


class ServiceAnalysisOutput(BaseModel):
    overview: str
    use_cases: list[str]
    quality_score: int = Field(ge=0, le=100)   # documentation quality
    quality_notes: str
    design_score: int = Field(ge=0, le=100)    # API design quality
    design_recommendations: str
    endpoint_analyses: list[EndpointAnalysisItem]


class EndpointDeepAnalysisOutput(BaseModel):
    inferred_summary: str
    request_example: Optional[str] = None   # JSON-encoded object, or null
    response_example: Optional[str] = None  # JSON-encoded object, or null


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def _resolve_refs(obj, root_doc: dict, max_depth: int = 10, _seen: frozenset | None = None):
    """Recursively resolve ``$ref`` pointers in an OpenAPI/Swagger document.

    Handles both ``#/components/schemas/X`` (OAS 3.x) and ``#/definitions/X``
    (Swagger 2.0).  Uses *max_depth* to cap expansion and *_seen* (per-branch)
    to detect circular references, replacing them with a marker.
    """
    if _seen is None:
        _seen = frozenset()
    if max_depth <= 0:
        return obj
    if isinstance(obj, dict):
        if "$ref" in obj and len(obj) == 1:
            ref = obj["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/"):
                return obj
            if ref in _seen:
                return {"$circular_ref": ref}
            parts = ref.lstrip("#/").split("/")
            resolved = root_doc
            for part in parts:
                if isinstance(resolved, dict):
                    resolved = resolved.get(part)
                else:
                    return obj  # can't resolve
            if resolved is None:
                return obj
            return _resolve_refs(resolved, root_doc, max_depth - 1, _seen | {ref})
        return {k: _resolve_refs(v, root_doc, max_depth - 1, _seen) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_refs(item, root_doc, max_depth - 1, _seen) for item in obj]
    return obj


def fetch_swagger_json(url: str) -> dict | str:
    """Fetches a Swagger/OpenAPI document from the given URL.

    Tries the URL and several common variants:
    - url as-is
    - url + "/swagger.json"
    - url + "/v1/swagger.json"
    - url + "/openapi.json"
    - url + "/api-docs"
    - url + "/docs"

    Returns:
        The parsed swagger dict on success, or an error description string.
    """
    base = url.rstrip("/")
    candidates = [
        base,
        base + "/swagger.json",
        base + "/v1/swagger.json",
        base + "/openapi.json",
        base + "/api-docs",
        base + "/docs",
    ]
    last_error: str = ""
    for candidate_url in candidates:
        try:
            resp = requests.get(candidate_url, timeout=30)
            if resp.status_code != 200:
                last_error = f"HTTP {resp.status_code} from {candidate_url}"
                continue
            content_type = resp.headers.get("Content-Type", "")
            is_json_content = "json" in content_type
            try:
                data = resp.json()
            except Exception:
                if not is_json_content:
                    last_error = f"Non-JSON response from {candidate_url}"
                    continue
                last_error = f"Invalid JSON from {candidate_url}"
                continue
            if not isinstance(data, dict):
                last_error = f"Response is not a JSON object from {candidate_url}"
                continue
            if "swagger" in data or "openapi" in data or "paths" in data:
                logger.info("fetch_swagger_json: fetched from %s", candidate_url)
                return data
            last_error = f"JSON from {candidate_url} does not look like OpenAPI (missing swagger/openapi/paths keys)"
        except requests.Timeout:
            last_error = f"Timeout connecting to {candidate_url}"
        except requests.ConnectionError as e:
            last_error = f"Connection error for {candidate_url}: {e}"
        except Exception as e:
            last_error = f"Unexpected error for {candidate_url}: {e}"

    error_msg = f"Could not fetch Swagger document from any URL variant. Last error: {last_error}"
    logger.error("fetch_swagger_json failed: %s", error_msg)
    return error_msg


def _resolve_server_url(
    server_url: str | None,
    swagger_url: str | None,
    variables: dict | None,
) -> str | None:
    """Resolve an OpenAPI server URL to a complete absolute URL.

    Handles template variable substitution (e.g. ``{scheme}``), relative URL
    resolution against *swagger_url*, and trailing-slash normalisation.
    """
    if not server_url:
        return None

    url = server_url

    # Step 1: substitute template variables using their defaults
    if variables and "{" in url:
        def _replace(match: re.Match) -> str:
            name = match.group(1)
            var = variables.get(name, {})
            return var.get("default", match.group(0))
        url = re.sub(r"\{(\w+)\}", _replace, url)

    # Step 2: resolve relative URLs against the swagger source URL
    parsed = urlparse(url)
    if not parsed.scheme and swagger_url:
        url = urljoin(swagger_url, url)

    # Step 3: strip trailing slash for consistency
    return url.rstrip("/") or None


def parse_swagger_document(swagger_data: dict, swagger_url: str | None = None) -> dict | str:
    """Parses a Swagger/OpenAPI document and extracts structured information.

    Supports OpenAPI 3.x and Swagger 2.0.

    Args:
        swagger_data: Raw swagger dict returned by fetch_swagger_json.
        swagger_url: The URL the document was fetched from; used to resolve
            relative server URLs and as a fallback when the spec lacks host info.

    Returns:
        A dict with keys title, description, version, base_url, endpoints on
        success. Returns an error string on failure.
    """
    try:
        info = swagger_data.get("info", {})
        title = info.get("title", "")
        description = info.get("description") or None
        version = info.get("version", "")

        # Detect spec version
        openapi_field = swagger_data.get("openapi", "")
        swagger_field = swagger_data.get("swagger", "")

        if isinstance(openapi_field, str) and openapi_field.startswith("3"):
            spec_version = openapi_field  # e.g. "3.0.0", "3.1.0"
            servers = swagger_data.get("servers", [])
            if servers and isinstance(servers, list) and isinstance(servers[0], dict):
                raw_url = servers[0].get("url")
                variables = servers[0].get("variables")
                base_url = _resolve_server_url(raw_url, swagger_url, variables)
            else:
                base_url = None
        elif swagger_field == "2.0":
            spec_version = swagger_field
            host = swagger_data.get("host", "")
            base_path = swagger_data.get("basePath", "")
            schemes = swagger_data.get("schemes", [])
            scheme = schemes[0] if schemes else "http"
            if host:
                base_url = f"{scheme}://{host}{base_path}".rstrip("/")
            elif swagger_url:
                parsed_source = urlparse(swagger_url)
                scheme_val = schemes[0] if schemes else (parsed_source.scheme or "https")
                base_url = f"{scheme_val}://{parsed_source.netloc}{base_path}".rstrip("/")
            else:
                base_url = None
        else:
            # Try to handle gracefully
            spec_version = openapi_field or swagger_field or "unknown"
            base_url = None

        # Fallback: derive scheme://host from the source URL when spec lacks info
        if base_url is None and swagger_url:
            parsed_source = urlparse(swagger_url)
            if parsed_source.scheme and parsed_source.netloc:
                base_url = f"{parsed_source.scheme}://{parsed_source.netloc}"

        # Extract security scheme definitions and global security requirements
        if spec_version.startswith("3"):
            security_schemes: dict = swagger_data.get("components", {}).get("securitySchemes", {})
        else:
            security_schemes = swagger_data.get("securityDefinitions", {})
        global_security = swagger_data.get("security")  # None when not defined in spec

        paths = swagger_data.get("paths", {})
        http_methods = {"get", "post", "put", "delete", "patch", "options", "head"}
        endpoints: list[dict] = []

        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            for method, operation in path_item.items():
                if method.lower() not in http_methods:
                    continue
                if not isinstance(operation, dict):
                    continue

                parameters = operation.get("parameters", [])
                request_body = operation.get("requestBody")
                responses = operation.get("responses", {})

                # Resolve $ref pointers so stored JSON shows real schemas
                if parameters:
                    parameters = _resolve_refs(parameters, swagger_data)
                if request_body is not None:
                    request_body = _resolve_refs(request_body, swagger_data)
                if responses:
                    responses = _resolve_refs(responses, swagger_data)

                parameters_json = json.dumps(parameters) if parameters else None
                request_body_json = json.dumps(request_body) if request_body is not None else None
                response_json = json.dumps(responses) if responses else None

                tags = operation.get("tags", [])
                tags_json = json.dumps(tags) if tags else None

                deprecated = bool(operation.get("deprecated", False))

                # Per-operation security overrides global; None means "not set" (inherit global)
                op_security = operation.get("security")
                effective_security = op_security if op_security is not None else global_security
                security_json = json.dumps(effective_security) if effective_security is not None else None

                endpoints.append({
                    "path": path,
                    "method": method.upper(),
                    "summary": operation.get("summary"),
                    "description": operation.get("description"),
                    "parameters_json": parameters_json,
                    "request_body_json": request_body_json,
                    "response_json": response_json,
                    "tags": tags_json,
                    "deprecated": deprecated,
                    "security_json": security_json,
                })

        result = {
            "title": title,
            "description": description,
            "version": spec_version,
            "base_url": base_url,
            "security_schemes": security_schemes,
            "endpoints": endpoints,
        }
        logger.info("parse_swagger_document: parsed %d endpoints, title=%r", len(endpoints), title)
        return result

    except Exception as e:
        error_msg = f"Error parsing Swagger document: {e}"
        logger.exception("parse_swagger_document failed")
        return error_msg


def save_service_data(service_id: int, parsed_data: dict) -> str:
    """Saves parsed service and endpoint data to the database.

    Args:
        service_id: Service ID in the database.
        parsed_data: Dict returned by parse_swagger_document.

    Returns:
        Save confirmation with endpoint count, or an error description.
    """
    db = SessionLocal()
    try:
        crud.update_service(
            db,
            service_id,
            description=parsed_data.get("description"),
            swagger_version=parsed_data.get("version"),
            base_url=parsed_data.get("base_url"),
            auth_type=parsed_data.get("auth_type"),
            last_scanned_at=datetime.now(timezone.utc),
            scan_status="completed",
            scan_error=None,
        )

        endpoints_data: list[dict] = parsed_data.get("endpoints", [])
        crud.replace_endpoints(db, service_id, endpoints_data)

        count = len(endpoints_data)
        result = f"Service {service_id} updated successfully. Saved {count} endpoints."
        logger.info("save_service_data: service_id=%d saved %d endpoints", service_id, count)
        return result

    except Exception as e:
        error_msg = f"Error saving service data for service_id={service_id}: {e}"
        logger.exception("save_service_data failed for service_id=%d", service_id)
        return error_msg
    finally:
        db.close()


def analyze_service_with_llm(service_id: int, parsed_data: dict) -> str:
    """Uses the LLM to generate enriched analysis for the entire service.

    Builds a structured prompt from the parsed Swagger data, calls gpt-5-mini,
    and saves ai_overview, ai_use_cases, ai_documentation_score, ai_documentation_notes,
    ai_design_score, ai_design_recommendations to the Service row, plus
    ai_summary / ai_use_cases / ai_notes per endpoint.

    Args:
        service_id: Service ID in the database.
        parsed_data: Dict returned by parse_swagger_document.

    Returns:
        Confirmation string or error/skip description.
    """
    if not settings.OPENAI_API_KEY:
        result = "LLM analysis skipped: no API key configured"
        logger.info("analyze_service_with_llm: skipped for service_id=%d (no API key)", service_id)
        return result

    try:
        title = parsed_data.get("title", "")
        spec_version = parsed_data.get("version", "")
        base_url = parsed_data.get("base_url", "")
        description = parsed_data.get("description") or "Not provided"
        endpoints: list[dict] = parsed_data.get("endpoints", [])
        security_schemes: dict = parsed_data.get("security_schemes", {})

        # Build condensed endpoint list (capped at 150 to stay within token budget)
        MAX_ENDPOINTS = 150
        truncated = len(endpoints) > MAX_ENDPOINTS
        endpoint_lines = []
        for ep in endpoints[:MAX_ENDPOINTS]:
            tags_str = ""
            if ep.get("tags"):
                try:
                    tags_list = json.loads(ep["tags"])
                    tags_str = f" [{', '.join(str(t) for t in tags_list)}]" if tags_list else ""
                except Exception:
                    tags_str = f" [{ep['tags']}]"
            summary_str = f" — {ep['summary']}" if ep.get("summary") else ""
            endpoint_lines.append(f"{ep.get('method', 'GET')} {ep.get('path', '/')}{summary_str}{tags_str}")

        endpoints_text = "\n".join(endpoint_lines)
        if truncated:
            endpoints_text += f"\n... (truncated to {MAX_ENDPOINTS} of {len(endpoints)} total)"

        security_schemes_text = json.dumps(security_schemes, indent=2) if security_schemes else "None defined in spec."

        prompt = f"""You are an expert API analyst. Analyze the following OpenAPI/Swagger service.

## SERVICE
Title: {title} | Version: {spec_version} | Base URL: {base_url}
Description: {description}

## SECURITY SCHEMES
{security_schemes_text}

## ENDPOINTS ({len(endpoints)} total)
{endpoints_text}

## YOUR TASK
Return a JSON object with exactly these keys:

"overview": A 4-5 paragraph plain-English description of what this API does, who uses it, and what business domain it serves. Infer from paths and names.

"use_cases": An array of 4-10 strings, each a concrete business workflow this API enables.

"quality_score": An integer 0-100 rating documentation quality. Evaluate every signal below, then assign a score in the matching band:
  Signals to evaluate:
    - What percentage of endpoints have a non-empty summary?
    - What percentage of endpoints have a description beyond the summary?
    - Are path/query parameters documented with name, type, and description?
    - Are request body schemas defined with property-level descriptions?
    - Are response schemas defined for success (2xx) and error (4xx/5xx) codes?
    - Are example values provided for parameters, request bodies, or responses?
    - Are authentication requirements documented per endpoint or globally?
  Score bands:
    90-100: >=95% of endpoints have summaries AND descriptions; parameter types and descriptions present; response schemas defined for 2xx and at least one error code; request/response examples provided for most endpoints.
    70-89:  >75% of endpoints have summaries; most have response schemas for 2xx; parameter types present but some lack descriptions; few or no inline examples.
    50-69:  40-75% of endpoints have summaries; response schemas present but incomplete (missing error codes or property descriptions); parameters listed but sparsely documented.
    30-49:  <40% of endpoints have summaries; most lack response schemas or parameter descriptions; no examples; authentication requirements unclear.
    0-29:   Endpoints have auto-generated or empty summaries only; no parameter documentation; no response schemas; no examples; undocumented auth.

"quality_notes": 3-5 sentences explaining the score. Cite specific counts (e.g., "12 of 35 endpoints lack summaries", "no endpoint defines error response schemas"). Name the top 3-4 specific gaps or strengths.

"design_score": An integer 0-100 rating API design quality. Evaluate every criterion below, then assign a score in the matching band:
  Criteria to evaluate:
    - Resource naming: consistent plural nouns, predictable hierarchy (e.g., /users/{{id}}/orders)
    - HTTP verb semantics: GET for reads, POST for creates, PUT/PATCH for updates, DELETE for removals; no verbs in path segments (e.g., /getUser is an anti-pattern)
    - Collection endpoints: consistent pagination (limit/offset or cursor), filtering, and sorting parameters on list endpoints
    - Versioning: clear and consistent strategy (path prefix, header, or query param)
    - Error model: consistent error response structure across endpoints (e.g., standard problem+json or {{error, message}} shape)
    - Idempotency: PUT/DELETE are naturally idempotent; POST endpoints for creates support idempotency keys where relevant
    - Security scheme design: appropriate auth for resource sensitivity (e.g., not leaving mutation endpoints unprotected)
  Score bands:
    90-100: Consistent plural-noun resources with logical nesting; correct verb semantics everywhere; all list endpoints support pagination; clear versioning; standard error model; auth properly scoped.
    70-89:  Mostly consistent naming and verbs; minor deviations (1-2 singular nouns or verb-in-path); most list endpoints paginated; versioning present but minor inconsistencies; error model mostly consistent.
    50-69:  Mixed naming conventions (some singular, some plural); occasional verb misuse (e.g., POST used for retrieval); no consistent pagination or filtering pattern; versioning unclear or mixed; no standard error model.
    30-49:  Significant REST anti-patterns — verbs in paths (e.g., /getUsers, /deleteItem), no resource hierarchy, inconsistent methods; no pagination; no versioning; no error structure.
    0-29:   RPC-style API — action-oriented paths, single HTTP method for everything, no discernible resource model, no REST conventions followed.

"design_recommendations": 4-6 concise, actionable recommendations. For each, reference the specific criterion it addresses and cite concrete path or method patterns from this API as examples of what to fix.

"endpoint_analyses": An array of objects, one per endpoint listed above. Each object must have:
  "path": the exact endpoint path
  "method": uppercase HTTP method
  "summary": plain-English description (inferred if missing, max 255 chars)
  "use_cases": pipe-separated use cases, e.g. "Get user profile|Pre-fill edit form"
  "notes": inferred caveats, or empty string if none"""

        model = init_chat_model(settings.LLM_ANALYSIS_MODEL, temperature=settings.LLM_ANALYSIS_TEMPERATURE)
        analysis = cast(ServiceAnalysisOutput, model.with_structured_output(ServiceAnalysisOutput).invoke(
            [HumanMessage(content=prompt)]
        ))

        # Write service-level AI fields
        db = SessionLocal()
        try:
            crud.update_service_ai(
                db,
                service_id,
                ai_overview=analysis.overview,
                ai_use_cases=json.dumps(analysis.use_cases),
                ai_documentation_score=analysis.quality_score,
                ai_documentation_notes=analysis.quality_notes,
                ai_design_score=analysis.design_score,
                ai_design_recommendations=analysis.design_recommendations,
            )

            # Write per-endpoint AI fields
            lookup = {(ea.path, ea.method.upper()): ea for ea in analysis.endpoint_analyses}
            enriched_count = 0
            for ep in endpoints:
                key = (ep.get("path", ""), ep.get("method", "").upper())
                ea = lookup.get(key)
                if not ea:
                    continue
                db_ep = crud.get_endpoint_by_path_method(db, service_id, ep["path"], ep["method"])
                if db_ep is None:
                    continue
                crud.update_endpoint_ai(
                    db,
                    db_ep.id,
                    ai_summary=ea.summary,
                    ai_use_cases=ea.use_cases,
                    ai_notes=ea.notes or None,
                )
                enriched_count += 1
        finally:
            db.close()

        result = (
            f"LLM analysis complete for service {service_id}. "
            f"Quality score: {analysis.quality_score}/100. "
            f"Enriched {enriched_count} endpoints."
        )
        logger.info("analyze_service_with_llm: service_id=%d quality=%d enriched=%d", service_id, analysis.quality_score, enriched_count)
        return result

    except Exception as e:
        error_msg = f"LLM analysis failed for service_id={service_id}: {e}"
        logger.exception("analyze_service_with_llm failed for service_id=%d", service_id)
        return error_msg


def analyze_endpoint_with_llm(service_id: int, path: str, method: str) -> str:
    """Deep-analyzes a single endpoint using the LLM to generate realistic examples.

    Fetches the endpoint from the DB, asks gpt-5-mini to infer what it does and
    generate realistic request/response examples, then saves the results.

    Args:
        service_id: Service ID.
        path: Endpoint path, e.g. "/users/{id}".
        method: HTTP method uppercase, e.g. "GET".

    Returns:
        Confirmation or error/skip description.
    """
    if not settings.OPENAI_API_KEY:
        result = "LLM analysis skipped: no API key configured"
        logger.info("analyze_endpoint_with_llm: skipped for service_id=%d %s %s (no API key)", service_id, method, path)
        return result

    db = SessionLocal()
    try:
        ep = crud.get_endpoint_by_path_method(db, service_id, path, method)
        if ep is None:
            result = f"Endpoint not found: {method.upper()} {path} for service {service_id}"
            logger.warning("analyze_endpoint_with_llm: endpoint not found service_id=%d %s %s", service_id, method, path)
            return result

        params_str = _format_json_for_prompt(ep.parameters_json) or "None"
        body_str = _format_json_for_prompt(ep.request_body_json) or "None"
        response_str = _format_json_for_prompt(ep.response_json) or "None"

        # Fetch service-level context for better domain inference
        service = crud.get_service(db, service_id)
        service_title = service.name if service else "Unknown"
        service_base_url = service.base_url if service else "Unknown"

        prompt = f"""You are an expert API analyst. Analyze this single API endpoint.

SERVICE: {service_title} ({service_base_url})

METHOD: {ep.method}
PATH: {ep.path}
SUMMARY: {ep.summary or "Not provided"}
DESCRIPTION: {ep.description or "Not provided"}

PARAMETERS:
{params_str}

REQUEST BODY SCHEMA:
{body_str}

RESPONSE SCHEMAS:
{response_str}

Provide:
- inferred_summary: A clear, specific 1-2 sentence description of what this endpoint does. Max 120 characters. Use the service context to infer domain-appropriate language.
- request_example: A realistic request body as a raw JSON string, or null if the endpoint accepts no request body. Use domain-realistic values (real-looking names, emails, UUIDs, dates). IMPORTANT: Return a plain JSON string, NOT wrapped in markdown code fences. Example: "{{\\"name\\": \\"Alice\\", \\"email\\": \\"alice@example.com\\"}}"
- response_example: A typical 200/201 response body as a raw JSON string, or null if no meaningful response body. Include realistic field values matching the response schema. IMPORTANT: Return a plain JSON string, NOT wrapped in markdown code fences. Example: "{{\\"id\\": 1, \\"name\\": \\"Alice\\", \\"created_at\\": \\"2025-01-15T09:30:00Z\\"}}" """

        model = init_chat_model(settings.LLM_ANALYSIS_MODEL, temperature=settings.LLM_ANALYSIS_TEMPERATURE)
        analysis = cast(EndpointDeepAnalysisOutput, model.with_structured_output(EndpointDeepAnalysisOutput).invoke(
            [HumanMessage(content=prompt)]
        ))

        crud.update_endpoint_ai(
            db,
            ep.id,
            ai_summary=analysis.inferred_summary if not ep.summary else None,
            ai_request_example=analysis.request_example,
            ai_response_example=analysis.response_example,
        )

        result = f"Deep analysis complete for {ep.method} {ep.path}."
        logger.info("analyze_endpoint_with_llm: complete for service_id=%d %s %s", service_id, method, path)
        return result

    except Exception as e:
        error_msg = f"Endpoint analysis failed for {method} {path}: {e}"
        logger.exception("analyze_endpoint_with_llm failed for service_id=%d %s %s", service_id, method, path)
        return error_msg
    finally:
        db.close()


def _format_json_for_prompt(value: str | None) -> str | None:
    """Pretty-prints a JSON string for inclusion in prompts."""
    if not value:
        return None
    try:
        return json.dumps(json.loads(value), indent=2, ensure_ascii=False)
    except Exception:
        return value


def get_service_info(service_id: int) -> str:
    """Retrieves current service information from the database.

    Args:
        service_id: Service ID.

    Returns:
        JSON string with service data, or an error description.
    """
    db = SessionLocal()
    try:
        service = crud.get_service(db, service_id)
        if service is None:
            logger.warning("get_service_info: service_id=%d not found", service_id)
            return "Service not found"

        result = json.dumps({
            "id": service.id,
            "name": service.name,
            "swagger_url": service.swagger_url,
            "scan_status": service.scan_status,
            "endpoint_count": len(service.endpoints),
        }, ensure_ascii=False)
        logger.info("get_service_info: service_id=%d retrieved", service_id)
        return result

    except Exception as e:
        error_msg = f"Error retrieving service info for service_id={service_id}: {e}"
        logger.exception("get_service_info failed for service_id=%d", service_id)
        return error_msg
    finally:
        db.close()
