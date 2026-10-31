"""HTTP-only admission and transport boundaries; unexpected errors propagate."""

from __future__ import annotations

import json
from collections.abc import Callable, Coroutine, Mapping
from typing import Any, NoReturn

from fastapi import HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

from entity.constant import GATEWAY_BUSINESS_HTTP_PREFIXES, GatewayErrorCode
from entity.error import ApplicationStoppingError
from entity.puretype import HTTPErrorDetail
from gateway.lifecycle import GatewayAdmission


def business_http_error(
    status_code: int,
    code: str,
    message: str,
    *,
    details: Mapping[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> HTTPException:
    extra = dict(details) if details is not None else {}
    if "code" in extra or "message" in extra:
        raise ValueError("Business error details cannot replace code or message")
    detail = HTTPErrorDetail(code=code, message=message, **extra)
    payload = detail.model_dump(mode="json", exclude_none=True)
    # 业务附加字段的显式null（例如current_version）具有协议含义。
    payload.update({key: None for key, value in extra.items() if value is None})
    return HTTPException(status_code=status_code, detail=payload, headers=headers)


def require_business_http(admission: GatewayAdmission) -> None:
    try:
        with admission.admit_business():
            pass
    except ApplicationStoppingError as exc:
        raise business_http_error(
            503, GatewayErrorCode.APPLICATION_STOPPING,
            "Application is shutting down",
        ) from exc


class GatewayAdmissionMiddleware:
    def __init__(self, app: ASGIApp, admission: GatewayAdmission) -> None:
        self._app = app
        self._admission = admission

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope["path"]
            if any(path == prefix or path.startswith(prefix + "/")
                   for prefix in GATEWAY_BUSINESS_HTTP_PREFIXES):
                try:
                    require_business_http(self._admission)
                except HTTPException as exc:
                    detail = HTTPErrorDetail.model_validate(exc.detail)
                    payload = detail.model_dump(mode="json")
                    payload["request_accepted"] = False
                    await JSONResponse({"detail": payload}, status_code=503)(scope, receive, send)
                    return
        await self._app(scope, receive, send)


class GatewayJSONRequest(Request):
    async def json(self) -> Any:
        try:
            return await super().json()
        except UnicodeDecodeError as exc:
            # FastAPI原生JSONDecodeError边界负责产生标准422列表。
            raise json.JSONDecodeError("Invalid JSON encoding", "", 0) from exc


class GatewayAPIRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def route(request: Request) -> Response:
            converted = GatewayJSONRequest(request.scope, request.receive)
            try:
                return await original(converted)
            except ApplicationStoppingError as exc:
                return await handle_application_stopping(converted, exc)

        return route


async def handle_http_exception(request: Request, exc: Exception) -> Response:
    # 框架回调契约接收Exception；按注册的异常族收窄，不转换其他错误。
    if not isinstance(exc, StarletteHTTPException):
        raise exc
    if exc.status_code in (204, 304) or (
        exc.status_code == 422 and isinstance(exc.detail, list)
    ):
        return await http_exception_handler(request, exc)
    if isinstance(exc.detail, dict):
        detail = HTTPErrorDetail.model_validate(exc.detail).model_dump(mode="json")
    elif isinstance(exc.detail, str):
        code = {
            404: GatewayErrorCode.ROUTE_NOT_FOUND,
            405: GatewayErrorCode.METHOD_NOT_ALLOWED,
        }.get(exc.status_code, GatewayErrorCode.HTTP_ERROR)
        detail = HTTPErrorDetail(code=code, message=exc.detail).model_dump(mode="json")
    else:
        raise TypeError("HTTP exception detail must be structured business data or text")
    return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=exc.headers)


async def handle_application_stopping(
    request: Request, exc: ApplicationStoppingError,
) -> JSONResponse:
    # 在途停止可能晚于业务提交，不能添加request_accepted=false。
    error = business_http_error(
        503, GatewayErrorCode.APPLICATION_STOPPING, "Application is shutting down",
    )
    return JSONResponse({"detail": error.detail}, status_code=error.status_code)


def raise_request_validation(
    message: str, *, location: tuple[str | int, ...],
) -> NoReturn:
    raise RequestValidationError([{
        "type": "value_error", "loc": location, "msg": message,
    }])
