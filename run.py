import logging
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime

from config import *

workspace_path = Path("workspace")
logs_path = workspace_path / "logs"
origin_agent_codes_path = Path("origin_agent")

# create directorys if they don't exist
if workspace_path.exists() == False:
    workspace_path.mkdir(parents=True, exist_ok=True)
if logs_path.exists() == False:
    logs_path.mkdir(parents=True, exist_ok=True)

log_file_path = logs_path / f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
file_stream = logging.FileHandler(log_file_path)
file_stream.setLevel(logging.INFO)
file_stream.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger = logging.getLogger(__name__)
logger.addHandler(file_stream)
logger.setLevel(logging.INFO)

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
from third.filesystem import File


if __name__ == "__main__":
    if fouce_init or (workspace_path/"init.lock").exists() == False:
        fast_agent_space = (workspace_path/fast_agent_space_path)
        fast_agent_space.mkdir(parents=True, exist_ok=True)
        slow_agent_space = (workspace_path/slow_agent_space_path)
        slow_agent_space.mkdir(parents=True, exist_ok=True)
        source = File(origin=str(origin_agent_codes_path))
        source.copy_to(str(fast_agent_space))
        source.copy_to(str(slow_agent_space))
    while True:
        logger.info(f"Running fast agent")
        task = subprocess.run([
            sys.executable, # 使用当前python解释器
            str(fast_agent_space/"__main__.py"), # 运行fast agent
            f"--workspace {workspace_path}", # 工作空间路径
            f"--log {log_file_path}", # 日志路径
            f"--console_log {console_log}", # 是否在控制台打印日志
            f"--self {fast_agent_space}", # 自身代码路径
            f"--evolve {slow_agent_space}", # 需要进化的代码路径
            f"--mode fast" # 运行模式
        ])
        exit_code = task.returncode
        if exit_code == 0:
            logger.info(f"Fast agent exited with code {exit_code}")
            if (workspace_path/"init.lock").exists():
                (workspace_path/"init.lock").unlink()
            break
        elif exit_code in (-1,):
            logger.info(f"Slow agent was updated, fast agent will update to new version")
            File(str(workspace_path/".fallback")).delete()
            File(str(fast_agent_space)).copy_to(str(workspace_path/".fallback"))
            File(str(slow_agent_space)).copy_to(str(fast_agent_space))
        else:
            logger.error(f"Fast agent exited with unknown error: {exit_code}")
            logger.info(f"Running fallback agent")
            task = subprocess.run([
                sys.executable, # 使用当前python解释器
                str(workspace_path/".fallback"/"__main__.py"), # 运行fallback agent
                f"--workspace {workspace_path}", # 工作空间路径
                f"--log {log_file_path}", # 日志路径
                f"--console_log {console_log}", # 是否在控制台打印日志
                f"--self {workspace_path/".fallback"}", # 自身代码路径
                f"--fix_fork {fast_agent_space}", # 需要修复的代码路径
                f"--fix {logs_path/"fast_agent_runtime_error.log"}", # 错误日志路径
                f"--mode fallback" # 运行模式
            ])
            if task.returncode == 0:
                logger.info(f"Fallback agent fixed successfully, restart...")
            else:
                logger.error(f"Fallback agent fixed failed, see {logs_path/"fallback_agent_runtime_error.log"}")
                break
            break
