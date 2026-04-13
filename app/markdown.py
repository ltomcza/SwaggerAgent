import json
import re
from datetime import datetime
from typing import Optional


def _make_anchor(name: str) -> str:
    """Creates a Markdown anchor from a service name (lowercase, spaces → hyphens, no special characters)."""
    anchor = name.lower()
    anchor = anchor.replace(" ", "-")
    anchor = re.sub(r"[^a-z0-9\-]", "", anchor)
    return anchor


def _parse_json_field(value: Optional[str]):
    """Tries to parse a JSON field. Returns (parsed_obj, raw_str) — parsed_obj may be None if parsing fails."""
    if not value:
        return None, None
    try:
        parsed = json.loads(value)
        return parsed, value
    except (json.JSONDecodeError, TypeError):
        return None, value


def _format_json_block(value: Optional[str]) -> Optional[str]:
    """Formats a JSON value as an indented block. If parsing fails, returns the raw string."""
    if not value:
        return None
    try:
        parsed = json.loads(value)
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return value


def _filter_json_content_types(data: dict) -> dict:
    """Removes non-application/json entries from OpenAPI 3.x content dicts."""
    if not isinstance(data, dict):
        return data
    if "content" in data and isinstance(data["content"], dict):
        # Request body: top-level "content" key
        data = dict(data)
        data["content"] = {k: v for k, v in data["content"].items() if k == "application/json"}
    else:
        # Responses: each key is a status code with optional "content"
        filtered = {}
        for status, resp_obj in data.items():
            if isinstance(resp_obj, dict) and "content" in resp_obj:
                resp_obj = dict(resp_obj)
                resp_obj["content"] = {
                    k: v for k, v in resp_obj["content"].items() if k == "application/json"
                }
            filtered[status] = resp_obj
        data = filtered
    return data


def _endpoint_to_markdown(endpoint) -> str:
    """Generates a Markdown section for a single endpoint."""
    lines = []

    method = (endpoint.method or "").upper()
    path = endpoint.path or ""

    lines.append(f"#### `{method}` {path}")
    lines.append("")

    if endpoint.deprecated:
        lines.append("⚠️ **Deprecated**")
        lines.append("")

    if endpoint.summary:
        lines.append(endpoint.summary)
        lines.append("")

    if endpoint.description:
        lines.append(endpoint.description)
        lines.append("")

    # Parameters
    if endpoint.parameters_json:
        parsed_params, raw_params = _parse_json_field(endpoint.parameters_json)
        lines.append("**Parameters:**")
        lines.append("")
        if parsed_params is not None and isinstance(parsed_params, list) and len(parsed_params) > 0:
            lines.append("| Name | Location | Type | Required | Description |")
            lines.append("|------|----------|------|----------|-------------|")
            for param in parsed_params:
                name = param.get("name", "")
                location = param.get("in", "")
                required = "Yes" if param.get("required", False) else "No"
                description = param.get("description", "")
                # Extract type from schema
                schema = param.get("schema", {})
                if isinstance(schema, dict):
                    param_type = schema.get("type", param.get("type", ""))
                else:
                    param_type = param.get("type", "")
                lines.append(f"| {name} | {location} | {param_type} | {required} | {description} |")
        elif raw_params:
            # JSON is not a list or failed to parse — display raw
            lines.append("```json")
            lines.append(raw_params)
            lines.append("```")
        lines.append("")

    # Request Body
    if endpoint.request_body_json:
        parsed, raw = _parse_json_field(endpoint.request_body_json)
        if parsed is not None:
            formatted = json.dumps(_filter_json_content_types(parsed), indent=2, ensure_ascii=False)
        else:
            formatted = raw
        lines.append("**Request Body:**")
        lines.append("")
        lines.append("```json")
        lines.append(formatted)
        lines.append("```")
        lines.append("")

    # Response
    if endpoint.response_json:
        parsed, raw = _parse_json_field(endpoint.response_json)
        if parsed is not None:
            formatted = json.dumps(_filter_json_content_types(parsed), indent=2, ensure_ascii=False)
        else:
            formatted = raw
        lines.append("**Response:**")
        lines.append("")
        lines.append("```json")
        lines.append(formatted)
        lines.append("```")
        lines.append("")

    # Auth Required (deterministic, not AI-generated)
    auth_required = getattr(endpoint, "auth_required", None)
    if auth_required is not None:
        badge = "Yes" if auth_required else "No"
        lines.append(f"**Auth Required:** {badge}")
        lines.append("")

    # AI Analysis section (only if any AI field is present)
    has_ai_content = any([
        getattr(endpoint, "ai_summary", None) and not endpoint.summary,
        getattr(endpoint, "ai_use_cases", None),
        getattr(endpoint, "ai_request_example", None),
        getattr(endpoint, "ai_response_example", None),
        getattr(endpoint, "ai_notes", None),
    ])
    if has_ai_content:
        lines.append("**AI Analysis:**")
        lines.append("")

        ai_summary = getattr(endpoint, "ai_summary", None)
        if ai_summary and not endpoint.summary:
            lines.append(f"_{ai_summary}_")
            lines.append("")

        ai_use_cases = getattr(endpoint, "ai_use_cases", None)
        if ai_use_cases:
            lines.append("*Use Cases:*")
            for uc in ai_use_cases.split("|"):
                uc = uc.strip()
                if uc:
                    lines.append(f"- {uc}")
            lines.append("")

        ai_request_example = getattr(endpoint, "ai_request_example", None)
        if ai_request_example:
            lines.append("*Example Request:*")
            lines.append("```json")
            lines.append(_format_json_block(ai_request_example) or ai_request_example)
            lines.append("```")
            lines.append("")

        ai_response_example = getattr(endpoint, "ai_response_example", None)
        if ai_response_example:
            lines.append("*Example Response:*")
            lines.append("```json")
            lines.append(_format_json_block(ai_response_example) or ai_response_example)
            lines.append("```")
            lines.append("")

        ai_notes = getattr(endpoint, "ai_notes", None)
        if ai_notes:
            lines.append(f"*Notes:* {ai_notes}")
            lines.append("")

    lines.append("---")
    lines.append("")

    return "\n".join(lines)


def service_to_markdown(service) -> str:
    """Generates a Markdown report for a single service with its endpoints.

    The service parameter is an ORM Service object with loaded endpoint relations.
    """
    lines = []

    lines.append(f"# {service.name}")
    lines.append("")

    swagger_url = service.swagger_url or "N/A"
    swagger_version = service.swagger_version or "N/A"
    base_url = service.base_url or "N/A"
    last_scanned = service.last_scanned_at if service.last_scanned_at else "Never"
    scan_status = service.scan_status or "N/A"

    lines.append(f"**Swagger URL:** {swagger_url}  ")
    lines.append(f"**API Version:** {swagger_version}  ")
    lines.append(f"**Base URL:** {base_url}  ")
    lines.append(f"**Last scanned:** {last_scanned}  ")
    lines.append(f"**Status:** {scan_status}  ")
    lines.append("")

    lines.append("## Description")
    lines.append("")
    lines.append(service.description if service.description else "No description.")
    lines.append("")

    # AI Analysis section
    ai_overview = getattr(service, "ai_overview", None)
    if ai_overview:
        lines.append("## AI Analysis")
        lines.append("")
        lines.append(ai_overview)
        lines.append("")

        ai_documentation_score = getattr(service, "ai_documentation_score", None)
        if ai_documentation_score is not None:
            filled = ai_documentation_score // 10
            bar = "█" * filled + "░" * (10 - filled)
            lines.append(f"**Documentation Quality:** {bar} {ai_documentation_score}/100")
            ai_documentation_notes = getattr(service, "ai_documentation_notes", None)
            if ai_documentation_notes:
                lines.append("")
                lines.append(ai_documentation_notes)
            lines.append("")

        ai_design_score = getattr(service, "ai_design_score", None)
        if ai_design_score is not None:
            filled = ai_design_score // 10
            bar = "█" * filled + "░" * (10 - filled)
            lines.append(f"**API Design Score:** {bar} {ai_design_score}/100")
            ai_design_recommendations = getattr(service, "ai_design_recommendations", None)
            if ai_design_recommendations:
                lines.append("")
                lines.append(ai_design_recommendations)
            lines.append("")

        ai_auth_type = getattr(service, "auth_type", None)
        if ai_auth_type:
            lines.append(f"**Authentication:** `{ai_auth_type}`")
            lines.append("")

        ai_use_cases = getattr(service, "ai_use_cases", None)
        if ai_use_cases:
            try:
                use_cases_list = json.loads(ai_use_cases)
            except (json.JSONDecodeError, TypeError):
                use_cases_list = [ai_use_cases]
            lines.append("**Key Business Workflows:**")
            lines.append("")
            for uc in use_cases_list:
                lines.append(f"- {uc}")
            lines.append("")

        ai_analyzed_at = getattr(service, "ai_analyzed_at", None)
        if ai_analyzed_at:
            lines.append(f"_AI analysis performed: {ai_analyzed_at}_")
            lines.append("")

    lines.append("## Endpoints")
    lines.append("")

    endpoints = service.endpoints if service.endpoints else []

    if not endpoints:
        lines.append("_No endpoints. Run a scan._")
        lines.append("")
    else:
        # Group endpoints by tag
        tag_groups: dict[str, list] = {}
        for endpoint in endpoints:
            tag = None
            if endpoint.tags:
                # tags can be a single-tag string or a JSON array
                parsed_tags, _ = _parse_json_field(endpoint.tags)
                if parsed_tags is not None and isinstance(parsed_tags, list) and len(parsed_tags) > 0:
                    tag = parsed_tags[0]
                elif parsed_tags is not None and isinstance(parsed_tags, str):
                    tag = parsed_tags
                else:
                    # Treat as a plain string (not JSON)
                    tag = endpoint.tags.strip()

            if not tag:
                tag = "Other"

            if tag not in tag_groups:
                tag_groups[tag] = []
            tag_groups[tag].append(endpoint)

        for tag_name, tag_endpoints in tag_groups.items():
            lines.append(f"### {tag_name}")
            lines.append("")
            for endpoint in tag_endpoints:
                lines.append(_endpoint_to_markdown(endpoint))

    return "\n".join(lines)


def all_services_to_markdown(services: list) -> str:
    """Generates a combined Markdown report with a table of contents for all services."""
    lines = []

    lines.append("# API Services Catalog")
    lines.append("")
    lines.append(f"Generated: {datetime.now()}  ")
    lines.append(f"Total services: {len(services)}")
    lines.append("")

    if services:
        lines.append("## Table of Contents")
        lines.append("")
        for i, service in enumerate(services, start=1):
            anchor = _make_anchor(service.name)
            scan_status = service.scan_status or "N/A"
            lines.append(f"{i}. [{service.name}](#{anchor}) - {scan_status}")
        lines.append("")
        lines.append("---")
        lines.append("")

        for service in services:
            lines.append(service_to_markdown(service))
            lines.append("")
            lines.append("---")
            lines.append("")

    return "\n".join(lines)
