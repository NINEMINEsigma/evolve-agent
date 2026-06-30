"""子 Agent 子系统。

核心模块：
- ``context.py`` — SubRuntimeContext
- ``loop.py`` — SubAgentLoop
- ``orchestrator.py`` — SubAgentOrchestrator（按主会话管理多个上下文）
"""

from .context import SubRuntimeContext
from .loop import SubAgentLoop
from .orchestrator import SubAgentOrchestrator

__all__ = [
    "SubRuntimeContext",
    "SubAgentLoop",
    "SubAgentOrchestrator",
]