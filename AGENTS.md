# Evolve Agent — AGENTS.md

## 开始之前

一切开始之前必须先阅读 `.gitignore`、`config.py`、`run.py`，再按下述顺序阅读开发文档，**先文档后代码**：

1. **根目录开发文档三件套（必须先读，缺一不可）**：
   - `DEV-README.md` — 总体设计目标、源码与运行时布局、模块地图、端到端数据流、扩展点。
   - `DEV-glossary.md` — 项目术语表（三位一体口径：开发者/用户、开发助手AI、Evolve Agent）。沟通、文档与 prompt 一律使用登记术语：Agent 一律大写、五仓库规范称谓（origin/fast/slow/fallback 仓库、工作空间）、审批三模式（手动/脱手/YOLO）、前端「导航栏」专指左侧 Sidebar 等；新增术语先登记后使用，退役词禁用。
   - `DEV-class_relationships.md` — Agent Loop 类关系图、protected 字段归属表、跨类/跨模块外部访问清单、关键设计变更记录。
2. **子包文档再代码**：`origin_agent/` 各子包目录下带有该包的开发文档（`abstract/`、`component/`、`entry/`、`frontend/`、`gateway/`、`subagent/` 均有 `DEV-README.md`）。深入某个目录的代码前先读其 `DEV-*` 文档；修改该目录代码后若行为或约定发生变化，应同步更新对应文档（包括根目录三件套中受影响的部分）。
3. **不要误认为riper协议的模式转换要求是agent或者system提示器的模式转换**

## 硬性警告（违反会破坏构建或丢失工作）

- **严禁在 `origin_agent/frontend/` 运行 pnpm/npm。** 前端构建只发生在运行时 `workspace/fast_agent_space/frontend/` 内。在 `origin_agent/` 运行 pnpm 会生成 `node_modules/`/`dist/`，`--force_init` 会把它们复制进 workspace 并破坏构建。
- **严禁替用户运行任何校验命令。** 包括 `npx tsc`、`pnpm exec tsc`、`npm run typecheck`、`npm run lint`、`pnpm build`、`python check_env.py` 等。用户报告构建错误时只修改源码，不得通过运行命令复现或验证。
- **严禁未经用户明确授权运行 `python run.py` / `python check_env.py` 或启动应用。**
- **严禁直接执行 `origin_agent/`。** `run.py` 会将其复制到 `workspace/fast_agent_space/` 并运行那个副本。禁止 `python origin_agent/__main__.py`，禁止任何通过 `sys.path`/`cwd` 技巧指向 `origin_agent/` 的做法。
- **严禁读取、搜索或修改 `workspace/` 下的代码文件。** 它们是 `origin_agent/` 的可丢弃运行时副本。非代码文件（日志、JSON、`.lock`）只读不写。细则见「保护 workspace 目录」。
- **Git 只读。** 只允许 `git diff` 和 `git log`。所有写操作（`add`、`commit`、`push`、`checkout`、`branch` 等）必须由用户本人执行。
- **严禁批量编辑脚本。** 只做有针对性的、可逐条审查的修改。
- **严禁自作主张推进代码进度。** 如果不知道要干什么，最好什么都不要干。
- **最大复用性与解耦优先。** 代码编写遵守最大复用性和解耦原则，而不是最小增量。
- **前端语法感知可能不准确。** `origin_agent/frontend/` 不在仓库根目录，编辑器对前端的语法/类型分析未必可靠；需要测试或构建验证时停下来通知用户。
- **未经明确批准不得切换 RIPER-5 模式。** 尤其严禁未经用户许可从 RESEARCH/PLAN 跳到 EXECUTE。
- **严禁在传给 `easysave.save()` 前先 `.model_dump()` 降级 BaseModel。** easysave 会保留类型并重建实例（见下文「easysave 序列化」小节）；先转 dict 会丢失类型，违背设计。

## 保护 workspace 目录

`workspace/` 下的代码文件只是 `origin_agent/` 的运行时副本，修改不会持久化到源码，读取也没有参考价值；非代码文件可能含调试所需上下文，可读但不可写。

| 类型 | 读取 | 修改 |
|---|---|---|
| **代码文件**（`.py`/`.js`/`.ts`/`.jsx`/`.tsx`/`.rs`/`.go`/`.java`/`.c`/`.cpp`/`.h`/`.hpp`/`.rb`/`.php`/`.swift`/`.kt`/`.scala`/`.sh`/`.bat`/`.ps1` 及任何可执行脚本/源码） | ❌ 禁止 | ❌ 禁止 |
| **非代码文件**（`.log`/`.lock`/`.json`/`.yaml`/`.yml`/`.toml`/`.csv`/`.txt`/`.ini`/`.cfg`/`.conf` 等） | ✅ 允许 | ❌ 禁止 |

行为约束：

1. **禁止搜索** — 不要通过搜索或 grep 等手段探查 `workspace/` 目录下的内容。
2. **禁止引用** — 不要将 `workspace/` 中的路径作为代码证据或上下文引用；引用日志内容时需注明来源是运行时日志。
3. **例外** — 仅当用户明确、具体地要求操作 `workspace/` 下某个文件时，先确认意图后再执行；默认严格遵守上述规则。

## 仓库布局

```
origin_agent/          ← origin仓库（源码真相源，编辑这里）
workspace/             ← 整个目录被 gitignore
third/                 ← git 子模块（easysave、framework），只读
custom_hooks/          ← 上下文钩子扩展点（见「记忆与上下文钩子」）
custom_llm_client/     ← LLM 客户端插件（工厂函数 create_llm_client）
custom_models/         ← 保留目录（*.gguf 被 gitignore）；当前无运行时接入
custom_tools/          ← 自定义工具（AST 扫描自动发现；含 memory_tools/）
pre-skills/ → skills/  ← run.py 首次启动时拷贝生成 skills/（/skills/ 被 gitignore）
desktop/               ← Electron 桌面壳（独立 package.json；node_modules/dist 被 gitignore）

其他 gitignore：/docs/、/temp/、/.tasks/、/config.json（含密钥）、custom_models/*.gguf
```

根目录另有 `SOUL.md`（agent 人格档案，首次启动复制到 agentspace）、`GENE.md`、`config_tui.py`（`--interactive` TUI）、`config.json.example`、`scripts/migrate_v0_to_v1.py`（会话存储 v0→v1 迁移）、`.docs/`（示例与引用资料）。

## 启动与生命周期

> 本节涉及的 workspace 内部目录（fast/slow 空间、agentspace、logs）与 `SOUL.md` 均按**默认配置名**描述；实际名称由 config.py 参数（`workspace_path`、`fast_agent_space_path`、`slow_agent_space_path`、`agentspace_path_name`、`logs_path_name`、`mcp_config_path_name`、`soul_file`）决定，只有 `.fallback/` 为 run.py 硬编码固定名。

- `python run.py`（无参数时提示输入 config key）；`--load <key>` / `--save <key>` / `--interactive` 互斥。`config.json` 用 easysave 按 key 存多份 `Config`，存密钥且被 gitignore。关键配置：`gateway_host/port`、`force_init`、`frontend_force_build`、`yolo`、`merge_concat_threshold`。审批模型（脱手模式）通过前端「模型配置」抽屉选择一个已有 LLM Profile 作为审批 Profile，不通过启动参数配置。
- **`--force_init`**：`true` 时 run.py 重置 workspace 空间，但**三个空间处理方式不同**：`slow_agent_space/` 与 `.fallback/` 先 `rmtree` 删除再 `copytree`（干净重置，旧残留清除）；`fast_agent_space/` **从不删除**，仅 `copytree(..., dirs_exist_ok=True)` 合并覆盖—— origin 中同名文件覆盖 fast，fast 中独有文件原样保留。同时**删除 origin 与 fast 的 `frontend/pnpm-lock.yaml`**（force_init 分支与首次初始化分支都做，run.py 154-173）。`enable_fallback = force_init == False`：force_init 为 true 时 fallback 修复流程被禁用（fallback 已被重置成与 fast 同源，拿它修无意义），fast 崩溃时直接退出。非 force_init 且 fast 尚未初始化（缺 `__main__.py`）时，也会执行同样的首次复制。持久化开发用 `force_init: false`。
- 每次启动 run.py 还会：把根目录 `SOUL.md` 复制到 agentspace（两者都不存在则创建空文件）；`skills/` 不存在时从 `pre-skills/` 复制；只读收集宿主 `git remote -v` 结果，经 `--git_remotes` 注入 system prompt。
- run.py 永不执行 `origin_agent/`，而是循环运行 `workspace/fast_agent_space/__main__.py`（`--mode fast --evolve <slow>`）：
  - 退出码 `0` → 正常停止
  - 退出码 `-1` / `4294967295` → 进化成功：fast→.fallback 备份、slow→fast 提升、重启。**备份与提升均为 `copytree(dirs_exist_ok=True)` 合并覆盖，不再先 rmtree**（避免前端 `node_modules`/`dist` 重新下载安装；目标侧独有旧文件残留）。各阶段（backup/swap/complete）追加写入 `workspace/logs/evolution.status` 供前端展示。
  - 其他 → 进入 fallback：`.fallback` 缺失时先从 origin 补齐，仍无 `__main__.py` 则退出；否则运行 `.fallback/__main__.py --mode fallback --fix_fork <fast> --fix <logs/fast_agent_runtime_error.log>` 修复。修复成功（退出码 0）回到循环重启 fast，失败则退出（日志见 `logs/fallback_agent_runtime_error.log`）。
- 入口链：`__main__.py`（CLI 解析 + 前端构建 + 日志）→ `main.py::App`（uvicorn gateway）→ `system/application.py::Application`（进程级单例，初始化各子系统，`Application.current()` 访问）。
- 前端在 agent 目录内由 `_build_frontend()` 用 `<pkg_mgr> install && <pkg_mgr> run build`（`CI=true`，包管理器优先 pnpm 回退 npm，由 `system/pkgmgr.py` 检测）构建；构建失败返回退出码 1 触发 fallback。构建结果按 `.frontend_build_signature.json` 签名缓存跳过，`--frontend_force_build` 可强制重建。

## 沙盒命名空间（system/sandbox.py）

所有工具文件操作必须使用逻辑前缀，禁止裸路径/`..`/绝对路径；子进程调用同样经 `Sandbox.run()` 路由（按会话登记活动进程，中断路径用 `kill_active(session_id)` 终止整棵进程树）。

> 下表「映射」列为**默认配置名**：`fork:`/`ws:`/`fix:` 的物理根由 RuntimeContext 的 `fork_path`/`agentspace`/`fix_path` 决定（对应 config 的 `slow_agent_space_path`/`agentspace_path_name` 及 run.py 硬编码的 `.fallback`），权威映射以 `namespace_bases()` 为准。

| 前缀 | 映射 | fast 模式 | fallback 模式 | 用途 |
|---|---|---|---|---|
| `fork:` | `workspace/slow_agent_space/` | rw | — | 读写进化代码 |
| `fix:` | `workspace/.fallback/` | — | rw | 修复目标 |
| `ws:` | `workspace/agentspace/` | rw | rw | 通用 I/O |
| `skills:` | 仓库根 `skills/` | rw | rw | 技能读写 |
| `third:` | 仓库根 `third/` | ro | ro | 第三方子模块 |
| `custom_hooks:` | 仓库根 `custom_hooks/` | ro | ro | 自定义钩子 |
| `custom_llm_client:` | 仓库根 `custom_llm_client/` | ro | ro | 自定义 LLM 客户端 |
| `custom_tools:` | 仓库根 `custom_tools/` | ro | ro | 自定义工具 |

**没有 `self:` 命名空间** — agent 不能读取或修改自身运行时副本，进化完全通过 `fork:`/`fix:` 实现。权限模型为 `_PERMISSIONS`（mode × namespace → Access 列表），`namespace_bases()` 是 ns→物理根的唯一映射来源（`resolve()` 与 LSP 反向映射复用）；`Namespace` 枚举定义在 `entity/constant.py`。

## 记忆与上下文钩子（custom_hooks/）

核心中**没有 MemoryManager**（已从 `ParentAgentLoop` 移除，详见 `DEV-class_relationships.md`「设计变更记录」）。记忆能力由运行时扩展承载：`custom_tools/memory_tools/`（remember/forget 工具 + `_store.py`）+ `custom_hooks/memory_hook.py`（每轮注入长期记忆块，`<|im_memory_context_start|>` 标记包裹，非持久化）。

其他内置钩子：`time_hook.py`、`session_meta_hook.py`、`recent_uploads_hook.py`、`agentspace_changes_hook.py`、`client_info_hook.py`、`token_usage_hook.py`。钩子协议：`hook_tag_name()` + `hook_message()`（非固着器：当轮注入、不落盘）或 `hook_fixator()`（固着器：产出持久化 `message_suffix`，写盘保留）；返回的上下文扩展块附加到用户消息末尾。

## easysave 序列化（`third/easysave/`，只读子模块）

easysave 是**类型保留**序列化库，原生支持 pydantic BaseModel。

- **机制**：`save(key, path, data)` 用 BFS 遍历对象图，为每个对象记录 `type_token = "module, ClassName"`；`load(key, path)` 会 import 该类并用 `model_construct()` 重建真正的实例（BaseModel / list / dict / Enum 等），而非裸 dict。
- **直接存 BaseModel 实例**：不要在 `save()` 前先 `.model_dump()` 把 BaseModel 降级为 dict —— 这会丢失类型信息，使存储层退化为普通 dict。直接传 `list[LLMProfile]`、`list[Message]` 等给 `save()` 即可，类型由 easysave 保留。参考 `system/session_store.py`、`system/llm_profile_store.py::save_profiles`。
- **load() 返回即类型实例**：对新格式文件直接复用，无需再 `model_validate`；为兼容旧版误存的 dict 文件，加载侧可用 `isinstance` 短路 + `model_validate` 兜底（见 `load_profiles`）。

## 类定义规范

- **尽量使用 BaseModel。** 语义上适合作为数据模型的类应直接或间接继承 `pydantic.BaseModel`。例外：需要自定义元类/Mixin 且 BaseModel 会导致冲突时，以及运行时工具类、异常类、枚举类、ABC 抽象基类等不适合作为数据模型的场景。
- **纯数据类放入 `entity/puretype/` 包。** 仅含字段、不含任何方法（含 `__init__`、普通方法、类方法、静态方法、property 等）的类，集中定义在 `entity/puretype/` 包中。包内按职责拆分子模块（`_base`、`approval`、`llm`、`skills`、`session`、`agent`、`ws`、`lsp`、`runtime`、`extools`），所有公共名称通过 `__init__.py` 再导出。
- **带方法/校验器的模型放业务模块。** 需要方法、`@field_validator` / `@model_validator` 校验器或业务逻辑的类不属于 pure type，应放在对应业务模块。

| 场景 | 位置 |
|---|---|
| 纯数据类（无方法） | `entity/puretype/` 包内对应子模块 |
| 带验证/转换/业务方法的模型 | 对应业务模块 |
| 工具类 / 异常类 / 枚举 | 按职责分散到各模块 |
| 项目级常量 | `entity/constant.py` 对应分区 |

新增纯数据类时先判断是否有方法；没有则优先放入 `entity/puretype/` 中合适的子模块，并在 `__init__.py` 中再导出。

### 常量集中在 `entity/constant.py`

项目级常量统一放在 `origin_agent/entity/constant.py`，业务模块内禁止散落魔法数字和硬编码字符串。该文件按职责用分区注释划分（版本、角色名、超时、I/O 上限、沙盒命名空间、上传、LLM、子 Agent、Cron、会话搜索等），新增常量放入对应分区（无合适分区时新建），并附中文注释说明用途与单位/取值含义。仅被单一函数私有使用、无复用价值的字面量除外。

## Windows 细节

- Python 命令是 `python`（非 python3）；原生可执行文件调用 `pnpm.cmd` 或 `npm.cmd`（由 `system/pkgmgr.py` 检测，优先 pnpm）；进程树终止用 `taskkill /T /F`；沙盒子进程用 `CREATE_NEW_PROCESS_GROUP`；`add_signal_handler` 不可用，回退 `signal.signal`。