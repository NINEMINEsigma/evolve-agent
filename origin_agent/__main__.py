"""Evolve Agent — 入口点。

按 run.py 编排器格式解析 CLI 参数（``--key value``，
合并为单个 sys.argv 元素），创建 RuntimeContext，
配置日志，启动异步 App。
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from system.pathutils import get_agent_dir, find_repo_root

# 确保 agent 自身目录在 sys.path 最前面，使
# ``from main import App`` 和 ``from system.context import RuntimeContext``
# 无论 CWD 或进程启动方式如何都能正确解析。
# 这对编排器将 agent 源码复制到 workspace/fast_agent_space/ 时至关重要 —
# 目录名与 "origin_agent" 不同。
_AGENT_DIR: str = str(get_agent_dir())
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

# 将 third-party 包目录加入 sys.path，使 ``from easysave import ...``
# 等第三方依赖在任意模块中都能直接导入，避免每个模块重复注入路径。
_THIRD_DIR: Path = find_repo_root() / "third"
for _p in (_THIRD_DIR, _THIRD_DIR / "easysave"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from main import App  # noqa: E402
from system.context import RuntimeContext  # noqa: E402
from system.convert import as_bool
from entity.constant import APPROVAL_MODEL_N_CTX_DEFAULT


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

    # 让 uvicorn 的 logger 向根 logger 传播，确保 ASGI 异常进入文件日志。
    for uvicorn_logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(uvicorn_logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True


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
        fork_path       = Path(cli["evolve"]).resolve() if "evolve" in cli else Path(cli["workspace"]).resolve() / "slow_agent_space",
        skills_path     = (find_repo_root() / "skills").resolve(),
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
        # LLM 配置 — 直接从 CLI 参数读取（config.py/run.py 已处理默认值）
        llm_api_key             = str(cli.get("llm_api_key", "")),
        llm_base_url            = str(cli.get("llm_base_url", "")),
        llm_model               = str(cli.get("llm_model", "")),
        llm_max_context_tokens  = int(cli["llm_max_context_tokens"]),
        llm_max_output_tokens   = int(cli["llm_max_output_tokens"]),
        llm_reasoning_effort    = str(cli["llm_reasoning_effort"]),
        # 脱手模式审批模型配置
        approval_model_path     = str(cli.get("approval_model_path", "")),
        approval_model_n_ctx    = int(cli.get("approval_model_n_ctx", APPROVAL_MODEL_N_CTX_DEFAULT)),
        approval_model_cuda     = as_bool(cli.get("approval_model_cuda", False)),
        approval_model_port     = int(cli.get("approval_model_port", 8081)),
        approval_remote_base_url= str(cli.get("approval_remote_base_url", "")),
        approval_remote_api_key = str(cli.get("approval_remote_api_key", "")),
        approval_remote_model   = str(cli.get("approval_remote_model", "")),
        mcp_config_path         = cli["mcp_config_path"],
        # 会话合并配置
        merge_concat_threshold  = int(cli.get("merge_concat_threshold", 50000)),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# ── 前端构建签名 ──────────────────────────────────────────────────────

_SIGNATURE_FILE = ".frontend_build_signature.json"

# 签名源文件清单（相对 frontend_dir）
_SIGNATURE_SOURCES = [
    "package.json",
    ".npmrc",
    "pnpm-workspace.yaml",
    "tsconfig.json",
    "tsconfig.app.json",
    "tsconfig.node.json",
    "vite.config.ts",
    "index.html",
]


def _compute_frontend_signature(frontend_dir: Path) -> str:
    """计算 frontend 构建输入的确定性签名。

    对每个源文件计算 ``sha256(relpath + "\\0" + bytes)``，
    按哈希值字典序排序后聚合为最终签名字符串。

    不存在的可选文件（如 public/）直接跳过；
    读取失败时抛异常由调用方处理（触发强制重建）。
    """
    logger = logging.getLogger("agent.frontend.signature")
    hasher = hashlib.sha256()
    file_hashes: list[str] = []

    def _hash_file(file_path: Path) -> None:
        """对文件内容做 sha256，将 hex 加入列表。"""
        file_hash = hashlib.sha256()
        # 相对路径 + 分隔符 + 文件内容，确保重命名也会导致签名变化
        rel = file_path.relative_to(frontend_dir).as_posix()
        file_hash.update(rel.encode("utf-8"))
        file_hash.update(b"\0")
        file_hash.update(file_path.read_bytes())
        file_hashes.append(file_hash.hexdigest())

    # 根目录级的签名源文件
    for name in _SIGNATURE_SOURCES:
        fp = frontend_dir / name
        if fp.is_file():
            _hash_file(fp)

    # src/ 目录下的所有文件（递归）
    src_dir = frontend_dir / "src"
    if src_dir.is_dir():
        for fp in sorted(src_dir.rglob("*")):
            if fp.is_file() and fp.name != _SIGNATURE_FILE:
                _hash_file(fp)

    # public/ 目录（可选）
    public_dir = frontend_dir / "public"
    if public_dir.is_dir():
        for fp in sorted(public_dir.rglob("*")):
            if fp.is_file():
                _hash_file(fp)

    # 排序后聚合成最终签名
    file_hashes.sort()
    for h in file_hashes:
        hasher.update(h.encode("utf-8"))
        hasher.update(b"\n")
    final = hasher.hexdigest()
    logger.debug("Computed signature: %s (%d source files)", final[:16], len(file_hashes))
    return final


def _read_build_signature(frontend_dir: Path) -> str | None:
    """读取之前保存的构建签名。

    文件不存在或 JSON 格式错误时返回 None。
    """
    sig_file = frontend_dir / _SIGNATURE_FILE
    if not sig_file.is_file():
        return None
    try:
        data = json.loads(sig_file.read_text(encoding="utf-8"))
        return data.get("signature")
    except (json.JSONDecodeError, KeyError):
        return None


def _write_build_signature(frontend_dir: Path, signature: str) -> None:
    """写入构建签名到隐藏文件。"""
    sig_file = frontend_dir / _SIGNATURE_FILE
    sig_file.write_text(
        json.dumps({"signature": signature}, ensure_ascii=False),
        encoding="utf-8",
    )


def _build_frontend(force: bool = False) -> bool:
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

    # ── 签名检查：不强制构建且签名匹配且产物存在时跳过 ──
    if not force:
        try:
            current_sig = _compute_frontend_signature(frontend_dir)
            stored_sig = _read_build_signature(frontend_dir)
            dist_index = frontend_dir / "dist" / "index.html"
            if stored_sig and current_sig == stored_sig and dist_index.is_file():
                logger.info("Frontend build up-to-date, skipping (%s source files matched)", frontend_dir)
                return True
        except Exception:
            # 签名计算失败（读取异常等）→ 回退到强制构建
            logger.debug("Signature check failed, will rebuild", exc_info=True)

    logger.info("Building frontend in %s ...", frontend_dir)

    def _log_output(proc: subprocess.CompletedProcess, label: str) -> None:
        """将子进程 stdout/stderr 写入 debug 日志流，确保落盘。"""
        for stream_name, stream in (("stdout", proc.stdout), ("stderr", proc.stderr)):
            if not stream:
                continue
            for line in stream.splitlines():
                if line.strip():
                    logger.debug("[%s] %s: %s", label, stream_name, line)

    try:
        pnpm: str = "pnpm.cmd" if sys.platform == "win32" else "pnpm"
        # 强制非交互模式：避免 pnpm 在子进程中弹出 ConfirmPrompt 导致 readline 崩溃
        env: dict[str, str] = {**os.environ, "CI": "true"}
        # pnpm install
        install_proc = subprocess.run(
            [pnpm, "install"],
            cwd=str(frontend_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        _log_output(install_proc, "install")
        install_proc.check_returncode()
        # pnpm run build
        build_proc = subprocess.run(
            [pnpm, "run", "build"],
            cwd=str(frontend_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        _log_output(build_proc, "build")
        build_proc.check_returncode()
        # 构建成功后写入签名，用于下次启动的比较
        try:
            sig = _compute_frontend_signature(frontend_dir)
            _write_build_signature(frontend_dir, sig)
        except Exception:
            logger.debug("Failed to write build signature", exc_info=True)
        logger.info("Frontend build complete → %s", frontend_dir / "dist")
        return True
    except subprocess.CalledProcessError as exc:
        # 即使 check_returncode 抛异常，之前 _log_output 已写入 debug 日志；
        # 若子进程解码失败，stdout/stderr 可能为 None，因此回退到对象属性
        out: str = ""
        if exc.stdout:
            out += exc.stdout
        if exc.stderr:
            out += "\n" + exc.stderr
        detail: str = out.strip()
        logger.error("Frontend build FAILED: %s", detail)
        return False
    except FileNotFoundError:
        logger.error("pnpm not found — frontend build is required")
        return False


def main() -> int:
    cli: dict = _parse_cli()
    ctx: RuntimeContext = _build_context(cli)
    from system.context import set_runtime_context
    set_runtime_context(ctx)

    # 创建运行时标志文件, 可供hook判断启动时间等
    runtime_flag_file: Path = ctx.workspace / "flag.json"
    with open(runtime_flag_file, "w", encoding="utf-8") as f:
        json.dump({
            "start_time": datetime.datetime.now().isoformat()
            }, f, ensure_ascii=False)    


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
    frontend_force_build = as_bool(cli.get("frontend_force_build", False))
    if not _build_frontend(force=frontend_force_build):
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