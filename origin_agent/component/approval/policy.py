"""审批策略定义。

将审批阈值的判断从分散在各处的硬编码条件分支，集中为显式命名的策略常量。
数据类 ApprovalPolicy 定义在 entity/puretype.py，本模块负责操作函数和预设策略。
"""

from __future__ import annotations

from entity.puretype import ApprovalPolicy, ToolDangerLevel


def needs_approval(
    policy: ApprovalPolicy,
    danger_level: ToolDangerLevel,
    handsfree: bool,
) -> bool:
    """判断工具是否需要审批。

    根据是否为脱手模式选择对应的 requires 集合，返回 danger_level 是否在该集合中。
    """
    requires = policy.handsfree_requires if handsfree else policy.normal_requires
    return danger_level in requires


# 主会话策略：主会话直接面对用户，正常模式仅 dangerous 需审批，脱手模式 write + dangerous 需审批
MAIN_SESSION_POLICY = ApprovalPolicy(
    normal_requires={ToolDangerLevel.dangerous},
    handsfree_requires={ToolDangerLevel.write, ToolDangerLevel.dangerous},
)

# 子会话策略：子会话的工具审批由主 agent 审批，因此采用更严格的阈值，
# write + dangerous 在两种模式下均需审批
SUB_SESSION_POLICY = ApprovalPolicy(
    normal_requires={ToolDangerLevel.write, ToolDangerLevel.dangerous},
    handsfree_requires={ToolDangerLevel.write, ToolDangerLevel.dangerous},
)