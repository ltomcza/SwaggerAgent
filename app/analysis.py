from __future__ import annotations

import json
import re

# Public endpoint patterns that are almost certainly unauthenticated
_PUBLIC_PATH_RE = re.compile(
    r"^/(health|status|version|ping|swagger|openapi|docs|redoc|metrics)(/.*)?$",
    re.IGNORECASE,
)

# Login entry-point patterns — public (no auth required to call)
_LOGIN_PATH_RE = re.compile(
    r"/(login|signin|sign-in|token|oauth/token|auth/token)(/.*)?$",
    re.IGNORECASE,
)

# Logout patterns — caller must be authenticated
_LOGOUT_PATH_RE = re.compile(
    r"/(logout|signout|sign-out)(/.*)?$",
    re.IGNORECASE,
)

# Path patterns that strongly suggest authentication is required
_PRIVATE_PATH_RE = re.compile(
    r"/(admin|private|me|account|profile|settings|dashboard)(/?|/.*)?$",
    re.IGNORECASE,
)

# Parameter names that indicate an auth token is passed
_AUTH_PARAM_NAMES = frozenset({"authorization", "api_key", "x-api-key", "token", "apikey"})

# HTTP methods that mutate state
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def compute_auth_type(security_schemes: dict) -> str:
    """Derive the primary authentication type from OpenAPI security scheme definitions.

    Maps scheme types to one of: "none", "apiKey", "http/bearer", "http/basic",
    "oauth2", "openIdConnect", "mixed".
    """
    if not security_schemes:
        return "none"

    canonical: set[str] = set()
    for scheme in security_schemes.values():
        if not isinstance(scheme, dict):
            continue
        scheme_type = scheme.get("type", "")
        if scheme_type == "apiKey":
            canonical.add("apiKey")
        elif scheme_type == "http":
            http_scheme = (scheme.get("scheme") or "").lower()
            if http_scheme == "bearer":
                canonical.add("http/bearer")
            elif http_scheme == "basic":
                canonical.add("http/basic")
            else:
                canonical.add("http/bearer")  # treat unknown http as bearer
        elif scheme_type == "oauth2":
            canonical.add("oauth2")
        elif scheme_type == "openIdConnect":
            canonical.add("openIdConnect")

    if len(canonical) == 0:
        return "none"
    if len(canonical) == 1:
        return next(iter(canonical))
    return "mixed"


def compute_auth_required(
    security_json: str | None,
    path: str,
    method: str,
    parameters_json: str | None = None,
) -> bool | None:
    """Deterministically infer whether an endpoint requires authentication.

    Priority order:
    1. Explicit security array in the spec (non-empty → True, empty [] → False)
    2. Auth-named parameters in parameters_json (→ True)
    3. Public path patterns (health, docs, …) → False
    4. Login path patterns (login, signin, …) → False
    5. Logout path patterns → True
    6. Private path patterns (admin, /me, …) → True
    7. Any mutating method (POST/PUT/PATCH/DELETE) → True
    8. Unknown → None
    """
    # 1. Check explicit security declaration
    if security_json is not None:
        try:
            security = json.loads(security_json)
            if isinstance(security, list):
                if len(security) > 0:
                    return True
                return False  # explicit empty array means "no auth"
        except (json.JSONDecodeError, ValueError):
            pass

    # 2. Check for auth-named parameters
    if parameters_json:
        try:
            params = json.loads(parameters_json)
            if isinstance(params, list):
                for p in params:
                    if isinstance(p, dict):
                        name = (p.get("name") or "").lower()
                        if name in _AUTH_PARAM_NAMES:
                            return True
        except (json.JSONDecodeError, ValueError):
            pass

    # 3. Public path patterns
    if _PUBLIC_PATH_RE.match(path):
        return False

    # 4. Login endpoints are public (they ARE the authentication entry point)
    if _LOGIN_PATH_RE.search(path):
        return False

    # 5. Logout requires an active session
    if _LOGOUT_PATH_RE.search(path):
        return True

    # 6. Private path patterns
    if _PRIVATE_PATH_RE.search(path):
        return True

    # 7. Any mutating method almost always requires auth
    if method.upper() in _MUTATING_METHODS:
        return True

    # 8. Path with a path parameter (e.g. /orders/{id}) accesses a specific resource
    if "{" in path:
        return True

    # 9. Unknown
    return None
