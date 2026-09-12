from __future__ import annotations

import json
from functools import cache
from pathlib import Path

_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH"}
_ACCESS = {"public", "authenticated"}


@cache
def routes() -> tuple[dict[str, str], ...]:
    value = json.loads(Path(__file__).with_name("api-contract.json").read_text())
    if not isinstance(value, dict) or value.get("version") != 1:
        raise RuntimeError("Unsupported API contract")
    raw_routes = value.get("routes")
    if not isinstance(raw_routes, list):
        raise TypeError("API contract routes must be a list")
    result: list[dict[str, str]] = []
    ids: set[str] = set()
    keys: set[str] = set()
    for route in raw_routes:
        if not isinstance(route, dict):
            raise TypeError("API contract route must be an object")
        normalized = {
            key: route.get(key)
            for key in ("id", "method", "path", "access", "handler")
        }
        if not all(isinstance(item, str) and item for item in normalized.values()):
            raise RuntimeError("API contract route fields must be non-empty strings")
        if normalized["method"] not in _METHODS or normalized["access"] not in _ACCESS:
            raise RuntimeError("API contract route has an unsupported method or access mode")
        route_id = normalized["id"]
        route_key = f"{normalized['method']} {normalized['path']}"
        if route_id in ids or route_key in keys:
            raise RuntimeError("API contract route IDs and keys must be unique")
        ids.add(route_id)
        keys.add(route_key)
        result.append(normalized)
    return tuple(result)


def authenticated_routes() -> tuple[dict[str, str], ...]:
    return tuple(route for route in routes() if route["access"] == "authenticated")


def authenticated_route_keys() -> frozenset[str]:
    return frozenset(
        f"{route['method']} {route['path']}" for route in authenticated_routes()
    )
