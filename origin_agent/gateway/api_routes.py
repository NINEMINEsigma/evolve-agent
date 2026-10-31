"""Reject duplicate protocol registrations without inferring URL precedence."""

from fastapi import APIRouter
from fastapi.routing import APIRoute, APIWebSocketRoute


def validate_api_routes(router: APIRouter) -> None:
    """Check exact path/method duplicates; template overlap remains explicit."""
    http_routes: dict[tuple[str, str], str] = {}
    websocket_routes: dict[str, str] = {}
    for route in router.routes:
        if isinstance(route, APIRoute):
            for method in sorted(route.methods):
                key = (method, route.path)
                if key in http_routes:
                    raise ValueError(
                        f"Duplicate HTTP route {method} {route.path}: "
                        f"{http_routes[key]} and {route.name}"
                    )
                http_routes[key] = route.name
        elif isinstance(route, APIWebSocketRoute):
            if route.path in websocket_routes:
                raise ValueError(
                    f"Duplicate WebSocket route {route.path}: "
                    f"{websocket_routes[route.path]} and {route.name}"
                )
            websocket_routes[route.path] = route.name
        else:
            raise TypeError(f"Unsupported Gateway API route type: {type(route).__name__}")
