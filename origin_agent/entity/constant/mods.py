"""Mod document protocol and bounded-loading constants."""

MODS_DIR_NAME = "custom_mods"  # 项目根目录下的只读功能指导目录。
MOD_DOCUMENT_FILENAME = "MOD.md"  # 功能指导正文。
MOD_METADATA_FILENAME = "MOD.md.meta"  # 同级分块元数据。
MOD_META_DESCRIPTION = "description"  # 单行发现简介。
MOD_META_RELATED = "related"  # 每行一个机械递归关联名称。
MOD_META_KEYWORDS = "keywords"  # 每行一个区分大小写的字面关键词。
MOD_NAME_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]{0,63}$"  # 规范名称，不接受路径。
MOD_FIXATOR_START = "<|im_mod_fixator_start|>"  # 持久上下文扩展起始标记。
MOD_FIXATOR_END = "<|im_mod_fixator_end|>"  # 持久上下文扩展结束标记。
MOD_MAX_COUNT = 256  # 可发现声明数量。
MOD_MAX_REQUEST_NAMES = 64  # 去重前的请求目标数。
MOD_MAX_RELATED = 256  # 每项去重前的关联数。
MOD_MAX_KEYWORDS = 32  # 每项去重前的关键词数。
MOD_MAX_KEYWORD_CHARS = 128  # 单关键词 Unicode 码点。
MOD_MAX_DESCRIPTION_CHARS = 256  # 简介 Unicode 码点。
MOD_MAX_META_BYTES = 8 * 1024  # 单元数据文件字节上限。
MOD_MAX_TOTAL_META_BYTES = 2 * 1024 * 1024  # 单次发现的元数据总字节上限。
MOD_MAX_DOCUMENT_BYTES = 64 * 1024  # 单正文文件字节上限。
MOD_MAX_BATCH_SOURCE_BYTES = 512 * 1024  # 单批正文原始字节上限。
MOD_MAX_RENDERED_BYTES = 1024 * 1024  # mod 自有完整编码内容字节，不含既有嵌入输入。
