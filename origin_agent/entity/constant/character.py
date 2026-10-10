"""角色档案与子Agent历史路径常量。"""

from .filesystem import META_FILE_SUFFIX

# 角色档案目录（位于 agentspace / ws: 根下）
CHARACTERS_DIR_NAME: str = "characters"
CHARACTER_ROLEPLAY_DIR_NAME: str = "roleplay"
CHARACTER_TASK_DIR_NAME: str = "task"
CHARACTER_PROFILE_FILENAME: str = "profile.md"
CHARACTER_PROFILE_META_FILENAME: str = CHARACTER_PROFILE_FILENAME + META_FILE_SUFFIX
CHARACTER_LLM_PROFILE_META_KEY: str = "llm_profile"
# profile.md.meta 中用于声明子Agent简介的键。
CHARACTER_DESCRIPTION_META_KEY: str = "description"
# 缺少简介时在发现目录中的展示文本。
CHARACTER_DESCRIPTION_FALLBACK: str = "未提供简介"
# profile.md.meta 中用于声明附加系统提示词逻辑路径的键。
CHARACTER_SYSTEM_PROMPT_PATHS_META_KEY: str = "profile"

# SOUL.md.meta 中用于声明主Agent角色名的键。
SOUL_META_CHARACTER_NAME_KEY: str = "character_name"

# 普通子Agent停止后保存历史的临时目录与格式
SUBAGENT_TEMP_DIR_NAME: str = "tmp"
SUBAGENT_HISTORY_SUFFIX: str = ".es"
