"""审批系统公共接口。

审批模型由项目级审批 Profile 名称指针选择，并通过 ``BaseLLMClient``
连接 Evolve Agent 外部管理的模型服务。脱手审批使用普通文本决策标记，
不请求或解析 JSON 格式输出。
"""

from entity.puretype import (
    ApprovalMode,
    ApprovalOutcome,
    ApprovalPolicy,
    ApprovalProfileMutationResponse,
    ApprovalProfileState,
    ApprovalProfileUpdateRequest,
    ApprovalResult,
)
from component.approval.backend import ApprovalBackend, ProfileApprovalBackend
from component.approval.handsfree import (
    disable_all_handsfree_modes,
    disable_all_non_manual_modes,
    get_approval_mode,
    is_handsfree_available,
    is_handsfree_mode,
    set_approval_mode,
    set_handsfree_mode,
)
from component.approval.core import build_denied_tool_result, request_user_confirm
from component.approval.executor import execute_with_approval
from component.approval.allowlist import add_allowed, is_allowed
from component.approval.policy import MAIN_SESSION_POLICY, SUB_SESSION_POLICY, needs_approval

__all__ = [
    "ApprovalResult",
    "ApprovalOutcome",
    "ApprovalMode",
    "ApprovalPolicy",
    "ApprovalProfileUpdateRequest",
    "ApprovalProfileState",
    "ApprovalProfileMutationResponse",
    "ApprovalBackend",
    "ProfileApprovalBackend",
    "set_approval_mode",
    "get_approval_mode",
    "set_handsfree_mode",
    "is_handsfree_mode",
    "disable_all_non_manual_modes",
    "disable_all_handsfree_modes",
    "is_handsfree_available",
    "request_user_confirm",
    "build_denied_tool_result",
    "execute_with_approval",
    "is_allowed",
    "add_allowed",
    "needs_approval",
    "MAIN_SESSION_POLICY",
    "SUB_SESSION_POLICY",
]