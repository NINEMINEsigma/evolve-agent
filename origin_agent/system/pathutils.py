"""共享路径工具 — 查找项目根目录。

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