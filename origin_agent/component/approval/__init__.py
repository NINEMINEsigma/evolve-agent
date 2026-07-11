"""审批流程统一入口包。

子模块：
- entity:    类型通过 entity.puretype 统一管理（ApprovalResult, ApprovalOutcome）
- backend:   审批后端抽象与实现（本地 GGUF / 远程 API）
- handsfree: 脱手模式状态管理与 LLM 审批核心流程
- core:      统一审批入口与 Agent 主模型提问回调
- executor:  工具审批执行器（封装 dangerous/write 判断、白名单、审批流程）
- allowlist: 工具 allowlist 持久化

重新导出策略：保持旧路径兼容，from component.approval import Xxx 继续可用。
"""

from entity.puretype import ApprovalResult, ApprovalOutcome
from component.approval.backend import (
    ApprovalBackend,
    FailedApprovalBackend,
    LocalApprovalBackend,
    RemoteApprovalBackend,
    create_approval_backend,
    is_local_approval_enabled,
)
from component.approval.handsfree import (
    set_handsfree_mode,
    is_handsfree_mode,
    APPROVAL_JSON_SCHEMA,
)
from component.approval.core import request_user_confirm, ask_agent_reason
from component.approval.executor import execute_with_approval
from component.approval.allowlist import is_allowed, add_allowed

__all__ = [
    "ApprovalResult",
    "ApprovalOutcome",
    "ApprovalBackend",
    "FailedApprovalBackend",
    "LocalApprovalBackend",
    "RemoteApprovalBackend",
    "create_approval_backend",
    "is_local_approval_enabled",
    "set_handsfree_mode",
    "is_handsfree_mode",
    "APPROVAL_JSON_SCHEMA",
    "request_user_confirm",
    "ask_agent_reason",
    "execute_with_approval",
    "is_allowed",
    "add_allowed",
]