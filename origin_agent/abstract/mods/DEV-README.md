# abstract/mods — 严格本地功能指导加载

本包无Application查询、全局缓存、后台任务或导入期I/O。运行验收尚未执行。

`loader.py`提供discover_mods、resolve_related_names、match_mod_keywords和read_mod_documents；目录调用方显式传入。发现只读meta及检查正文文件类型，按名称确定性排序；related采用可环的稳定深度优先先序，visited按名称去重。关键词为每个文字段独立的区分大小写字面子串，不跨段匹配。

元信息使用util.file_metadata.parse_meta_content，只有description/related/keywords；缺整根为空，损坏声明、未知键、重复键、关联缺失、链接/reparse、编码和I/O失败不降级。只读UTF-8（可带BOM），单文件有界读取并核对同来源stat前后版本。预算取entity/constant/mods，不执行文档、YAML、include或Shell。

`render.py`只消费ModDocument和ModRenderContext，一次替换显式简单占位符，反斜杠转义保留字面内容；未知/缺失值抛ModTemplateError，不执行表达式。新增类型位于消息前puretype；异常统一来自entity.error。

调用方负责运行时值、类型化消息构造、History提交、自动可见性去重及现有失败边界。本包不负责工具权限、已加载名单、持久化或前端投影。通用协议与预算见根custom_mods/DEV-README，不维护具体安装清单。
