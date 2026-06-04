"""Evolve Agent — 入口点。

按 run.py 编排器格式解析 CLI 参数（``--key value``，
合并为单个 sys.argv 元素），创建 RuntimeContext，
配置日志，启动异步 App。
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path
from system.pathutils import get_agent_dir

# 确保 agent 自身目录在 sys.path 最前面，使
# ``from main import App`` 和 ``from system.context import RuntimeContext``
# 无论 CWD 或进程启动方式如何都能正确解析。
# 这对编排器将 agent 源码复制到 workspace/fast_agent_space/ 时至关重要 —
# 目录名与 "origin_agent" 不同。
_AGENT_DIR: str = str(get_agent_dir())
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

from main import App  # noqa: E402
from system.context import RuntimeContext  # noqa: E402
from system.convert import as_bool


# ---------------------------------------------------------------------------
# CLI 解析（run.py 编排器格式）
# ---------------------------------------------------------------------------

def _parse_cli() -> dict:
    """从 sys.argv 解析 ``--key value`` 参数。

    格式：``--key value`` 作为两个独立的 sys.argv 条目。
    单独的 ``--flag``（无值）存储为 True。
    """
    parsed: dict = {}
    args: list[str] = sys.argv[1:]
    i: int = 0
    while i < len(args):
        arg: str = args[i]
        if arg.startswith("--"):
            body: str = arg[2:]
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                parsed[body] = args[i + 1].strip("\"'")
                i += 1
            else:
                parsed[body] = True
        i += 1
    return parsed


# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------

def _setup_logging(log_path: str | None, console: bool) -> None:
    """使用文件 handler 和可选的终端 handler 配置根 logger。"""
    root: logging.Logger = logging.getLogger()
    root.setLevel(logging.DEBUG)
    fmt: logging.Formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        fh: logging.FileHandler = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        root.addHandler(fh)

    if console:
        ch: logging.StreamHandler = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        root.addHandler(ch)


# ---------------------------------------------------------------------------
# 上下文构建器
# ---------------------------------------------------------------------------


def _build_context(cli: dict) -> RuntimeContext:
    """从解析后的 CLI 参数构建 RuntimeContext。

    路径解析为绝对形式，下游代码无需关心 CWD 变化。
    """
    return RuntimeContext(
        workspace       = Path(cli["workspace"]).resolve(),
        agentspace      = Path(cli["agentspace"]).resolve(),
        fork_path       = Path(cli["evolve"]).resolve(),
        log_path        = Path(cli["log"]).resolve(),
        mode            = str(cli["mode"]),
        console_log     = as_bool(cli["console_log"]),
        gateway_host    = str(cli["gateway_host"]),
        gateway_port    = int(cli["gateway_port"]),
        # 仅 fallback 模式字段
        fix_path=(
            Path(cli["fix_fork"]).resolve() if "fix_fork" in cli else None
        ),
        fix_log_path=(
            Path(cli["fix"]).resolve() if "fix" in cli else None
        ),
        # LLM 配置 — env var 覆盖 CLI 参数，CLI 参数覆盖默认值
        llm_api_key=(
            os.environ.get("OPENAI_API_KEY", "")
            or str(cli.get("llm_api_key", ""))
        ),
        llm_base_url=(
            os.environ.get("OPENAI_BASE_URL", "")
            or str(cli.get("llm_base_url", ""))
        ),
        llm_model=(
            os.environ.get("LLM_MODEL", "")
            or str(cli.get("llm_model", ""))
        ),
        llm_max_context_tokens  = int(cli["llm_max_context_tokens"]),
        llm_max_output_tokens   = int(cli["llm_max_output_tokens"]),
        llm_reasoning_effort    = str(cli["llm_reasoning_effort"]),
        # 冒险模式审批模型配置
        approval_model_path     = str(cli.get("approval_model_path", "")),
        approval_model_n_ctx    = int(cli.get("approval_model_n_ctx", 4096)),
        approval_model_cuda     = as_bool(cli.get("approval_model_cuda", False)),
        mcp_config_path         = cli["mcp_config_path"],
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _build_frontend() -> bool:
    """在前端目录中运行 ``pnpm install && pnpm run build``。

    前端位于 *AGENT_DIR* 下（例如 ``origin_agent/frontend/`` 或
    ``workspace/fast_agent_space/frontend/``）。构建输出写入
    ``frontend/dist/``，由 gateway 提供服务。

    返回 True 表示构建成功或无前端存在。
    """
    frontend_dir: Path = Path(_AGENT_DIR) / "frontend"
    pkg_json: Path = frontend_dir / "package.json"
    if not pkg_json.exists():
        return True  # 无前端需要构建

    logger: logging.Logger = logging.getLogger("agent.frontend")
    logger.info("Building frontend in %s ...", frontend_dir)

    try:
        pnpm: str = "pnpm.cmd" if sys.platform == "win32" else "pnpm"
        # pnpm install
        install_proc = subprocess.run(
            [pnpm, "install"],
            cwd=str(frontend_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        install_proc.check_returncode()
        # pnpm run build
        build_proc = subprocess.run(
            [pnpm, "run", "build"],
            cwd=str(frontend_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        build_proc.check_returncode()
        # 将构建输出打入日志，便于诊断构建时长和结果
        build_lines: list[str] = build_proc.stdout.strip().split("\n")
        logger.info("Frontend build output:\n%s", "\n".join(build_lines))
        logger.info("Frontend build complete → %s", frontend_dir / "dist")
        return True
    except subprocess.CalledProcessError as exc:
        detail: str = (exc.stderr or exc.stdout or "").strip()
        logger.error("Frontend build FAILED: %s", detail)
        return False
    except FileNotFoundError:
        logger.warning("pnpm not found — skipping frontend build")
        return True  # 非致命


def main() -> int:
    cli: dict = _parse_cli()
    ctx: RuntimeContext = _build_context(cli)
    from system.context import set_runtime_context
    set_runtime_context(ctx)

    # 仅当通过 --log 显式请求时才创建日志文件。
    log_target: str | None = str(ctx.log_path) if "log" in cli else None
    _setup_logging(log_target, ctx.console_log)

    # 压制第三方库的冗余 debug 日志
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logger: logging.Logger = logging.getLogger("agent")
    logger.info(
        "Evolve Agent starting | mode=%s workspace=%s agentspace=%s",
        ctx.mode, ctx.workspace, ctx.agentspace,
    )

    # ---- 构建前端（失败则致命）----
    if not _build_frontend():
        logger.critical("Frontend build FAILED — aborting start")
        return 1  # 非零，非(-1) → 触发 run.py fallback 分支

    app: App = App(ctx)
    exit_code: int
    try:
        exit_code = asyncio.run(app.run())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        exit_code = 0

    logger.info("Evolve Agent exiting | code=%d", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())