"""Native dynamic sandbox directory picker."""

import asyncio
import json
import logging
import subprocess
import sys
from typing import Any
from fastapi import APIRouter
from entity.constant import GatewayErrorCode, SUBPROCESS_TIMEOUT_DEFAULT
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent

logger = logging.getLogger(__name__)


class PickSandboxDirectoryAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sandbox-spaces/pick-directory", self.handler, methods=["POST"], name="pick_sandbox_directory")

    async def handler(self) -> dict[str, Any]:
        script = "\n".join([
            "import json, tkinter as tk", "from tkinter import filedialog",
            "root = tk.Tk()", "root.withdraw()", "root.attributes('-topmost', True)",
            "selected = filedialog.askdirectory(title='Select dynamic sandbox directory')",
            "root.destroy()", "print(json.dumps(selected))",
        ])
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, lambda: subprocess.run(
                [sys.executable, "-c", script], capture_output=True, text=True,
                timeout=SUBPROCESS_TIMEOUT_DEFAULT,
            ))
        except subprocess.TimeoutExpired as exc:
            raise business_http_error(408, GatewayErrorCode.DIRECTORY_PICKER_TIMEOUT, "Directory picker timed out") from exc
        if result.returncode != 0:
            logger.warning("Dynamic sandbox directory picker subprocess failed: %s", result.stderr.strip())
            raise business_http_error(502, GatewayErrorCode.DIRECTORY_PICKER_FAILED, "Directory picker failed")
        selected = json.loads(result.stdout.strip())
        if not selected:
            return {"selected": False, "path": None}
        return {"selected": True, "path": selected}


api = PickSandboxDirectoryAPI()
