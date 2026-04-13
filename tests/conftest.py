"""
conftest.py - pytest fixtures for SwaggerAgent unit tests.

Bootstrap strategy:
  1. Patch pyodbc (not installed in CI) before any app import touches it.
  2. Create an in-memory SQLite engine and inject it into app.database so that
     every module that does `from app.database import SessionLocal / engine`
     gets the test version.
  3. Override FastAPI's get_db dependency to use the per-test SQLite session.
"""

import sys
import types
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# 1. Stub pyodbc before SQLAlchemy / app.database tries to import it
# ---------------------------------------------------------------------------

try:
    import pyodbc  # noqa: F401 — ensure real pyodbc is loaded if installed
except ImportError:
    sys.modules["pyodbc"] = MagicMock()

# ---------------------------------------------------------------------------
# 2. Now we can safely import SQLAlchemy and app modules
# ---------------------------------------------------------------------------

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# Import Base and get_db *after* pyodbc is stubbed.  app.database will try
# to create_engine(mssql+pyodbc://...) at module level; we patch create_engine
# so it returns a no-op mock, and then immediately replace the real attributes
# with our SQLite ones.
with patch("sqlalchemy.create_engine") as _mock_ce:
    _mock_ce.return_value = MagicMock()
    from app.database import Base, get_db
    import app.database as _app_database

# ---------------------------------------------------------------------------
# 3. Create a shared in-memory SQLite engine for the test suite
# ---------------------------------------------------------------------------

SQLALCHEMY_TEST_URL = "sqlite://"

# We need a *single* connection that persists for the life of the engine so
# that in-memory tables survive across sessions.
from sqlalchemy import StaticPool

_test_engine = create_engine(
    SQLALCHEMY_TEST_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@event.listens_for(_test_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# Inject the test engine into app.database so that tools.py
# that do `from app.database import SessionLocal` get the SQLite one.
_app_database.engine = _test_engine
_TestSession = sessionmaker(bind=_test_engine, autocommit=False, autoflush=False)
_app_database.SessionLocal = _TestSession


# ---------------------------------------------------------------------------
# 4. Now import the FastAPI app
# ---------------------------------------------------------------------------

from app.main import app  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def db_engine():
    """Re-create all tables on a fresh in-memory SQLite engine for each test."""
    engine = create_engine(
        SQLALCHEMY_TEST_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(db_engine):
    """Provide a transactional SQLite session, rolled back after each test."""
    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()
    # Also point app.database.SessionLocal at this engine so tools work
    _app_database.SessionLocal = sessionmaker(bind=db_engine)
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="function")
def client(db_session):
    """TestClient wired to the per-test SQLite session, scheduler disabled."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture
def mock_agent():
    """Patch the background scan function so tests don't call the real agent."""
    with patch("app.api._run_scan_background") as mock:
        yield mock


# ---------------------------------------------------------------------------
# Sample Swagger documents
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_swagger_json():
    return {
        "openapi": "3.0.0",
        "info": {
            "title": "Test API",
            "version": "1.0.0",
            "description": "A test service",
        },
        "servers": [{"url": "https://api.test.com"}],
        "paths": {
            "/users": {
                "get": {
                    "summary": "List users",
                    "description": "Returns all users",
                    "tags": ["Users"],
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer"},
                        }
                    ],
                    "responses": {"200": {"description": "Success"}},
                },
                "post": {
                    "summary": "Create user",
                    "tags": ["Users"],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"name": {"type": "string"}},
                                }
                            }
                        }
                    },
                    "responses": {"201": {"description": "Created"}},
                },
            },
            "/users/{id}": {
                "get": {
                    "summary": "Get user by ID",
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
                        "200": {"description": "Success"},
                        "404": {"description": "Not found"},
                    },
                    "deprecated": True,
                }
            },
        },
    }


@pytest.fixture
def sample_swagger_2_json():
    return {
        "swagger": "2.0",
        "info": {
            "title": "Legacy API",
            "version": "2.0.0",
            "description": "Legacy service",
        },
        "host": "api.legacy.com",
        "basePath": "/v2",
        "schemes": ["https"],
        "paths": {
            "/items": {
                "get": {
                    "summary": "List items",
                    "parameters": [],
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }
