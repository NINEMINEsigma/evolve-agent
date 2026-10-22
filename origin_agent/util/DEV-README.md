# util/ — 前置辅助模块

本包承载无需 Application 装配即可导入和复用的辅助函数模块。前置辅助模块的规范定义见根目录 `DEV-glossary.md`；“前置”表示依赖方向，不等于所有函数无 I/O，也不表示把本包整体提前初始化。

## 依赖与初始化边界

- 允许标准库、第三方库、已经核实不会反向引入业务实现的 `entity/` 或 `interface/` 子模块，以及本包其他前置辅助模块。
- 检查范围包括模块级、函数内部、平台条件分支和 `TYPE_CHECKING` 中的导入；延迟导入不豁免依赖约束。
- 不导入 `system/`、`entry/`、`subagent/`、`gateway/`、`component/` 或 `abstract/` 的具体实现，不通过 `Application.current()` 查询 System，不持有业务生命周期、共享业务缓存或后台资源。
- `__init__.py` 保持为空，调用方显式导入职责子模块，不建立全包聚合导出、运行时初始化、旧路径代理或 `sys.modules` 别名。
- 本批实际项目内依赖只有 `entity.constant`、`util.pathutils` 和 `util.text_codec`。常量包内部与标准库依赖不会反向引入消息体系；不能把整个 entity/interface 包无条件视为安全依赖。

## 模块地图

| 模块 | 职责 | 项目内依赖 |
|---|---|---|
| `pathutils.py` | 项目根、当前代码副本根与模板路径 | 无 |
| `templates.py` | 模板读取、多Agent模板占位符渲染 | `util.pathutils`；渲染函数内 `entity.constant` |
| `text_codec.py` | 编码探测、解码与 LF 分行/行尾处理 | 无 |
| `text_preview.py` | 不改变原文的逐行展示截断 | `util.text_codec` |
| `convert.py` | 枚举、布尔值转换 | 无 |
| `error_utils.py` | 可恢复辅助副作用的日志与同步/异步调用包装 | 无 |
| `file_metadata.py` | 同级元数据文本解析与 `MetaFormatError` | 无 |
| `local_fonts.py` | 字体路径/MIME校验与 `LocalFontAccessError` | `entity.constant` |
| `pkgmgr.py` | 包管理器探测，Windows 返回显式 `.cmd` 名称 | 无 |
| `atomic_io.py` | 跨平台原子替换、独占创建及无覆盖文件/目录操作 | 无 |

`pathutils.py` 与迁移前处于相同目录深度；`get_agent_dir()` 仍指当前代码副本根，模板仍位于其 `templates/`。路径查询和模板/字体文件读取发生于函数调用，不在包导入时扫描模板或启动服务。需要模板目录的调用方直接从 `util.pathutils` 导入 `get_templates_dir`，不通过模板读取模块间接取得。

## 平台限制与既有行为

`atomic_io.py` 在 Windows 的模块导入分支通过 `ctypes.WinDLL` 绑定 `kernel32`，这是保留的现有行为。它符合依赖方向约束，但不是零导入副作用模块；导入其他辅助模块不会因空包入口顺带绑定该 DLL。

本次整文件迁移保持函数签名、默认值、返回值、专用异常及错误处理策略。模板缺失返回空串、Read 的 LF/CRLF 与元数据展示、字体在线/导出权限及原子写入重试均未改变。日志对象名称自然随定义模块变为 `util.*`；不修改日志级别或正文。不改变持久化模型、typeref 映射、easysave key 或 20 个 System 的装配。

## 调用与部署

正式源码及扩展统一使用 `util.<模块>`。原 system 下十个模块已移除，不保留兼容转发。消息层的模板依赖为 `entity.messages → util.templates → util.pathutils`，模板渲染另依赖 `entity.constant`；本包不反向导入消息类、类型映射或纯类型聚合入口。

部署须同步完整批次的辅助模块和所有调用方。启动入口的合并复制不保证清除目标侧旧文件，已有运行进程也不会自动替换已加载模块。用户应完成整批部署并重启对应进程后验收。已生成技能不会因预置技能源变化自动覆盖，需要用户定向同步对应技能脚本并保留其他修改；开发助手AI不处理运行时副本或已生成技能。

## 验收状态

本次仅实施源码并做文件、导入和差异的只读静态审阅；未运行测试、实际导入、校验、构建或应用。正式运行验收由用户完成，不在 origin仓库添加测试源、夹具或测试入口。
