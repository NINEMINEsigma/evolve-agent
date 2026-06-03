"""共享路径工具 — 查找项目根目录和常用路径。

由 prompt.py、memory/provider.py 和 shell.py 使用，
通过向上查找 run.py 来一致定位项目根目录。
"""

from pathlib import Path


def find_repo_root() -> Path:
    """从此模块向上遍历，找到项目根目录（run.py 所在处）。"""
    p: Path = Path(__file__).resolve()
    for _ in range(6):
        p = p.parent
        if (p / "run.py").exists():
            return p
    return Path(__file__).resolve().parents[3]  # 兜底


def get_templates_dir() -> Path:
    """返回 templates 目录路径（相对于当前代码副本）。

    在源码树（origin_agent/）和 workspace 运行时副本
    （workspace/fast_agent_space/）中均可正确工作。
    """
    return Path(__file__).resolve().parent.parent / "templates"


def get_template_path(*segments: str) -> Path:
    """返回 templates 目录下指定子路径的完整路径。

    Args:
        *segments: 相对于 templates 的路径片段，如 "dashboard", "index.html"

    Returns:
        拼接后的完整 Path 对象
    """
    return get_templates_dir().joinpath(*segments)