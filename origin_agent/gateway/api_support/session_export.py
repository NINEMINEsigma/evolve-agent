"""Bounded export HTTP requests with ownership of real work preserved."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError

from entity.constant import (
    GATEWAY_EXPORT_DISCONNECT_POLL_SECONDS, GatewayErrorCode,
    SESSION_EXPORT_REQUEST_TIMEOUT_SECONDS,
)
from gateway.http_boundary import business_http_error, require_business_http
from interface.gateway_system import IGatewaySystem

T = TypeVar("T")
TModel = TypeVar("TModel", bound=BaseModel)


async def run_export_http(
    request: Request,
    gateway: IGatewaySystem,
    factory: Callable[[], Coroutine[Any, Any, T]],
    name: str,
) -> T:
    work = asyncio.create_task(gateway.task_owner.run_request(
        factory, name=name, admission=gateway.admission.admit_business,
        cancel_timeout=SESSION_EXPORT_REQUEST_TIMEOUT_SECONDS,
    ))

    async def watch_disconnect() -> None:
        while not await request.is_disconnected():
            await asyncio.sleep(GATEWAY_EXPORT_DISCONNECT_POLL_SECONDS)

    disconnected = asyncio.create_task(watch_disconnect())
    try:
        done, _ = await asyncio.wait({work, disconnected}, return_when=asyncio.FIRST_COMPLETED)
        if work in done:
            return await work
        await disconnected
        work.cancel()
        try:
            await work
        except asyncio.CancelledError:
            pass
        raise business_http_error(
            499, GatewayErrorCode.EXPORT_CANCELLED, "Export client disconnected",
        )
    finally:
        if not disconnected.done():
            disconnected.cancel()
        try:
            await disconnected
        except asyncio.CancelledError:
            pass
        if not work.done():
            work.cancel()
            try:
                await work
            except asyncio.CancelledError:
                pass


async def read_export_body(
    request: Request, gateway: IGatewaySystem, maximum: int,
) -> bytes:
    require_business_http(gateway.admission)
    pieces: list[bytes] = []
    size = 0
    try:
        async with asyncio.timeout(SESSION_EXPORT_REQUEST_TIMEOUT_SECONDS):
            async for piece in request.stream():
                size += len(piece)
                if size > maximum:
                    raise business_http_error(
                        413, GatewayErrorCode.EXPORT_LIMIT, "Export request body is too large",
                    )
                pieces.append(piece)
    except TimeoutError as exc:
        raise business_http_error(
            408, GatewayErrorCode.EXPORT_TIMEOUT, "Export request body timed out",
        ) from exc
    return b"".join(pieces)


def parse_export_model(body: bytes, model_type: type[TModel]) -> TModel:
    try:
        return model_type.model_validate_json(body)
    except ValidationError as exc:
        errors: list[dict[str, Any]] = []
        for item in exc.errors(include_input=False, include_context=False, include_url=False):
            if item["type"] == "json_invalid":
                errors.append({
                    "type": "json_invalid", "loc": ("body", 0),
                    "msg": "Invalid JSON request body",
                })
            else:
                errors.append({
                    "type": item["type"], "loc": ("body", *item["loc"]),
                    "msg": item["msg"],
                })
        raise RequestValidationError(errors) from exc
