"""Tests for the MCP server endpoint at POST /mcp."""

import json

import pytest


def mcp(client, method: str, params: dict = None, request_id=1):
    """Helper: send a JSON-RPC 2.0 request and return the parsed response body."""
    body = {"jsonrpc": "2.0", "method": method, "id": request_id}
    if params is not None:
        body["params"] = params
    resp = client.post("/mcp", json=body)
    assert resp.status_code == 200
    return resp.json()


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------


class TestInitialize:
    def test_returns_protocol_version(self, client):
        data = mcp(client, "initialize")
        assert data["result"]["protocolVersion"] == "2024-11-05"

    def test_returns_server_info(self, client):
        data = mcp(client, "initialize")
        assert data["result"]["serverInfo"]["name"] == "SwaggerAgent"

    def test_echoes_request_id(self, client):
        data = mcp(client, "initialize", request_id=42)
        assert data["id"] == 42

    def test_has_tools_capability(self, client):
        data = mcp(client, "initialize")
        assert "tools" in data["result"]["capabilities"]


# ---------------------------------------------------------------------------
# tools/list
# ---------------------------------------------------------------------------


class TestToolsList:
    def test_returns_two_tools(self, client):
        data = mcp(client, "tools/list")
        assert len(data["result"]["tools"]) == 2

    def test_tool_names(self, client):
        data = mcp(client, "tools/list")
        names = {t["name"] for t in data["result"]["tools"]}
        assert names == {"GetServices", "GetServiceDetails"}

    def test_get_service_details_requires_service_name(self, client):
        data = mcp(client, "tools/list")
        tool = next(t for t in data["result"]["tools"] if t["name"] == "GetServiceDetails")
        assert "service_name" in tool["inputSchema"]["required"]

    def test_get_services_has_empty_required(self, client):
        data = mcp(client, "tools/list")
        tool = next(t for t in data["result"]["tools"] if t["name"] == "GetServices")
        assert tool["inputSchema"]["required"] == []


# ---------------------------------------------------------------------------
# tools/call — GetServices
# ---------------------------------------------------------------------------


class TestGetServices:
    def test_empty_when_no_services(self, client):
        data = mcp(client, "tools/call", {"name": "GetServices", "arguments": {}})
        text = data["result"]["content"][0]["text"]
        items = json.loads(text)
        assert items == []

    def test_lists_registered_services(self, client, db_session):
        from app import crud

        crud.create_service(db_session, "Alpha API", "http://alpha.example.com/swagger.json")
        crud.create_service(db_session, "Beta API", "http://beta.example.com/swagger.json")

        data = mcp(client, "tools/call", {"name": "GetServices", "arguments": {}})
        text = data["result"]["content"][0]["text"]
        items = json.loads(text)

        names = [i["service_name"] for i in items]
        assert "Alpha API" in names
        assert "Beta API" in names

    def test_uses_ai_overview_as_description(self, client, db_session):
        from app import crud

        svc = crud.create_service(db_session, "My API", "http://my.example.com/swagger.json")
        svc.ai_overview = "An AI-generated overview of My API."
        db_session.commit()

        data = mcp(client, "tools/call", {"name": "GetServices", "arguments": {}})
        text = data["result"]["content"][0]["text"]
        items = json.loads(text)

        item = next(i for i in items if i["service_name"] == "My API")
        assert item["service_description"] == "An AI-generated overview of My API."

    def test_falls_back_to_description_when_no_ai_overview(self, client, db_session):
        from app import crud

        svc = crud.create_service(db_session, "Fallback API", "http://fallback.example.com/swagger.json")
        svc.description = "Plain spec description."
        db_session.commit()

        data = mcp(client, "tools/call", {"name": "GetServices", "arguments": {}})
        text = data["result"]["content"][0]["text"]
        items = json.loads(text)

        item = next(i for i in items if i["service_name"] == "Fallback API")
        assert item["service_description"] == "Plain spec description."

    def test_result_content_type_is_text(self, client):
        data = mcp(client, "tools/call", {"name": "GetServices", "arguments": {}})
        assert data["result"]["content"][0]["type"] == "text"


# ---------------------------------------------------------------------------
# tools/call — GetServiceDetails
# ---------------------------------------------------------------------------


class TestGetServiceDetails:
    def test_not_found_returns_text_message(self, client):
        data = mcp(
            client,
            "tools/call",
            {"name": "GetServiceDetails", "arguments": {"service_name": "Nonexistent"}},
        )
        text = data["result"]["content"][0]["text"]
        assert "not found" in text.lower()

    def test_missing_service_name_returns_error(self, client):
        data = mcp(client, "tools/call", {"name": "GetServiceDetails", "arguments": {}})
        assert "error" in data
        assert data["error"]["code"] == -32602

    def test_returns_markdown_for_existing_service(self, client, db_session):
        from app import crud

        svc = crud.create_service(db_session, "Detail API", "http://detail.example.com/swagger.json")
        svc.description = "A detailed service."
        db_session.commit()

        data = mcp(
            client,
            "tools/call",
            {"name": "GetServiceDetails", "arguments": {"service_name": "Detail API"}},
        )
        text = data["result"]["content"][0]["text"]
        assert "# Detail API" in text

    def test_markdown_includes_endpoints(self, client, db_session):
        from app import crud

        svc = crud.create_service(db_session, "EP API", "http://ep.example.com/swagger.json")
        crud.replace_endpoints(
            db_session,
            svc.id,
            [
                {
                    "path": "/items",
                    "method": "GET",
                    "summary": "List items",
                    "description": None,
                    "parameters_json": None,
                    "request_body_json": None,
                    "response_json": None,
                    "tags": '["Items"]',
                    "deprecated": False,
                }
            ],
        )

        data = mcp(
            client,
            "tools/call",
            {"name": "GetServiceDetails", "arguments": {"service_name": "EP API"}},
        )
        text = data["result"]["content"][0]["text"]
        assert "/items" in text
        assert "GET" in text

    def test_lookup_is_case_insensitive(self, client, db_session):
        from app import crud

        crud.create_service(db_session, "Case API", "http://case.example.com/swagger.json")

        data = mcp(
            client,
            "tools/call",
            {"name": "GetServiceDetails", "arguments": {"service_name": "case api"}},
        )
        text = data["result"]["content"][0]["text"]
        assert "# Case API" in text

    def test_result_content_type_is_text(self, client, db_session):
        from app import crud

        crud.create_service(db_session, "Type API", "http://type.example.com/swagger.json")

        data = mcp(
            client,
            "tools/call",
            {"name": "GetServiceDetails", "arguments": {"service_name": "Type API"}},
        )
        assert data["result"]["content"][0]["type"] == "text"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_notification_returns_202_no_body(self, client):
        # Notifications have no "id" key — server must not send a JSON-RPC response
        resp = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert resp.status_code == 202
        assert resp.content == b""

    def test_ping_returns_empty_result(self, client):
        data = mcp(client, "ping")
        assert data["result"] == {}
        assert "error" not in data


class TestErrorCases:
    def test_unknown_method_returns_error(self, client):
        data = mcp(client, "no/such/method")
        assert "error" in data
        assert data["error"]["code"] == -32601

    def test_unknown_tool_returns_error(self, client):
        data = mcp(client, "tools/call", {"name": "DoSomethingElse", "arguments": {}})
        assert "error" in data
        assert data["error"]["code"] == -32601

    def test_malformed_json_returns_parse_error(self, client):
        resp = client.post(
            "/mcp",
            content=b"not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"]["code"] == -32700

    def test_response_is_always_200(self, client):
        resp = client.post("/mcp", json={"jsonrpc": "2.0", "method": "bad", "id": 1})
        assert resp.status_code == 200
