"""子 Agent 子系统。

核心模块：
- ``context.py`` — SubRuntimeContext
- ``loop.py`` — SubAgentLoop
- ``orchestrator.py`` — SubAgentOrchestrator（进程级单例）
- ``report_tool.py`` — report_to_parent 工具注册
"""

from .context import SubRuntimeContext
from .loop import SubAgentLoop
from .orchestrator import SubAgentOrchestrator, get_orchestrator, set_orchestrator

__all__ = [
    "SubRuntimeContext",
    "SubAgentLoop",
    "SubAgentOrchestrator",
    "get_orchestrator",
    "set_orchestrator",
]