"""MCP (Model Context Protocol) server — plain JSON-RPC 2.0 over HTTP POST.

Exposes two tools:
  GetServices()              — list of {service_name, service_description}
  GetServiceDetails(name)    — full Markdown report for a named service
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session, selectinload

from app import crud
from app.database import get_db
from app.markdown import service_to_markdown
from app.models import Service

logger = logging.getLogger(__name__)

router = APIRouter()

_PROTOCOL_VERSION = "2024-11-05"
_SERVER_INFO = {"name": "SwaggerAgent", "version": "1.0.0"}

_TOOLS = [
    {
        "name": "GetServices",
        "description": (
            "Returns all registered API services with their names and "
            "AI-generated overview descriptions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "GetServiceDetails",
        "description": (
            "Returns full Markdown documentation for a named service, "
            "including all endpoints and AI analysis results."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "service_name": {
                    "type": "string",
                    "description": "Name of the service to retrieve (case-insensitive).",
                }
            },
            "required": ["service_name"],
        },
    },
]


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------


def _ok(result: Any, request_id: Any) -> dict:
    return {"jsonrpc": "2.0", "result": result, "id": request_id}


def _err(code: int, message: str, request_id: Any) -> dict:
    return {"jsonrpc": "2.0", "error": {"code": code, "message": message}, "id": request_id}


def _text(text: str) -> dict:
    """Wraps a string in the MCP tool-call content envelope."""
    return {"content": [{"type": "text", "text": text}]}


# ---------------------------------------------------------------------------
# Method handlers
# ---------------------------------------------------------------------------


def _handle_initialize(request_id: Any) -> dict:
    return _ok(
        {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": _SERVER_INFO,
        },
        request_id,
    )


def _handle_tools_list(request_id: Any) -> dict:
    return _ok({"tools": _TOOLS}, request_id)


def _handle_tools_call(params: dict, request_id: Any, db: Session) -> dict:
    tool_name = params.get("name")
    arguments: dict = params.get("arguments") or {}

    if tool_name == "GetServices":
        services = crud.list_services(db)
        items = [
            {
                "service_name": s.name,
                "service_description": s.ai_overview or s.description or "",
            }
            for s in services
        ]
        return _ok(_text(json.dumps(items, ensure_ascii=False, indent=2)), request_id)

    if tool_name == "GetServiceDetails":
        name: str = arguments.get("service_name", "").strip()
        if not name:
            return _err(-32602, "Missing required argument: service_name", request_id)

        matches = crud.get_services_by_name(db, name)
        if not matches:
            return _ok(_text(f"Service '{name}' not found."), request_id)

        service = (
            db.query(Service)
            .options(selectinload(Service.endpoints))
            .filter(Service.id == matches[0].id)
            .first()
        )
        return _ok(_text(service_to_markdown(service)), request_id)

    return _err(-32601, f"Unknown tool: {tool_name}", request_id)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/mcp")
async def mcp_endpoint(request: Request, db: Session = Depends(get_db)):
    """Single JSON-RPC 2.0 endpoint for the MCP server."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(_err(-32700, "Parse error", None))

    if not isinstance(body, dict):
        return JSONResponse(_err(-32600, "Invalid Request", None))

    # JSON-RPC notifications have no "id" key — must not send a response
    if "id" not in body:
        return Response(status_code=202)

    request_id = body.get("id")
    method = body.get("method")
    params: dict = body.get("params") or {}

    if method == "initialize":
        result = _handle_initialize(request_id)
    elif method == "ping":
        result = _ok({}, request_id)
    elif method == "tools/list":
        result = _handle_tools_list(request_id)
    elif method == "tools/call":
        result = _handle_tools_call(params, request_id, db)
    else:
        result = _err(-32601, f"Method not found: {method}", request_id)

    return JSONResponse(result)
