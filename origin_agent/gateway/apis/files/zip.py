"""Public bounded directory ZIP download."""

import io
import os
import re
import stat as stat_module
import zipfile
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from entity.constant import DIR_ZIP_HTTP_PREFIX, DIR_ZIP_MAX_TOTAL_BYTES, VISUAL_RAW_PARAM, VISUAL_QUERY_ENABLED
from entity.error import SandboxError
from entity.puretype import SessionVisualKind
from interface.api_component import APIComponent
from interface.agentspace_service import IAgentspaceService
from interface.sandbox import ISandbox


class DownloadDirectoryZipAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route(DIR_ZIP_HTTP_PREFIX + "/{namespace}/{file_path:path}", self.handler, methods=["GET"], name="download_dir_zip")

    def handler(self, namespace: str, file_path: str, request: Request) -> Response:
        """Package a sandbox directory as ZIP in Starlette's synchronous thread pool."""
        logical = f"{namespace}:{file_path}"
        try:
            sandbox = self.get_system(ISandbox)
            resolved = sandbox.resolve_read(logical)
            if request.query_params.get(VISUAL_RAW_PARAM) != VISUAL_QUERY_ENABLED:
                service = self.get_system(IAgentspaceService).visual_resources
                source = service.match_source_directory(logical)
                if source is not None and source.kind == SessionVisualKind.site:
                    state = service.get_state(source.session_id, source.kind)
                    if state.redirected:
                        target = sandbox.resolve_read(state.effective_path)
                        if target.namespace != resolved.namespace or target.real != resolved.real:
                            target_ns, relative = state.effective_path.split(":", 1)
                            location = f"{DIR_ZIP_HTTP_PREFIX}/{quote(target_ns, safe='')}/{quote(relative, safe='/')}?{VISUAL_RAW_PARAM}={VISUAL_QUERY_ENABLED}"
                            return RedirectResponse(url=location, status_code=307, headers={"Cache-Control": "no-store"})
        except SandboxError:
            return HTMLResponse("Sandbox access denied", status_code=403)
        if not resolved.real.exists() or not resolved.real.is_dir():
            return HTMLResponse("Directory not found", status_code=404)
        files: list[tuple[Path, str]] = []
        total_size = 0
        root = resolved.real
        for dirpath, dirnames, filenames in os.walk(str(root), followlinks=False):
            # 不递归Windows junction，每个文件独立检查沙盒权限。
            dirnames[:] = [name for name in dirnames
                if not (Path(dirpath) / name).is_symlink()
                and not (os.name == "nt" and (Path(dirpath) / name).lstat().st_file_attributes & stat_module.FILE_ATTRIBUTE_REPARSE_POINT)]
            for fname in filenames:
                fpath = Path(dirpath) / fname
                relative = fpath.relative_to(root).as_posix()
                try:
                    sandbox.resolve_read(logical.rstrip("/") + "/" + relative)
                except SandboxError:
                    return HTMLResponse("Archive contains an inaccessible file", status_code=403)
                if not fpath.is_file():
                    continue
                arcname = str(fpath.relative_to(root.parent))
                files.append((fpath, arcname))
                total_size += fpath.stat().st_size
        if not files:
            return HTMLResponse("Directory is empty", status_code=404)
        if total_size > DIR_ZIP_MAX_TOTAL_BYTES:
            return HTMLResponse(f"Directory too large: {total_size} bytes exceeds limit {DIR_ZIP_MAX_TOTAL_BYTES}", status_code=413)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
            for fpath, arcname in files:
                archive.write(str(fpath), arcname)
        zip_filename = f"{root.name}.zip"
        safe_ascii = re.sub(r'[^\x20-\x7e]', '_', zip_filename)
        return Response(buf.getvalue(), media_type="application/zip", headers={
            "Content-Disposition": f'attachment; filename="{safe_ascii}"; ' + f"filename*=UTF-8''{quote(zip_filename, safe='')}",
        })


api = DownloadDirectoryZipAPI()
