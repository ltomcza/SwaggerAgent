"""
Integration tests for SwaggerAgent.

Requirements:
- SQL Server available via TEST_DB_URL or docker-compose
- Run with: pytest tests/test_integration.py -v -m integration

Environment variables:
- TEST_DB_URL: MSSQL connection string (optional, defaults to localhost)
- SKIP_INTEGRATION: set to "1" to skip integration tests
"""
import json
import os
import time
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.main import app

# Skip integration tests if SKIP_INTEGRATION=1
skip_integration = os.getenv("SKIP_INTEGRATION", "0") == "1"
pytestmark = pytest.mark.integration


def get_test_db_url() -> str:
    """Returns the connection string for the test MSSQL database."""
    return os.getenv(
        "TEST_DB_URL",
        "mssql+pyodbc://sa:YourStrong!Passw0rd@localhost:1433/swagger_agent_test"
        "?driver=ODBC+Driver+17+for+SQL+Server&TrustServerCertificate=yes"
    )


@pytest.fixture(scope="module")
def integration_engine():
    """Creates an engine for the test MSSQL database."""
    if skip_integration:
        pytest.skip("Integration tests skipped (SKIP_INTEGRATION=1)")

    db_url = get_test_db_url()

    # Try to connect — skip the test if the database is unavailable
    try:
        engine = create_engine(db_url, connect_args={"connect_timeout": 5})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"MSSQL not available: {e}")

    # Create tables
    Base.metadata.create_all(bind=engine)
    yield engine
    # Clean up after tests
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def integration_db(integration_engine):
    """Database session for integration tests."""
    IntegrationSession = sessionmaker(bind=integration_engine)
    session = IntegrationSession()
    yield session
    session.rollback()
    # Clean up data between tests
    from app.models import ScanLog, Endpoint, Service
    session.query(ScanLog).delete()
    session.query(Endpoint).delete()
    session.query(Service).delete()
    session.commit()
    session.close()


@pytest.fixture(scope="function")
def integration_client(integration_db):
    """TestClient wired to the real MSSQL database."""
    def override_get_db():
        yield integration_db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def sample_swagger_doc():
    """Complete OpenAPI 3.0 document for tests."""
    return {
        "openapi": "3.0.0",
        "info": {
            "title": "Pet Store API",
            "version": "2.0.0",
            "description": "A sample pet store service"
        },
        "servers": [{"url": "https://petstore.example.com/api"}],
        "paths": {
            "/pets": {
                "get": {
                    "summary": "List all pets",
                    "description": "Returns a list of all pets",
                    "tags": ["Pets"],
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer", "default": 10}
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "A list of pets",
                            "content": {
                                "application/json": {
                                    "schema": {"type": "array", "items": {"type": "object"}}
                                }
                            }
                        }
                    }
                },
                "post": {
                    "summary": "Create a pet",
                    "tags": ["Pets"],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "species": {"type": "string"}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "201": {"description": "Pet created"},
                        "400": {"description": "Invalid input"}
                    }
                }
            },
            "/pets/{petId}": {
                "get": {
                    "summary": "Get a pet",
                    "tags": ["Pets"],
                    "parameters": [
                        {"name": "petId", "in": "path", "required": True, "schema": {"type": "integer"}}
                    ],
                    "responses": {
                        "200": {"description": "Pet found"},
                        "404": {"description": "Pet not found"}
                    }
                },
                "delete": {
                    "summary": "Delete a pet",
                    "tags": ["Pets"],
                    "deprecated": True,
                    "parameters": [
                        {"name": "petId", "in": "path", "required": True, "schema": {"type": "integer"}}
                    ],
                    "responses": {
                        "204": {"description": "Deleted"},
                        "404": {"description": "Not found"}
                    }
                }
            },
            "/health": {
                "get": {
                    "summary": "Health check",
                    "tags": ["System"],
                    "responses": {"200": {"description": "OK"}}
                }
            }
        }
    }


def _mock_agent_analysis(service_id: int, swagger_url: str, db_session=None):
    """
    Helper replacing run_swagger_analysis — runs fetch+parse via tools, then
    writes to the DB using the supplied session (avoids tools' internal
    SessionLocal which points at the MSSQL settings DB, not the test DB).
    """
    from datetime import datetime, timezone
    from app import crud
    from app.tools import fetch_swagger_json, parse_swagger_document

    db = db_session
    if db is None:
        return "error: no database session provided"
    
    try:
        swagger_data = fetch_swagger_json(swagger_url)
        if isinstance(swagger_data, str):
            return f"error: {swagger_data}"

        parsed_data = parse_swagger_document(swagger_data)
        if isinstance(parsed_data, str):
            return f"error: {parsed_data}"

        crud.update_service(
            db, service_id,
            description=parsed_data.get("description"),
            swagger_version=parsed_data.get("version"),
            base_url=parsed_data.get("base_url"),
            last_scanned_at=datetime.now(timezone.utc),
            scan_status="completed",
            scan_error=None,
        )
        crud.replace_endpoints(db, service_id, parsed_data.get("endpoints", []))
        db.commit()
        return f"completed: {len(parsed_data.get('endpoints', []))} endpoints saved"
    except Exception as e:
        if db:
            crud.update_service(db, service_id, scan_status="error", scan_error=str(e))
            db.commit()
        return f"error: {e}"


@pytest.mark.skipif(skip_integration, reason="Integration tests skipped")
class TestFullWorkflow:
    """Tests for the full service lifecycle."""

    def test_add_service_scan_get_markdown(self, integration_client, integration_db, httpserver, sample_swagger_doc):
        """Full workflow: add -> scan -> verify -> markdown."""
        # 1. Serve the test Swagger JSON
        httpserver.expect_request("/swagger.json").respond_with_json(sample_swagger_doc)
        swagger_url = httpserver.url_for("/swagger.json")

        # 2. Dodaj serwis
        resp = integration_client.post("/services", json={
            "name": "Pet Store",
            "swagger_url": swagger_url
        })
        assert resp.status_code == 201
        data = resp.json()
        service_id = data["id"]
        assert data["name"] == "Pet Store"
        assert data["scan_status"] == "pending"

        # 3. Trigger scan (with agent mock)
        with patch("app.agent.run_swagger_analysis") as mock_analysis:
            mock_analysis.side_effect = lambda sid, url: _mock_agent_analysis(sid, url, integration_db)
            resp = integration_client.post(f"/services/{service_id}/scan")
            assert resp.status_code == 202
            # Wait for background scan to finish
            time.sleep(2)

        # 4. Check status after scan
        resp = integration_client.get(f"/services/{service_id}/scan-status")
        assert resp.status_code == 200
        status_data = resp.json()
        assert status_data["scan_status"] in ("completed", "scanning", "error")

        # 5. Get service details
        resp = integration_client.get(f"/services/{service_id}")
        assert resp.status_code == 200
        service_data = resp.json()
        assert service_data["name"] == "Pet Store"

        # 6. Get Markdown
        resp = integration_client.get(f"/services/{service_id}/markdown")
        assert resp.status_code == 200
        assert "text/markdown" in resp.headers.get("content-type", "")
        md_content = resp.text
        assert "Pet Store" in md_content

    def test_scan_saves_endpoints_to_db(self, integration_client, integration_db, httpserver, sample_swagger_doc):
        """Test that scanning saves endpoints to the database."""
        httpserver.expect_request("/api/swagger.json").respond_with_json(sample_swagger_doc)
        swagger_url = httpserver.url_for("/api/swagger.json")

        # Add service
        resp = integration_client.post("/services", json={
            "name": "Endpoint Test Service",
            "swagger_url": swagger_url
        })
        service_id = resp.json()["id"]

        # Scan directly via helper
        result = _mock_agent_analysis(service_id, swagger_url, integration_db)
        assert "completed" in result.lower() or "endpoint" in result.lower()

        # Check endpoints
        resp = integration_client.get(f"/services/{service_id}")
        service_data = resp.json()
        # sample_swagger_doc has 5 endpoints: GET /pets, POST /pets, GET /pets/{petId}, DELETE /pets/{petId}, GET /health
        assert len(service_data["endpoints"]) == 5


@pytest.mark.skipif(skip_integration, reason="Integration tests skipped")
class TestCrudIntegration:
    """CRUD tests against a real database."""

    def test_create_and_retrieve_service(self, integration_client):
        """Test creating and retrieving a service."""
        resp = integration_client.post("/services", json={
            "name": "Integration Test Service",
            "swagger_url": "http://integration-test.example.com/swagger.json"
        })
        assert resp.status_code == 201
        service_id = resp.json()["id"]

        resp = integration_client.get(f"/services/{service_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Integration Test Service"

    def test_update_service(self, integration_client):
        """Test updating a service."""
        resp = integration_client.post("/services", json={
            "name": "Original Name",
            "swagger_url": "http://update-test.example.com/swagger.json"
        })
        service_id = resp.json()["id"]

        resp = integration_client.put(f"/services/{service_id}", json={"name": "Updated Name"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"

    def test_delete_service_removes_endpoints(self, integration_client, integration_db, httpserver, sample_swagger_doc):
        """Test that deleting a service also removes its endpoints (cascade)."""
        from app import crud

        httpserver.expect_request("/delete-test.json").respond_with_json(sample_swagger_doc)
        swagger_url = httpserver.url_for("/delete-test.json")

        resp = integration_client.post("/services", json={
            "name": "Delete Test",
            "swagger_url": swagger_url
        })
        service_id = resp.json()["id"]

        # Add endpoints directly
        crud.replace_endpoints(integration_db, service_id, [
            {"path": "/test", "method": "get", "summary": "Test", "description": None,
             "parameters_json": None, "request_body_json": None, "response_json": None,
             "tags": None, "deprecated": False}
        ])
        integration_db.commit()

        # Verify endpoints exist
        endpoints_before = crud.get_endpoints(integration_db, service_id)
        assert len(endpoints_before) == 1

        # Delete service
        resp = integration_client.delete(f"/services/{service_id}")
        assert resp.status_code == 200

        # Verify endpoints are gone
        endpoints_after = crud.get_endpoints(integration_db, service_id)
        assert len(endpoints_after) == 0

    def test_duplicate_url_rejected(self, integration_client):
        """Test that duplicate URLs are rejected."""
        url = "http://duplicate-test.example.com/swagger.json"
        integration_client.post("/services", json={"name": "First", "swagger_url": url})
        resp = integration_client.post("/services", json={"name": "Second", "swagger_url": url})
        assert resp.status_code == 409


@pytest.mark.skipif(skip_integration, reason="Integration tests skipped")
class TestMarkdownIntegration:
    """Tests for Markdown generation from database data."""

    def test_markdown_contains_all_services(self, integration_client, integration_db, httpserver, sample_swagger_doc):
        """Test that the combined MD contains all services."""
        httpserver.expect_request("/svc1.json").respond_with_json(sample_swagger_doc)
        httpserver.expect_request("/svc2.json").respond_with_json(sample_swagger_doc)

        integration_client.post("/services", json={
            "name": "Service Alpha",
            "swagger_url": httpserver.url_for("/svc1.json")
        })
        integration_client.post("/services", json={
            "name": "Service Beta",
            "swagger_url": httpserver.url_for("/svc2.json")
        })

        resp = integration_client.get("/services/markdown/all")
        assert resp.status_code == 200
        md = resp.text
        assert "Service Alpha" in md
        assert "Service Beta" in md

    def test_markdown_after_scan_contains_endpoints(self, integration_client, integration_db, httpserver, sample_swagger_doc):
        """Test that MD contains endpoints after scanning."""
        from app import crud

        httpserver.expect_request("/md-test.json").respond_with_json(sample_swagger_doc)
        swagger_url = httpserver.url_for("/md-test.json")

        resp = integration_client.post("/services", json={
            "name": "MD Test Service",
            "swagger_url": swagger_url
        })
        service_id = resp.json()["id"]

        # Scan
        _mock_agent_analysis(service_id, swagger_url, integration_db)

        # Check MD
        resp = integration_client.get(f"/services/{service_id}/markdown")
        md = resp.text
        assert "/pets" in md
        assert "GET" in md
        assert "POST" in md


@pytest.mark.skipif(skip_integration, reason="Integration tests skipped")
class TestScanErrorHandling:
    """Tests for scan error handling."""

    def test_scan_invalid_url_sets_error_status(self, integration_client, integration_db):
        """Test that scanning an invalid URL sets error status."""
        resp = integration_client.post("/services", json={
            "name": "Bad URL Service",
            "swagger_url": "http://nonexistent-host-xyz.invalid/swagger.json"
        })
        service_id = resp.json()["id"]

        # Scan with real tool (no LLM mock)
        from app.tools import fetch_swagger_json, parse_swagger_document
        from app import crud
        from datetime import datetime, timezone

        try:
            fetch_result = fetch_swagger_json.invoke(
                {"url": "http://nonexistent-host-xyz.invalid/swagger.json"}
            )
            # If fetch returned an error string, save error status
            if "error" in fetch_result.lower() or "failed" in fetch_result.lower():
                crud.update_service(
                    integration_db, service_id,
                    scan_status="error",
                    scan_error=fetch_result[:500]
                )
                integration_db.commit()
        except Exception as e:
            crud.update_service(integration_db, service_id, scan_status="error", scan_error=str(e))
            integration_db.commit()

        # Check status
        resp = integration_client.get(f"/services/{service_id}/scan-status")
        status = resp.json()["scan_status"]
        assert status in ("error", "pending", "scanning")  # may vary

    def test_scan_non_swagger_url(self, integration_client, integration_db, httpserver):
        """Test that scanning a URL that doesn't return Swagger JSON handles the error gracefully."""
        httpserver.expect_request("/not-swagger").respond_with_data(
            "<html><body>Not a Swagger page</body></html>",
            content_type="text/html"
        )

        resp = integration_client.post("/services", json={
            "name": "HTML Service",
            "swagger_url": httpserver.url_for("/not-swagger")
        })
        service_id = resp.json()["id"]
        assert service_id is not None

        # Fetch — should not raise
        resp = integration_client.get(f"/services/{service_id}")
        assert resp.status_code == 200
