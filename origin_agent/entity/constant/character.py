"""角色档案与子Agent历史路径常量。"""

from .filesystem import META_FILE_SUFFIX

# 角色档案目录（位于 agentspace / ws: 根下）
CHARACTERS_DIR_NAME: str = "characters"
CHARACTER_ROLEPLAY_DIR_NAME: str = "roleplay"
CHARACTER_TASK_DIR_NAME: str = "task"
CHARACTER_PROFILE_FILENAME: str = "profile.md"
CHARACTER_PROFILE_META_FILENAME: str = CHARACTER_PROFILE_FILENAME + META_FILE_SUFFIX
CHARACTER_LLM_PROFILE_META_KEY: str = "llm_profile"

# 普通子Agent停止后保存历史的临时目录与格式
SUBAGENT_TEMP_DIR_NAME: str = "tmp"
SUBAGENT_HISTORY_SUFFIX: str = ".es"
