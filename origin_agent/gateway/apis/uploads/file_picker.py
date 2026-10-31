"""Native local file picker and uploads."""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import textwrap
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fastapi import APIRouter
from entity.constant import GatewayErrorCode, SUBPROCESS_TIMEOUT_DEFAULT, UPLOADS_DIR_NAME, UPLOADS_WS_PREFIX, UPLOAD_FILENAME_TIME_FORMAT
from gateway.http_boundary import business_http_error, require_business_http
from interface.api_component import APIComponent
from interface.runtime_system import IRuntimeSystem

logger = logging.getLogger(__name__)


class FilePickerAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/file-picker", self.handler, methods=["POST"], name="file_picker")

    async def handler(self) -> dict[str, Any]:
        """Open the native local picker and hardlink or copy selected files into uploads."""
        script = textwrap.dedent("""\
        import json, tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        files = filedialog.askopenfilenames(title="Select files to upload")
        root.destroy()
        print(json.dumps(list(files)))
        """)
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, lambda: subprocess.run(
                [sys.executable, "-c", script], capture_output=True, text=True,
                timeout=SUBPROCESS_TIMEOUT_DEFAULT,
            ))
            if result.returncode != 0:
                logger.warning("File dialog subprocess failed: %s", result.stderr.strip())
                raise business_http_error(502, GatewayErrorCode.FILE_PICKER_FAILED, "File picker failed")
            paths: list[str] = json.loads(result.stdout.strip())
        except subprocess.TimeoutExpired as exc:
            logger.warning("File dialog subprocess timed out")
            raise business_http_error(408, GatewayErrorCode.FILE_PICKER_TIMEOUT, "File picker timed out") from exc
        if not paths:
            return {"uploaded": False, "files": []}
        require_business_http(self.gateway.admission)
        upload_dir = self.get_system(IRuntimeSystem).context.agentspace / UPLOADS_DIR_NAME
        upload_dir.mkdir(parents=True, exist_ok=True)
        results: list[dict[str, Any]] = []
        for path in paths:
            src = Path(path)
            if not src.is_file():
                continue
            safe_name = src.name
            timestamp = datetime.now(timezone.utc).strftime(UPLOAD_FILENAME_TIME_FORMAT)
            unique_name = f"{timestamp}_{uuid.uuid4().hex[:8]}_{safe_name}"
            dest = upload_dir / unique_name
            method = "hardlink"
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
            results.append({"uploaded": True, "path": f"{UPLOADS_WS_PREFIX}{unique_name}", "filename": safe_name, "size": dest.stat().st_size, "method": method})
        return {"uploaded": True, "files": results}


api = FilePickerAPI()
