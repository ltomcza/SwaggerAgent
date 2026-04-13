import json
import pytest
from datetime import datetime

from app.markdown import all_services_to_markdown, service_to_markdown
from app.models import Endpoint, Service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_service(
    name="Test API",
    swagger_url="http://test.com/swagger.json",
    description="A test service",
    swagger_version="1.0.0",
    base_url="http://test.com",
    scan_status="completed",
    last_scanned_at=None,
    endpoints=None,
):
    """Helper that creates a service mock."""
    service = Service()
    service.id = 1
    service.name = name
    service.swagger_url = swagger_url
    service.description = description
    service.swagger_version = swagger_version
    service.base_url = base_url
    service.scan_status = scan_status
    service.last_scanned_at = last_scanned_at or datetime(2024, 1, 1)
    service.scan_error = None
    service.endpoints = endpoints if endpoints is not None else []
    return service


def make_endpoint(
    path="/users",
    method="GET",
    summary="List users",
    description="Returns users",
    tags='["Users"]',
    deprecated=False,
    parameters_json=None,
    request_body_json=None,
    response_json=None,
):
    ep = Endpoint()
    ep.id = 1
    ep.path = path
    ep.method = method
    ep.summary = summary
    ep.description = description
    ep.tags = tags
    ep.deprecated = deprecated
    ep.parameters_json = parameters_json
    ep.request_body_json = request_body_json
    ep.response_json = response_json
    return ep


# ---------------------------------------------------------------------------
# TestServiceToMarkdown
# ---------------------------------------------------------------------------


class TestServiceToMarkdown:
    def test_contains_service_name(self):
        service = make_service()
        md = service_to_markdown(service)
        assert "# Test API" in md

    def test_contains_swagger_url(self):
        service = make_service()
        md = service_to_markdown(service)
        assert "http://test.com/swagger.json" in md

    def test_contains_description(self):
        service = make_service()
        md = service_to_markdown(service)
        assert "A test service" in md

    def test_no_endpoints_message(self):
        service = make_service(endpoints=[])
        md = service_to_markdown(service)
        assert "No endpoints" in md

    def test_endpoint_in_markdown(self):
        endpoint = make_endpoint()
        service = make_service(endpoints=[endpoint])
        md = service_to_markdown(service)
        assert "GET" in md
        assert "/users" in md
        assert "List users" in md

    def test_deprecated_endpoint_marked(self):
        endpoint = make_endpoint(deprecated=True)
        service = make_service(endpoints=[endpoint])
        md = service_to_markdown(service)
        assert "Deprecated" in md or "deprecated" in md.lower()

    def test_endpoints_grouped_by_tag(self):
        ep1 = make_endpoint(path="/users", method="GET", tags='["Users"]')
        ep2 = make_endpoint(path="/products", method="GET", tags='["Products"]')
        ep2.id = 2
        service = make_service(endpoints=[ep1, ep2])
        md = service_to_markdown(service)
        assert "Users" in md
        assert "Products" in md

    def test_parameters_json_rendered(self):
        params = json.dumps(
            [{"name": "limit", "in": "query", "schema": {"type": "integer"}}]
        )
        endpoint = make_endpoint(parameters_json=params)
        service = make_service(endpoints=[endpoint])
        md = service_to_markdown(service)
        assert "limit" in md

    def test_request_body_rendered(self):
        body = json.dumps(
            {"content": {"application/json": {"schema": {"type": "object"}}}}
        )
        endpoint = make_endpoint(request_body_json=body)
        service = make_service(endpoints=[endpoint])
        md = service_to_markdown(service)
        assert "Request Body" in md or "request" in md.lower()

    def test_scan_status_in_markdown(self):
        service = make_service(scan_status="completed")
        md = service_to_markdown(service)
        assert "completed" in md

    def test_base_url_in_markdown(self):
        service = make_service(base_url="https://base.example.com")
        md = service_to_markdown(service)
        assert "https://base.example.com" in md

    def test_version_in_markdown(self):
        service = make_service(swagger_version="2.5.0")
        md = service_to_markdown(service)
        assert "2.5.0" in md

    def test_endpoint_with_tags_none_goes_to_other(self):
        endpoint = make_endpoint(tags=None)
        service = make_service(endpoints=[endpoint])
        md = service_to_markdown(service)
        assert "Other" in md

    def test_response_json_rendered(self):
        response = json.dumps({"200": {"description": "Success"}})
        endpoint = make_endpoint(response_json=response)
        service = make_service(endpoints=[endpoint])
        md = service_to_markdown(service)
        assert "Response" in md or "200" in md

    def test_xml_content_type_excluded_from_request_body(self):
        body = json.dumps({
            "content": {
                "application/json": {"schema": {"type": "object"}},
                "application/xml": {"schema": {"type": "object"}},
            }
        })
        endpoint = make_endpoint(request_body_json=body)
        md = service_to_markdown(make_service(endpoints=[endpoint]))
        assert "application/json" in md
        assert "application/xml" not in md

    def test_xml_content_type_excluded_from_response(self):
        resp = json.dumps({
            "200": {
                "description": "OK",
                "content": {
                    "application/json": {"schema": {"type": "object"}},
                    "application/xml": {"schema": {"type": "object"}},
                },
            }
        })
        endpoint = make_endpoint(response_json=resp)
        md = service_to_markdown(make_service(endpoints=[endpoint]))
        assert "application/json" in md
        assert "application/xml" not in md

    def test_renders_api_design_audit_section(self):
        service = make_service()
        service.ai_overview = "Overview text"
        service.ai_design_score = 74
        service.ai_design_recommendations = "Normalize resource names and standardize pagination."
        md = service_to_markdown(service)
        assert "API Design Score" in md
        assert "74/100" in md
        assert "standardize pagination" in md


# ---------------------------------------------------------------------------
# TestAllServicesToMarkdown
# ---------------------------------------------------------------------------


class TestAllServicesToMarkdown:
    def test_empty_services(self):
        md = all_services_to_markdown([])
        # Header is "# API Services Catalog"
        assert "Catalog" in md or "0" in md

    def test_contains_all_service_names(self):
        s1 = make_service(name="Service A")
        s1.id = 1
        s2 = make_service(name="Service B")
        s2.id = 2
        md = all_services_to_markdown([s1, s2])
        assert "Service A" in md
        assert "Service B" in md

    def test_contains_table_of_contents(self):
        service = make_service()
        md = all_services_to_markdown([service])
        assert "Table of Contents" in md

    def test_header_present(self):
        md = all_services_to_markdown([])
        assert "# API Services Catalog" in md

    def test_service_count_displayed(self):
        s1 = make_service(name="Only Service")
        s1.id = 1
        md = all_services_to_markdown([s1])
        assert "1" in md

    def test_multiple_services_all_rendered(self):
        services = []
        for i in range(3):
            s = make_service(name=f"Service {i}")
            s.id = i
            services.append(s)
        md = all_services_to_markdown(services)
        for i in range(3):
            assert f"Service {i}" in md

    def test_each_service_section_has_hash_header(self):
        s = make_service(name="Alpha Service")
        s.id = 1
        md = all_services_to_markdown([s])
        assert "# Alpha Service" in md
