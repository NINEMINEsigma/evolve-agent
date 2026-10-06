"""LLM、审批、多模态和 Profile 持久化常量。"""

# ============================================================================
# LLM
# ============================================================================

# 审批调用固定采样参数；通过临时 Profile 副本覆盖，不修改根对象
APPROVAL_TEMPERATURE: float = 0.3
APPROVAL_MAX_OUTPUT_TOKENS: int = 4096

# 审批模型普通文本响应中的显式决策标记（解析前统一 casefold）
APPROVAL_ALLOW_MARKERS: tuple[str, ...] = ("[allow]", "[approve]")
APPROVAL_DENY_MARKERS: tuple[str, ...] = ("[deny]", "[reject]", "[拒绝]", "[否决]")

# 会话级审批模式枚举值（手动/脱手/YOLO 三态互斥）
APPROVAL_MODE_MANUAL: str = "manual"
APPROVAL_MODE_HANDSFREE: str = "handsfree"
APPROVAL_MODE_YOLO: str = "yolo"

# 会话级审批模式持久化（存于各会话目录下，easysave 类型保留序列化）
SESSION_APPROVAL_MODE_ES_FILENAME: str = "approval_mode.es"
SESSION_APPROVAL_MODE_ES_KEY: str = "v1"

# 多模态能力缓存（存放于 workspace/ 下，easysave 序列化，dict[cache_key, ModalityCapability]）
MODALITY_CAPABILITY_ES_FILENAME: str = "modality_capability_cache.es"
MODALITY_CAPABILITY_ES_KEY: str = "v1"

# ReadForward 生成的多模态内容块载荷上限（字节，45 MiB）。
# 仅约束工具构造的 JSON 内容块，不保证第三方 LLM SDK 最终 HTTP 请求体大小。
READ_FORWARD_MAX_PAYLOAD_BYTES: int = 45 * 1024 * 1024

# 多模态转发描述标签名 — 模型不支持某模态时，转发给引用模型取回描述并以这些标签包裹，
# 供活跃模型识别转发来源。两条转发路径（preprocess 与 Read 工具）共用，保证一致。
FORWARDED_VISION_TAG: str = "forwarded_vision"
FORWARDED_AUDIO_TAG: str = "forwarded_audio"
FORWARDED_VIDEO_TAG: str = "forwarded_video"

# 音频格式后缀 → data URL 中的标准 MIME 子类型
# NOTE: mp3 必须归一化为 mpeg（audio/mpeg）：部分 provider（如小米 MiMo）会静默拒绝非标准的 audio/mp3
AUDIO_FORMAT_MIME_SUBTYPE: dict[str, str] = {"mp3": "mpeg", "wav": "wav"}

# 所有LLM解析的重试次数
LLM_RETRY_COUNT: int = 3

# LLM Profile 根对象持久化（存放于 agentspace 下，easysave 序列化）
# v2 是唯一受支持格式，直接保存 LLMProfileData。
LLM_PROFILES_ES_FILENAME: str = "llm_profiles.es"
LLM_PROFILES_ES_KEY: str = "v2"

# 会话级最近使用 Profile 名称指针文件名（存于会话目录下）
SESSION_LLM_PROFILE_FILENAME: str = "llm_profile.json"

# 全局最近使用 Profile 名称指针文件名（存于 sessions 根目录）
GLOBAL_LLM_PROFILE_FILENAME: str = "active_llm_profile.json"

# 会话工具集加载状态文件名（存于会话目录下，记录已加载的工具集名称列表）
LOADED_TOOLSETS_FILENAME: str = "loaded_toolsets.json"
