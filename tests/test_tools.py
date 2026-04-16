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
# TestFetchSwaggerJsonHtmlExtraction
# ---------------------------------------------------------------------------

VALID_SPEC = {"openapi": "3.0.0", "info": {"title": "Test", "version": "1"}, "paths": {}}
VALID_SPEC_JSON = json.dumps(VALID_SPEC)

VALID_YAML_SPEC = """\
openapi: "3.0.0"
info:
  title: Test
  version: "1"
paths: {}
"""


def _html_resp(html_body: str):
    """Create a mock response that returns HTML."""
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"Content-Type": "text/html; charset=utf-8"}
    resp.text = html_body
    resp.json.side_effect = ValueError("Not JSON")
    return resp


def _json_spec_resp():
    """Create a mock response that returns a valid OpenAPI JSON spec."""
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"Content-Type": "application/json"}
    resp.json.return_value = VALID_SPEC
    resp.text = VALID_SPEC_JSON
    return resp


def _yaml_spec_resp():
    """Create a mock response that returns a valid OpenAPI YAML spec."""
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"Content-Type": "text/yaml"}
    resp.json.side_effect = ValueError("Not JSON")
    resp.text = VALID_YAML_SPEC
    return resp


def _not_found_resp():
    resp = MagicMock()
    resp.status_code = 404
    resp.headers = {"Content-Type": "text/plain", "Link": ""}
    return resp


class TestHelperIsSwaggerDict:
    def test_positive_openapi(self):
        from app.tools import _is_swagger_dict
        assert _is_swagger_dict({"openapi": "3.0.0"}) is True

    def test_positive_swagger(self):
        from app.tools import _is_swagger_dict
        assert _is_swagger_dict({"swagger": "2.0"}) is True

    def test_positive_paths(self):
        from app.tools import _is_swagger_dict
        assert _is_swagger_dict({"paths": {}}) is True

    def test_negative_random_dict(self):
        from app.tools import _is_swagger_dict
        assert _is_swagger_dict({"foo": "bar"}) is False

    def test_negative_not_dict(self):
        from app.tools import _is_swagger_dict
        assert _is_swagger_dict([1, 2, 3]) is False
        assert _is_swagger_dict("string") is False


class TestHelperTryParseYaml:
    def test_valid_yaml(self):
        from app.tools import _try_parse_yaml
        result = _try_parse_yaml(VALID_YAML_SPEC)
        assert result is not None
        assert "openapi" in result

    def test_invalid_yaml(self):
        from app.tools import _try_parse_yaml
        assert _try_parse_yaml("just a plain string") is None

    def test_yaml_not_swagger(self):
        from app.tools import _try_parse_yaml
        assert _try_parse_yaml("foo: bar\nbaz: 1") is None


class TestHelperExtractSpecUrls:
    def test_swagger_ui_bundle(self):
        from app.tools import _extract_spec_urls_from_html
        html = '''<script>SwaggerUIBundle({ url: "/v1/swagger.json", dom_id: "#app" })</script>'''
        urls = _extract_spec_urls_from_html(html, "https://example.com/docs")
        assert "https://example.com/v1/swagger.json" in urls

    def test_redoc_spec_url(self):
        from app.tools import _extract_spec_urls_from_html
        html = '''<redoc spec-url="/api/openapi.json"></redoc>'''
        urls = _extract_spec_urls_from_html(html, "https://example.com/docs")
        assert "https://example.com/api/openapi.json" in urls

    def test_rapidoc_spec_url(self):
        from app.tools import _extract_spec_urls_from_html
        html = '''<rapi-doc spec-url="https://other.com/openapi.yaml"></rapi-doc>'''
        urls = _extract_spec_urls_from_html(html, "https://example.com/")
        assert "https://other.com/openapi.yaml" in urls

    def test_relative_url_resolution(self):
        from app.tools import _extract_spec_urls_from_html
        html = '''<a href="./openapi.json">Download spec</a>'''
        urls = _extract_spec_urls_from_html(html, "https://example.com/docs/index.html")
        assert "https://example.com/docs/openapi.json" in urls

    def test_deduplication(self):
        from app.tools import _extract_spec_urls_from_html
        html = '''
        <script>SwaggerUIBundle({ url: "/openapi.json" })</script>
        <a href="/openapi.json">link</a>
        '''
        urls = _extract_spec_urls_from_html(html, "https://example.com/")
        assert urls.count("https://example.com/openapi.json") == 1


class TestHelperExtractEmbeddedSpec:
    def test_script_application_json(self):
        from app.tools import _extract_embedded_spec_from_html
        html = f'<script type="application/json">{VALID_SPEC_JSON}</script>'
        result = _extract_embedded_spec_from_html(html)
        assert result is not None
        assert "openapi" in result

    def test_inline_spec_in_config(self):
        from app.tools import _extract_embedded_spec_from_html
        html = f'SwaggerUIBundle({{ spec: {VALID_SPEC_JSON}, dom_id: "#app" }})'
        result = _extract_embedded_spec_from_html(html)
        assert result is not None
        assert "openapi" in result

    def test_no_embedded_spec(self):
        from app.tools import _extract_embedded_spec_from_html
        html = "<html><body>No spec here</body></html>"
        assert _extract_embedded_spec_from_html(html) is None


class TestFetchSwaggerJsonHtmlExtraction:
    def test_swagger_ui_url_extraction(self):
        """HTML page with SwaggerUIBundle url -> follows the link to get spec."""
        swagger_ui_html = '''
        <html><body>
        <script>
        SwaggerUIBundle({ url: "/v1/swagger.json", dom_id: "#swagger-ui" })
        </script>
        </body></html>
        '''
        html_resp = _html_resp(swagger_ui_html)
        json_resp = _json_spec_resp()

        def side_effect(url, **kwargs):
            if url.endswith("/v1/swagger.json"):
                return json_resp
            return html_resp

        with patch("requests.get", side_effect=side_effect):
            from app.tools import fetch_swagger_json
            result = fetch_swagger_json("http://test.com")

        assert isinstance(result, dict)
        assert "openapi" in result

    def test_redoc_spec_url(self):
        """HTML with <redoc spec-url=...> attribute -> follows the link."""
        redoc_html = '<html><body><redoc spec-url="/api/openapi.yaml"></redoc></body></html>'
        html_resp = _html_resp(redoc_html)
        yaml_resp = _yaml_spec_resp()

        def side_effect(url, **kwargs):
            if url.endswith("/api/openapi.yaml"):
                return yaml_resp
            return html_resp

        with patch("requests.get", side_effect=side_effect):
            from app.tools import fetch_swagger_json
            result = fetch_swagger_json("http://test.com")

        assert isinstance(result, dict)
        assert "openapi" in result

    def test_rapidoc_spec_url(self):
        """HTML with <rapi-doc spec-url=...> -> follows the link."""
        rapidoc_html = '<html><body><rapi-doc spec-url="https://ext.com/openapi.json"></rapi-doc></body></html>'
        html_resp = _html_resp(rapidoc_html)
        json_resp = _json_spec_resp()

        def side_effect(url, **kwargs):
            if url == "https://ext.com/openapi.json":
                return json_resp
            return html_resp

        with patch("requests.get", side_effect=side_effect):
            from app.tools import fetch_swagger_json
            result = fetch_swagger_json("http://test.com")

        assert isinstance(result, dict)
        assert "openapi" in result

    def test_embedded_json_in_script_tag(self):
        """Spec embedded in <script type='application/json'> -> extracted directly."""
        html = f'<html><body><script type="application/json">{VALID_SPEC_JSON}</script></body></html>'
        html_resp = _html_resp(html)

        with patch("requests.get", return_value=html_resp):
            from app.tools import fetch_swagger_json
            result = fetch_swagger_json("http://test.com")

        assert isinstance(result, dict)
        assert "openapi" in result

    def test_embedded_spec_in_swagger_config(self):
        """Spec embedded inline via spec: {...} in JS config -> extracted directly."""
        html = f'<html><script>SwaggerUIBundle({{ spec: {VALID_SPEC_JSON}, dom_id: "#app" }})</script></html>'
        html_resp = _html_resp(html)

        with patch("requests.get", return_value=html_resp):
            from app.tools import fetch_swagger_json
            result = fetch_swagger_json("http://test.com")

        assert isinstance(result, dict)
        assert "openapi" in result

    def test_yaml_direct(self):
        """URL returns YAML directly -> parsed successfully."""
        yaml_resp = _yaml_spec_resp()

        with patch("requests.get", return_value=yaml_resp):
            from app.tools import fetch_swagger_json
            result = fetch_swagger_json("http://test.com/openapi.yaml")

        assert isinstance(result, dict)
        assert "openapi" in result

    def test_yaml_fallback_candidates(self):
        """JSON candidates fail, YAML candidate succeeds."""
        yaml_resp = _yaml_spec_resp()

        def side_effect(url, **kwargs):
            if url.endswith(".yaml") or url.endswith(".yml"):
                return yaml_resp
            return _not_found_resp()

        with patch("requests.get", side_effect=side_effect):
            from app.tools import fetch_swagger_json
            result = fetch_swagger_json("http://test.com")

        assert isinstance(result, dict)
        assert "openapi" in result

    def test_no_duplicate_fetches(self):
        """URLs extracted from HTML that overlap with Phase 1 candidates are not re-fetched."""
        # The HTML points to the same /swagger.json already tried in Phase 1
        swagger_ui_html = '''<script>SwaggerUIBundle({ url: "/swagger.json" })</script>'''
        html_resp = _html_resp(swagger_ui_html)

        call_urls = []

        def side_effect(url, **kwargs):
            call_urls.append(url)
            return html_resp

        with patch("requests.get", side_effect=side_effect):
            from app.tools import fetch_swagger_json
            result = fetch_swagger_json("http://test.com")

        # Should be an error since there's no real spec
        assert isinstance(result, str)
        # The URL http://test.com/swagger.json should appear only once (Phase 1),
        # not again in Phase 2.
        swagger_json_calls = [u for u in call_urls if u == "http://test.com/swagger.json"]
        assert len(swagger_json_calls) == 1

    def test_all_fail_still_returns_error(self):
        """HTML found but no spec extracted -> returns error string."""
        html = "<html><body>Just a normal page</body></html>"
        html_resp = _html_resp(html)

        with patch("requests.get", return_value=html_resp):
            from app.tools import fetch_swagger_json
            result = fetch_swagger_json("http://test.com")

        assert isinstance(result, str)
        assert "could not" in result.lower() or "Last error" in result

    def test_link_header_service_desc(self):
        """HTTP Link header with rel=service-desc -> follows the URL."""
        # Phase 1 candidates all return 404, but include Link header on first response
        link_resp = MagicMock()
        link_resp.status_code = 404
        link_resp.headers = {
            "Content-Type": "text/plain",
            "Link": '</api/v3/openapi.json>; rel="service-desc"',
        }

        json_resp = _json_spec_resp()

        def side_effect(url, **kwargs):
            if url.endswith("/api/v3/openapi.json"):
                return json_resp
            return link_resp

        with patch("requests.get", side_effect=side_effect):
            from app.tools import fetch_swagger_json
            result = fetch_swagger_json("http://test.com")

        assert isinstance(result, dict)
        assert "openapi" in result

    def test_swagger_resources_spring_boot(self):
        """Spring Boot /swagger-resources returns JSON array with spec URL."""
        not_found = _not_found_resp()

        resources_resp = MagicMock()
        resources_resp.status_code = 200
        resources_resp.headers = {"Content-Type": "application/json", "Link": ""}
        resources_resp.json.return_value = [
            {"url": "/api/internal/v2/api-docs", "swaggerVersion": "2.0", "name": "default"}
        ]
        resources_resp.text = json.dumps([{"url": "/api/internal/v2/api-docs"}])

        json_resp = _json_spec_resp()

        def side_effect(url, **kwargs):
            if url.endswith("/swagger-resources"):
                return resources_resp
            if url.endswith("/api/internal/v2/api-docs"):
                return json_resp
            return not_found

        with patch("requests.get", side_effect=side_effect):
            from app.tools import fetch_swagger_json
            result = fetch_swagger_json("http://test.com")

        assert isinstance(result, dict)
        assert "openapi" in result

    def test_redoc_init_js_pattern(self):
        """Redoc.init('url', ...) JavaScript pattern -> follows the link."""
        redoc_html = """
        <html><body>
        <div id="redoc-container"></div>
        <script src="https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"></script>
        <script>
        Redoc.init('/api/openapi.yaml', {
            expandResponses: "200,400"
        }, document.getElementById('redoc-container'))
        </script>
        </body></html>
        """
        html_resp = _html_resp(redoc_html)
        yaml_resp = _yaml_spec_resp()

        def side_effect(url, **kwargs):
            if url.endswith("/api/openapi.yaml"):
                return yaml_resp
            return html_resp

        with patch("requests.get", side_effect=side_effect):
            from app.tools import fetch_swagger_json
            result = fetch_swagger_json("http://test.com")

        assert isinstance(result, dict)
        assert "openapi" in result

    def test_swagger_ui_urls_array(self):
        """SwaggerUIBundle with urls: [{url: ...}] array -> follows the first URL."""
        html = """
        <script>
        const ui = SwaggerUIBundle({
            urls: [{url: "/api/v1/openapi.json", name: "v1"}, {url: "/api/v2/openapi.json", name: "v2"}],
            dom_id: '#swagger-ui'
        })
        </script>
        """
        html_resp = _html_resp(html)
        json_resp = _json_spec_resp()

        def side_effect(url, **kwargs):
            if "openapi.json" in url and "/api/" in url:
                return json_resp
            return html_resp

        with patch("requests.get", side_effect=side_effect):
            from app.tools import fetch_swagger_json
            result = fetch_swagger_json("http://test.com")

        assert isinstance(result, dict)
        assert "openapi" in result


class TestHelperLinkHeader:
    def test_extracts_service_desc(self):
        from app.tools import _extract_urls_from_link_header
        header = '</openapi.json>; rel="service-desc", </docs>; rel="service-doc"'
        urls = _extract_urls_from_link_header(header, "https://example.com/api")
        assert "https://example.com/openapi.json" in urls
        # service-doc should NOT be extracted (only service-desc)
        assert len(urls) == 1

    def test_empty_header(self):
        from app.tools import _extract_urls_from_link_header
        assert _extract_urls_from_link_header("", "https://example.com") == []

    def test_no_service_desc(self):
        from app.tools import _extract_urls_from_link_header
        header = '</style.css>; rel="stylesheet"'
        assert _extract_urls_from_link_header(header, "https://example.com") == []


class TestHelperSwaggerResources:
    def test_extracts_urls_from_array(self):
        from app.tools import _extract_urls_from_swagger_resources
        data = [
            {"url": "/v2/api-docs", "swaggerVersion": "2.0", "name": "default"},
            {"url": "/v3/api-docs", "swaggerVersion": "3.0", "name": "v3"},
        ]
        urls = _extract_urls_from_swagger_resources(data, "https://example.com/swagger-resources")
        assert len(urls) == 2
        assert "https://example.com/v2/api-docs" in urls
        assert "https://example.com/v3/api-docs" in urls

    def test_not_array(self):
        from app.tools import _extract_urls_from_swagger_resources
        assert _extract_urls_from_swagger_resources({"url": "/api"}, "https://example.com") == []

    def test_empty_array(self):
        from app.tools import _extract_urls_from_swagger_resources
        assert _extract_urls_from_swagger_resources([], "https://example.com") == []


class TestHelperExtractSpecUrlsExtra:
    def test_redoc_init_pattern(self):
        from app.tools import _extract_spec_urls_from_html
        html = """Redoc.init('/api/openapi.yaml', {}, document.getElementById('redoc'))"""
        urls = _extract_spec_urls_from_html(html, "https://example.com/docs")
        assert "https://example.com/api/openapi.yaml" in urls

    def test_swagger_ui_urls_array(self):
        from app.tools import _extract_spec_urls_from_html
        html = """urls: [{url: "/v1/spec.json", name: "v1"}]"""
        urls = _extract_spec_urls_from_html(html, "https://example.com/")
        assert "https://example.com/v1/spec.json" in urls


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
