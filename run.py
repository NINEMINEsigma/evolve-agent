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
        fast_agent_space_path = (workspace_path/fast_agent_space_path)
        fast_agent_space_path.mkdir(parents=True, exist_ok=True)
        slow_agent_space_path = (workspace_path/slow_agent_space_path)
        slow_agent_space_path.mkdir(parents=True, exist_ok=True)
        source = File(origin=str(origin_agent_codes_path))
        source.copy_to(str(fast_agent_space_path))
        source.copy_to(str(slow_agent_space_path))
    while True:
        task = subprocess.run([
            sys.executable,
            str(fast_agent_space_path/"__main__.py"),
            f"--workspace {workspace_path}",
            f"--log {log_file_path}",
            f"--console_log {console_log}",
            f"--self {fast_agent_space_path}",
            f"--fork {slow_agent_space_path}",
        ])
        if task.returncode == 0:
            break
        else:
            logger.error(f"Error running fast agent: {task.returncode}")
            break