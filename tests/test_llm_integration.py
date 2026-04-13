"""
LLM integration tests for SwaggerAgent.

These tests make real OpenAI API calls and are skipped when OPENAI_API_KEY is
not set in the environment.

Run with:
    pytest tests/test_llm_integration.py -v -m llm_integration

They use the same in-memory SQLite engine as unit tests (no MSSQL needed) and
exercise the LLM tools and the full pipeline against a local HTTP server.
"""
import json
import os
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.llm_integration

_HAS_API_KEY = bool(os.getenv("OPENAI_API_KEY", ""))


# ---------------------------------------------------------------------------
# LLM-specific session fixture
#
# Both app.tools and app.agent do `from app.database import SessionLocal`,
# which creates a local binding at import time.  The conftest trick of setting
# `app.database.SessionLocal = ...` does not reach those local bindings.
# We patch SessionLocal directly in each module's namespace so that calls to
# `SessionLocal()` inside the real tool/agent functions hit the test DB.
# ---------------------------------------------------------------------------


@pytest.fixture
def llm_db_session(db_engine):
    """Real SQLite session with SessionLocal patched in tools and agent."""
    import app.tools
    import app.agent

    TestSession = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    session = TestSession()

    with patch.object(app.tools, "SessionLocal", TestSession), \
         patch.object(app.agent, "SessionLocal", TestSession):
        yield session

    session.rollback()
    session.close()


# ---------------------------------------------------------------------------
# Shared fixture: a minimal but realistic OpenAPI 3.0 document
# ---------------------------------------------------------------------------

_USER_API_DOC = {
    "openapi": "3.0.0",
    "info": {
        "title": "User Management API",
        "version": "1.0.0",
        "description": "Manages user accounts for an e-commerce platform",
    },
    "servers": [{"url": "https://api.example.com"}],
    "paths": {
        "/users": {
            "get": {
                "summary": "List users",
                "tags": ["Users"],
                "parameters": [
                    {
                        "name": "limit",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer", "default": 20},
                    }
                ],
                "responses": {"200": {"description": "OK"}},
            },
            "post": {
                "summary": "Create user",
                "tags": ["Users"],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "email": {"type": "string", "format": "email"},
                                },
                                "required": ["name", "email"],
                            }
                        }
                    },
                },
                "responses": {
                    "201": {"description": "User created"},
                    "400": {"description": "Validation error"},
                },
            },
        },
        "/users/{id}": {
            # intentionally no summary or description → triggers deep analysis
            "get": {
                "tags": ["Users"],
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {
                    "200": {"description": "User found"},
                    "404": {"description": "Not found"},
                },
            }
        },
    },
}


# ---------------------------------------------------------------------------
# TestAnalyzeServiceWithLLM
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_API_KEY, reason="OPENAI_API_KEY not set")
class TestAnalyzeServiceWithLLM:
    """Tests for analyze_service_with_llm making real LLM calls."""

    def test_returns_quality_score_string(self, llm_db_session):
        """Result string should mention quality score and service id."""
        from app import crud
        from app.tools import analyze_service_with_llm, parse_swagger_document

        service = crud.create_service(
            llm_db_session, "LLM Quality Test", "http://llm-quality.example.com/swagger.json"
        )

        parsed = parse_swagger_document(_USER_API_DOC)
        assert isinstance(parsed, dict), f"parse_swagger_document returned error: {parsed}"

        result = analyze_service_with_llm(service.id, parsed)

        assert isinstance(result, str)
        assert "error" not in result.lower()
        assert "quality" in result.lower()
        assert str(service.id) in result

    def test_saves_ai_overview_to_db(self, llm_db_session):
        """ai_overview and ai_documentation_score should be written to the Service row."""
        from app import crud
        from app.tools import analyze_service_with_llm, parse_swagger_document

        service = crud.create_service(
            llm_db_session, "LLM Overview Test", "http://llm-overview.example.com/swagger.json"
        )

        parsed = parse_swagger_document(_USER_API_DOC)
        result = analyze_service_with_llm(service.id, parsed)
        assert "error" not in result.lower()

        llm_db_session.expire_all()
        updated = crud.get_service(llm_db_session, service.id)
        assert updated.ai_overview is not None
        assert len(updated.ai_overview) > 20, "Overview should be a non-trivial paragraph"
        assert updated.ai_documentation_score is not None
        assert 0 <= updated.ai_documentation_score <= 100

    def test_enriches_endpoints_in_db_with_ai_summaries(self, llm_db_session):
        """Per-endpoint ai_summary should be written for endpoints that exist in the DB."""
        from app import crud
        from app.tools import analyze_service_with_llm, parse_swagger_document

        service = crud.create_service(
            llm_db_session, "LLM Endpoint Enrichment", "http://llm-enrich.example.com/swagger.json"
        )

        parsed = parse_swagger_document(_USER_API_DOC)
        # Endpoints must be in the DB before the LLM tool can write back to them
        crud.replace_endpoints(llm_db_session, service.id, parsed["endpoints"])

        result = analyze_service_with_llm(service.id, parsed)
        assert "error" not in result.lower()

        # At least some endpoints should have received an AI summary
        llm_db_session.expire_all()
        endpoints = crud.get_endpoints(llm_db_session, service.id)
        ai_enriched = [ep for ep in endpoints if ep.ai_summary]
        assert len(ai_enriched) > 0, "Expected at least one endpoint to have ai_summary set"

    def test_result_mentions_enriched_count(self, llm_db_session):
        """The result string should mention how many endpoints were enriched."""
        from app import crud
        from app.tools import analyze_service_with_llm, parse_swagger_document

        service = crud.create_service(
            llm_db_session, "LLM Count Test", "http://llm-count.example.com/swagger.json"
        )

        parsed = parse_swagger_document(_USER_API_DOC)
        crud.replace_endpoints(llm_db_session, service.id, parsed["endpoints"])

        result = analyze_service_with_llm(service.id, parsed)

        assert "Enriched" in result
        # _USER_API_DOC has 3 endpoints, all should be enriched
        assert "3" in result


# ---------------------------------------------------------------------------
# TestAnalyzeEndpointWithLLM
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_API_KEY, reason="OPENAI_API_KEY not set")
class TestAnalyzeEndpointWithLLM:
    """Tests for analyze_endpoint_with_llm making real LLM calls."""

    def _add_get_endpoint(self, session, service_id: int) -> None:
        """Helper: save GET /users/{id} with no summary/description."""
        from app import crud

        crud.replace_endpoints(
            session,
            service_id,
            [
                {
                    "path": "/users/{id}",
                    "method": "GET",
                    "summary": None,
                    "description": None,
                    "parameters_json": json.dumps(
                        [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}]
                    ),
                    "request_body_json": None,
                    "response_json": json.dumps(
                        {"200": {"description": "User found"}, "404": {"description": "Not found"}}
                    ),
                    "tags": json.dumps(["Users"]),
                    "deprecated": False,
                }
            ],
        )

    def test_returns_completion_string(self, llm_db_session):
        """Result string should say the analysis completed."""
        from app import crud
        from app.tools import analyze_endpoint_with_llm

        service = crud.create_service(
            llm_db_session, "EP Completion Test", "http://ep-completion.example.com/swagger.json"
        )
        self._add_get_endpoint(llm_db_session, service.id)

        result = analyze_endpoint_with_llm(service.id, "/users/{id}", "GET")

        assert isinstance(result, str)
        assert "error" not in result.lower()
        assert "complete" in result.lower()

    def test_saves_inferred_summary_for_undocumented_endpoint(self, llm_db_session):
        """An endpoint with no summary should receive an ai_summary after deep analysis."""
        from app import crud
        from app.tools import analyze_endpoint_with_llm

        service = crud.create_service(
            llm_db_session, "EP Summary Test", "http://ep-summary.example.com/swagger.json"
        )
        self._add_get_endpoint(llm_db_session, service.id)

        result = analyze_endpoint_with_llm(service.id, "/users/{id}", "GET")
        assert "error" not in result.lower()

        llm_db_session.expire_all()
        ep = crud.get_endpoint_by_path_method(llm_db_session, service.id, "/users/{id}", "GET")
        assert ep is not None
        assert ep.ai_summary is not None
        assert len(ep.ai_summary) > 5

    def test_post_endpoint_gets_request_and_response_examples(self, llm_db_session):
        """A POST endpoint with a request body schema should receive generated examples."""
        from app import crud
        from app.tools import analyze_endpoint_with_llm

        service = crud.create_service(
            llm_db_session, "EP Examples Test", "http://ep-examples.example.com/swagger.json"
        )
        crud.replace_endpoints(
            llm_db_session,
            service.id,
            [
                {
                    "path": "/users",
                    "method": "POST",
                    "summary": None,
                    "description": None,
                    "parameters_json": None,
                    "request_body_json": json.dumps(
                        {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"},
                                            "email": {"type": "string", "format": "email"},
                                        },
                                        "required": ["name", "email"],
                                    }
                                }
                            },
                        }
                    ),
                    "response_json": json.dumps({"201": {"description": "User created"}}),
                    "tags": json.dumps(["Users"]),
                    "deprecated": False,
                }
            ],
        )

        result = analyze_endpoint_with_llm(service.id, "/users", "POST")
        assert "error" not in result.lower()

        llm_db_session.expire_all()
        ep = crud.get_endpoint_by_path_method(llm_db_session, service.id, "/users", "POST")
        assert ep is not None
        # POST with a defined request body should produce a realistic example
        assert ep.ai_request_example is not None


# ---------------------------------------------------------------------------
# TestFullPipelineWithRealLLM
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_API_KEY, reason="OPENAI_API_KEY not set")
class TestFullPipelineWithRealLLM:
    """End-to-end pipeline tests: real HTTP fetch + real LLM calls."""

    def test_pipeline_saves_endpoints_and_ai_overview(self, llm_db_session, httpserver):
        """Full run_swagger_analysis should persist endpoints and populate AI fields."""
        from app import crud
        from app.agent import run_swagger_analysis

        httpserver.expect_request("/swagger.json").respond_with_json(_USER_API_DOC)
        swagger_url = httpserver.url_for("/swagger.json")

        service = crud.create_service(llm_db_session, "Full Pipeline LLM", swagger_url)

        result = run_swagger_analysis(service.id, swagger_url)

        assert isinstance(result, str)
        assert "Pipeline complete" in result

        # Endpoints should be saved (3 in _USER_API_DOC)
        llm_db_session.expire_all()
        endpoints = crud.get_endpoints(llm_db_session, service.id)
        assert len(endpoints) == 3

        # LLM should have populated ai_overview on the service
        updated = crud.get_service(llm_db_session, service.id)
        assert updated.ai_overview is not None
        assert updated.scan_status == "completed"

    def test_pipeline_triggers_deep_analysis_for_undocumented_endpoint(self, llm_db_session, httpserver):
        """GET /users/{id} has no summary — deep analysis should set ai_summary on that endpoint."""
        from app import crud
        from app.agent import run_swagger_analysis

        httpserver.expect_request("/api.json").respond_with_json(_USER_API_DOC)
        swagger_url = httpserver.url_for("/api.json")

        service = crud.create_service(llm_db_session, "Deep Analysis LLM", swagger_url)

        result = run_swagger_analysis(service.id, swagger_url)
        assert "Pipeline complete" in result

        llm_db_session.expire_all()
        ep = crud.get_endpoint_by_path_method(llm_db_session, service.id, "/users/{id}", "GET")
        assert ep is not None
        # Deep analysis (step 6) should have inferred a summary for this endpoint
        assert ep.ai_summary is not None

    def test_pipeline_result_includes_save_and_analysis_summaries(self, llm_db_session, httpserver):
        """The pipeline output should include save confirmation and analysis result."""
        from app import crud
        from app.agent import run_swagger_analysis

        httpserver.expect_request("/v2.json").respond_with_json(_USER_API_DOC)
        swagger_url = httpserver.url_for("/v2.json")

        service = crud.create_service(llm_db_session, "Summary Check LLM", swagger_url)

        result = run_swagger_analysis(service.id, swagger_url)

        # save_service_data confirms "Saved 3 endpoints"
        assert "3" in result
        # analyze_service_with_llm confirms "Quality score"
        assert "quality" in result.lower() or "Quality" in result
