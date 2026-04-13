import pytest
from sqlalchemy.exc import IntegrityError

from app import crud
from app.models import Endpoint, ScanLog, Service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(db_session, name="Test Service", url="http://test.com/swagger.json"):
    return crud.create_service(db_session, name=name, swagger_url=url)


def _make_endpoint_data(path="/users", method="get"):
    return {
        "path": path,
        "method": method,
        "summary": "List users",
        "description": "Returns all users",
        "parameters_json": None,
        "request_body_json": None,
        "response_json": None,
        "tags": None,
        "deprecated": False,
    }


# ---------------------------------------------------------------------------
# TestCreateService
# ---------------------------------------------------------------------------


class TestCreateService:
    def test_create_service_success(self, db_session):
        service = _make_service(db_session)
        assert service.id is not None
        assert service.name == "Test Service"
        assert service.swagger_url == "http://test.com/swagger.json"
        assert service.scan_status == "pending"

    def test_create_service_sets_defaults(self, db_session):
        service = _make_service(db_session)
        assert service.scan_status == "pending"
        assert service.last_scanned_at is None


# ---------------------------------------------------------------------------
# TestGetService
# ---------------------------------------------------------------------------


class TestGetService:
    def test_get_service_found(self, db_session):
        created = _make_service(db_session)
        fetched = crud.get_service(db_session, created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.name == created.name

    def test_get_service_not_found(self, db_session):
        result = crud.get_service(db_session, 99999)
        assert result is None


# ---------------------------------------------------------------------------
# TestGetServicesByName
# ---------------------------------------------------------------------------


class TestGetServicesByName:
    def test_get_services_by_name_case_insensitive(self, db_session):
        created = _make_service(
            db_session,
            name="Payments",
            url="http://payments.com/swagger.json",
        )

        result = crud.get_services_by_name(db_session, "payments")
        assert len(result) == 1
        assert result[0].id == created.id

    def test_get_services_by_name_returns_all_matches_ordered(self, db_session):
        first = _make_service(
            db_session,
            name="SharedName",
            url="http://shared-a.com/swagger.json",
        )
        second = _make_service(
            db_session,
            name="sharedname",
            url="http://shared-b.com/swagger.json",
        )

        result = crud.get_services_by_name(db_session, "SHAREDNAME")
        assert [service.id for service in result] == [first.id, second.id]

    def test_get_services_by_name_no_match(self, db_session):
        _make_service(db_session)
        result = crud.get_services_by_name(db_session, "DoesNotExist")
        assert result == []


# ---------------------------------------------------------------------------
# TestListServices
# ---------------------------------------------------------------------------


class TestListServices:
    def test_list_services_empty(self, db_session):
        services = crud.list_services(db_session)
        assert services == []

    def test_list_services_multiple(self, db_session):
        _make_service(db_session, name="Service A", url="http://a.com/swagger.json")
        _make_service(db_session, name="Service B", url="http://b.com/swagger.json")
        _make_service(db_session, name="Service C", url="http://c.com/swagger.json")
        services = crud.list_services(db_session)
        assert len(services) == 3


# ---------------------------------------------------------------------------
# TestUpdateService
# ---------------------------------------------------------------------------


class TestUpdateService:
    def test_update_service_name(self, db_session):
        service = _make_service(db_session)
        updated = crud.update_service(db_session, service.id, name="Updated Name")
        assert updated is not None
        assert updated.name == "Updated Name"

    def test_update_service_status(self, db_session):
        service = _make_service(db_session)
        updated = crud.update_service(db_session, service.id, scan_status="scanning")
        assert updated is not None
        assert updated.scan_status == "scanning"

    def test_update_service_not_found(self, db_session):
        result = crud.update_service(db_session, 99999, name="Ghost")
        assert result is None

    def test_update_service_ignores_none_values(self, db_session):
        service = _make_service(db_session, name="Original Name")
        original_name = service.name
        crud.update_service(db_session, service.id, name=None)
        refreshed = crud.get_service(db_session, service.id)
        assert refreshed.name == original_name

    def test_update_service_ai_design_fields(self, db_session):
        service = _make_service(db_session)
        updated = crud.update_service_ai(
            db_session,
            service.id,
            ai_design_score=82,
            ai_design_recommendations="Use consistent plural nouns and add standard pagination parameters.",
        )
        assert updated is not None
        assert updated.ai_design_score == 82
        assert "pagination" in updated.ai_design_recommendations.lower()
        assert updated.ai_analyzed_at is not None


# ---------------------------------------------------------------------------
# TestDeleteService
# ---------------------------------------------------------------------------


class TestDeleteService:
    def test_delete_service_success(self, db_session):
        service = _make_service(db_session)
        result = crud.delete_service(db_session, service.id)
        assert result is True
        assert crud.get_service(db_session, service.id) is None

    def test_delete_service_not_found(self, db_session):
        result = crud.delete_service(db_session, 99999)
        assert result is False

    def test_delete_service_cascades_endpoints(self, db_session):
        service = _make_service(db_session)
        crud.replace_endpoints(db_session, service.id, [_make_endpoint_data()])
        # Verify endpoint exists before delete
        endpoints_before = crud.get_endpoints(db_session, service.id)
        assert len(endpoints_before) == 1

        crud.delete_service(db_session, service.id)

        remaining = (
            db_session.query(Endpoint)
            .filter(Endpoint.service_id == service.id)
            .all()
        )
        assert remaining == []


# ---------------------------------------------------------------------------
# TestReplaceEndpoints
# ---------------------------------------------------------------------------


class TestReplaceEndpoints:
    def test_replace_endpoints_adds_new(self, db_session):
        service = _make_service(db_session)
        endpoints = crud.replace_endpoints(
            db_session,
            service.id,
            [_make_endpoint_data("/users", "get"), _make_endpoint_data("/products", "get")],
        )
        assert len(endpoints) == 2
        paths = {e.path for e in endpoints}
        assert "/users" in paths
        assert "/products" in paths

    def test_replace_endpoints_replaces_existing(self, db_session):
        service = _make_service(db_session)
        # Create initial endpoints
        crud.replace_endpoints(
            db_session,
            service.id,
            [_make_endpoint_data("/old1", "get"), _make_endpoint_data("/old2", "post")],
        )
        # Replace with new endpoints
        new_endpoints = crud.replace_endpoints(
            db_session,
            service.id,
            [_make_endpoint_data("/new1", "get")],
        )
        assert len(new_endpoints) == 1
        assert new_endpoints[0].path == "/new1"
        # Make sure old endpoints are gone
        all_endpoints = crud.get_endpoints(db_session, service.id)
        assert len(all_endpoints) == 1
        assert all_endpoints[0].path == "/new1"

    def test_replace_endpoints_empty_list(self, db_session):
        service = _make_service(db_session)
        # Create initial endpoints
        crud.replace_endpoints(
            db_session,
            service.id,
            [_make_endpoint_data("/users", "get")],
        )
        # Replace with empty list - all existing endpoints should be removed
        result = crud.replace_endpoints(db_session, service.id, [])
        assert result == []
        remaining = crud.get_endpoints(db_session, service.id)
        assert remaining == []


# ---------------------------------------------------------------------------
# TestScanLogs
# ---------------------------------------------------------------------------


class TestScanLogs:
    def test_create_scan_log(self, db_session):
        service = _make_service(db_session)
        log = crud.create_scan_log(db_session, service.id)
        assert log.id is not None
        assert log.service_id == service.id
        assert log.started_at is not None
        assert log.finished_at is None
        assert log.status is None

    def test_finish_scan_log_success(self, db_session):
        service = _make_service(db_session)
        log = crud.create_scan_log(db_session, service.id)
        finished = crud.finish_scan_log(
            db_session, log.id, status="completed", endpoints_found=5
        )
        assert finished is not None
        assert finished.status == "completed"
        assert finished.endpoints_found == 5
        assert finished.finished_at is not None
        assert finished.error_message is None

    def test_finish_scan_log_error(self, db_session):
        service = _make_service(db_session)
        log = crud.create_scan_log(db_session, service.id)
        finished = crud.finish_scan_log(
            db_session,
            log.id,
            status="error",
            endpoints_found=0,
            error="Connection timeout",
        )
        assert finished is not None
        assert finished.status == "error"
        assert finished.error_message == "Connection timeout"
        assert finished.finished_at is not None


# ---------------------------------------------------------------------------
# TestEndpointsHaveChanged
# ---------------------------------------------------------------------------


class TestEndpointsHaveChanged:
    def _save_endpoints(self, db_session, service_id, endpoint_list):
        return crud.replace_endpoints(db_session, service_id, endpoint_list)

    def test_no_change_same_endpoints(self, db_session):
        service = _make_service(db_session)
        data = [_make_endpoint_data("/users", "GET")]
        crud.replace_endpoints(db_session, service.id, data)
        existing = crud.get_endpoints(db_session, service.id)
        assert crud.endpoints_have_changed(existing, data) is False

    def test_change_detected_added_endpoint(self, db_session):
        service = _make_service(db_session)
        data = [_make_endpoint_data("/users", "GET")]
        crud.replace_endpoints(db_session, service.id, data)
        existing = crud.get_endpoints(db_session, service.id)
        new_data = data + [_make_endpoint_data("/products", "GET")]
        assert crud.endpoints_have_changed(existing, new_data) is True

    def test_change_detected_removed_endpoint(self, db_session):
        service = _make_service(db_session)
        data = [
            _make_endpoint_data("/users", "GET"),
            _make_endpoint_data("/products", "GET"),
        ]
        crud.replace_endpoints(db_session, service.id, data)
        existing = crud.get_endpoints(db_session, service.id)
        assert crud.endpoints_have_changed(existing, data[:1]) is True

    def test_change_detected_field_change(self, db_session):
        service = _make_service(db_session)
        original = [_make_endpoint_data("/users", "GET")]
        crud.replace_endpoints(db_session, service.id, original)
        existing = crud.get_endpoints(db_session, service.id)
        modified = [{**original[0], "summary": "Updated summary"}]
        assert crud.endpoints_have_changed(existing, modified) is True

    def test_no_change_empty_sets(self, db_session):
        service = _make_service(db_session)
        existing = crud.get_endpoints(db_session, service.id)
        assert crud.endpoints_have_changed(existing, []) is False

    def test_change_none_to_value_in_optional_field(self, db_session):
        service = _make_service(db_session)
        data = [_make_endpoint_data("/users", "GET")]
        crud.replace_endpoints(db_session, service.id, data)
        existing = crud.get_endpoints(db_session, service.id)
        changed = [{**data[0], "description": "Now has a description"}]
        assert crud.endpoints_have_changed(existing, changed) is True
