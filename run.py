import logging
import os
from pathlib import Path
import subprocess
import shutil
import sys
from datetime import datetime

from config import *

def quote(path) -> str:
    result = str(path)
    if path == "":
        return "\"\""
    return result

origin_agent_codes_path = Path("origin_agent")

# create directorys if they don't exist
if workspace_path.exists() == False:
    workspace_path.mkdir(parents=True, exist_ok=True)
if logs_path_name.exists() == False:
    logs_path_name.mkdir(parents=True, exist_ok=True)
if agentspace_path_name.exists() == False:
    agentspace_path_name.mkdir(parents=True, exist_ok=True)

log_file_path = logs_path_name / f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
file_stream = logging.FileHandler(log_file_path)
file_stream.setLevel(logging.DEBUG)
file_stream.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger = logging.getLogger(__name__)
logger.addHandler(file_stream)
logger.setLevel(logging.DEBUG)

if console_log:
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(stream_handler)

# add third party modules to path
'''
for module in Path("third").iterdir():
    logger.info(f"Checking {module} for third party directory")
    if module.is_dir():
        sys.path.append(str(module))
        logger.info(f"Try to import {module} module")
        try:
            __import__(module.name)
            logger.info(f"Successfully imported {module} module")
        except Exception as e:
            logger.error(f"Error importing {module} module: {e}")
    else:
        logger.error(f"{module} is not a directory")
'''


# ── git remote 收集（注入 system prompt）─────────────────────────────
def _collect_git_remotes() -> str:
    """读取宿主仓库 git remote（只读），失败返回空串。"""
    try:
        out = subprocess.run(
            ["git", "remote", "-v"],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        if out.returncode != 0:
            return ""
        lines, seen = [], set()
        for line in out.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                name, url = parts[0], parts[1].split(" ")[0]
                if (name, url) not in seen:
                    seen.add((name, url))
                    lines.append(f"{name}={url}")
        return "\n".join(lines)
    except Exception:
        return ""


git_remotes = _collect_git_remotes()

# ── evolution status journal ─────────────────────────────────────────
_EVOLVE_STATUS_PATH = logs_path_name / "evolution.status"


def _append_evolve_event(stage: str, detail: str) -> None:
    """Append a timestamped event to the evolution status file for frontend display."""
    import json as _json
    entry = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "stage": stage,
        "detail": detail,
    }
    try:
        existing = []
        if _EVOLVE_STATUS_PATH.exists():
            existing = _json.loads(_EVOLVE_STATUS_PATH.read_text(encoding="utf-8"))
        existing.append(entry)
        _EVOLVE_STATUS_PATH.write_text(
            _json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass  # non-critical


def _build_base_args():
    """构建 fast/fallback 共用的命令行参数列表"""
    return [
        "--workspace",              quote(workspace_path),
        "--agentspace",             quote(agentspace_path_name),
        "--log",                    quote(log_file_path),
        "--console_log",            quote(console_log),
        "--gateway_host",           quote(gateway_host),
        "--gateway_port",           quote(gateway_port),
        "--llm_base_url",           quote(llm_base_url),
        "--llm_model",              quote(llm_model),
        "--llm_api_key",            quote(llm_api_key),
        "--llm_max_context_tokens", quote(llm_max_context_tokens),
        "--llm_max_output_tokens",  quote(llm_max_output_tokens),
        "--llm_temperature",        quote(llm_temperature),
        "--llm_reasoning_effort",   quote(llm_reasoning_effort),
        "--client",                 quote(llm_client_name),
        "--mcp_config_path",        quote(mcp_config_path),
        "--approval_model_path",    quote(approval_model_path),
        "--approval_model_n_ctx",   quote(approval_model_n_ctx),
        "--approval_model_cuda",    quote(approval_model_cuda),
        "--approval_model_port",    quote(approval_model_port),
        "--approval_remote_base_url",   quote(approval_remote_base_url),
        "--approval_remote_api_key",    quote(approval_remote_api_key),
        "--approval_remote_model",      quote(approval_remote_model),
        "--approval_remote_client_name", quote(approval_remote_client_name),
        "--merge_concat_threshold",     quote(merge_concat_threshold),
        "--frontend_force_build",       quote("true" if frontend_force_build else "false"),
        "--git_remotes",                quote(git_remotes),
    ]


if __name__ == "__main__":
    fast_agent_space = (workspace_path/fast_agent_space_path)
    slow_agent_space = (workspace_path/slow_agent_space_path)
    source = Path(origin_agent_codes_path)
    if (agentspace_path_name / "SOUL.md").exists() == False:
        if Path("SOUL.md").exists():
            shutil.copy("SOUL.md", agentspace_path_name / "SOUL.md")
        else:
            (agentspace_path_name / "SOUL.md").touch() # 创建空SOUL.md文件
    if force_init:
        fallback_space = workspace_path / ".fallback"
        shutil.rmtree(slow_agent_space, ignore_errors=True) # 删除slow agent空间
        shutil.rmtree(fallback_space, ignore_errors=True) # 删除备份空间

        slow_agent_space.mkdir(parents=True, exist_ok=True) # 创建slow agent空间
        fast_agent_space.mkdir(parents=True, exist_ok=True) # 创建fast agent空间
        fallback_space.mkdir(parents=True, exist_ok=True) # 创建备份空间

        pnpm_lock_yaml = source/"frontend"/"pnpm-lock.yaml"
        if pnpm_lock_yaml.exists():
            pnpm_lock_yaml.unlink()

        shutil.copytree(source, fast_agent_space, dirs_exist_ok=True) # 复制源代码到fast agent空间
        shutil.copytree(source, slow_agent_space, dirs_exist_ok=True) # 复制源代码到slow agent空间
        shutil.copytree(source, fallback_space, dirs_exist_ok=True) # 复制源代码到备份空间
        
        fast_pnpm_lock_yaml = fast_agent_space/"frontend"/"pnpm-lock.yaml"
        if fast_pnpm_lock_yaml.exists():
            fast_pnpm_lock_yaml.unlink()
    elif (fast_agent_space / "__main__.py").exists() == False:
        fast_agent_space.mkdir(parents=True, exist_ok=True) # 创建fast agent空间
        pnpm_lock_yaml = source/"frontend"/"pnpm-lock.yaml"
        if pnpm_lock_yaml.exists():
            pnpm_lock_yaml.unlink()
        shutil.copytree(source, fast_agent_space, dirs_exist_ok=True) # 复制源代码到fast agent空间
        fast_pnpm_lock_yaml = fast_agent_space/"frontend"/"pnpm-lock.yaml"
        if fast_pnpm_lock_yaml.exists():
            fast_pnpm_lock_yaml.unlink()

    enable_fallback = force_init == False
    while True:
        logger.info(f"Running fast agent")
        try:
            task = subprocess.run([
                sys.executable,
                quote(fast_agent_space / "__main__.py"),
                *_build_base_args(),
                "--mode", "fast",
                "--evolve", quote(slow_agent_space),
            ])
        except KeyboardInterrupt:
            logger.info("Interrupted by user (KeyboardInterrupt)")
            break
        exit_code = task.returncode
        if exit_code == 0:
            logger.info(f"Fast agent exited with code {exit_code}")
            break
        elif exit_code in (-1, 4294967295):
            logger.info(f"Slow agent was updated, fast agent will update to new version")
            enable_fallback = True
            _append_evolve_event("backup", f"fast → .fallback")
            # 不再尝试每次都删除备份空间，避免前端可能的重新下载
            # shutil.rmtree(workspace_path / ".fallback")
            shutil.copytree(fast_agent_space, workspace_path / ".fallback", dirs_exist_ok=True)

            _append_evolve_event("swap", f"slow → fast")
            # 不再尝试每次都删除代理空间，避免前端可能的重新下载
            # shutil.rmtree(fast_agent_space)
            shutil.copytree(slow_agent_space, fast_agent_space, dirs_exist_ok=True)

            _append_evolve_event("complete", "swap finished, restarting")
        else:
            logger.error(f"Fast agent exited with unknown error: {exit_code}")
            if not enable_fallback:
                logger.error(f"Fallback is not enabled because current fallback version is from force init, exiting")
                break
            if (workspace_path / ".fallback").exists() == False:
                shutil.copytree(source, workspace_path / ".fallback", dirs_exist_ok=True) # 复制源代码到备份空间
            fallback_main = workspace_path / ".fallback" / "__main__.py"
            if not fallback_main.exists():
                logger.warning(
                    "Fallback agent not found at %s — this is normal on first "
                    "initialisation. Exiting.",
                    fallback_main,
                )
                break
            logger.info(f"Running fallback agent")
            try:
                task = subprocess.run([
                    sys.executable,
                    quote(fallback_main),
                    *_build_base_args(),
                    "--mode", "fallback",
                    "--fix_fork", quote(fast_agent_space),
                    "--fix", quote(logs_path_name / "fast_agent_runtime_error.log"),
                ])
            except KeyboardInterrupt:
                logger.info("Interrupted by user (KeyboardInterrupt)")
                break
            if task.returncode == 0:
                logger.info(f"Fallback agent fixed successfully, restart...")
            else:
                logger.error(f"Fallback agent fixed failed, see {logs_path_name/"fallback_agent_runtime_error.log"}")
                break
            break
