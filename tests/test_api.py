import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_service(client, name="Test Service", url="http://test.com/swagger.json"):
    resp = client.post("/services", json={"name": name, "swagger_url": url})
    assert resp.status_code == 201, f"Failed to create service: {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# TestCreateServiceEndpoint
# ---------------------------------------------------------------------------


class TestCreateServiceEndpoint:
    def test_create_service_success(self, client):
        resp = client.post(
            "/services",
            json={"name": "My API", "swagger_url": "http://example.com/swagger.json"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] is not None
        assert data["name"] == "My API"
        assert data["swagger_url"] == "http://example.com/swagger.json"
        assert data["scan_status"] == "pending"
        assert data["endpoints"] == []

    def test_create_service_duplicate_url(self, client):
        url = "http://example.com/swagger.json"
        _create_service(client, name="First", url=url)
        resp = client.post("/services", json={"name": "Second", "swagger_url": url})
        assert resp.status_code == 409

    def test_create_service_missing_name(self, client):
        resp = client.post(
            "/services", json={"swagger_url": "http://example.com/swagger.json"}
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# TestListServicesEndpoint
# ---------------------------------------------------------------------------


class TestListServicesEndpoint:
    def test_list_services_empty(self, client):
        resp = client.get("/services")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_services_with_data(self, client):
        _create_service(client, name="Service A", url="http://a.com/swagger.json")
        _create_service(client, name="Service B", url="http://b.com/swagger.json")
        resp = client.get("/services")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        names = {s["name"] for s in data}
        assert "Service A" in names
        assert "Service B" in names


# ---------------------------------------------------------------------------
# TestGetServiceEndpoint
# ---------------------------------------------------------------------------


class TestGetServiceEndpoint:
    def test_get_service_found(self, client):
        created = _create_service(client)
        resp = client.get(f"/services/{created['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == created["id"]
        assert data["name"] == created["name"]

    def test_get_service_not_found(self, client):
        resp = client.get("/services/999")
        assert resp.status_code == 404

    def test_get_service_includes_design_fields(self, client):
        created = _create_service(client)
        resp = client.get(f"/services/{created['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert "ai_design_score" in data
        assert "ai_design_recommendations" in data


# ---------------------------------------------------------------------------
# TestUpdateServiceEndpoint
# ---------------------------------------------------------------------------


class TestUpdateServiceEndpoint:
    def test_update_service_name(self, client):
        created = _create_service(client)
        resp = client.put(f"/services/{created['id']}", json={"name": "Updated Name"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"

    def test_update_service_not_found(self, client):
        resp = client.put("/services/999", json={"name": "Ghost"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestDeleteServiceEndpoint
# ---------------------------------------------------------------------------


class TestDeleteServiceEndpoint:
    def test_delete_service_success(self, client):
        created = _create_service(client)
        resp = client.delete(f"/services/{created['id']}")
        assert resp.status_code == 200
        # Verify it's gone
        get_resp = client.get(f"/services/{created['id']}")
        assert get_resp.status_code == 404

    def test_delete_service_not_found(self, client):
        resp = client.delete("/services/999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestTriggerScan
# ---------------------------------------------------------------------------


class TestTriggerScan:
    def test_trigger_scan_success(self, client, mock_agent):
        created = _create_service(client)
        resp = client.post(f"/services/{created['id']}/scan")
        assert resp.status_code == 202
        data = resp.json()
        assert data["service_id"] == created["id"]
        assert "scan" in data["message"].lower() or data["message"] != ""

    def test_trigger_scan_not_found(self, client):
        resp = client.post("/services/999/scan")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestTriggerScanByName
# ---------------------------------------------------------------------------


class TestTriggerScanByName:
    def test_trigger_scan_by_name_single_match(self, client, mock_agent):
        created = _create_service(
            client,
            name="Orders",
            url="http://orders.com/swagger.json",
        )

        resp = client.post("/services/by-name/Orders/scan")
        assert resp.status_code == 202
        data = resp.json()
        assert data["service_name"] == "Orders"
        assert data["service_count"] == 1
        assert data["service_ids"] == [created["id"]]
        assert mock_agent.call_count == 1

    def test_trigger_scan_by_name_multiple_matches(self, client, mock_agent):
        first = _create_service(
            client,
            name="Shared",
            url="http://shared-a.com/swagger.json",
        )
        second = _create_service(
            client,
            name="shared",
            url="http://shared-b.com/swagger.json",
        )

        resp = client.post("/services/by-name/SHARED/scan")
        assert resp.status_code == 202
        data = resp.json()
        assert data["service_name"] == "SHARED"
        assert data["service_count"] == 2
        assert data["service_ids"] == [first["id"], second["id"]]
        assert mock_agent.call_count == 2

    def test_trigger_scan_by_name_not_found(self, client):
        resp = client.post("/services/by-name/DoesNotExist/scan")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestScanStatus
# ---------------------------------------------------------------------------


class TestScanStatus:
    def test_get_scan_status(self, client):
        created = _create_service(client)
        resp = client.get(f"/services/{created['id']}/scan-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service_id"] == created["id"]
        assert "scan_status" in data

    def test_get_scan_status_not_found(self, client):
        resp = client.get("/services/999/scan-status")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestMarkdownEndpoints
# ---------------------------------------------------------------------------


class TestMarkdownEndpoints:
    def test_get_service_markdown(self, client):
        created = _create_service(client, name="My Markdown Service")
        resp = client.get(f"/services/{created['id']}/markdown")
        assert resp.status_code == 200
        assert "text/markdown" in resp.headers["content-type"]
        assert "My Markdown Service" in resp.text

    def test_get_all_services_markdown(self, client):
        _create_service(client, name="Service Alpha", url="http://alpha.com/swagger.json")
        _create_service(client, name="Service Beta", url="http://beta.com/swagger.json")
        resp = client.get("/services/markdown/all")
        assert resp.status_code == 200
        assert "Service Alpha" in resp.text
        assert "Service Beta" in resp.text

    def test_get_service_markdown_not_found(self, client):
        resp = client.get("/services/999/markdown")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestScanAll
# ---------------------------------------------------------------------------


class TestScanAll:
    def test_scan_all_no_services(self, client, mock_agent):
        resp = client.post("/services/scan")
        assert resp.status_code == 202
        data = resp.json()
        assert data["service_count"] == 0
        mock_agent.assert_not_called()

    def test_scan_all_triggers_each_service(self, client, mock_agent):
        _create_service(client, name="Service A", url="http://a.com/swagger.json")
        _create_service(client, name="Service B", url="http://b.com/swagger.json")
        resp = client.post("/services/scan")
        assert resp.status_code == 202
        data = resp.json()
        assert data["service_count"] == 2
        assert "2" in data["message"]
        assert mock_agent.call_count == 2

    def test_scan_all_sets_status_scanning(self, client, mock_agent):
        created = _create_service(client)
        client.post("/services/scan")
        status_resp = client.get(f"/services/{created['id']}/scan-status")
        assert status_resp.json()["scan_status"] == "scanning"


# ---------------------------------------------------------------------------
# TestForceScan
# ---------------------------------------------------------------------------


class TestForceScan:
    def test_force_scan_single_service(self, client, mock_agent):
        created = _create_service(client)
        resp = client.post(f"/services/{created['id']}/scan/force")
        assert resp.status_code == 202
        data = resp.json()
        assert data["service_id"] == created["id"]
        assert "force" in data["message"].lower()

    def test_force_scan_single_service_not_found(self, client):
        resp = client.post("/services/999/scan/force")
        assert resp.status_code == 404

    def test_force_scan_passes_force_true_to_background(self, client):
        """Force scan endpoint must call _run_scan_background with force=True."""
        created = _create_service(client)
        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "app.api._run_scan_background"
        ) as mock_bg:
            client.post(f"/services/{created['id']}/scan/force")
            assert mock_bg.called
            call_args = mock_bg.call_args
            # force=True must be passed (positional or keyword)
            assert True in call_args.args or call_args.kwargs.get("force") is True

    def test_force_scan_all(self, client, mock_agent):
        _create_service(client, name="Service A", url="http://a.com/swagger.json")
        _create_service(client, name="Service B", url="http://b.com/swagger.json")
        resp = client.post("/services/scan/force")
        assert resp.status_code == 202
        data = resp.json()
        assert data["service_count"] == 2
        assert "force" in data["message"].lower()
        assert mock_agent.call_count == 2

    def test_force_scan_all_no_services(self, client, mock_agent):
        resp = client.post("/services/scan/force")
        assert resp.status_code == 202
        data = resp.json()
        assert data["service_count"] == 0
        mock_agent.assert_not_called()

    def test_force_scan_sets_status_scanning(self, client, mock_agent):
        created = _create_service(client)
        client.post(f"/services/{created['id']}/scan/force")
        status_resp = client.get(f"/services/{created['id']}/scan-status")
        assert status_resp.json()["scan_status"] == "scanning"


# ---------------------------------------------------------------------------
# TestHealthEndpoint
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_health_check(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
