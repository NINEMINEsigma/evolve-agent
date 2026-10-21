"""基于 FastAPI 的静态路由表与运行实例工厂。

路由定义为模块级 ``APIRouter``，只含导入期协议元数据；``build_router_app()``
由 GatewaySystem 唤醒时创建唯一运行 ``FastAPI`` 实例并计算构建哈希。

提供：
  - ``GET /health`` — 存活与接收状态检查
  - ``WS /ws/chat`` — 聊天 WebSocket
  - ``build_router_app()`` — 唯一运行实例工厂

聊天连接注册到 FrontendSink；``stream_delta`` / ``stream_done`` 由事件出口
直接序列化稳定模型并发送，本模块不再维护字符串事件转发回调。
"""

from __future__ import annotations

from interface.approval_system import IApprovalSystem
from interface.agentspace_service import IAgentspaceService
from interface.cron_router import ICronRouter
from interface.dynamic_endpoint_system import IDynamicEndpointSystem
from interface.frontend_sink import IFrontendSink
from interface.gateway_system import IGatewaySystem
from interface.llm_profile_store import ILLMProfileStore
from interface.runtime_system import IRuntimeSystem
from interface.sandbox import ISandbox
from interface.session_manager import ISessionManager
from interface.session_metadata_service import ISessionMetadataService
from interface.shell_manager import IShellManager
from interface.subagent_orchestrator import ISubAgentOrchestrator

import hashlib
import json
import logging
import re
import sys
import uuid
from pathlib import Path
from typing import * # type: ignore
from urllib.parse import parse_qs, quote, urlsplit

from pydantic import BaseModel, ValidationError
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, WebSocketException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState
from system.session_file_changes import SessionFileChangeStore, SessionFileChangesBusyError
from system.lifecycle import ApplicationStoppingError, LifecycleFailure

from .chat import Message, MessageType
from .message_router import MessageRouter
from .agentspace_event_bridge import (
    AgentspaceConnectionClosed,
    attach_agentspace_events,
    build_initial_agentspace_events,
    detach_agentspace_events,
    is_connection_termination,
    requires_connection_eviction,
)
from datetime import datetime, timezone
from entity.constant import (
    CRON_STDOUT_PREVIEW_MAX_LENGTH,
    SUBPROCESS_TIMEOUT_DEFAULT,
    UPLOAD_FILENAME_TIME_FORMAT,
    USER_CHARACTER_NAME,
    UPLOADS_DIR_NAME,
    UPLOADS_WS_PREFIX,
    STATIC_FILE_HTTP_PREFIX,
    DOWNLOADS_HTTP_PREFIX,
    DIR_ZIP_HTTP_PREFIX,
    DIR_ZIP_MAX_TOTAL_BYTES,
    SYSTEM_CHARACTER_NAME,
    AGENTSPACE_SSE_HEARTBEAT_SECONDS,
    LOCAL_FONT_HTTP_PREFIX,
    LOCAL_FONT_MIME_TYPES,
    SESSION_HISTORY_PAGE_DEFAULT_LIMIT,
    SESSION_HISTORY_PAGE_MAX_LIMIT,
    SESSION_FILE_CHANGES_DEFAULT_LIMIT,
    SESSION_FILE_CHANGES_MAX_LIMIT,
    SESSION_MEDIA_DEFAULT_OFFSET,
    SESSION_MEDIA_DEFAULT_LIMIT,
    SESSION_MEDIA_MAX_LIMIT,
    SESSION_MEDIA_ID_PATTERN,
    WEBSOCKET_CLOSE_SESSION_DELETED,
    VISUAL_RAW_PARAM,
    VISUAL_PROBE_PARAM,
    VISUAL_SID_PARAM,
    VISUAL_KIND_PARAM,
    VISUAL_QUERY_ENABLED,
    VISUAL_VERSION_HEADER,
)
from entity.puretype import (
    SessionMediaListResponse,
    SessionMediaUpdateRequest,
    SessionMediaUpdateResponse,
    SessionStatus,
    SessionVariablePoolResponse,
    SessionTabCapabilities,
    SessionFileChangesSummary,
    SessionFileChangesPage,
    ClientInfo,
    CharacterAvatarsResponse,
    CharacterProfilesResponse,
    SessionTagsUpdateRequest,
    SessionTitleUpdateRequest,
    SessionMessageEditRequest,
    SessionRegenerateRequest,
    SessionMergeRequest,
    ConfirmResponseRequest,
    AskResponseRequest,
    DynamicEndpointRequest,
    AgentspaceOperationRequest,
    MessageContent,
    LLMProfile,
    LLMProfilePayload,
    LLMProfileUpdateRequest,
    LLMProfileDeleteRequest,
    LLMProfileMutationResponse,
    LLMProfileDeleteResult,
    SessionLlmProfileState,
    MetadataProfileUpdateRequest,
    MetadataProfileMutationResponse,
    ToolchainSummaryProfileUpdateRequest,
    ToolchainSummaryProfileMutationResponse,
    ModalityProfileUpdateRequest,
    ModalityProfileMutationResponse,
    ModalityProfileState,
    ModalityProfileStates,
    AgentspaceWriteRequest,
    AgentspacePathRequest,
    AgentspaceRenameRequest,
    AgentspaceEvent,
    DynamicSandboxSpace,
    DynamicSandboxSpaceCreateRequest,
    DynamicSandboxSpaceUpdateRequest,
    SessionRuntimeStatus,
    SessionMessageEditResult,
    SessionMessageDeletionResult,
    SessionRegenerateResult,
    SessionToolResources,
    MainSessionActivitySource,
    SessionVisualKind,
    SubAgentSnapshotResponse,
    SubAgentUpdate,
)
from entity.messages import ImageBlock, VideoBlock
from entry.history_media import (
    HistoryMediaConflictError,
    HistoryMediaNotFoundError,
    HistoryMediaPreviewError,
    decode_media_preview,
)
from system.llm_profile_store import ProfileConflictError, ProfileNotFoundError
from system.session_metadata import MetadataGenerationError, MetadataProfileUnavailableError
from system.agentspace import AgentspaceError
from system.sandbox import (
    DynamicSandboxConflictError,
    DynamicSandboxInputError,
    DynamicSandboxNotFoundError,
    SandboxError,
)

if TYPE_CHECKING:
    from system.application import Application
    from entry.parent_agent_loop import ParentAgentLoop
    from entry.base_agent_loop import IMainSessionLoop

logger = logging.getLogger(__name__)


def _get_sm() -> ISessionManager|None:
    """返回 Application 的 SessionManager。"""
    from system.application import Application
    return Application.current().get_system(ISessionManager)


def _get_loop(session_id: str):
    """返回指定 session 的 BaseAgentLoop（可能是 ParentAgentLoop 或 MultiAgentLoop）。"""
    sm = _get_sm()
    return sm.get_loop(session_id) if sm else None


def _get_ws(session_id: str):
    """返回指定 session 的 WebSocket sink。"""
    from system.application import Application
    sink = Application.current().get_system(IFrontendSink)
    return sink.get_ws(session_id)


def _agentspace_root() -> Path:
    """文件上传目标目录（ws: 命名空间根）的唯一来源。"""
    from system.application import Application
    return Application.current().get_system(IRuntimeSystem).context.agentspace


def _gateway():
    """当前唯一 GatewaySystem；路由仅在装配完成后可达。"""
    from system.application import Application
    return Application.current().get_system(IGatewaySystem)


def _admit_business_http() -> None:
    """新业务 HTTP 输入的同步准入；STOPPING/未开放时返回 503。"""
    from system.lifecycle import ApplicationStoppingError
    try:
        with _gateway().admission.admit_business():
            pass
    except ApplicationStoppingError as exc:
        raise HTTPException(status_code=503, detail="Application is shutting down") from exc


async def _send_optional_ws_message(ws: WebSocket, message: Message) -> None:
    """HTTP 操作的附带通知允许客户端断线；编码和内部错误直接传播。"""
    payload = message.model_dump_json(exclude_none=True)
    if ws.application_state is WebSocketState.DISCONNECTED:
        return
    try:
        await ws.send_text(payload)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected during notification | session=%s", message.session_id)


async def push_subagent_update(
    parent_session_id: str,
    update: SubAgentUpdate,
) -> None:
    """将稳定类型的子Agent状态更新序列化后推送到前端 WebSocket。

    ``removed`` 在传输边界映射为历史协议字段 ``_removed``；其余字段
    沿用稳定模型的字段名。
    """
    ws = _get_ws(parent_session_id)
    if ws is None:
        return
    await _send_optional_ws_message(
        ws,
        Message(
            type=MessageType.SUBAGENT_UPDATE,
            session_id=parent_session_id,
            result=json.dumps({
                **update.model_dump(mode="json", exclude={"removed"}),
                "_removed": update.removed,
            }, ensure_ascii=False),
        ),
    )


# ---------------------------------------------------------------------------
# FastAPI 静态路由表
# ---------------------------------------------------------------------------


import asyncio


router: APIRouter = APIRouter()

# ---------------------------------------------------------------------------
# 构建前端产物发现
# ---------------------------------------------------------------------------

_FRONTEND_DIST: Path = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def _compute_build_hash() -> str:
    """计算构建后 index.html 的哈希值，用于缓存破坏检测。"""
    idx: Path = _FRONTEND_DIST / "index.html"
    if not idx.exists():
        return ""
    return hashlib.md5(idx.read_bytes()).hexdigest()[:12]


def build_router_app() -> FastAPI:
    """由 GatewaySystem 唤醒时创建唯一运行实例并挂载静态资源。"""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        yield

    application = FastAPI(title="Evolve Agent Gateway", lifespan=_lifespan)
    application.include_router(router)
    application.state.build_hash = _compute_build_hash()
    if _FRONTEND_DIST.is_dir():
        assets_dir: Path = _FRONTEND_DIST / "assets"
        if assets_dir.is_dir():
            application.mount(
                "/assets", StaticFiles(directory=str(assets_dir)), name="assets",
            )
        logger.info(
            "Frontend dist found at %s (build=%s)",
            _FRONTEND_DIST, application.state.build_hash or "unknown",
        )
    return application

# ---------------------------------------------------------------------------
# Agentspace 用户变更摘要兼容入口
# ---------------------------------------------------------------------------


def _flush_pending_changes() -> str | None:
    """供现有 agentspace_changes_hook 调用，委托给唯一业务服务。"""
    from system.application import Application
    return Application.current().get_system(IAgentspaceService).flush_pending_changes()


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


_NO_CACHE: dict[str, str] = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}

TRequest = TypeVar("TRequest", bound=BaseModel)


async def _parse_request_model(
    req: Request,
    model_type: type[TRequest],
) -> TRequest:
    """在 HTTP 入站边界把 JSON 解析为稳定请求模型。"""
    try:
        payload = await req.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    try:
        return model_type.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _parse_dynamic_endpoint_request(
    req: Request,
) -> tuple[DynamicEndpointRequest | None, str | None]:
    """解析动态端点请求，并把 block 校验错误映射为既有 400 文本。"""
    try:
        payload = await req.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, "invalid JSON body"
    try:
        request = DynamicEndpointRequest.model_validate(payload)
    except ValidationError:
        raw_content = payload.get("content") if isinstance(payload, dict) else None
        if isinstance(raw_content, list):
            from entry.agent_support.multimodal import validate_content_blocks
            error = validate_content_blocks(raw_content)
            return None, error or "invalid content blocks"
        return None, "'content' must be a string or an array of content blocks"
    if isinstance(request.content, list):
        from entry.agent_support.multimodal import validate_content_blocks
        error = validate_content_blocks(payload.get("content", []))
        if error is not None:
            return None, error
    return request, None


# 文本类 MIME 需要追加 charset=utf-8
_TEXT_MIME_PREFIXES = ("text/", "application/json", "application/xml", "application/javascript")
_TEXT_MIME_EXTS = {".html", ".htm", ".md", ".txt", ".log", ".json", ".csv", ".py", ".js", ".css",
                   ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".svg"}


def _guess_media_type_with_charset(path: Path) -> str:
    """根据扩展名猜测 MIME 类型，文本类自动追加 charset=utf-8。"""
    import mimetypes
    ext = path.suffix.lower()
    mime, _ = mimetypes.guess_type(str(path))
    if mime is None:
        mime = "application/octet-stream"
    if mime.startswith(_TEXT_MIME_PREFIXES) or ext in _TEXT_MIME_EXTS:
        if "charset" not in mime:
            mime = f"{mime}; charset=utf-8"
    return mime


@router.get("/")
async def index():
    """返回构建后的 React 前端，未构建时返回 HTTP 500 错误。"""
    index_html: Path = _FRONTEND_DIST / "index.html"
    if not index_html.exists():
        logger.error("Frontend not built: %s missing", index_html)
        return HTMLResponse(
            "Frontend not built. Please run the build first.",
            status_code=500,
        )
    return HTMLResponse(
        index_html.read_text(encoding="utf-8"),
        headers=_NO_CACHE,
    )


@router.get("/health")
async def health():
    """存活检查只报告状态，不创建会话或 Loop。"""
    serving = _gateway().admission.is_serving()
    payload: dict[str, object] = {"sessions": _get_sm().count, "serving": serving}
    if serving:
        payload["status"] = "ok"
        return payload
    return JSONResponse(
        {"status": "shutting_down", **payload},
        status_code=503,
    )


@router.get("/api/sessions")
async def list_sessions():
    """返回所有活跃 session 及其元数据。"""
    return {"sessions": _get_sm().get_all()}


@router.get("/api/tags")
async def list_tags():
    """返回全局已有标签列表。"""
    return {"tags": _get_sm().get_all_tags()}


@router.put("/api/sessions/{session_id}/tags")
async def update_session_tags(session_id: str, req: Request):
    """更新 session 的标签列表。"""
    request = await _parse_request_model(req, SessionTagsUpdateRequest)
    tags: list[str] = [str(tag).strip() for tag in request.tags]
    valid = _get_sm().set_session_tags(session_id, tags)
    logger.info("Update tags | session=%s tags=%s", session_id, valid)
    return {"updated": True, "session_id": session_id, "tags": valid}


@router.get("/api/sessions/{session_id}/tool-resources")
async def get_session_tool_resources(session_id: str) -> SessionToolResources:
    """返回 session 的可恢复工具副作用资源快照。"""
    from system.application import Application
    endpoints = Application.current().get_system(IDynamicEndpointSystem).list_session_endpoints(session_id)
    loop = _get_loop(session_id)
    if loop is None:
        return SessionToolResources(
            session_id=session_id,
            dynamic_endpoints=endpoints,
        )
    resources = loop.loop.get_tool_resources().model_copy(
        update={"dynamic_endpoints": endpoints}
    )
    return resources


@router.get("/api/sessions/{session_id}/file-changes/summary", response_model=SessionFileChangesSummary)
async def get_session_file_changes_summary(session_id: str, response: Response) -> SessionFileChangesSummary:
    from starlette.concurrency import run_in_threadpool
    from system.application import Application

    _admit_business_http()
    manager = _get_sm()
    if not manager.exists(session_id) or manager.is_session_deleting(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    store = Application.current().get_system(IAgentspaceService).file_changes
    try:
        result = await run_in_threadpool(store.get_summary, session_id)
    except FileNotFoundError as exc:
        if not manager.exists(session_id) or manager.is_session_deleting(session_id):
            raise HTTPException(status_code=404, detail="Session not found") from exc
        raise
    if not manager.exists(session_id) or manager.is_session_deleting(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/api/sessions/{session_id}/file-changes", response_model=SessionFileChangesPage)
async def get_session_file_changes(
    session_id: str, response: Response,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=SESSION_FILE_CHANGES_DEFAULT_LIMIT, ge=1, le=SESSION_FILE_CHANGES_MAX_LIMIT),
) -> SessionFileChangesPage:
    from starlette.concurrency import run_in_threadpool
    from system.application import Application

    _admit_business_http()
    manager = _get_sm()
    if not manager.exists(session_id) or manager.is_session_deleting(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    store = Application.current().get_system(IAgentspaceService).file_changes
    try:
        result = await run_in_threadpool(store.get_page, session_id, offset=offset, limit=limit)
    except FileNotFoundError as exc:
        if not manager.exists(session_id) or manager.is_session_deleting(session_id):
            raise HTTPException(status_code=404, detail="Session not found") from exc
        raise
    if not manager.exists(session_id) or manager.is_session_deleting(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/api/sessions/{session_id}/tab-capabilities", response_model=SessionTabCapabilities)
async def get_session_tab_capabilities(
    session_id: str, response: Response,
) -> SessionTabCapabilities:
    """Return lightweight content capabilities for session-dependent tabs."""
    from starlette.concurrency import run_in_threadpool
    from system.application import Application
    from system.session_variables import (
        SessionVariableInputError, SessionVariableAccessError,
        SessionVariableLimitError, SessionVariableConflictError,
    )

    loop = _require_media_loop(session_id, writable=False)
    application = Application.current()
    manager = application.get_system(ISessionManager)
    service = application.get_system(IAgentspaceService).session_variables
    try:
        variables_available = await run_in_threadpool(
            service.has_visible_content, session_id,
        )
    except (SessionVariableInputError, SessionVariableAccessError,
            SessionVariableLimitError, SessionVariableConflictError) as exc:
        status = 400
        if isinstance(exc, SessionVariableAccessError):
            status = 403
        elif isinstance(exc, SessionVariableLimitError):
            status = 413
        elif isinstance(exc, SessionVariableConflictError):
            status = 409
        raise HTTPException(status_code=status, detail={
            "code": exc.code, "message": str(exc), "path": exc.logical_path,
        }) from exc
    if not manager.exists(session_id) or manager.is_session_deleting(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    response.headers["Cache-Control"] = "no-store"
    return SessionTabCapabilities(
        session_id=session_id,
        media_count=loop.loop.get_session_media_count(),
        variables_available=variables_available,
    )


@router.get("/api/sessions/{session_id}/variables")
async def get_session_variables(session_id: str, response: Response) -> SessionVariablePoolResponse:
    """只读会话变量池，不创建 Loop；与 Agent 全量读取复用同一解析服务。"""
    from starlette.concurrency import run_in_threadpool
    from system.application import Application
    from system.session_variables import (
        SessionVariableInputError, SessionVariableAccessError,
        SessionVariableLimitError, SessionVariableConflictError,
    )

    _admit_business_http()
    manager = _get_sm()
    if not manager.exists(session_id) or manager.is_session_deleting(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    response.headers["Cache-Control"] = "no-store"
    service = Application.current().get_system(IAgentspaceService).session_variables
    try:
        result = await run_in_threadpool(service.read_pool, session_id)
    except (SessionVariableInputError, SessionVariableAccessError,
            SessionVariableLimitError, SessionVariableConflictError) as exc:
        status = 400
        if isinstance(exc, SessionVariableAccessError):
            status = 403
        elif isinstance(exc, SessionVariableLimitError):
            status = 413
        elif isinstance(exc, SessionVariableConflictError):
            status = 409
        raise HTTPException(status_code=status, detail={
            "code": exc.code, "message": str(exc), "path": exc.logical_path,
        }) from exc
    if not manager.exists(session_id) or manager.is_session_deleting(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return result


@router.get("/api/sessions/{session_id}/status")
async def get_session_status(session_id: str, conn_token: str | None = None):
    """返回会话存在性、占用状态和当前主会话活动快照。"""
    from system.application import Application
    sm = _get_sm()
    exists = bool(
        sm
        and sm.exists(session_id)
        and not sm.is_session_deleting(session_id)
    )
    sink = Application.current().get_system(IFrontendSink)
    occupied: bool = bool(
        exists and sink.is_session_occupied(session_id, conn_token)
    )
    managed_loop = _get_loop(session_id) if exists else None
    activity = (
        managed_loop.loop.get_main_session_activity()
        if managed_loop is not None
        else None
    )
    processing = bool(
        managed_loop is not None and managed_loop.loop.is_active()
    )
    from starlette.concurrency import run_in_threadpool
    visual_resources = (
        await run_in_threadpool(
            Application.current().get_system(IAgentspaceService).visual_resources.get_all_states, session_id,
        ) if exists else None
    )
    return SessionRuntimeStatus(
        session_id=session_id,
        exists=exists,
        occupied=occupied,
        processing=processing,
        activity=activity,
        visual_resources=visual_resources,
    )


@router.get("/api/sessions/{session_id}/llm-profile", response_model=SessionLlmProfileState)
async def get_session_llm_profile(session_id: str, response: Response) -> SessionLlmProfileState:
    """只读恢复会话保存的名称；不创建 Loop，也不提交浏览器待用选择。"""
    from entity.constant import SESSIONS_DIR_NAME
    from system.application import Application
    from system.session_store import SessionStore

    application = Application.current()
    profile_store = application.get_system(ILLMProfileStore)
    sm = application.get_system(ISessionManager)
    if sm is None or not sm.exists(session_id) or sm.is_session_deleting(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    with profile_store.locked():
        if not sm.exists(session_id) or sm.is_session_deleting(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        store = SessionStore(application.get_system(IRuntimeSystem).context.workspace / SESSIONS_DIR_NAME)
        name = store.read_active_profile_name(session_id)
        available = False
        if name:
            try:
                profile_store.get_profile(name)
                available = True
            except ProfileNotFoundError:
                pass
        response.headers["Cache-Control"] = "no-store"
        return SessionLlmProfileState(
            session_id=session_id, profile_name=name, available=available,
        )


@router.get("/api/characters/avatars", response_model=CharacterAvatarsResponse)
async def get_character_avatars(response: Response) -> CharacterAvatarsResponse:
    """实时组装主Agent与全部子Agent角色的头像映射；不创建 Loop、不依赖会话。"""
    from system.application import Application
    from system.character_avatars import collect_character_avatars

    application = Application.current()
    sandbox = application.get_system(ISandbox)
    runtime = application.get_system(IRuntimeSystem)
    response.headers["Cache-Control"] = "no-store"
    return await asyncio.to_thread(collect_character_avatars, sandbox, runtime)


@router.get("/api/characters/profiles", response_model=CharacterProfilesResponse)
async def get_character_profiles(response: Response) -> CharacterProfilesResponse:
    """实时扫描全部子Agent角色档案（含提示词全文与错误），密钥不出模块。"""
    from system.application import Application
    from system.character_profiles import collect_character_profiles

    application = Application.current()
    sandbox = application.get_system(ISandbox)
    profile_store = application.get_system(ILLMProfileStore)
    response.headers["Cache-Control"] = "no-store"
    return await asyncio.to_thread(collect_character_profiles, sandbox, profile_store)


@router.get("/api/sessions/{session_id}/subagents")
async def get_session_subagents(session_id: str):
    """返回当前活跃子会话的快照。"""
    from system.application import Application
    snapshot = Application.current().get_system(ISubAgentOrchestrator).get_snapshot(
        parent_session_id=session_id,
    )
    return SubAgentSnapshotResponse(
        session_id=session_id,
        subagents=snapshot.subagents,
    )


@router.post("/api/confirm/{request_id}")
async def http_confirm(request_id: str, req: Request):
    """通过 HTTP 处理确认响应（独立于 WebSocket 连接状态）。"""
    _admit_business_http()
    request = await _parse_request_model(
        req,
        ConfirmResponseRequest,
    )
    action: str = request.action
    if action not in ("allow_once", "allow_always", "deny"):
        action = "deny"
    deny_reason: str | None = request.deny_reason or None
    denied_by: str = request.denied_by
    if action != "deny":
        deny_reason = None
    from system.application import Application
    sink = Application.current().get_system(IFrontendSink)
    sink.resolve_confirm(request_id, action, deny_reason=deny_reason, denied_by=denied_by)
    logger.info("HTTP confirm | request_id=%s action=%s denied_by=%s", request_id, action, denied_by)
    return {"resolved": True, "request_id": request_id, "action": action}


@router.post("/api/ask/{request_id}")
async def http_ask(request_id: str, req: Request):
    """通过 HTTP 处理提问响应（独立于 WebSocket 连接状态）。"""
    _admit_business_http()
    request = await _parse_request_model(
        req,
        AskResponseRequest,
    )
    from system.application import Application
    sink = Application.current().get_system(IFrontendSink)
    sink.resolve_ask(request_id, answers=request.answers)
    logger.info("HTTP ask response | request_id=%s answers=%d", request_id, len(request.answers or []))
    return {
        "resolved": True,
        "request_id": request_id,
        "answers": [a.model_dump(exclude_none=True) for a in (request.answers or [])],
    }


@router.post("/api/interrupt/{session_id}")
async def http_interrupt(session_id: str):
    """通过 HTTP 强制中断主会话当前轮次，返回权威结果。

    按「是否存在登记的活动任务」判定 idle；有活动任务时调用统一的
    ``request_interrupt()``，等待收尾确认（上限 MAIN_SESSION_INTERRUPT_TIMEOUT），
    返回 cancelled / timeout / failed / not_found。
    """
    _admit_business_http()
    logger.info("HTTP interrupt | session=%s", session_id)
    loop = _get_loop(session_id)
    if loop is None:
        return {"interrupted": False, "status": "not_found", "session_id": session_id}
    result = await loop.request_interrupt(reason="user")
    logger.info(
        "HTTP interrupt result | session=%s status=%s",
        session_id,
        result.status,
    )
    payload = result.model_dump()
    payload["interrupted"] = result.status in ("idle", "cancelled")
    if result.status == "timeout":
        return HTMLResponse(
            json.dumps(payload, ensure_ascii=False),
            media_type="application/json",
            status_code=409,
        )
    if result.status == "failed":
        return HTMLResponse(
            json.dumps(payload, ensure_ascii=False),
            media_type="application/json",
            status_code=500,
        )
    return payload


@router.post("/api/disgust/{session_id}")
async def http_disgust(session_id: str):
    """通过 HTTP 处理厌恶请求，使其在 WS handler 被
    ``process_message()`` 阻塞时仍能生效。"""
    _admit_business_http()
    logger.info("HTTP disgust | session=%s", session_id)
    loop = _get_loop(session_id)
    if loop is not None:
        loop.loop.disgust()
    return {"disgusted": True, "session_id": session_id}


@asynccontextmanager
async def _file_changes_delete_scope(
    session_id: str, manager: ISessionManager, store: SessionFileChangeStore,
) -> AsyncIterator[None]:
    # REQUEST 的 Owner 持有本作用域，取消后仍观察真实线程结果。
    block = asyncio.create_task(asyncio.to_thread(store.block_session, session_id))
    original: BaseException | None = None
    try:
        await asyncio.shield(block)
        yield
    except BaseException as exc:
        original = exc
        raise
    finally:
        errors: list[BaseException] = []
        try:
            await asyncio.shield(block)
        except BaseException as exc:
            if exc is not original:
                errors.append(exc)
        else:
            action = store.unblock_session if manager.exists(session_id) else store.forget_session
            cleanup = asyncio.create_task(asyncio.to_thread(action, session_id))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                # 外层请求再次取消不会取消 Owner 持有的必要收尾。
                await asyncio.shield(cleanup)
                raise
            except Exception as exc:
                failure = LifecycleFailure("Session file changes deletion cleanup failed")
                failure.__cause__ = exc
                errors.append(failure)
        if errors:
            if original is not None:
                errors.insert(0, original)
            raise BaseExceptionGroup("Session deletion and file changes cleanup failed", errors)


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """永久删除由 Gateway 请求 Owner 保持完整收尾所有权。"""
    _admit_business_http()
    gateway = _gateway()
    try:
        return await gateway.task_owner.run_request(
            lambda: _delete_session_impl(session_id),
            name=f"delete-session-{session_id}", admission=gateway.admission.admit_business,
        )
    except ApplicationStoppingError as exc:
        raise HTTPException(status_code=503, detail="Application is shutting down") from exc
    except SessionFileChangesBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _delete_session_impl(session_id: str):
    """保留原删除步骤，先封闭统计再拆除连接和运行时。"""
    from entity.puretype import Loop
    from system.application import Application

    sm = _get_sm()
    info = sm.get(session_id) if sm else None
    if info is None:
        logger.warning("Delete session rejected (not found) | session=%s", session_id)
        return HTMLResponse(
            json.dumps({"deleted": False, "error": "session not found"}, ensure_ascii=False),
            media_type="application/json",
            status_code=404,
        )
    if info.loop_type == Loop.colloquy:
        logger.warning("Delete session rejected (colloquy) | session=%s", session_id)
        return HTMLResponse(
            json.dumps({"deleted": False, "error": "colloquy session cannot be deleted"}, ensure_ascii=False),
            media_type="application/json",
            status_code=403,
        )
    if not sm.begin_session_delete(session_id):
        logger.warning("Delete session rejected (already deleting) | session=%s", session_id)
        return HTMLResponse(
            json.dumps({"deleted": False, "error": "session deletion already in progress"}, ensure_ascii=False),
            media_type="application/json",
            status_code=409,
        )

    logger.info("Delete session | session=%s", session_id)
    try:
        store = Application.current().get_system(IAgentspaceService).file_changes
        async with _file_changes_delete_scope(session_id, sm, store):
            sink = Application.current().get_system(IFrontendSink)
            await sink.close_session(
                session_id,
                code=WEBSOCKET_CLOSE_SESSION_DELETED,
                reason="session_deleted",
            )

            # 停止子Agent失败时直接终止删除，不能继续移除仍在使用的会话。
            orch = Application.current().get_system(ISubAgentOrchestrator)
            await orch.shutdown(session_id)

            await sm.delete_session_runtime(session_id)
            sm.remove(session_id)

            # 删除已提交；清理失败直接报告，不伪装成完整成功。
            from gateway.session_cleanup import cleanup_session_resources
            await cleanup_session_resources(session_id)
    finally:
        sm.end_session_delete(session_id)

    logger.info("Delete session ok | session=%s", session_id)
    return {"deleted": True, "session_id": session_id}


ExportHTTPResultT = TypeVar("ExportHTTPResultT")


async def _run_export_http(req: Request, factory: Callable[[], Coroutine[Any, Any, ExportHTTPResultT]], name: str) -> ExportHTTPResultT:
    """HTTP 断开取消等待方，实际业务和线程收尾继续由 Gateway Owner 持有。"""
    from entity.constant import SESSION_EXPORT_REQUEST_TIMEOUT_SECONDS
    gateway = _gateway()
    work = asyncio.create_task(gateway.task_owner.run_request(
        factory, name=name, admission=gateway.admission.admit_business,
        cancel_timeout=SESSION_EXPORT_REQUEST_TIMEOUT_SECONDS,
    ))
    async def watch_disconnect() -> None:
        while not await req.is_disconnected():
            await asyncio.sleep(0.25)
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
        raise HTTPException(status_code=499, detail={"code": "export_cancelled", "message": "Export client disconnected"})
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


@router.post("/api/sessions/{session_id}/export/snapshot")
async def capture_session_export(session_id: str, req: Request):
    """一次性只读捕获完整主会话，避免复用前端已加载页。"""
    from entry.session_export import SessionExportError
    from system.lifecycle import ApplicationStoppingError
    from entity.constant import SESSION_EXPORT_REQUEST_TIMEOUT_SECONDS
    gateway = _gateway()

    async def capture_response() -> Response:
        snapshot = await gateway.session_exports.capture(session_id)
        content = await gateway.session_exports.encode_snapshot(snapshot)
        return Response(content, media_type="application/json", headers={"Cache-Control": "no-store"})

    try:
        return await _run_export_http(req, capture_response, f"session-export-snapshot:{session_id}")
    except SessionExportError as error:
        raise HTTPException(status_code=error.status, detail={"code": error.code, "message": str(error)}) from error
    except ApplicationStoppingError as error:
        raise HTTPException(status_code=503, detail={"code": "application_stopping", "message": "Application is stopping"}) from error


async def _read_export_body(request: Request, maximum: int) -> bytes:
    from entity.constant import SESSION_EXPORT_REQUEST_TIMEOUT_SECONDS
    _admit_business_http()
    pieces: list[bytes] = []
    size = 0
    try:
        async with asyncio.timeout(SESSION_EXPORT_REQUEST_TIMEOUT_SECONDS):
            async for piece in request.stream():
                size += len(piece)
                if size > maximum:
                    raise HTTPException(status_code=413, detail={"code": "export_limit", "message": "Export request body is too large"})
                pieces.append(piece)
    except TimeoutError as error:
        raise HTTPException(status_code=408, detail={"code": "export_timeout", "message": "Export request body timed out"}) from error
    return b"".join(pieces)


@router.post("/api/sessions/{session_id}/export/resource")
async def read_session_export_resource(session_id: str, req: Request):
    from entity.puretype import SessionExportResourceRequest, SessionExportResourceIssue
    from entity.constant import (
        SESSION_EXPORT_RESOURCE_BODY_MAX_BYTES, SESSION_EXPORT_REQUEST_TIMEOUT_SECONDS,
        SESSION_EXPORT_DIGEST_HEADER, SESSION_EXPORT_IDENTITY_HEADER,
    )
    from entry.session_export import SessionExportError
    from system.lifecycle import ApplicationStoppingError
    body = await _read_export_body(req, SESSION_EXPORT_RESOURCE_BODY_MAX_BYTES)
    try:
        payload = SessionExportResourceRequest.model_validate_json(body)
    except ValidationError as error:
        raise HTTPException(status_code=400, detail={"code": "invalid_export_request", "message": "Invalid export resource request"}) from error
    gateway = _gateway()
    try:
        result = await _run_export_http(req, lambda: gateway.session_exports.read_resource(session_id, payload), f"session-export-resource:{session_id}")
    except SessionExportError as error:
        raise HTTPException(status_code=error.status, detail={"code": error.code, "message": str(error)}) from error
    except ApplicationStoppingError as error:
        raise HTTPException(status_code=503, detail={"code": "application_stopping", "message": "Application is stopping"}) from error
    if result.status != "saved":
        status_code = {"missing": 404, "denied": 403, "too_large": 413}[result.status]
        issue = SessionExportResourceIssue(
            code=result.code, source=result.proof.source, proof=result.proof,
        )
        return JSONResponse({"detail": issue.model_dump(mode="json")}, status_code=status_code, headers={"Cache-Control": "no-store"})
    return Response(result.content, media_type=result.mime_type, headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        SESSION_EXPORT_DIGEST_HEADER: result.proof.digest,
        SESSION_EXPORT_IDENTITY_HEADER: result.proof.identity,
    })


@router.post("/api/sessions/{session_id}/export/verify")
async def verify_session_export(session_id: str, req: Request):
    from entity.puretype import SessionExportVerifyRequest
    from entity.constant import SESSION_EXPORT_VERIFY_BODY_MAX_BYTES, SESSION_EXPORT_REQUEST_TIMEOUT_SECONDS
    from entry.session_export import SessionExportError
    from system.lifecycle import ApplicationStoppingError
    body = await _read_export_body(req, SESSION_EXPORT_VERIFY_BODY_MAX_BYTES)
    try:
        payload = SessionExportVerifyRequest.model_validate_json(body)
    except ValidationError as error:
        raise HTTPException(status_code=400, detail={"code": "invalid_export_request", "message": "Invalid export verification request"}) from error
    gateway = _gateway()
    try:
        result = await _run_export_http(req, lambda: gateway.session_exports.verify(session_id, payload), f"session-export-verify:{session_id}")
        return JSONResponse(result.model_dump(mode="json"), headers={"Cache-Control": "no-store"})
    except SessionExportError as error:
        raise HTTPException(status_code=error.status, detail={"code": error.code, "message": str(error)}) from error
    except ApplicationStoppingError as error:
        raise HTTPException(status_code=503, detail={"code": "application_stopping", "message": "Application is stopping"}) from error


@router.get("/api/session-export/viewer/{asset_name}")
async def get_session_export_viewer(asset_name: str):
    from entity.constant import SESSION_EXPORT_VIEWER_ASSETS, SESSION_EXPORT_VIEWER_MAX_BYTES
    _admit_business_http()
    if asset_name not in SESSION_EXPORT_VIEWER_ASSETS:
        raise HTTPException(status_code=404, detail="Unknown offline viewer asset")
    path = _FRONTEND_DIST / "export" / asset_name
    if not path.is_file():
        raise HTTPException(status_code=503, detail="Offline viewer is not built")
    if path.stat().st_size > SESSION_EXPORT_VIEWER_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Offline viewer exceeds byte budget")
    return FileResponse(str(path), media_type="text/javascript" if asset_name.endswith(".js") else "text/css", headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })


@router.get("/api/sessions/{session_id}/history/skeleton")
async def get_session_history_skeleton(session_id: str, start_index: int = 0):
    """返回前端全历史骨架或从指定 History 索引开始的后缀。"""
    loop = _get_loop(session_id)
    if loop is None:
        raise HTTPException(status_code=404, detail="agent loop not ready")
    if start_index < 0 or start_index > loop.loop.history.count:
        raise HTTPException(status_code=400, detail="start_index out of range")
    return loop.loop.get_session_history_skeleton(start_index)


@router.get("/api/sessions/{session_id}/history/page")
async def get_session_history_page(
    session_id: str,
    start_index: int = 0,
    limit: int = SESSION_HISTORY_PAGE_DEFAULT_LIMIT,
):
    """按 History 消息索引范围返回完整前端内容行。"""
    if start_index < 0:
        raise HTTPException(status_code=400, detail="start_index must be >= 0")
    if limit < 1 or limit > SESSION_HISTORY_PAGE_MAX_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"limit must be between 1 and {SESSION_HISTORY_PAGE_MAX_LIMIT}",
        )
    loop = _get_loop(session_id)
    if loop is None:
        raise HTTPException(status_code=404, detail="agent loop not ready")
    return loop.loop.get_session_history_page(start_index, limit)


@router.get("/api/sessions/{session_id}/history/resources")
async def get_session_history_resources(session_id: str):
    """返回完整会话 History 的图片与下载资源索引。"""
    loop = _get_loop(session_id)
    if loop is None:
        raise HTTPException(status_code=404, detail="agent loop not ready")
    return loop.loop.get_session_history_resources()


def _require_media_loop(session_id: str, *, writable: bool) -> IMainSessionLoop:
    """控制只访问现存主会话 Loop，绝不恢复空会话或另读活动磁盘副本。"""
    from system.application import Application
    _admit_business_http()
    manager = Application.current().get_system(ISessionManager)
    if not manager.exists(session_id) or manager.is_session_deleting(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    info = manager.get(session_id)
    if info is None:
        raise RuntimeError("Existing session has no metadata")
    if writable and info.status == SessionStatus.archived:
        raise HTTPException(status_code=403, detail="Archived session media cannot be changed")
    loop = manager.get_loop(session_id)
    if loop is None:
        raise HTTPException(status_code=409, detail="Session connection is not ready. Open the session and refresh.")
    if loop.loop.session_id != session_id:
        raise HTTPException(status_code=409, detail="Session is rotating; refresh the current session")
    return loop


def _validate_media_id(media_id: str) -> None:
    if re.fullmatch(SESSION_MEDIA_ID_PATTERN, media_id) is None:
        raise HTTPException(status_code=400, detail="Invalid media instance identity")


@router.get("/api/sessions/{session_id}/history/media")
async def get_session_media(
    session_id: str, response: Response,
    offset: int = SESSION_MEDIA_DEFAULT_OFFSET, limit: int = SESSION_MEDIA_DEFAULT_LIMIT,
) -> SessionMediaListResponse:
    if offset < 0 or limit < 1 or limit > SESSION_MEDIA_MAX_LIMIT:
        raise HTTPException(status_code=400, detail="Invalid media page range")
    loop = _require_media_loop(session_id, writable=False)
    response.headers["Cache-Control"] = "no-store"
    from system.application import Application
    info = Application.current().get_system(ISessionManager).get(session_id)
    if info is None:
        raise RuntimeError("Existing session has no metadata")
    return loop.loop.get_session_media(
        offset=offset, limit=limit, editable=info.status != SessionStatus.archived,
    )


@router.put("/api/sessions/{session_id}/history/media/{media_id}")
async def update_session_media(
    session_id: str, media_id: str, req: Request, response: Response,
) -> SessionMediaUpdateResponse:
    _admit_business_http()
    _validate_media_id(media_id)
    payload = await _parse_request_model(req, SessionMediaUpdateRequest)
    # JSON准备期间会话可能旋转/删除；再次定位后同步保存，无await提交间隙。
    loop = _require_media_loop(session_id, writable=True)
    response.headers["Cache-Control"] = "no-store"
    try:
        return loop.loop.set_session_media_enabled(
            media_id, payload.send_multimodal, payload.expected_send_multimodal,
        )
    except HistoryMediaNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HistoryMediaConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/sessions/{session_id}/history/media/{media_id}/content")
async def get_session_media_content(session_id: str, media_id: str) -> Response:
    _validate_media_id(media_id)
    loop = _require_media_loop(session_id, writable=False)
    try:
        block = loop.loop.get_session_media_block(media_id)
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
        if isinstance(block, (ImageBlock, VideoBlock)):
            url = block.image_url if isinstance(block, ImageBlock) else block.video_url
            if not url.startswith("data:"):
                parsed = urlsplit(url)
                if parsed.scheme not in ("http", "https") or not parsed.netloc:
                    raise HistoryMediaPreviewError("Media preview URL is not supported", 415)
                return RedirectResponse(url=url, status_code=307, headers=headers)
        content, mime_type = decode_media_preview(block)
        if mime_type == "image/svg+xml":
            headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
        return Response(content=content, media_type=mime_type, headers=headers)
    except HistoryMediaNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HistoryMediaPreviewError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.put("/api/sessions/{session_id}/messages/{message_index}")
async def update_session_message(session_id: str, message_index: int, req: Request):
    """编辑指定 session 中一条历史消息的正文或 visible_characters，不触发重新生成。"""
    _admit_business_http()
    logger.info("Edit message request | session=%s index=%d", session_id, message_index)
    request = await _parse_request_model(
        req,
        SessionMessageEditRequest,
    )
    content = request.content
    if isinstance(content, list):
        content = [block.model_dump(mode="json") for block in content]
    visible_characters = request.visible_characters
    info = _get_sm().get(session_id)
    if info and info.status == SessionStatus.archived:
        result = SessionMessageEditResult(
            updated=False,
            session_id=session_id,
            error="archived session cannot be edited",
        )
        return HTMLResponse(
            result.model_dump_json(exclude_none=True),
            media_type="application/json",
            status_code=403,
        )
    loop = _get_loop(session_id)
    if loop is None:
        return SessionMessageEditResult(
            updated=False,
            session_id=session_id,
            error="agent loop not ready",
        )
    if loop.loop.is_processing():
        result = SessionMessageEditResult(
            updated=False,
            session_id=session_id,
            error="session is processing",
        )
        return HTMLResponse(
            result.model_dump_json(exclude_none=True),
            media_type="application/json",
            status_code=409,
        )
    result = loop.loop.edit_session_message(message_index, content, visible_characters)
    status_code = 200 if result.updated else 400
    logger.info("Edit message result | session=%s index=%d updated=%s", session_id, message_index, result.updated)
    return HTMLResponse(
        result.model_dump_json(exclude_none=True),
        media_type="application/json",
        status_code=status_code,
    )


@router.delete("/api/sessions/{session_id}/messages")
async def delete_session_messages(session_id: str, count: int = 1):
    """删除最后 count 个逻辑轮次的消息（从倒数第 count 条 user 起，覆盖其后所有 tool/assistant）。"""
    _admit_business_http()
    logger.info("Delete messages request | session=%s count=%d", session_id, count)
    info = _get_sm().get(session_id)
    if info and info.status == SessionStatus.archived:
        result = SessionMessageDeletionResult(
            deleted=False,
            session_id=session_id,
            error="archived session",
        )
        return HTMLResponse(
            result.model_dump_json(exclude_none=True),
            media_type="application/json",
            status_code=403,
        )
    loop = _get_loop(session_id)
    if loop is None:
        return SessionMessageDeletionResult(
            deleted=False,
            session_id=session_id,
            error="agent loop not ready",
        )
    if loop.loop.is_processing():
        result = SessionMessageDeletionResult(
            deleted=False,
            session_id=session_id,
            error="session is processing",
        )
        return HTMLResponse(
            result.model_dump_json(exclude_none=True),
            media_type="application/json",
            status_code=409,
        )
    result = loop.loop.delete_session_messages(count)
    if result.deleted:
        result = result.model_copy(
            update={"history_count": loop.loop.history.count}
        )
    status_code = 200 if result.deleted else 400
    logger.info("Delete messages result | session=%s count=%d deleted=%s remaining=%s", session_id, count, result.deleted, result.remaining_count)
    return HTMLResponse(
        result.model_dump_json(exclude_none=True),
        media_type="application/json",
        status_code=status_code,
    )


@router.delete("/api/sessions/{session_id}/messages/single")
async def delete_single_message(session_id: str, index: int):
    """删除最后一轮范围内的单条消息（含配对联动清理）。"""
    _admit_business_http()
    logger.info("Delete single message request | session=%s index=%d", session_id, index)
    info = _get_sm().get(session_id)
    if info and info.status == SessionStatus.archived:
        result = SessionMessageDeletionResult(
            deleted=False,
            session_id=session_id,
            error="archived session",
        )
        return HTMLResponse(
            result.model_dump_json(exclude_none=True),
            media_type="application/json",
            status_code=403,
        )
    loop = _get_loop(session_id)
    if loop is None:
        return SessionMessageDeletionResult(
            deleted=False,
            session_id=session_id,
            error="agent loop not ready",
        )

    # 并发防护：处理中拒绝删除
    if loop.loop.is_processing():
        result = SessionMessageDeletionResult(
            deleted=False,
            session_id=session_id,
            error="session is processing",
        )
        return HTMLResponse(
            result.model_dump_json(exclude_none=True),
            media_type="application/json",
            status_code=409,
        )

    result = loop.loop.delete_single_message(index)
    if not result.deleted:
        return HTMLResponse(
            result.model_dump_json(exclude_none=True),
            media_type="application/json",
            status_code=400,
        )

    # 返回 token_usage 和 context_tokens 供前端更新（不通过 WS 全量推送，避免滚动位置重置）
    result = result.model_copy(update={
        "token_usage": loop.get_token_usage(),
        "context_tokens": loop.get_context_tokens(),
        "history_count": loop.loop.history.count,
    })

    logger.info("Delete single message result | session=%s index=%d deleted=%s remaining=%s",
                session_id, index, result.deleted, result.remaining_count)
    return HTMLResponse(
        result.model_dump_json(exclude_none=True),
        media_type="application/json",
        status_code=200,
    )


@router.post("/api/sessions/{session_id}/regenerate")
async def regenerate_response(session_id: str, req: Request):
    """重新生成指定 user 消息的响应：截断历史，刷新扩展块，重新调用 process_message。"""
    _admit_business_http()
    logger.info("Regenerate request | session=%s", session_id)
    info = _get_sm().get(session_id)
    if info and info.status == SessionStatus.archived:
        result = SessionRegenerateResult(
            regenerate=False,
            session_id=session_id,
            error="archived session",
        )
        return HTMLResponse(
            result.model_dump_json(exclude_none=True),
            media_type="application/json",
            status_code=403,
        )
    loop = _get_loop(session_id)
    if loop is None:
        return SessionRegenerateResult(
            regenerate=False,
            session_id=session_id,
            error="agent loop not ready",
        )

    # 并发防护：处理中拒绝重新生成
    # NOTE: 存在窄 TOCTOU 窗口（is_processing 检查为 False 到 process_message
    # 取锁之间），属尽力防护而非强互斥；强互斥需非阻塞 TryLock，超出本任务范围。
    if loop.loop.is_processing():
        result = SessionRegenerateResult(
            regenerate=False,
            session_id=session_id,
            error="session is processing",
        )
        return HTMLResponse(
            result.model_dump_json(exclude_none=True),
            media_type="application/json",
            status_code=409,
        )

    # 解析请求模型，保留该端点原有的 400 错误结构。
    try:
        request = await _parse_request_model(req, SessionRegenerateRequest)
    except HTTPException as exc:
        detail = str(exc.detail)
        if "message_index" in detail:
            error = "invalid message_index"
        elif "llm_profile_name" in detail:
            error = "invalid llm_profile_name"
        else:
            error = "invalid JSON body"
        return HTMLResponse(
            json.dumps({"regenerate": False, "error": error}, ensure_ascii=False),
            media_type="application/json",
            status_code=400,
        )

    message_index = request.message_index
    profile_name = request.llm_profile_name
    from system.application import Application
    application = Application.current()
    profile_store = application.get_system(ILLMProfileStore)
    with profile_store.locked():
        try:
            profile = profile_store.resolve_profile_name(profile_name)
        except ProfileNotFoundError as exc:
            return HTMLResponse(
                json.dumps({"regenerate": False, "error": str(exc)}, ensure_ascii=False),
                media_type="application/json",
                status_code=400,
            )
        loop.set_profile(profile)

    # Profile 切换成功后、截断 History 前登记活动；失败时由 Gateway 收回。
    activity_id = loop.loop.ensure_main_session_activity(
        MainSessionActivitySource.regenerate,
        character_name=loop.current_character_agent,
    )
    try:
        result = loop.loop.regenerate_response(message_index)
        if not result.regenerate:
            return HTMLResponse(
                result.model_dump_json(exclude_none=True),
                media_type="application/json",
                status_code=400,
            )
        ws = _get_ws(session_id)
        if ws:
            await _send_optional_ws_message(
                ws,
                Message(
                    type=MessageType.SYSTEM,
                    session_id=session_id,
                    content=json.dumps({
                        "regenerate_trim": True,
                        "keep_count": result.remaining_count,
                        "message_index": result.message_index,
                        "message_suffix": result.message_suffix,
                        "dynamic_message_suffix": result.dynamic_message_suffix,
                    }),
                ),
            )
        # History 已包含最后一条 user 消息；Loop 自行登记本轮 task。
        reply = await loop.loop.process_message(
            result.last_user_content,
            skip_append=True,
            visible_characters=result.visible_characters,
            response_characters=result.response_characters,
            activity_source=MainSessionActivitySource.regenerate,
            activity_id=activity_id,
        )
    finally:
        # 释放本次登记，包含取消和通知编码失败，不吞掉原异常。
        loop.loop.finish_main_session_activity(activity_id)
    from system.application import Application
    sink = Application.current().get_system(IFrontendSink)
    if reply:
        await sink.emit_assistant_message(
            session_id, reply, loop.current_character_agent,
        )
    if ws:
        await _send_optional_ws_message(
            ws,
            Message(
                type=MessageType.HISTORY_SYNC,
                session_id=session_id,
                history_count=loop.loop.history.count,
                processing=loop.loop.is_active(),
                token_usage=loop.get_token_usage(),
                context_tokens=loop.get_context_tokens(),
            ),
        )
    logger.info("Regenerate ok | session=%s", session_id)
    return {
        "regenerate": True,
        "session_id": session_id,
        "history_count": loop.loop.history.count,
    }


@router.post("/api/sessions/{session_id}/resume")
async def resume_session_endpoint(session_id: str):
    """从当前历史状态恢复工具链执行。

    清除中断标志、重置工具调用计数器，从当前历史直接重新进入工具循环。
    不追加任何 user 消息，不截断历史。
    """
    _admit_business_http()
    info = _get_sm().get(session_id)
    if info and info.status == SessionStatus.archived:
        result = {"resumed": False, "error": "archived session"}
        return HTMLResponse(
            json.dumps(result, ensure_ascii=False),
            media_type="application/json",
            status_code=403,
        )
    loop = _get_loop(session_id)
    if loop is None:
        return {"resumed": False, "error": "agent loop not ready"}
    if loop.loop.is_processing():
        result = {"resumed": False, "error": "session is processing"}
        return HTMLResponse(
            json.dumps(result, ensure_ascii=False),
            media_type="application/json",
            status_code=409,
        )
    # Loop 在取得处理锁后自行登记当前回复 task。
    reply = await loop.resume()
    logger.info("Resume ok | session=%s reply_len=%d", session_id, len(reply))
    ws = _get_ws(session_id)
    if ws:
        await _send_optional_ws_message(
            ws,
            Message(
                type=MessageType.HISTORY_SYNC,
                session_id=session_id,
                history_count=loop.loop.history.count,
                processing=loop.loop.is_active(),
                token_usage=loop.get_token_usage(),
                context_tokens=loop.get_context_tokens(),
            ),
        )
    return {
        "resumed": True,
        "session_id": session_id,
        "history_count": loop.loop.history.count,
    }


@router.put("/api/sessions/{session_id}/title")
async def update_session_title(session_id: str, req: Request):
    """手动重命名 session。"""
    request = await _parse_request_model(
        req,
        SessionTitleUpdateRequest,
    )
    title = request.title.strip()[:50]
    _get_sm().update_title(session_id, title)
    logger.info("Update title | session=%s title=%s", session_id, title)
    return {"updated": True, "session_id": session_id, "title": title}


def _raise_metadata_http(
    exc: MetadataProfileUnavailableError | MetadataGenerationError,
) -> NoReturn:
    """只转换已识别的元数据业务错误。"""
    status = 409 if isinstance(exc, MetadataProfileUnavailableError) else 502
    raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.post("/api/sessions/{session_id}/auto-title")
async def auto_title_session(session_id: str):
    """使用全局元数据服务生成并保存会话标题。"""
    _admit_business_http()
    from system.application import Application

    sm = _get_sm()
    if sm is None or not sm.exists(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    try:
        title = await Application.current().get_system(ISessionMetadataService).generate_title(
            session_id
        )
    except (MetadataProfileUnavailableError, MetadataGenerationError) as exc:
        _raise_metadata_http(exc)
    sm.update_title(session_id, title)
    logger.info("Auto title | session=%s title=%s", session_id, title)
    return {"title": title, "session_id": session_id}


@router.post("/api/sessions/{session_id}/auto-tags")
async def auto_tags_session(session_id: str):
    """使用全局元数据服务生成并保存会话标签。"""
    _admit_business_http()
    from system.application import Application

    sm = _get_sm()
    if sm is None or not sm.exists(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    try:
        tags = await Application.current().get_system(ISessionMetadataService).generate_tags(
            session_id,
            sm.get_all_tags(),
        )
    except (MetadataProfileUnavailableError, MetadataGenerationError) as exc:
        _raise_metadata_http(exc)
    sm.set_session_tags(session_id, tags)
    logger.info("Auto tags | session=%s tags=%s", session_id, tags)
    return {"tags": tags, "session_id": session_id}


@router.post("/api/sessions/{session_id}/regenerate-summary")
async def regenerate_summary_endpoint(session_id: str):
    """使用全局元数据服务重新生成指定会话摘要。"""
    _admit_business_http()
    from entity.puretype import Loop
    from system.application import Application

    sm = _get_sm()
    info = sm.get(session_id) if sm is not None else None
    if info is None:
        raise HTTPException(status_code=404, detail="session not found")
    if info.loop_type == Loop.colloquy:
        logger.warning("Regenerate summary rejected (colloquy) | session=%s", session_id)
        raise HTTPException(
            status_code=403,
            detail="colloquy session cannot be manually compressed",
        )
    logger.info("Regenerate summary | session=%s", session_id)
    try:
        summary = await Application.current().get_system(ISessionMetadataService).regenerate_summary(
            session_id
        )
    except (MetadataProfileUnavailableError, MetadataGenerationError) as exc:
        _raise_metadata_http(exc)
    return {"success": True, "summary": summary, "session_id": session_id}


@router.post("/api/sessions/{session_id}/terminate")
async def terminate_session_endpoint(session_id: str):
    """手动终结指定会话：归档 + 压缩（生成摘要），不旋转。colloquy session 不可终结。"""
    _admit_business_http()
    from entity.puretype import Loop
    info = _get_sm().get(session_id)
    if info and info.loop_type == Loop.colloquy:
        logger.warning("Terminate session rejected (colloquy) | session=%s", session_id)
        return HTMLResponse(
            json.dumps({"terminated": False, "error": "colloquy session cannot be terminated"}, ensure_ascii=False),
            media_type="application/json",
            status_code=403,
        )
    logger.info("Terminate session | session=%s", session_id)
    # 先停止该父会话的所有子 Agent 会话
    from system.application import Application
    orch = Application.current().get_system(ISubAgentOrchestrator)
    await orch.shutdown(session_id)
    loop = _get_loop(session_id)
    if loop is not None:
        result = await loop.loop.terminate_session()
        logger.info(
            "Terminate session complete | session=%s terminated=%s warnings=%d",
            session_id,
            result.terminated,
            len(result.metadata_warnings),
        )
        return result
    logger.warning("Terminate session fail | session=%s error=agent loop not ready", session_id)
    return {"terminated": False, "error": "agent loop not ready", "session_id": session_id}


@router.post("/api/sessions/{session_id}/pin")
async def pin_session_endpoint(session_id: str):
    """切换 session 置顶状态。"""
    pinned: bool = _get_sm().toggle_pin(session_id)
    logger.info("Toggle pin | session=%s pinned=%s", session_id, pinned)
    return {"pinned": pinned, "session_id": session_id}


@router.post("/api/sessions/merge")
async def merge_sessions_endpoint(req: Request):
    """合并多个会话（或单源分支）。

    Body: {"sources": ["sid1", "sid2", ...]}
    """
    _admit_business_http()
    request = await _parse_request_model(
        req,
        SessionMergeRequest,
    )
    sources = request.sources
    logger.info("Merge sessions | sources=%s", sources)
    if not sources:
        return {"error": "sources array required", "merged": False}
    err = _get_sm().validate_merge_sources(sources)
    if err:
        return {"error": err, "merged": False}
    sm = _get_sm()
    if sm is not None:
        for _, loop in sm.get_all_loops().items():
            result = await loop.loop.merge_sessions(sources)
            return result
    return {"error": "agent loop not ready", "merged": False}


@router.post("/api/sessions/{session_id}/branch")
async def branch_session_endpoint(session_id: str):
    """从指定会话创建分支延续（单源 merge 的快捷端点）。"""
    _admit_business_http()
    logger.info("Branch session | source=%s", session_id)
    err = _get_sm().validate_merge_sources([session_id])
    if err:
        return {"error": err, "merged": False}
    loop = _get_loop(session_id)
    if loop is not None:
        result = await loop.loop.merge_sessions([session_id])
        return result
    return {"error": "agent loop not ready", "session_id": session_id}


@router.get("/api/sessions/{session_id}/shells")
async def list_shells_endpoint(session_id: str):
    """列出指定主会话的全部 Shell会话元数据。"""
    from system.application import Application

    shells = Application.current().get_system(IShellManager).list_shells(session_id)
    return {"shells": shells}


@router.post("/api/sessions/{session_id}/shells/{shell_id}/stop")
async def stop_shell_endpoint(session_id: str, shell_id: str):
    """由前端用户停止指定主会话中的 Shell会话。"""
    _admit_business_http()
    from system.application import Application
    from system.shell_manager import ShellAccessError

    logger.info("Stop Shell from frontend | session=%s shell=%s", session_id, shell_id)
    try:
        info = await Application.current().get_system(IShellManager).stop_shell_for_user(
            session_id, shell_id,
        )
    except ShellAccessError as exc:
        raise HTTPException(status_code=404, detail={"code": "shell_not_found", "message": str(exc)}) from exc
    return {"stopped": True, "shell": info}


@router.get("/api/sessions/{session_id}/cron-tasks")
async def list_cron_tasks_endpoint(session_id: str):
    """列出指定会话的所有定时任务。"""
    from system.application import Application
    tasks = Application.current().get_system(ICronRouter).list_cron_tasks_for_session(session_id)
    return {"tasks": tasks}


@router.post("/api/sessions/{session_id}/cron-tasks/{task_id}/trigger")
async def trigger_cron_task_endpoint(session_id: str, task_id: str):
    """立即触发指定的定时任务执行一次。"""
    _admit_business_http()
    logger.info("Trigger cron task | session=%s task_id=%s", session_id, task_id)
    from system.application import Application
    result = Application.current().get_system(ICronRouter).trigger_cron_task(session_id, task_id)
    return result


@router.post("/api/sessions/{session_id}/cron-tasks/{task_id}/cancel")
async def cancel_cron_task_endpoint(session_id: str, task_id: str):
    """取消指定的定时任务。"""
    logger.info("Cancel cron task | session=%s task_id=%s", session_id, task_id)
    from system.application import Application
    result = Application.current().get_system(ICronRouter).cancel_cron_task(session_id, task_id)
    return result


@router.post("/dynamic/{session_id}/{agent_name}/{endpoint_name}")
async def dynamic_endpoint_handler(
    session_id: str,
    agent_name: str,
    endpoint_name: str,
    req: Request,
):
    """动态端点回调 — 向指定会话中的指定 agent 投递仅自身可见的系统消息。

    agent 通过 ``RegisterDynamicEndpoint`` 工具注册端点后，在消息气泡中
    渲染按钮（走 SafeHtml iframe 路径），用户点击按钮时通过 fetch POST 触发
    此端点。POST body 支持两种内容载体：

    - ``message`` (str)：纯文本消息（向后兼容，watching service 等既有调用方使用）。
    - ``content`` (str | list[dict])：多模态有序混合内容，格式与聊天输入框一致——
      block 数组中的每项为 ``{type:"text", text:"..."}``、
      ``{type:"image_url", image_url:{url:"data:image/...;base64,..."}}``、
      ``{type:"input_audio", input_audio:{data:"<base64>", format:"mp3"}}``、
      ``{type:"video_url", video_url:{url:"data:video/...;base64,..."}}``。
      ``content`` 也可以是纯字符串（等价于 ``message``）。

    ``content`` 优先于 ``message``：两者同时提供时 ``message`` 被忽略，
    ``content`` 为空数组或空白字符串时回退到 ``message``。
    block 数组严格校验，任一 block 不合法返回 400 并指明 block 索引。

    投递消息格式: ``[dynamic-endpoint] {endpoint_name}\\n{message}``；
    使用 ``content`` block 数组时，前缀作为独立的首个 text block 注入。
    """
    from system.application import Application

    info = Application.current().get_system(IDynamicEndpointSystem).lookup_endpoint(endpoint_name)
    if info is None:
        return HTMLResponse(
            json.dumps({"error": "endpoint not found", "endpoint_name": endpoint_name}),
            media_type="application/json",
            status_code=404,
        )

    # 验证三要素匹配
    if info.session_id != session_id or info.agent_name != agent_name:
        logger.warning(
            "Dynamic endpoint mismatch | endpoint=%s expected sid=%s agent=%s got sid=%s agent=%s",
            endpoint_name, info.session_id, info.agent_name,
            session_id, agent_name,
        )
        return HTMLResponse(
            json.dumps({"error": "endpoint mismatch", "endpoint_name": endpoint_name}),
            media_type="application/json",
            status_code=404,
        )

    # NOTE: 防御性校验 — 会话已被删除时拒绝投递，作为 cleanup_session_resources
    # 清理失败的兜底，堵住孤儿端点被触发投递到已死会话。sm 为 None 时不阻断
    #（SessionManager 尚未初始化，保持原行为）。
    sm = _get_sm()
    if sm is not None and not sm.exists(session_id):
        return HTMLResponse(
            json.dumps({"error": "session not found", "session_id": session_id}),
            media_type="application/json",
            status_code=404,
        )

    request, request_error = await _parse_dynamic_endpoint_request(req)
    if request_error is not None or request is None:
        error_payload = {"error": request_error or "invalid JSON body"}
        if request_error != "invalid JSON body":
            error_payload["endpoint_name"] = endpoint_name
        return HTMLResponse(
            json.dumps(error_payload, ensure_ascii=False),
            media_type="application/json",
            status_code=400,
        )

    message = request.message

    # 解析 content 字段：支持多模态有序混合内容（与聊天输入框格式一致）
    raw_content = request.content
    payload: MessageContent
    used: str

    if isinstance(raw_content, list):
        if not raw_content:
            # 空数组 → 回退 message 路径
            payload = f"[dynamic-endpoint] {endpoint_name}\n{message}"
            used = "message"
        else:
            # 前缀作为独立首个 text block，后接原始 blocks（保序）
            raw_blocks = [block.model_dump(mode="json") for block in raw_content]
            payload = [{"type": "text", "text": f"[dynamic-endpoint] {endpoint_name}\n"}] + raw_blocks
            used = "content"
            block_types = [block.type for block in raw_content]
            logger.info(
                "Dynamic endpoint content blocks | endpoint=%s types=%s",
                endpoint_name, block_types,
            )
    elif isinstance(raw_content, str):
        if raw_content.strip():
            payload = f"[dynamic-endpoint] {endpoint_name}\n{raw_content}"
            used = "content"
        else:
            # 空白字符串 → 回退 message 路径
            payload = f"[dynamic-endpoint] {endpoint_name}\n{message}"
            used = "message"
    else:
        # 未提供 content → message 路径（watching service 等既有调用方）
        payload = f"[dynamic-endpoint] {endpoint_name}\n{message}"
        used = "message"

    loop = _get_loop(session_id)
    if loop is None:
        return HTMLResponse(
            json.dumps({"error": "agent loop not ready", "session_id": session_id}),
            media_type="application/json",
            status_code=503,
        )

    # 先完成接收登记再回报成功；关闭中的拒绝明确返回 503。
    from system.lifecycle import ApplicationStoppingError
    try:
        loop.loop.message_queue.push(
            payload,
            character_name=SYSTEM_CHARACTER_NAME,
            source="dynamic-endpoint",
            visible_characters=[agent_name],
            response_characters=[agent_name],
        )
    except ApplicationStoppingError:
        return HTMLResponse(
            json.dumps({
                "delivered": False, "error": "application shutting down",
                "endpoint_name": endpoint_name, "session_id": session_id,
            }, ensure_ascii=False),
            media_type="application/json",
            status_code=503,
        )

    logger.info(
        "Dynamic endpoint triggered | endpoint=%s session=%s agent=%s used=%s",
        endpoint_name, session_id, agent_name, used,
    )

    return HTMLResponse(
        json.dumps({
            "delivered": True, "queued": True,
            "endpoint_name": endpoint_name, "session_id": session_id, "used": used,
        }, ensure_ascii=False),
        media_type="application/json",
        status_code=202,
    )


@router.post("/api/file-picker")
async def file_picker():
    """打开原生 Windows 文件选择对话框（仅本地 localhost 有效），
    选中的文件通过硬链接（同盘）或复制（跨盘）放入 uploads 目录。"""
    import json
    import os
    import shutil
    import subprocess
    import sys
    import textwrap
    import uuid
    from pathlib import Path

    script: str = textwrap.dedent("""\
    import json, tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    files = filedialog.askopenfilenames(title="选择要上传的文件")
    root.destroy()
    print(json.dumps(list(files)))
    """)

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                timeout=SUBPROCESS_TIMEOUT_DEFAULT,
            ),
        )
        if result.returncode != 0:
            logger.warning("File dialog subprocess failed: %s", result.stderr.strip())
            return {"uploaded": False, "error": "dialog_failed"}
        paths: list[str] = json.loads(result.stdout.strip())
    except subprocess.TimeoutExpired:
        logger.warning("File dialog subprocess timed out")
        return {"uploaded": False, "error": "dialog_timeout"}

    if not paths:
        return {"uploaded": False, "files": []}

    upload_dir: Path = _agentspace_root() / UPLOADS_DIR_NAME
    upload_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    for p in paths:
        src: Path = Path(p)
        if not src.is_file():
            continue
        safe_name: str = src.name
        timestamp: str = datetime.now(timezone.utc).strftime(UPLOAD_FILENAME_TIME_FORMAT)
        unique_name: str = f"{timestamp}_{uuid.uuid4().hex[:8]}_{safe_name}"
        dest: Path = upload_dir / unique_name
        method: str = "hardlink"
        try:
            os.link(str(src), str(dest))
        except OSError:
            try:
                shutil.copy2(str(src), str(dest))
                method = "copy"
            except OSError as exc:
                results.append({"uploaded": False, "filename": safe_name, "error": str(exc)})
                continue

        logger.info("File %s | picker src=%s dest=%s", method, src, dest)
        results.append({
            "uploaded": True,
            "path": f"{UPLOADS_WS_PREFIX}{unique_name}",
            "filename": safe_name,
            "size": dest.stat().st_size,
            "method": method,
        })

    return {"uploaded": True, "files": results}


@router.get(STATIC_FILE_HTTP_PREFIX + "/{namespace}/{file_path:path}")
@router.head(STATIC_FILE_HTTP_PREFIX + "/{namespace}/{file_path:path}")
def serve_workspace_file(namespace: str, file_path: str, request: Request):
    """在线程池解析视觉入口；最终 HEAD 响应独立校验来源并返回版本。"""
    from system.application import Application
    from system.sandbox import SandboxError
    from system.session_visual_resources import SessionVisualResourceError, SessionVisualVersionUnavailable
    from entity.puretype import SessionVisualKind, SessionVisualSource, SessionVisualStatus

    sandbox = Application.current().get_system(ISandbox)
    service = Application.current().get_system(IAgentspaceService).visual_resources
    logical = f"{namespace}:{file_path}"
    raw = request.query_params.get(VISUAL_RAW_PARAM) == VISUAL_QUERY_ENABLED
    probe = request.query_params.get(VISUAL_PROBE_PARAM) == VISUAL_QUERY_ENABLED
    headers = {**_NO_CACHE, "Cache-Control": "no-store"} if probe else dict(_NO_CACHE)
    state = None

    def failure(message: str, code: int) -> Response:
        return Response(
            content=b"" if request.method == "HEAD" else message,
            status_code=code, headers=headers, media_type="text/plain",
        )

    try:
        # 即使源目录尚未部署，也要先检查逻辑路径权限和遍历。
        resolved = sandbox.resolve_read(logical)
        if raw and probe:
            sid = request.query_params.get(VISUAL_SID_PARAM)
            kind = request.query_params.get(VISUAL_KIND_PARAM)
            if not sid or not kind:
                return failure("Missing visual source", 400)
            try:
                visual_kind = SessionVisualKind(kind)
            except ValueError:
                return failure("Invalid visual kind", 400)
            source = SessionVisualSource(session_id=sid, kind=visual_kind)
            state = service.get_state(source.session_id, source.kind)
            expected = sandbox.resolve_read(service.build_entry_logical_path(state))
            if expected.namespace != resolved.namespace or expected.real != resolved.real:
                return failure("Visual source changed", 409)
        elif not raw:
            parent, separator, filename = logical.rpartition("/")
            source = service.match_source_directory(parent) if separator else None
            if source is not None and filename == service.entry_name(source.kind):
                state = service.get_state(source.session_id, source.kind)
                if state.redirected and state.status == SessionVisualStatus.ready:
                    expected = sandbox.resolve_read(service.build_entry_logical_path(state))
                    if expected.namespace != resolved.namespace or expected.real != resolved.real:
                        return RedirectResponse(
                            url=service.build_entry_url(state, source=source if probe else None),
                            status_code=307, headers={**_NO_CACHE, "Cache-Control": "no-store"},
                        )
        if probe and state is None:
            return failure("Invalid visual probe", 400)
        if not resolved.real.is_file():
            return failure("File not found", 404)
        with resolved.real.open("rb"):
            pass
        if probe and state is not None:
            headers[VISUAL_VERSION_HEADER] = service.get_version(state)
        media_type = _guess_media_type_with_charset(resolved.real)
        if request.method == "HEAD":
            headers["Content-Length"] = str(resolved.real.stat().st_size)
            return Response(headers=headers, media_type=media_type)
        return FileResponse(str(resolved.real), media_type=media_type, headers=headers)
    except SessionVisualVersionUnavailable:
        return failure("Visual version unavailable", 503)
    except SandboxError:
        return failure("Sandbox access denied", 403)
    except SessionVisualResourceError:
        return failure("Invalid visual request", 400)
    except FileNotFoundError:
        return failure("File not found", 404)
    except PermissionError:
        return failure("File access denied", 403)


@router.get(LOCAL_FONT_HTTP_PREFIX + "/{font_path:path}")
async def serve_local_font(font_path: str):
    """提供本地字体文件的 HTTP 访问，供 CSS @font-face src 使用。

    URL 格式: /local-font/{绝对路径}
    例如: /local-font/C:/Windows/Fonts/arial.ttf

    安全约束：
    - 仅接受 woff2/woff/ttf/otf 扩展名
    - 文件大小 ≤ LOCAL_FONT_MAX_BYTES (20 MiB)
    - 拒绝 .. 路径遍历
    - 响应头：Cache-Control: no-cache + Access-Control-Allow-Origin: *
    """
    from system.local_fonts import resolve_local_font, LocalFontAccessError

    try:
        font_file = resolve_local_font(font_path)
    except LocalFontAccessError as error:
        return HTMLResponse(str(error), status_code=error.status)
    ext = font_file.suffix.lower()
    media_type = LOCAL_FONT_MIME_TYPES.get(ext, "application/octet-stream")
    font_headers = {
        **_NO_CACHE,
        "Access-Control-Allow-Origin": "*",
    }
    return FileResponse(str(font_file), media_type=media_type, headers=font_headers)


@router.get(DOWNLOADS_HTTP_PREFIX + "/{namespace}/{file_path:path}")
async def download_workspace_file(namespace: str, file_path: str):
    """提供沙盒命名空间下文件的 HTTP 下载（强制 Content-Disposition: attachment）。"""
    from system.application import Application
    from system.sandbox import SandboxError

    logical = f"{namespace}:{file_path}"
    try:
        sandbox = Application.current().get_system(ISandbox)
        resolved = sandbox.resolve_read(logical)
    except SandboxError as exc:
        return HTMLResponse(str(exc), status_code=403)
    if not resolved.real.exists() or not resolved.real.is_file():
        return HTMLResponse("File not found", status_code=404)
    filename = resolved.real.name
    # RFC 5987: non-ASCII filename needs filename* with UTF-8 encoding
    safe_ascii = re.sub(r'[^\x20-\x7e]', '_', filename)
    return FileResponse(
        str(resolved.real),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{safe_ascii}"; '
                f"filename*=UTF-8''{quote(filename, safe='')}"
            ),
        },
    )


@router.get(DIR_ZIP_HTTP_PREFIX + "/{namespace}/{file_path:path}")
def download_dir_zip(namespace: str, file_path: str, request: Request):
    """将沙盒命名空间下的整个目录打包为 zip 后下载。

    URL 格式: /zip/{namespace}/{file_path}
    例如: /zip/ws/sessions/{sid}/site → agentspace/sessions/{sid}/site 打包为 site.zip

    同步 def（非 async）使 Starlette 自动走 threadpool，避免 zip 构建阻塞事件循环。
    """
    import io
    import os
    import zipfile

    from system.application import Application
    from system.sandbox import SandboxError

    logical = f"{namespace}:{file_path}"
    try:
        sandbox = Application.current().get_system(ISandbox)
        resolved = sandbox.resolve_read(logical)
        if request.query_params.get(VISUAL_RAW_PARAM) != VISUAL_QUERY_ENABLED:
            service = Application.current().get_system(IAgentspaceService).visual_resources
            source = service.match_source_directory(logical)
            if source is not None and source.kind == SessionVisualKind.site:
                state = service.get_state(source.session_id, source.kind)
                if state.redirected:
                    target = sandbox.resolve_read(state.effective_path)
                    if target.namespace != resolved.namespace or target.real != resolved.real:
                        target_ns, relative = state.effective_path.split(":", 1)
                        location = (
                            f"{DIR_ZIP_HTTP_PREFIX}/{quote(target_ns, safe='')}/"
                            f"{quote(relative, safe='/')}?{VISUAL_RAW_PARAM}={VISUAL_QUERY_ENABLED}"
                        )
                        return RedirectResponse(url=location, status_code=307, headers={"Cache-Control": "no-store"})
    except SandboxError:
        return HTMLResponse("Sandbox access denied", status_code=403)
    if not resolved.real.exists() or not resolved.real.is_dir():
        return HTMLResponse("Directory not found", status_code=404)

    # 收集文件并检查总大小
    files: list[tuple[Path, str]] = []
    total_size: int = 0
    root: Path = resolved.real
    import stat as stat_module
    for dirpath, dirnames, filenames in os.walk(str(root), followlinks=False):
        # 不递归 Windows junction；每个文件还必须独立经过 Sandbox 校验。
        dirnames[:] = [
            name for name in dirnames
            if not (Path(dirpath) / name).is_symlink()
            and not (
                os.name == "nt"
                and (Path(dirpath) / name).lstat().st_file_attributes
                & stat_module.FILE_ATTRIBUTE_REPARSE_POINT
            )
        ]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            relative = fpath.relative_to(root).as_posix()
            try:
                sandbox.resolve_read(logical.rstrip("/") + "/" + relative)
            except SandboxError:
                return HTMLResponse("Archive contains an inaccessible file", status_code=403)
            if not fpath.is_file():
                continue
            # arcname 以所打包目录名称为根
            arcname = str(fpath.relative_to(root.parent))
            files.append((fpath, arcname))
            total_size += fpath.stat().st_size

    if not files:
        return HTMLResponse("Directory is empty", status_code=404)
    if total_size > DIR_ZIP_MAX_TOTAL_BYTES:
        return HTMLResponse(
            f"Directory too large: {total_size} bytes exceeds limit {DIR_ZIP_MAX_TOTAL_BYTES}",
            status_code=413,
        )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fpath, arcname in files:
            zf.write(str(fpath), arcname)

    zip_filename = f"{root.name}.zip"
    safe_ascii = re.sub(r'[^\x20-\x7e]', '_', zip_filename)
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{safe_ascii}"; '
                f"filename*=UTF-8''{quote(zip_filename, safe='')}"
            ),
        },
    )


# ---------------------------------------------------------------------------
# Dynamic sandbox spaces API
# ---------------------------------------------------------------------------


def _sandbox_space_payload(space: DynamicSandboxSpace, available: bool | None = None) -> dict[str, object]:
    payload = space.model_dump()
    if available is not None:
        payload["available"] = available
    return payload


def _raise_sandbox_space_http(
    exc: DynamicSandboxInputError | DynamicSandboxNotFoundError | SandboxError,
) -> NoReturn:
    if isinstance(exc, DynamicSandboxNotFoundError):
        status = 404
    elif isinstance(exc, DynamicSandboxConflictError):
        status = 409
    else:
        status = 400
    raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.get("/api/sandbox-spaces")
async def list_sandbox_spaces():
    from system.application import Application

    entries = Application.current().get_system(ISandbox).list_dynamic_spaces_with_availability()
    return {"spaces": [_sandbox_space_payload(space, available) for space, available in entries]}


@router.post("/api/sandbox-spaces")
async def create_sandbox_space(request: DynamicSandboxSpaceCreateRequest):
    from system.application import Application

    try:
        space, created = Application.current().get_system(ISandbox).add_dynamic_space(
            name=request.name,
            path=request.path,
            description=request.description,
            is_readonly=request.is_readonly,
        )
        return {"space": _sandbox_space_payload(space), "created": created}
    except (DynamicSandboxInputError, DynamicSandboxNotFoundError, SandboxError) as exc:
        _raise_sandbox_space_http(exc)


@router.put("/api/sandbox-spaces/{name}")
async def update_sandbox_space(name: str, request: DynamicSandboxSpaceUpdateRequest):
    from system.application import Application

    if name != request.name:
        raise HTTPException(status_code=400, detail="动态沙盒空间名称不可修改，且必须与路径参数一致")
    try:
        space = Application.current().get_system(ISandbox).update_dynamic_space(
            name,
            path=request.path,
            description=request.description,
            is_readonly=request.is_readonly,
        )
        return {"space": _sandbox_space_payload(space)}
    except (DynamicSandboxInputError, DynamicSandboxNotFoundError, SandboxError) as exc:
        _raise_sandbox_space_http(exc)


@router.delete("/api/sandbox-spaces/{name}")
async def delete_sandbox_space(name: str):
    from system.application import Application

    try:
        removed = Application.current().get_system(ISandbox).remove_dynamic_space(name)
        return {"removed": removed, "name": name}
    except (DynamicSandboxInputError, DynamicSandboxNotFoundError, SandboxError) as exc:
        _raise_sandbox_space_http(exc)


@router.post("/api/sandbox-spaces/pick-directory")
async def pick_sandbox_directory():
    import subprocess
    import sys

    script = "\n".join([
        "import json, tkinter as tk",
        "from tkinter import filedialog",
        "root = tk.Tk()",
        "root.withdraw()",
        "root.attributes('-topmost', True)",
        "selected = filedialog.askdirectory(title='选择动态沙盒空间目录')",
        "root.destroy()",
        "print(json.dumps(selected))",
    ])
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                timeout=SUBPROCESS_TIMEOUT_DEFAULT,
            ),
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="目录选择对话框超时")
    if result.returncode != 0:
        logger.warning("Dynamic sandbox directory picker subprocess failed: %s", result.stderr.strip())
        raise HTTPException(status_code=500, detail="目录选择对话框启动失败")
    selected = json.loads(result.stdout.strip())
    if not selected:
        return {"selected": False, "path": None}
    return {"selected": True, "path": selected}


# ---------------------------------------------------------------------------
# Approval Profile API
# ---------------------------------------------------------------------------


def _missing_profile_connection_fields(profile: LLMProfile) -> list[str]:
    return [
        name
        for name, value in (
            ("llm_client_name", profile.llm_client_name),
            ("base_url", profile.base_url),
            ("model", profile.model),
        )
        if not value.strip()
    ]


@router.get("/api/approval/profile")
async def get_approval_profile():
    """返回项目级审批 Profile 的权威状态。"""
    from system.application import Application
    return Application.current().get_system(IApprovalSystem).backend_manager.get_state()


@router.put("/api/approval/profile")
async def put_approval_profile(request: Request):
    """设置或清空项目级审批 Profile 引用。

    请求体为 ApprovalProfileUpdateRequest，profile_name=null 表示清空。
    """
    from system.application import Application
    from entity.puretype import ApprovalProfileUpdateRequest, ApprovalProfileMutationResponse

    update = await _parse_request_model(req=request, model_type=ApprovalProfileUpdateRequest)

    app = Application.current()
    store = app.get_system(ILLMProfileStore)
    mgr = app.get_system(IApprovalSystem).backend_manager

    with store.locked():
        if update.profile_name is None:
            previous = store.get_approval_profile()
            store.set_approval_profile(None)
            logger.info(
                "Approval profile cleared | previous=%s",
                previous.name if previous else None,
            )
        else:
            try:
                profile = store.get_profile(update.profile_name)
            except ProfileNotFoundError:
                raise HTTPException(status_code=404, detail=f"Profile not found: {update.profile_name!r}")
            missing = _missing_profile_connection_fields(profile)
            if missing:
                raise HTTPException(
                    status_code=409,
                    detail=f"Approval Profile {profile.name!r} is missing required fields: " + ", ".join(missing),
                )
            previous = store.get_approval_profile()
            store.set_approval_profile(profile)
            logger.info(
                "Approval profile set | name=%s model=%s client=%s",
                profile.name,
                profile.model,
                profile.llm_client_name,
            )
        mgr.invalidate()

    state = mgr.get_state()
    failures = await app.get_system(IFrontendSink).broadcast_approval_profile_change(state)
    return ApprovalProfileMutationResponse(
        state=state,
        notification_failures=failures,
    )


# ---------------------------------------------------------------------------
# Modality fallback Profile API
# ---------------------------------------------------------------------------


def _modality_profile_state(profile: LLMProfile | None) -> ModalityProfileState:
    """将全局多模态 Profile 实例转换为 REST/WS 状态。"""
    if profile is None:
        return ModalityProfileState()
    missing = _missing_profile_connection_fields(profile)
    return ModalityProfileState(
        profile_name=profile.name,
        model=profile.model or None,
        available=not missing,
    )


def _get_modality_profile_states(application: Application) -> ModalityProfileStates:
    data = application.get_system(ILLMProfileStore).get_data()
    return ModalityProfileStates(
        image=_modality_profile_state(data.global_vision_image_profile),
        audio=_modality_profile_state(data.global_audio_profile),
        video=_modality_profile_state(data.global_vision_video_profile),
    )


@router.get("/api/modality/profiles")
async def get_modality_profiles():
    """返回图片、音频、视频三路全局回退 Profile 状态。"""
    from system.application import Application

    return _get_modality_profile_states(Application.current())


@router.put(
    "/api/modality/profiles",
    response_model=ModalityProfileMutationResponse,
)
async def put_modality_profile(update: ModalityProfileUpdateRequest):
    """设置或清空单种媒体的全局回退 Profile 引用。"""
    from system.application import Application

    application = Application.current()
    profile_store = application.get_system(ILLMProfileStore)
    try:
        with profile_store.locked():
            profile = (
                profile_store.get_profile(update.profile_name)
                if update.profile_name is not None else None
            )
            if profile is not None:
                missing = _missing_profile_connection_fields(profile)
                if missing:
                    raise ProfileConflictError(
                        f"Modality Profile {profile.name!r} is missing required fields: "
                        + ", ".join(missing)
                    )
            profile_store.set_global_modality_profile(
                update.media_type,
                profile,
            )
            states = _get_modality_profile_states(application)
            if update.media_type == "image":
                state = states.image
            elif update.media_type == "audio":
                state = states.audio
            else:
                state = states.video
    except ProfileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Profile not found: {update.profile_name!r}",
        )
    except ProfileConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    failures = await application.get_system(IFrontendSink).broadcast_modality_profile_change(states)
    return ModalityProfileMutationResponse(
        state=state,
        notification_failures=failures,
    )


# ---------------------------------------------------------------------------
# Metadata Profile API
# ---------------------------------------------------------------------------


@router.get("/api/metadata/profile")
async def get_metadata_profile():
    """返回项目级全局元数据 Profile 的权威状态。"""
    from system.application import Application

    return Application.current().get_system(ISessionMetadataService).get_state()


@router.put(
    "/api/metadata/profile",
    response_model=MetadataProfileMutationResponse,
)
async def put_metadata_profile(
    update: MetadataProfileUpdateRequest,
):
    """设置或清空项目级全局元数据 Profile 引用。"""
    from system.application import Application
    from system.session_metadata import (
        MetadataProfileUnavailableError,
    )

    application = Application.current()
    store = application.get_system(ILLMProfileStore)
    metadata_service = application.get_system(ISessionMetadataService)
    try:
        with store.locked():
            profile = (
                store.get_profile(update.profile_name)
                if update.profile_name is not None
                else None
            )
            state = metadata_service.select_profile(profile)
    except ProfileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Profile not found: {update.profile_name!r}",
        )
    except MetadataProfileUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    failures = await application.get_system(IFrontendSink).broadcast_metadata_profile_change(
        state
    )
    return MetadataProfileMutationResponse(
        state=state,
        notification_failures=failures,
    )


# ---------------------------------------------------------------------------
# Toolchain Summary Profile API
# ---------------------------------------------------------------------------


@router.get("/api/toolchain-summary/profile")
async def get_toolchain_summary_profile():
    """返回项目级工具链摘要 Profile 的权威状态。"""
    from system.application import Application

    return Application.current().get_system(ISessionMetadataService).get_toolchain_summary_state()


@router.put(
    "/api/toolchain-summary/profile",
    response_model=ToolchainSummaryProfileMutationResponse,
)
async def put_toolchain_summary_profile(
    update: ToolchainSummaryProfileUpdateRequest,
):
    """设置或清空项目级工具链摘要 Profile 引用。"""
    from system.application import Application
    from system.session_metadata import (
        MetadataProfileUnavailableError,
    )

    application = Application.current()
    store = application.get_system(ILLMProfileStore)
    metadata_service = application.get_system(ISessionMetadataService)
    try:
        with store.locked():
            profile = (
                store.get_profile(update.profile_name)
                if update.profile_name is not None
                else None
            )
            state = metadata_service.select_toolchain_summary_profile(profile)
    except ProfileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Profile not found: {update.profile_name!r}",
        )
    except MetadataProfileUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    failures = await application.get_system(IFrontendSink).broadcast_toolchain_summary_profile_change(
        state
    )
    return ToolchainSummaryProfileMutationResponse(
        state=state,
        notification_failures=failures,
    )


# ---------------------------------------------------------------------------
# Agentspace editor API
# ---------------------------------------------------------------------------


def _agentspace_service():
    from system.application import Application
    return Application.current().get_system(IAgentspaceService)


def _raise_agentspace_http(exc: AgentspaceError) -> NoReturn:
    from system.agentspace import (
        AgentspaceAlreadyExistsError,
        AgentspaceInvalidPathError,
        AgentspaceLockedError,
        AgentspaceNotFoundError,
        AgentspaceNotTextError,
        AgentspaceVersionConflictError,
    )

    if isinstance(exc, AgentspaceInvalidPathError):
        status = 400
    elif isinstance(exc, AgentspaceNotFoundError):
        status = 404
    elif isinstance(exc, (AgentspaceAlreadyExistsError, AgentspaceVersionConflictError)):
        status = 409
    elif isinstance(exc, AgentspaceNotTextError):
        status = 415
    elif isinstance(exc, AgentspaceLockedError):
        status = 423
    else:
        status = 400
    raise HTTPException(status_code=status, detail=exc.as_detail()) from exc


@router.get("/api/agentspace/list")
async def agentspace_list(path: str = ""):
    try:
        entries = await asyncio.to_thread(_agentspace_service().list_directory, path)
        return {
            "entries": [
                {**entry.model_dump(mode="json"), "type": entry.kind.value}
                for entry in entries
            ]
        }
    except AgentspaceError as exc:
        _raise_agentspace_http(exc)


@router.get("/api/agentspace/read")
async def agentspace_read(path: str = ""):
    try:
        snapshot = await asyncio.to_thread(_agentspace_service().read_file, path)
        return snapshot
    except AgentspaceError as exc:
        _raise_agentspace_http(exc)


@router.post("/api/agentspace/write")
async def agentspace_write(request: AgentspaceWriteRequest):
    operation_id = request.operation_id or uuid.uuid4().hex
    try:
        snapshot = await asyncio.to_thread(
            _agentspace_service().write_file,
            request.path,
            request.content,
            request.expected_version,
            operation_id,
        )
        return {**snapshot.model_dump(mode="json"), "operation_id": operation_id}
    except AgentspaceError as exc:
        _raise_agentspace_http(exc)


@router.post("/api/agentspace/mkdir")
async def agentspace_mkdir(request: AgentspacePathRequest):
    operation_id = request.operation_id or uuid.uuid4().hex
    try:
        entry = await asyncio.to_thread(
            _agentspace_service().create_directory,
            request.path,
            operation_id,
        )
        return {"entry": entry, "operation_id": operation_id}
    except AgentspaceError as exc:
        _raise_agentspace_http(exc)


@router.post("/api/agentspace/rename")
async def agentspace_rename(request: AgentspaceRenameRequest):
    operation_id = request.operation_id or uuid.uuid4().hex
    try:
        old_path, new_path = await asyncio.to_thread(
            _agentspace_service().rename_path,
            request.path,
            request.new_name,
            operation_id,
        )
        return {
            "old_path": old_path,
            "new_path": new_path,
            "operation_id": operation_id,
        }
    except AgentspaceError as exc:
        _raise_agentspace_http(exc)


@router.post("/api/agentspace/delete")
async def agentspace_delete(request: AgentspacePathRequest):
    """用户删除语义：移动到 Agentspace 垃圾桶。"""
    operation_id = request.operation_id or uuid.uuid4().hex
    try:
        entry = await asyncio.to_thread(
            _agentspace_service().move_to_trash,
            request.path,
            operation_id,
        )
        return {"entry": entry, "operation_id": operation_id}
    except AgentspaceError as exc:
        _raise_agentspace_http(exc)


@router.get("/api/agentspace/trash")
async def agentspace_trash_list():
    try:
        entries = await asyncio.to_thread(_agentspace_service().list_trash)
        return {"entries": entries}
    except AgentspaceError as exc:
        _raise_agentspace_http(exc)


@router.post("/api/agentspace/trash/{entry_id}/restore")
async def agentspace_trash_restore(entry_id: str, req: Request):
    operation_request = await _parse_request_model(
        req,
        AgentspaceOperationRequest,
    )
    operation_id = operation_request.operation_id.strip() or uuid.uuid4().hex
    try:
        entry, restored_path = await asyncio.to_thread(
            _agentspace_service().restore_trash,
            entry_id,
            operation_id,
        )
        return {
            "entry": entry,
            "restored_path": restored_path,
            "operation_id": operation_id,
        }
    except AgentspaceError as exc:
        _raise_agentspace_http(exc)


@router.delete("/api/agentspace/trash/{entry_id}")
async def agentspace_trash_purge(entry_id: str, req: Request):
    operation_request = await _parse_request_model(
        req,
        AgentspaceOperationRequest,
    )
    operation_id = operation_request.operation_id.strip() or uuid.uuid4().hex
    try:
        await asyncio.to_thread(
            _agentspace_service().purge_trash,
            entry_id,
            operation_id,
        )
        return {"success": True, "operation_id": operation_id}
    except AgentspaceError as exc:
        _raise_agentspace_http(exc)


@router.delete("/api/agentspace/trash")
async def agentspace_trash_empty(req: Request):
    operation_request = await _parse_request_model(
        req,
        AgentspaceOperationRequest,
    )
    operation_id = operation_request.operation_id.strip() or uuid.uuid4().hex
    try:
        deleted, failures = await asyncio.to_thread(
            _agentspace_service().empty_trash,
            operation_id,
        )
        return {
            "deleted": deleted,
            "failures": failures,
            "operation_id": operation_id,
        }
    except AgentspaceError as exc:
        _raise_agentspace_http(exc)


@router.get("/api/agentspace/locks")
async def agentspace_locks():
    return {"locks": _agentspace_service().locks_snapshot()}


def _agentspace_sse(event: AgentspaceEvent) -> str:
    return (
        f"id: {event.sequence}\n"
        "event: agentspace\n"
        f"data: {event.model_dump_json()}\n\n"
    )


@router.get("/api/agentspace/events")
async def agentspace_events(req: Request):
    service = _agentspace_service()
    subscription_id, queue = service.subscribe_events()

    async def stream():
        try:
            for initial_event in build_initial_agentspace_events(service):
                yield _agentspace_sse(initial_event)
            from system.application import Application
            shutdown_wait = _gateway().task_owner.track(
                asyncio.create_task(
                    Application.current().get_system(IRuntimeSystem).shutdown_event.wait(),
                    name="agentspace-sse-shutdown-wait",
                )
            )
            try:
                while not await req.is_disconnected():
                    event_wait = _gateway().task_owner.track(
                        asyncio.create_task(queue.get(), name="agentspace-sse-event-wait")
                    )
                    try:
                        done, _ = await asyncio.wait(
                            (event_wait, shutdown_wait),
                            timeout=AGENTSPACE_SSE_HEARTBEAT_SECONDS,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                    finally:
                        if not event_wait.done():
                            _gateway().task_owner.cancel(event_wait)
                            await asyncio.gather(event_wait, return_exceptions=True)
                    if shutdown_wait in done:
                        return
                    if event_wait in done:
                        error = event_wait.exception()
                        if error is not None:
                            raise error
                        yield _agentspace_sse(event_wait.result())
                    else:
                        yield ": keepalive\n\n"
            finally:
                _gateway().task_owner.cancel(shutdown_wait)
                await asyncio.gather(shutdown_wait, return_exceptions=True)
        finally:
            service.unsubscribe_events(subscription_id)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/skills/list")
async def skills_list():
    """列出所有可用 skill，供前端 @/ 补全菜单使用。

    返回 { skills: [{ name, description, category }] }
    """
    from abstract.skills.loader import list_skills
    from system.application import Application
    from entity.constant import Namespace
    skills_dir = Application.current().get_system(ISandbox).get_base(Namespace.SKILLS)
    if not skills_dir.exists():
        return {"skills": [], "total": 0}
    skills = list_skills(skills_dir=skills_dir)
    return {
        "skills": [
            {
                "name": s["name"],
                "description": s.get("description", ""),
                "category": s.get("category"),
            }
            for s in skills
        ],
        "total": len(skills),
    }


@router.get("/api/llm/clients")
async def list_llm_clients_endpoint():
    """返回可用的 LLM 客户端实现列表。"""
    from abstract.llm.loader import list_llm_clients
    return {"clients": list_llm_clients()}


@router.get("/api/llm/profiles")
async def get_llm_profiles():
    """返回共享 v2 根对象的扁平 Profile 列表。"""
    from system.application import Application
    store = Application.current().get_system(ILLMProfileStore)
    return {
        "profiles": [
            store.to_payload(profile)
            for profile in store.list_profiles()
        ]
    }


@router.post("/api/llm/profiles", response_model=LLMProfileMutationResponse)
async def create_llm_profile(payload: LLMProfilePayload):
    """创建单个 LLM Profile。"""
    from system.application import Application

    application = Application.current()
    store = application.get_system(ILLMProfileStore)
    try:
        with store.locked():
            profile = store.create_profile(payload)
            response_payload = store.to_payload(profile)
        return LLMProfileMutationResponse(profile=response_payload)
    except ProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ProfileConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.put("/api/llm/profiles", response_model=LLMProfileMutationResponse)
async def update_llm_profile(request: LLMProfileUpdateRequest):
    """原地更新单个 LLM Profile，并在重命名后广播名称变更。"""
    from entity.constant import SESSIONS_DIR_NAME
    from system.application import Application
    from system.session_store import SessionStore

    application = Application.current()
    store = application.get_system(ILLMProfileStore)
    metadata_service = application.get_system(ISessionMetadataService)
    old_name = request.profile_name
    try:
        with store.locked():
            profile = store.update_profile(
                old_name,
                request.profile,
            )
            # 根配置已提交，后续名称指针写入失败也不能保留旧客户端缓存。
            mgr = application.get_system(IApprovalSystem).backend_manager
            mgr.invalidate()
            new_name = profile.name
            if new_name != old_name:
                SessionStore(
                    application.get_system(IRuntimeSystem).context.workspace / SESSIONS_DIR_NAME
                ).replace_profile_name_pointers(old_name, new_name)
            response_payload = store.to_payload(profile)
            metadata_state = metadata_service.get_state()
            toolchain_summary_state = metadata_service.get_toolchain_summary_state()
            modality_states = _get_modality_profile_states(application)
        failures: list[str] = []
        if new_name != old_name:
            failures = await application.get_system(IFrontendSink).broadcast_profile_change(
                "renamed", old_name, new_name,
            )
        # 广播审批 Profile 状态变更
        approval_state = mgr.get_state()
        approval_failures = await application.get_system(IFrontendSink).broadcast_approval_profile_change(
            approval_state,
        )
        metadata_failures = await application.get_system(IFrontendSink).broadcast_metadata_profile_change(
            metadata_state,
        )
        toolchain_summary_failures = await application.get_system(IFrontendSink).broadcast_toolchain_summary_profile_change(
            toolchain_summary_state,
        )
        modality_failures = await application.get_system(IFrontendSink).broadcast_modality_profile_change(
            modality_states,
        )
        return LLMProfileMutationResponse(
            profile=response_payload,
            notification_failures=(
                failures + approval_failures + metadata_failures
                + toolchain_summary_failures + modality_failures
            ),
        )
    except ProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ProfileConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.delete("/api/llm/profiles", response_model=LLMProfileDeleteResult)
async def delete_llm_profile(request: LLMProfileDeleteRequest):
    """删除 Profile，并只切换当前空闲的受影响主会话。"""
    from entity.constant import SESSIONS_DIR_NAME
    from system.application import Application
    from system.session_store import SessionStore

    application = Application.current()
    store = application.get_system(ILLMProfileStore)
    metadata_service = application.get_system(ISessionMetadataService)
    try:
        with store.locked():
            source = store.get_profile(request.profile_name)
            replacement = (
                store.get_profile(request.replacement_profile_name)
                if request.replacement_profile_name is not None else None
            )
            if replacement is source:
                raise ProfileConflictError("replacement Profile must differ from deleted Profile")
            # 先检查所有阻止删除的引用，再提交删除与审批/元数据/工具链摘要引用清空。
            store.assert_removable(source, clear_global_selections=True)
            store.remove_profile(request.profile_name, clear_global_selections=True)
            application.get_system(IApprovalSystem).backend_manager.invalidate()
            switched, busy = application.get_system(ISessionManager).replace_idle_loops_using_profile(
                source,
                replacement,
            )
            SessionStore(
                application.get_system(IRuntimeSystem).context.workspace / SESSIONS_DIR_NAME
            ).replace_profile_name_pointers(
                request.profile_name,
                request.replacement_profile_name,
            )
            metadata_state = metadata_service.get_state()
            toolchain_summary_state = metadata_service.get_toolchain_summary_state()
            modality_states = _get_modality_profile_states(application)

        failures = await application.get_system(IFrontendSink).broadcast_profile_change(
            "deleted",
            request.profile_name,
            request.replacement_profile_name,
        )
        # 广播审批 Profile 状态变更
        approval_state = application.get_system(IApprovalSystem).backend_manager.get_state()
        approval_failures = await application.get_system(IFrontendSink).broadcast_approval_profile_change(
            approval_state,
        )
        metadata_failures = await application.get_system(IFrontendSink).broadcast_metadata_profile_change(
            metadata_state,
        )
        toolchain_summary_failures = await application.get_system(IFrontendSink).broadcast_toolchain_summary_profile_change(
            toolchain_summary_state,
        )
        modality_failures = await application.get_system(IFrontendSink).broadcast_modality_profile_change(
            modality_states,
        )
        return LLMProfileDeleteResult(
            deleted=True,
            profile_name=request.profile_name,
            replacement_profile_name=request.replacement_profile_name,
            switched_sessions=switched,
            pending_sessions=busy,
            notification_failures=(
                failures + approval_failures + metadata_failures
                + toolchain_summary_failures + modality_failures
            ),
        )
    except ProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ProfileConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    """SPA 客户端路由的兜底处理。

    必须在所有 API 路由之后定义，确保 API 优先匹配。
    若请求路径对应 dist/ 下的真实文件（如 icon.ico），直接返回该文件；
    否则返回构建后的 index.html，前端未构建时返回 404。
    """
    # 先尝试作为 dist/ 下的静态文件返回（favicon 等 public 资源）
    candidate: Path = _FRONTEND_DIST / full_path
    if full_path and candidate.is_file():
        media_type = _guess_media_type_with_charset(candidate)
        return FileResponse(str(candidate), media_type=media_type, headers=_NO_CACHE)
    index_html: Path = _FRONTEND_DIST / "index.html"
    if index_html.exists():
        return HTMLResponse(
            index_html.read_text(encoding="utf-8"),
            headers=_NO_CACHE,
        )
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail=f"Not found: {full_path}")


async def _send_approval_mode_state(ws: WebSocket, session_id: str) -> None:
    """向当前连接发送该会话的权威审批模式。"""
    from component.approval import ApprovalMode, get_approval_mode

    mode = get_approval_mode(session_id)
    await ws.send_text(
        Message(
            type=MessageType.HANDSFREE_MODE,
            session_id=session_id,
            handsfree_mode=mode == ApprovalMode.HANDSFREE,
            approval_mode=mode.value,
        ).model_dump_json(exclude_none=True)
    )


async def _send_agentspace_ws_event(
    ws: WebSocket,
    session_id: str,
    event: AgentspaceEvent,
) -> None:
    """通过聊天 WebSocket 发送 typed Agentspace 事件。"""
    await ws.send_text(
        Message(
            type=MessageType.AGENTSPACE_EVENT,
            session_id=session_id,
            agentspace_event=event,
        ).model_dump_json(exclude_none=True)
    )


@router.websocket("/ws/chat")
async def ws_chat(ws: WebSocket) -> None:
    """WebSocket 聊天端点：接收用户消息，转发给 AgentLoop，返回回复。"""
    from system.application import Application
    from system.lifecycle import ApplicationStoppingError, LifecycleFailure

    gateway = _gateway()
    try:
        with gateway.admission.admit_connection():
            pass
    except ApplicationStoppingError:
        logger.info("WebSocket rejected (application shutting down)")
        raise WebSocketException(code=1001, reason="shutting_down")

    # 在 accept 之前解析 query string
    qs: dict[str, list[str]] = parse_qs(ws.scope.get("query_string", b"").decode())
    resume: str | None = qs.get("resume", [None])[0]
    conn_token: str | None = qs.get("conn_token", [None])[0]
    sid: str
    sm = _get_sm()
    if resume:
        if sm.is_session_deleting(resume):
            logger.info("WebSocket rejected (session deleting) | session=%s", resume)
            raise WebSocketException(
                code=WEBSOCKET_CLOSE_SESSION_DELETED,
                reason="session_deleted",
            )
        if not sm.exists(resume):
            # 防御性地从磁盘重新加载一次；仍不存在时禁止把旧 ID 转成随机新会话。
            sm.load_from_disk()
        if not sm.exists(resume) or sm.is_session_deleting(resume):
            logger.info("WebSocket rejected (session missing) | session=%s", resume)
            raise WebSocketException(
                code=WEBSOCKET_CLOSE_SESSION_DELETED,
                reason="session_deleted",
            )
        sid = resume
    else:
        sid = sm.create()

    # 会话占用检查 — 握手前拒绝。
    # 使用 WebSocketException 而非 ws.close()，因为 close()-before-accept()
    # 的行为在不同 Starlette 版本中不一致，WebSocketException 是官方推荐的
    # 握手拒绝方式，版本无关。
    from system.application import Application as _AppLock
    _sink = _AppLock.current().get_system(IFrontendSink)
    if _sink.is_session_occupied(sid, conn_token):
        logger.info("WebSocket rejected (session locked) | session=%s", sid)
        raise WebSocketException(code=4001, reason="session_locked")

    # 通过检查 → accept；accept 会让出事件循环，因此注册前再次确认删除与关闭状态。
    await ws.accept()
    if sm.is_session_deleting(sid) or not sm.exists(sid):
        logger.info("WebSocket closed after accept (session deleted) | session=%s", sid)
        await ws.close(
            code=WEBSOCKET_CLOSE_SESSION_DELETED,
            reason="session_deleted",
        )
        return
    try:
        _sink.register_ws(sid, ws, conn_token or "")
    except ApplicationStoppingError:
        await ws.close(code=1001, reason="shutting_down")
        return
    logger.info("WebSocket connected | session=%s", sid)

    agentspace_subscription_id: str | None = None
    agentspace_event_task: asyncio.Task[None] | None = None

    try:
        # 注册后的所有初始化都属于本连接生命周期；失败也必须释放连接登记。
        client_ip = ws.client.host if ws.client else ""
        if client_ip:
            existing = sm.get_client_info(sid)
            sm.set_client_info(
                sid,
                existing.model_copy(update={"client_ip": client_ip})
                if existing else ClientInfo(client_ip=client_ip),
            )

        from system.application import Application
        from entity.constant import SESSIONS_DIR_NAME
        application = Application.current()
        application.get_system(ISessionManager).create_session(
            session_id=sid,
            frontend_sink=application.get_system(IFrontendSink),
            history_store_dir=application.get_system(IRuntimeSystem).context.workspace / SESSIONS_DIR_NAME,
        )
        # 发送欢迎消息
        await ws.send_text(
            json.dumps(
                Message(
                    type=MessageType.SYSTEM,
                    session_id=sid,
                    content="Connected to Evolve Agent",
                ).model_dump(exclude_none=True),
                ensure_ascii=False,
            )
        )

        # 发送构建哈希，使前端能检测进化并自动重载
        build_hash: str = ws.app.state.build_hash
        if build_hash:
            await ws.send_text(
                json.dumps(
                    Message(
                        type=MessageType.SYSTEM,
                        session_id=sid,
                        content=json.dumps({"build_hash": build_hash}),
                    ).model_dump(exclude_none=True),
                    ensure_ascii=False,
                )
            )

        # 服务端状态构造失败直接终止连接，不继续提供不完整的握手状态。
        state = application.get_system(IApprovalSystem).backend_manager.get_state()
        await ws.send_text(
            Message(
                type=MessageType.SYSTEM,
                session_id=sid,
                content=json.dumps({
                    "server_info": {
                        "approval_model_name": state.profile_name or "",
                        "approval_model_available": state.available,
                    },
                }),
            ).model_dump_json(exclude_none=True)
        )

        # 新会话与恢复会话均主动同步会话级权威审批模式。
        await _send_approval_mode_state(ws, sid)

        # 新会话与恢复会话都只推送正典历史元数据；正文由 REST 按需读取。
        loop = _get_loop(sid)
        if loop is not None:
            agents_info: list[str] | None = None
            from entry.multi_agent_loop import MultiAgentLoop
            if isinstance(loop, MultiAgentLoop):
                agents_info = list(loop.get_agents().keys())
            await ws.send_text(
                json.dumps(
                    Message(
                        type=MessageType.HISTORY_SYNC,
                        session_id=sid,
                        history_count=loop.loop.history.count,
                        processing=loop.loop.is_active(),
                        token_usage=loop.get_token_usage(),
                        context_tokens=loop.get_context_tokens(),
                        agents=agents_info,
                    ).model_dump(exclude_none=True),
                    ensure_ascii=False,
                )
            )

        # 聊天页通过现有 WebSocket 接收 Agentspace 变化；订阅失败直接传播。
        agentspace_service = _agentspace_service()

        async def _send_current_agentspace_event(event: AgentspaceEvent) -> None:
            # 预检：close 帧已发出后 Starlette 抛 RuntimeError 而非
            # WebSocketDisconnect，故先用状态判定让已死连接稳定落入哨兵。
            if ws.application_state is WebSocketState.DISCONNECTED:
                raise AgentspaceConnectionClosed(
                    f"agentspace connection closed | session={sid}"
                )
            try:
                await _send_agentspace_ws_event(ws, sid, event)
            except (WebSocketDisconnect, ConnectionResetError, BrokenPipeError) as exc:
                raise AgentspaceConnectionClosed(
                    f"agentspace send failed on closed connection | session={sid}"
                ) from exc
            except RuntimeError:
                # 仅当连接确已断开时才归类为连接级结束；其余 RuntimeError
                # 属于序列化/协议错误，必须原样传播。
                if ws.application_state is not WebSocketState.DISCONNECTED:
                    raise
                raise AgentspaceConnectionClosed(
                    f"agentspace send raced with connection close | session={sid}"
                )

        agentspace_subscription_id, agentspace_event_task = await attach_agentspace_events(
            agentspace_service,
            _send_current_agentspace_event,
            connection_label=conn_token or sid,
        )

        def _close_on_agentspace_failure(task: asyncio.Task[None]) -> None:
            if task.cancelled():
                return
            failure = task.exception()
            if failure is None:
                return
            # 判定顺序不可交换：AgentspaceSendTimeout 同时满足两个判定，
            # 必须先判驱逐，否则慢消费者会被静默收尾而失去 1011 驱逐能力。
            if requires_connection_eviction(failure):
                # 例常的连接级驱逐：标记预期失败，不触发应用失败关闭。
                try:
                    gateway.task_owner.mark_expected_failure(task)
                except LifecycleFailure:
                    # Owner 已在关闭收尾；应用本就停止中，无需标记。
                    pass
                logger.warning(
                    "Agentspace WebSocket send timeout; evicting slow connection | session=%s",
                    sid,
                )
            elif is_connection_termination(failure):
                # 对端已断开：只做连接级静默收尾，不发送关闭帧（发送必然
                # 失败），连接与订阅登记由 ws_chat 的 finally 统一回收。
                try:
                    gateway.task_owner.mark_expected_failure(task)
                except LifecycleFailure:
                    pass
                logger.info(
                    "Agentspace WebSocket peer disconnected | session=%s", sid,
                )
            else:
                logger.error(
                    "Agentspace WebSocket forwarding failed | session=%s",
                    sid,
                    exc_info=(type(failure), failure, failure.__traceback__),
                )
            if ws.application_state is WebSocketState.DISCONNECTED:
                # 连接已消失：再发关闭帧只会产生二次异常。
                return
            try:
                gateway.spawn_work(
                    ws.close(code=1011, reason="agentspace_event_forward_failed"),
                    name=f"agentspace-ws-close-{sid[:8]}",
                )
            except LifecycleFailure:
                # Gateway 已在关闭：连接会随 stop_server 统一结束。
                logger.info("Gateway closing; skip agentspace failure close | session=%s", sid)

        # 本回调必须先于下方 task_owner.track 注册：done_callback 按注册顺序
        # 执行，标记预期失败须在 Owner 的结算回调读取前完成。
        agentspace_event_task.add_done_callback(_close_on_agentspace_failure)
        gateway.task_owner.track(agentspace_event_task)

        # 创建消息路由器 — 所有消息处理委托给 MessageRouter
        router = MessageRouter(ws, sid, conn_token=conn_token or "")

        while True:
            # 优雅关闭时 uvicorn 会关闭 WebSocket；超时强制取消时
            # CancelledError 由下方处理，避免干扰正常关闭日志。
            raw: str = await ws.receive_text()

            # 每条输入都检查应用接收状态，不只在握手时检查。
            try:
                gateway.admission.require_open_connection()
            except ApplicationStoppingError:
                await ws.close(code=1001, reason="shutting_down")
                return

            # 解析接收到的消息
            msg: Message
            try:
                msg = Message.model_validate_json(raw)
            except ValidationError as exc:
                await ws.send_text(
                    json.dumps(
                        Message(
                            type=MessageType.ERROR,
                            session_id=sid,
                            message=f"Invalid message: {exc}",
                        ).model_dump(exclude_none=True),
                        ensure_ascii=False,
                    )
                )
                continue

            ok: bool = await router.route(msg)
            if not ok:
                return
            # session 旋转后同步 sid
            sid = router.sid

    except (WebSocketDisconnect, AgentspaceConnectionClosed):
        logger.info("WebSocket disconnected | session=%s", sid)
    except asyncio.CancelledError:
        logger.debug("WebSocket handler cancelled for session=%s (server shutting down)", sid)
        raise
    finally:
        try:
            await detach_agentspace_events(
                _agentspace_service(),
                agentspace_subscription_id,
                agentspace_event_task,
            )
        finally:
            from system.application import Application
            sink = Application.current().get_system(IFrontendSink)
            # 旧连接释放不得取消已经接管该会话的新连接的交互。
            # unregister_ws 自身已拒绝该会话的待处理审批与提问，无需另行调用内部方法。
            if _get_ws(sid) is ws:
                sink.unregister_ws(sid)


# ---------------------------------------------------------------------------
# 端口探测与运行实例由 GatewaySystem 持有（gateway/system.py）
# ---------------------------------------------------------------------------