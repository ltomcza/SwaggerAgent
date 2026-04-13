import json
import pytest

from app.analysis import compute_auth_required, compute_auth_type


# ---------------------------------------------------------------------------
# compute_auth_type
# ---------------------------------------------------------------------------

class TestComputeAuthType:
    def test_no_schemes_returns_none(self):
        assert compute_auth_type({}) == "none"

    def test_api_key_scheme(self):
        schemes = {"apiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}}
        assert compute_auth_type(schemes) == "apiKey"

    def test_http_bearer(self):
        schemes = {"bearerAuth": {"type": "http", "scheme": "bearer"}}
        assert compute_auth_type(schemes) == "http/bearer"

    def test_http_basic(self):
        schemes = {"basicAuth": {"type": "http", "scheme": "basic"}}
        assert compute_auth_type(schemes) == "http/basic"

    def test_oauth2(self):
        schemes = {"oauth2": {"type": "oauth2", "flows": {}}}
        assert compute_auth_type(schemes) == "oauth2"

    def test_open_id_connect(self):
        schemes = {"oidc": {"type": "openIdConnect", "openIdConnectUrl": "https://example.com/.well-known/openid-configuration"}}
        assert compute_auth_type(schemes) == "openIdConnect"

    def test_mixed_two_distinct_types(self):
        schemes = {
            "apiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
            "bearer": {"type": "http", "scheme": "bearer"},
        }
        assert compute_auth_type(schemes) == "mixed"

    def test_two_same_type_not_mixed(self):
        # Two apiKey schemes of the same canonical type → single type, not "mixed"
        schemes = {
            "key1": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
            "key2": {"type": "apiKey", "in": "query", "name": "api_key"},
        }
        assert compute_auth_type(schemes) == "apiKey"

    def test_non_dict_scheme_ignored(self):
        schemes = {"broken": "not-a-dict"}
        assert compute_auth_type(schemes) == "none"


# ---------------------------------------------------------------------------
# compute_auth_required
# ---------------------------------------------------------------------------

class TestComputeAuthRequired:
    # --- Explicit security array ---

    def test_explicit_nonempty_security_returns_true(self):
        security = json.dumps([{"bearerAuth": []}])
        assert compute_auth_required(security, "/users", "GET") is True

    def test_explicit_empty_security_returns_false(self):
        security = json.dumps([])
        assert compute_auth_required(security, "/users", "GET") is False

    def test_invalid_security_json_falls_through(self):
        # Falls through to pattern matching; /health → False
        result = compute_auth_required("not-json", "/health", "GET")
        assert result is False

    # --- Auth-named parameters ---

    def test_authorization_param_returns_true(self):
        params = json.dumps([{"name": "Authorization", "in": "header"}])
        assert compute_auth_required(None, "/data", "GET", params) is True

    def test_api_key_param_returns_true(self):
        params = json.dumps([{"name": "api_key", "in": "query"}])
        assert compute_auth_required(None, "/data", "GET", params) is True

    def test_x_api_key_param_returns_true(self):
        params = json.dumps([{"name": "x-api-key", "in": "header"}])
        assert compute_auth_required(None, "/data", "GET", params) is True

    def test_unrelated_param_falls_through(self):
        params = json.dumps([{"name": "limit", "in": "query"}])
        # No security JSON, no auth param, /health path → False
        result = compute_auth_required(None, "/health", "GET", params)
        assert result is False

    # --- Public path patterns ---

    def test_get_health_returns_false(self):
        assert compute_auth_required(None, "/health", "GET") is False

    def test_get_status_returns_false(self):
        assert compute_auth_required(None, "/status", "GET") is False

    def test_get_version_returns_false(self):
        assert compute_auth_required(None, "/version", "GET") is False

    def test_get_swagger_returns_false(self):
        assert compute_auth_required(None, "/swagger", "GET") is False

    def test_get_docs_returns_false(self):
        assert compute_auth_required(None, "/docs", "GET") is False

    def test_get_metrics_returns_false(self):
        assert compute_auth_required(None, "/metrics", "GET") is False

    # --- Private path patterns ---

    def test_admin_path_returns_true(self):
        assert compute_auth_required(None, "/admin/users", "GET") is True

    def test_private_path_returns_true(self):
        assert compute_auth_required(None, "/private/data", "GET") is True

    def test_me_path_returns_true(self):
        assert compute_auth_required(None, "/me", "GET") is True

    def test_account_path_returns_true(self):
        assert compute_auth_required(None, "/account/settings", "GET") is True

    # --- Mutating methods with path params ---

    def test_delete_with_path_param_returns_true(self):
        assert compute_auth_required(None, "/users/{id}", "DELETE") is True

    def test_put_with_path_param_returns_true(self):
        assert compute_auth_required(None, "/items/{item_id}", "PUT") is True

    def test_post_with_path_param_returns_true(self):
        assert compute_auth_required(None, "/orders/{id}/cancel", "POST") is True

    def test_get_with_path_param_no_private_pattern_returns_true(self):
        # GET on a parameterised path (specific resource) → auth required
        assert compute_auth_required(None, "/users/{id}", "GET") is True

    # --- Login path patterns ---

    def test_login_path_returns_false(self):
        assert compute_auth_required(None, "/user/login", "GET") is False

    def test_signin_path_returns_false(self):
        assert compute_auth_required(None, "/signin", "POST") is False

    def test_oauth_token_path_returns_false(self):
        assert compute_auth_required(None, "/oauth/token", "POST") is False

    def test_auth_token_path_returns_false(self):
        assert compute_auth_required(None, "/auth/token", "POST") is False

    # --- Logout path patterns ---

    def test_logout_path_returns_true(self):
        assert compute_auth_required(None, "/user/logout", "GET") is True

    def test_signout_path_returns_true(self):
        assert compute_auth_required(None, "/signout", "GET") is True

    # --- All mutating methods default to True ---

    def test_post_without_path_param_returns_true(self):
        assert compute_auth_required(None, "/store/order", "POST") is True

    def test_post_to_user_path_returns_true(self):
        assert compute_auth_required(None, "/user", "POST") is True

    def test_post_to_list_path_returns_true(self):
        assert compute_auth_required(None, "/user/createWithList", "POST") is True

    def test_patch_without_path_param_returns_true(self):
        assert compute_auth_required(None, "/settings", "PATCH") is True

    # --- Unknown / fallback ---

    def test_unknown_path_returns_none(self):
        assert compute_auth_required(None, "/some/random/path", "GET") is None
