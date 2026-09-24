"""easysave 类型稳定名版本常量。"""

# ============================================================================
# easysave 类型稳定名版本
# ============================================================================
# 与 ES key 常量（如 History_Version）不同，这些版本号用于构造 easysave
# type_token 的稳定名格式 "{version}::{ClassName}"，使类名变更或模块移动
# 后旧文件仍可通过 namespace 别名加载。命名以 _Type_Version 结尾避免与
# ES key 常量混淆。

History_Type_Version = "v1"
LLMProfileData_Type_Version = "v2"
AgentConfig_Type_Version = "v1"
