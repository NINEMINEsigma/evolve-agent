"""Public sandbox file download."""

import re
from urllib.parse import quote
from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, Response
from entity.constant import DOWNLOADS_HTTP_PREFIX
from entity.error import SandboxError
from interface.api_component import APIComponent
from interface.sandbox import ISandbox


class DownloadWorkspaceFileAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route(DOWNLOADS_HTTP_PREFIX + "/{namespace}/{file_path:path}", self.handler, methods=["GET"], name="download_workspace_file")

    async def handler(self, namespace: str, file_path: str) -> Response:
        """Download a sandbox file with Content-Disposition attachment."""
        logical = f"{namespace}:{file_path}"
        try:
            resolved = self.get_system(ISandbox).resolve_read(logical)
        except SandboxError as exc:
            return HTMLResponse(str(exc), status_code=403)
        if not resolved.real.exists() or not resolved.real.is_file():
            return HTMLResponse("File not found", status_code=404)
        filename = resolved.real.name
        safe_ascii = re.sub(r'[^\x20-\x7e]', '_', filename)
        return FileResponse(str(resolved.real), media_type="application/octet-stream", headers={
            "Content-Disposition": f'attachment; filename="{safe_ascii}"; ' + f"filename*=UTF-8''{quote(filename, safe='')}",
        })
