"""Public sandbox file serving and visual probes."""

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from entity.constant import (
    HTTP_NO_CACHE_HEADERS, STATIC_FILE_HTTP_PREFIX, VISUAL_RAW_PARAM,
    VISUAL_PROBE_PARAM, VISUAL_SID_PARAM, VISUAL_KIND_PARAM,
    VISUAL_QUERY_ENABLED, VISUAL_VERSION_HEADER,
)
from entity.error import SandboxError, SessionVisualResourceError, SessionVisualVersionUnavailable
from entity.puretype import SessionVisualKind, SessionVisualSource, SessionVisualStatus
from gateway.frontend_assets import guess_media_type_with_charset
from interface.api_component import APIComponent
from interface.agentspace_service import IAgentspaceService
from interface.sandbox import ISandbox


class ServeWorkspaceFileAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route(STATIC_FILE_HTTP_PREFIX + "/{namespace}/{file_path:path}", self.handler, methods=["HEAD"], name="serve_workspace_file")
        router.add_api_route(STATIC_FILE_HTTP_PREFIX + "/{namespace}/{file_path:path}", self.handler, methods=["GET"], name="serve_workspace_file")

    def handler(self, namespace: str, file_path: str, request: Request) -> Response:
        """Resolve visual entries in the thread pool and independently validate final HEAD versions."""
        sandbox = self.get_system(ISandbox)
        service = self.get_system(IAgentspaceService).visual_resources
        logical = f"{namespace}:{file_path}"
        raw = request.query_params.get(VISUAL_RAW_PARAM) == VISUAL_QUERY_ENABLED
        probe = request.query_params.get(VISUAL_PROBE_PARAM) == VISUAL_QUERY_ENABLED
        headers = {**HTTP_NO_CACHE_HEADERS, "Cache-Control": "no-store"} if probe else dict(HTTP_NO_CACHE_HEADERS)
        state = None

        def failure(message: str, code: int) -> Response:
            return Response(content=b"" if request.method == "HEAD" else message, status_code=code, headers=headers, media_type="text/plain")

        try:
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
                            return RedirectResponse(url=service.build_entry_url(state, source=source if probe else None), status_code=307, headers={**HTTP_NO_CACHE_HEADERS, "Cache-Control": "no-store"})
            if probe and state is None:
                return failure("Invalid visual probe", 400)
            if not resolved.real.is_file():
                return failure("File not found", 404)
            with resolved.real.open("rb"):
                pass
            if probe and state is not None:
                headers[VISUAL_VERSION_HEADER] = service.get_version(state)
            media_type = guess_media_type_with_charset(resolved.real)
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
