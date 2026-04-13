import json
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# TestFetchSwaggerJson
# ---------------------------------------------------------------------------


class TestFetchSwaggerJson:
    def test_fetch_swagger_json_success(self):
        swagger_doc = {"openapi": "3.0.0", "paths": {}, "info": {"title": "T", "version": "1"}}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = swagger_doc

        with patch("requests.get", return_value=mock_resp):
            from app.tools import fetch_swagger_json
            result = fetch_swagger_json("http://test.com/swagger.json")

        assert isinstance(result, dict)
        assert "openapi" in result or "paths" in result

    def test_fetch_swagger_json_fallback_url(self):
        """First URL returns 404, second candidate (url + /swagger.json) returns valid JSON."""
        swagger_doc = {
            "openapi": "3.0.0",
            "paths": {},
            "info": {"title": "Test", "version": "1.0"},
        }

        fail_resp = MagicMock()
        fail_resp.status_code = 404
        fail_resp.headers = {"content-type": "text/html"}
        fail_resp.json.side_effect = Exception("Not JSON")

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.headers = {"content-type": "application/json"}
        ok_resp.json.return_value = swagger_doc

        with patch("requests.get", side_effect=[fail_resp, ok_resp]):
            from app.tools import fetch_swagger_json
            result = fetch_swagger_json("http://test.com")

        assert isinstance(result, dict)
        assert "openapi" in result

    def test_fetch_swagger_json_all_fail(self):
        with patch("requests.get", side_effect=Exception("Connection error")):
            from app.tools import fetch_swagger_json
            result = fetch_swagger_json("http://nonexistent.test")

        assert isinstance(result, str)
        lower = result.lower()
        assert "error" in lower or "failed" in lower or "could not" in lower

    def test_fetch_swagger_json_non_swagger_json(self):
        """Response is valid JSON but not a Swagger document."""
        not_swagger = {"some": "data", "without": "swagger_keys"}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = not_swagger

        with patch("requests.get", return_value=mock_resp):
            from app.tools import fetch_swagger_json
            result = fetch_swagger_json("http://test.com/data")

        assert isinstance(result, str)
        assert "error" in result.lower() or "could not" in result.lower() or "Last error" in result

    def test_fetch_swagger_json_with_paths_key(self):
        """Document that has 'paths' but not 'openapi' or 'swagger' should still be accepted."""
        swagger_doc = {"paths": {"/users": {}}}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = swagger_doc

        with patch("requests.get", return_value=mock_resp):
            from app.tools import fetch_swagger_json
            result = fetch_swagger_json("http://test.com/swagger.json")

        assert isinstance(result, dict)
        assert "paths" in result


# ---------------------------------------------------------------------------
# TestParseSwaggerDocument
# ---------------------------------------------------------------------------


class TestParseSwaggerDocument:
    def test_parse_openapi_3(self, sample_swagger_json):
        from app.tools import parse_swagger_document
        result = parse_swagger_document(sample_swagger_json)
        assert isinstance(result, dict)
        assert result["title"] == "Test API"
        assert result["version"] == "3.0.0"
        assert result["base_url"] == "https://api.test.com"
        assert len(result["endpoints"]) == 3

    def test_parse_swagger_2(self, sample_swagger_2_json):
        from app.tools import parse_swagger_document
        result = parse_swagger_document(sample_swagger_2_json)
        assert isinstance(result, dict)
        assert result["title"] == "Legacy API"
        assert "api.legacy.com" in result["base_url"]
        assert len(result["endpoints"]) >= 1

    def test_parse_endpoint_fields(self, sample_swagger_json):
        from app.tools import parse_swagger_document
        result = parse_swagger_document(sample_swagger_json)
        assert isinstance(result, dict)
        get_endpoint = next(
            e for e in result["endpoints"]
            if e["path"] == "/users" and e["method"].lower() == "get"
        )
        assert get_endpoint["summary"] == "List users"
        assert get_endpoint["tags"] is not None
        assert get_endpoint["deprecated"] is False

    def test_parse_deprecated_endpoint(self, sample_swagger_json):
        from app.tools import parse_swagger_document
        result = parse_swagger_document(sample_swagger_json)
        assert isinstance(result, dict)
        deprecated_ep = next(
            (e for e in result["endpoints"] if e["path"] == "/users/{id}" and e.get("deprecated")),
            None,
        )
        assert deprecated_ep is not None

    def test_parse_post_endpoint_has_request_body(self, sample_swagger_json):
        from app.tools import parse_swagger_document
        result = parse_swagger_document(sample_swagger_json)
        assert isinstance(result, dict)
        post_endpoint = next(
            e for e in result["endpoints"]
            if e["path"] == "/users" and e["method"].lower() == "post"
        )
        assert post_endpoint["request_body_json"] is not None

    def test_parse_parameters_extracted(self, sample_swagger_json):
        from app.tools import parse_swagger_document
        result = parse_swagger_document(sample_swagger_json)
        assert isinstance(result, dict)
        get_endpoint = next(
            e for e in result["endpoints"]
            if e["path"] == "/users" and e["method"].lower() == "get"
        )
        params = json.loads(get_endpoint["parameters_json"])
        assert any(p["name"] == "limit" for p in params)

    def test_parse_swagger2_base_url_construction(self, sample_swagger_2_json):
        from app.tools import parse_swagger_document
        result = parse_swagger_document(sample_swagger_2_json)
        assert isinstance(result, dict)
        assert "https" in result["base_url"]
        assert "/v2" in result["base_url"]

    def test_parse_empty_paths(self):
        from app.tools import parse_swagger_document
        doc = {"openapi": "3.0.0", "info": {"title": "Empty", "version": "1.0"}, "paths": {}}
        result = parse_swagger_document(doc)
        assert isinstance(result, dict)
        assert result["endpoints"] == []

    def test_parse_resolves_refs_in_request_body(self):
        from app.tools import parse_swagger_document
        doc = {
            "openapi": "3.0.0",
            "info": {"title": "Ref Test", "version": "1.0"},
            "components": {
                "schemas": {
                    "Pet": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "id": {"type": "integer"},
                        },
                    }
                }
            },
            "paths": {
                "/pets": {
                    "post": {
                        "summary": "Add pet",
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Pet"}
                                }
                            }
                        },
                        "responses": {
                            "200": {
                                "description": "OK",
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "#/components/schemas/Pet"}
                                    }
                                },
                            }
                        },
                    }
                }
            },
        }
        result = parse_swagger_document(doc)
        assert isinstance(result, dict)
        post_ep = result["endpoints"][0]
        req_body = json.loads(post_ep["request_body_json"])
        schema = req_body["content"]["application/json"]["schema"]
        assert schema["type"] == "object"
        assert "name" in schema["properties"]
        resp = json.loads(post_ep["response_json"])
        resp_schema = resp["200"]["content"]["application/json"]["schema"]
        assert resp_schema["type"] == "object"

    def test_parse_openapi3_relative_server_url(self):
        from app.tools import parse_swagger_document
        doc = {
            "openapi": "3.0.0",
            "info": {"title": "Relative", "version": "1.0"},
            "servers": [{"url": "/api/v3"}],
            "paths": {},
        }
        result = parse_swagger_document(doc, swagger_url="https://petstore3.swagger.io/openapi.json")
        assert isinstance(result, dict)
        assert result["base_url"] == "https://petstore3.swagger.io/api/v3"

    def test_parse_openapi3_template_variables(self):
        from app.tools import parse_swagger_document
        doc = {
            "openapi": "3.0.0",
            "info": {"title": "Templated", "version": "1.0"},
            "servers": [{
                "url": "{scheme}://api.example.com/{version}",
                "variables": {
                    "scheme": {"default": "https"},
                    "version": {"default": "v3"},
                },
            }],
            "paths": {},
        }
        result = parse_swagger_document(doc)
        assert isinstance(result, dict)
        assert result["base_url"] == "https://api.example.com/v3"

    def test_parse_swagger2_empty_host_with_swagger_url(self):
        from app.tools import parse_swagger_document
        doc = {
            "swagger": "2.0",
            "info": {"title": "No Host", "version": "1.0"},
            "basePath": "/v2",
            "paths": {},
        }
        result = parse_swagger_document(doc, swagger_url="https://legacy.example.com/swagger.json")
        assert isinstance(result, dict)
        assert result["base_url"] == "https://legacy.example.com/v2"

    def test_parse_fallback_to_swagger_url(self):
        from app.tools import parse_swagger_document
        doc = {
            "openapi": "3.0.0",
            "info": {"title": "No Servers", "version": "1.0"},
            "paths": {},
        }
        result = parse_swagger_document(doc, swagger_url="https://example.com/docs/openapi.json")
        assert isinstance(result, dict)
        assert result["base_url"] == "https://example.com"

    def test_parse_openapi3_template_and_relative(self):
        from app.tools import parse_swagger_document
        doc = {
            "openapi": "3.0.0",
            "info": {"title": "Both", "version": "1.0"},
            "servers": [{
                "url": "/{version}",
                "variables": {"version": {"default": "v3"}},
            }],
            "paths": {},
        }
        result = parse_swagger_document(doc, swagger_url="https://api.example.com/openapi.json")
        assert isinstance(result, dict)
        assert result["base_url"] == "https://api.example.com/v3"


# ---------------------------------------------------------------------------
# TestResolveRefs
# ---------------------------------------------------------------------------


class TestResolveRefs:
    def test_resolves_simple_ref(self):
        from app.tools import _resolve_refs
        root = {
            "components": {
                "schemas": {
                    "Pet": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}, "id": {"type": "integer"}},
                    }
                }
            }
        }
        result = _resolve_refs({"$ref": "#/components/schemas/Pet"}, root)
        assert result["type"] == "object"
        assert "name" in result["properties"]

    def test_resolves_nested_ref(self):
        from app.tools import _resolve_refs
        root = {
            "components": {
                "schemas": {
                    "Category": {"type": "object", "properties": {"name": {"type": "string"}}},
                    "Pet": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "category": {"$ref": "#/components/schemas/Category"},
                        },
                    },
                }
            }
        }
        result = _resolve_refs({"$ref": "#/components/schemas/Pet"}, root)
        assert result["properties"]["category"]["type"] == "object"

    def test_handles_circular_ref(self):
        from app.tools import _resolve_refs
        root = {
            "components": {
                "schemas": {
                    "Node": {
                        "type": "object",
                        "properties": {
                            "value": {"type": "string"},
                            "child": {"$ref": "#/components/schemas/Node"},
                        },
                    }
                }
            }
        }
        result = _resolve_refs({"$ref": "#/components/schemas/Node"}, root)
        assert result["properties"]["child"] == {"$circular_ref": "#/components/schemas/Node"}

    def test_resolves_swagger2_definitions(self):
        from app.tools import _resolve_refs
        root = {"definitions": {"Item": {"type": "object", "properties": {"id": {"type": "integer"}}}}}
        result = _resolve_refs({"$ref": "#/definitions/Item"}, root)
        assert result["type"] == "object"

    def test_leaves_non_ref_dicts_unchanged(self):
        from app.tools import _resolve_refs
        obj = {"type": "string", "format": "date"}
        assert _resolve_refs(obj, {}) == obj

    def test_resolves_refs_in_list(self):
        from app.tools import _resolve_refs
        root = {"components": {"schemas": {"Tag": {"type": "object", "properties": {"name": {"type": "string"}}}}}}
        result = _resolve_refs([{"$ref": "#/components/schemas/Tag"}, {"type": "string"}], root)
        assert result[0]["type"] == "object"
        assert result[1] == {"type": "string"}

    def test_unresolvable_ref_left_as_is(self):
        from app.tools import _resolve_refs
        obj = {"$ref": "#/components/schemas/Missing"}
        assert _resolve_refs(obj, {"components": {"schemas": {}}}) == obj


# ---------------------------------------------------------------------------
# TestSaveServiceData
# ---------------------------------------------------------------------------


class TestSaveServiceData:
    def test_save_service_data_success(self, db_session):
        from app import crud

        service = crud.create_service(db_session, "Test", "http://test.com/swagger.json")
        service_id = service.id  # capture before tool closes the session

        parsed_data = {
            "title": "Test API",
            "description": "A test",
            "version": "1.0.0",
            "base_url": "http://test.com",
            "endpoints": [
                {
                    "path": "/users",
                    "method": "get",
                    "summary": "List",
                    "description": None,
                    "parameters_json": None,
                    "request_body_json": None,
                    "response_json": None,
                    "tags": None,
                    "deprecated": False,
                }
            ],
        }

        with patch("app.tools.SessionLocal", return_value=db_session):
            from app.tools import save_service_data
            result = save_service_data(service_id, parsed_data)

        assert str(service_id) in result or "endpoint" in result.lower()

    def test_save_service_data_empty_endpoints(self, db_session):
        from app import crud

        service = crud.create_service(db_session, "Test2", "http://test2.com/swagger.json")

        parsed_data = {
            "title": "Test API",
            "description": None,
            "version": "1.0.0",
            "base_url": "http://test2.com",
            "endpoints": [],
        }

        with patch("app.tools.SessionLocal", return_value=db_session):
            from app.tools import save_service_data
            result = save_service_data(service.id, parsed_data)

        assert "0" in result or "endpoint" in result.lower()

    def test_save_service_data_multiple_endpoints(self, db_session):
        from app import crud

        service = crud.create_service(db_session, "Multi", "http://multi.com/swagger.json")

        parsed_data = {
            "title": "Multi API",
            "description": None,
            "version": "1.0.0",
            "base_url": "http://multi.com",
            "endpoints": [
                {
                    "path": f"/path{i}",
                    "method": "get",
                    "summary": f"Endpoint {i}",
                    "description": None,
                    "parameters_json": None,
                    "request_body_json": None,
                    "response_json": None,
                    "tags": None,
                    "deprecated": False,
                }
                for i in range(3)
            ],
        }

        with patch("app.tools.SessionLocal", return_value=db_session):
            from app.tools import save_service_data
            result = save_service_data(service.id, parsed_data)

        assert "3" in result


# ---------------------------------------------------------------------------
# TestGetServiceInfo
# ---------------------------------------------------------------------------


class TestGetServiceInfo:
    def test_get_service_info_found(self, db_session):
        from app import crud

        service = crud.create_service(db_session, "Test", "http://test.com/swagger.json")

        with patch("app.tools.SessionLocal", return_value=db_session):
            from app.tools import get_service_info
            result = get_service_info(service.id)

        data = json.loads(result)
        assert data["name"] == "Test"
        assert data["id"] == service.id
        assert "swagger_url" in data
        assert "scan_status" in data

    def test_get_service_info_not_found(self, db_session):
        with patch("app.tools.SessionLocal", return_value=db_session):
            from app.tools import get_service_info
            result = get_service_info(99999)

        assert "not found" in result.lower() or "service" in result.lower()

    def test_get_service_info_includes_endpoint_count(self, db_session):
        from app import crud

        service = crud.create_service(db_session, "Counted", "http://counted.com/swagger.json")
        crud.replace_endpoints(
            db_session,
            service.id,
            [
                {
                    "path": "/a",
                    "method": "get",
                    "summary": None,
                    "description": None,
                    "parameters_json": None,
                    "request_body_json": None,
                    "response_json": None,
                    "tags": None,
                    "deprecated": False,
                }
            ],
        )

        with patch("app.tools.SessionLocal", return_value=db_session):
            from app.tools import get_service_info
            result = get_service_info(service.id)

        data = json.loads(result)
        assert data["endpoint_count"] == 1


# ---------------------------------------------------------------------------
# TestAnalyzeServiceWithLLM
# ---------------------------------------------------------------------------


class TestAnalyzeServiceWithLLM:
    def test_persists_design_audit_fields(self, db_session):
        from app import crud
        from app.tools import (
            EndpointAnalysisItem,
            ServiceAnalysisOutput,
            analyze_service_with_llm,
        )

        service = crud.create_service(db_session, "Design API", "http://design.example.com/swagger.json")
        service_id = service.id
        parsed_data = {
            "title": "Design API",
            "description": "desc",
            "version": "3.0.0",
            "base_url": "http://design.example.com",
            "security_schemes": {},
            "endpoints": [
                {
                    "path": "/users",
                    "method": "GET",
                    "summary": "List users",
                    "tags": None,
                    "security_json": None,
                }
            ],
        }
        crud.replace_endpoints(
            db_session,
            service.id,
            [
                {
                    "path": "/users",
                    "method": "GET",
                    "summary": "List users",
                    "description": None,
                    "parameters_json": None,
                    "request_body_json": None,
                    "response_json": None,
                    "tags": None,
                    "deprecated": False,
                }
            ],
        )

        analysis = ServiceAnalysisOutput(
            overview="overview",
            use_cases=["List users"],
            quality_score=80,
            quality_notes="quality notes",
            design_score=72,
            design_recommendations="Standardize pagination and use plural resources.",
            endpoint_analyses=[
                EndpointAnalysisItem(
                    path="/users",
                    method="GET",
                    summary="List users",
                    use_cases="Browse users",
                    notes="",
                )
            ],
        )

        mock_model = MagicMock()
        mock_model.with_structured_output.return_value.invoke.return_value = analysis

        with patch("app.tools.SessionLocal", return_value=db_session), \
             patch("app.tools.init_chat_model", return_value=mock_model), \
             patch("app.tools.settings.OPENAI_API_KEY", "test-key"), \
             patch.object(db_session, "close", return_value=None):
            result = analyze_service_with_llm(service_id, parsed_data)

        assert "LLM analysis complete" in result
        updated = crud.get_service(db_session, service_id)
        assert updated.ai_design_score == 72
        assert "pagination" in updated.ai_design_recommendations.lower()


# ---------------------------------------------------------------------------
# TestSaveServiceDataAuthFields
# Verify that auth_type and auth_required are persisted by save_service_data
# when the caller has already enriched parsed_data with computed values.
# ---------------------------------------------------------------------------


class TestSaveServiceDataAuthFields:
    def _parsed_data(self, endpoints, auth_type="http/bearer"):
        return {
            "title": "Auth API",
            "description": None,
            "version": "1.0.0",
            "base_url": "http://example.com",
            "auth_type": auth_type,
            "endpoints": endpoints,
        }

    def test_saves_auth_type_to_service(self, db_session):
        from app import crud
        from app.tools import save_service_data

        service = crud.create_service(db_session, "Auth Test", "http://auth.example.com/swagger.json")
        parsed_data = self._parsed_data([], auth_type="http/bearer")

        with patch("app.tools.SessionLocal", return_value=db_session), \
             patch.object(db_session, "close", return_value=None):
            save_service_data(service.id, parsed_data)

        updated = crud.get_service(db_session, service.id)
        assert updated.auth_type == "http/bearer"

    def test_saves_auth_required_per_endpoint(self, db_session):
        from app import crud
        from app.tools import save_service_data

        service = crud.create_service(db_session, "Endpoint Auth", "http://ep.example.com/swagger.json")
        parsed_data = self._parsed_data(
            auth_type="none",
            endpoints=[
                {
                    "path": "/admin/data",
                    "method": "GET",
                    "summary": None,
                    "description": None,
                    "parameters_json": None,
                    "request_body_json": None,
                    "response_json": None,
                    "tags": None,
                    "deprecated": False,
                    "auth_required": True,
                },
                {
                    "path": "/health",
                    "method": "GET",
                    "summary": None,
                    "description": None,
                    "parameters_json": None,
                    "request_body_json": None,
                    "response_json": None,
                    "tags": None,
                    "deprecated": False,
                    "auth_required": False,
                },
                {
                    "path": "/items",
                    "method": "GET",
                    "summary": None,
                    "description": None,
                    "parameters_json": None,
                    "request_body_json": None,
                    "response_json": None,
                    "tags": None,
                    "deprecated": False,
                    "auth_required": None,
                },
            ],
        )

        with patch("app.tools.SessionLocal", return_value=db_session), \
             patch.object(db_session, "close", return_value=None):
            save_service_data(service.id, parsed_data)

        admin_ep = crud.get_endpoint_by_path_method(db_session, service.id, "/admin/data", "GET")
        health_ep = crud.get_endpoint_by_path_method(db_session, service.id, "/health", "GET")
        items_ep = crud.get_endpoint_by_path_method(db_session, service.id, "/items", "GET")
        assert admin_ep.auth_required is True
        assert health_ep.auth_required is False
        assert items_ep.auth_required is None

    def test_none_auth_type_not_overwritten(self, db_session):
        from app import crud
        from app.tools import save_service_data

        service = crud.create_service(db_session, "No Auth", "http://noauth.example.com/swagger.json")
        parsed_data = self._parsed_data([], auth_type="none")

        with patch("app.tools.SessionLocal", return_value=db_session), \
             patch.object(db_session, "close", return_value=None):
            save_service_data(service.id, parsed_data)

        # crud.update_service skips None values, but "none" is a valid string
        updated = crud.get_service(db_session, service.id)
        assert updated.auth_type == "none"
