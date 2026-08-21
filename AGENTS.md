# Evolve Agent — AGENTS.md

> 本文件只收录硬性警告与严禁事项，是唯一可信的仓库指引。任何其他描述性文档/段落都可能严重过时，一律以源码为准，不要依赖历史文档中的架构说明。

## 硬性警告（违反会破坏构建或丢失工作）

- **严禁在 `origin_agent/frontend/` 运行 pnpm/npm。** 前端构建只发生在运行时 `workspace/fast_agent_space/frontend/` 内。在 `origin_agent/` 运行 pnpm 会生成 `node_modules/`/`dist/`，`--force_init` 会把它们复制进 workspace 并破坏构建。
- **严禁替用户运行任何校验命令。** 包括 `npx tsc`、`pnpm exec tsc`、`npm run typecheck`、`npm run lint`、`pnpm build`、`python check_env.py` 等。用户报告构建错误时只修改源码，不得通过运行命令复现或验证。
- **严禁未经用户明确授权运行 `python run.py` / `python check_env.py` 或启动应用。**
- **严禁直接执行 `origin_agent/`。** `run.py` 会将其复制到 `workspace/fast_agent_space/` 并运行那个副本。禁止 `python origin_agent/__main__.py`，禁止任何通过 `sys.path`/`cwd` 技巧指向 `origin_agent/` 的做法。
- **严禁读取、搜索或修改 `workspace/` 下的代码文件。** 它们是 `origin_agent/` 的可丢弃运行时副本。非代码文件（日志、JSON、`.lock`）只读不写。
- **Git 只读。** 只允许 `git diff` 和 `git log`。所有写操作（`add`、`commit`、`push`、`checkout`、`branch` 等）必须由用户本人执行。
- **严禁批量编辑脚本。** 只做有针对性的、可逐条审查的修改。
- **未经明确批准不得切换 RIPER-5 模式。** 尤其严禁未经用户许可从 RESEARCH/PLAN 跳到 EXECUTE。
- **严禁在传给 `easysave.save()` 前先 `.model_dump()` 降级 BaseModel。** easysave 会保留类型并重建实例（见下文「easysave 序列化」小节）；先转 dict 会丢失类型，违背设计。

## 仓库布局

```
origin_agent/        ← origin仓库（源码真相源，编辑这里）
workspace/
  fast_agent_space/  ← fast仓库（当前运行副本）
  slow_agent_space/  ← slow仓库（进化目标副本，fork:）
  .fallback/         ← fallback仓库（备份 / 回退修复体，fix:）
  agentspace/        ← 工作空间（agent 的 workspace，ws:），含 SOUL.md、uploads/
  sessions/          ← 会话历史与索引
  logs/              ← 运行日志、evolution.status
third/               ← git 子模块（easysave、llamaapis），只读
custom_*、skills/    ← 根目录扩展点；skills/ 由 run.py 从 pre-skills/ 拷贝生成
```

## 启动与生命周期

- `python run.py --load <config_key>`（config.py 中 `--load`/`--save`/`--interactive` 互斥；无参数时交互式提示）。`config.json` 存密钥且被 gitignore。
- **`--force_init`**：`true` 时 run.py 重置 workspace 空间，但**三个空间处理方式不同**：`slow_agent_space/` 与 `.fallback/` 先 `rmtree` 删除再 `copytree`（干净重置，旧残留清除）；`fast_agent_space/` **从不删除**，仅 `copytree(..., dirs_exist_ok=True)` 合并覆盖——origin 中同名文件覆盖 fast，但 fast 中独有的、origin 里不存在的文件**原样保留**。同时**删除 `origin_agent/frontend/pnpm-lock.yaml`**（run.py:117-142）。另外 `enable_fallback = force_init == False`，force_init 为 true 时 fallback 修复流程被禁用（因 fallback 已被重置成与 fast 同源，拿它修无意义），fast 崩溃时直接退出。持久化开发用 `force_init: false`。
- run.py 永不执行 `origin_agent/`，而是循环运行 `workspace/fast_agent_space/__main__.py`：
  - 退出码 `0` → 正常停止
  - 退出码 `-1` / `4294967295` → 进化成功：fast→.fallback 备份、slow→fast 交换、重启
  - 其他 → 进入 fallback：运行 `.fallback/__main__.py --mode fallback --fix_fork <fast>` 修复
- 入口链：`__main__.py`（CLI 解析 + 前端构建 + 日志）→ `main.py::App`（uvicorn gateway）→ `system/application.py::Application`（单例，初始化各子系统）。
- 前端在 agent 目录内由 `_build_frontend()` 用 `<pkg_mgr> install && <pkg_mgr> run build`（`CI=true`，包管理器优先 pnpm 回退 npm，由 `system/pkgmgr.py` 检测）构建；构建失败返回退出码 1 触发 fallback。构建结果按 `.frontend_build_signature.json` 签名缓存跳过。

## 沙盒命名空间（system/sandbox.py）

所有工具文件操作必须使用逻辑前缀，禁止裸路径/`..`/绝对路径。

| 前缀 | 映射 | fast 模式 | fallback 模式 |
|---|---|---|---|
| `fork:` | `slow_agent_space/` | rw | — |
| `fix:` | `.fallback/` | — | rw |
| `ws:` | `agentspace/` | rw | rw |
| `skills:` | 根目录 `skills/` | rw | rw |
| `third:` / `custom_hooks:` / `custom_llm_client:` / `custom_models:` / `custom_tools:` | 项目根对应目录 | ro | ro |

**没有 `self:` 命名空间** — agent 不能读写自身运行副本，进化只通过 `fork:`/`fix:`。

## 工具注册

- 模块级 `registry.register()` 调用由 AST 扫描自动发现（`abstract/tools/discover.py`，main.py:188-205）。
- 内置来源：`component/tools/`（核心）、`component/extools/`（web/ssh/cron/…）、`component/multiagenttools/`（多代理 / 子代理工具）、`component/automation/`（桌面自动化）、`component/browser/`（浏览器控制）+ 根目录 `custom_tools/`（存在即加载）+ MCP 桥接（`component/mcp_tools.py`，配置在 `ws:mcp_config.json`，即 `workspace/agentspace/mcp_config.json`）。
- 工具 schema 的 `description` 用英文，紧邻其上注释为中文。

## 模板系统（system/prompt.py）

组装顺序：根目录 GENE.md（基因——先天身份）→ agentspace/SOUL.md（灵魂——后天个性，run.py 首次启动时创建/复制）→ `templates/base.txt` → `templates/modes/{fast,fallback}.txt` → `templates/tools.txt` → `tools_subagent.txt`（仅 MAIN scope）→ 额外块。

## 审批系统

- 手动模式：前端 WebSocket 弹窗确认。
- 脱手模式：本地 GGUF 自动审批。启动时自动检测 `custom_models/*.gguf`（跳过 mmproj 文件）；`--approval_model` 只存文件名。无本地模型时 fallback 到远程端点（`--approval_remote_*`），两者皆无时脱手模式不可用。
- 实现：`component/approval/`（core/backend/executor/allowlist/handsfree/policy）+ `system/application.py` 的 `ApprovalBackendManager`。

## 会话与记忆

- 会话持久化在 `workspace/sessions/`（不是 logs/）：每会话 `history.es`（easysave 序列化）+ `summary.txt`/`token_usage.json`/`tool_resources.json`；元数据索引 + `tags.json` 由 `gateway/chat.py::SessionManager` 管理。
- 记忆系统在 `custom_tools/memory_tools/`（remember/forget 工具），`custom_hooks/memory_hook.py` 在每轮注入上下文；`custom_hooks/` 还含 time、session_meta、recent_uploads、agentspace_changes、client_info、token_usage 钩子。

## easysave 序列化（`third/easysave/`，只读子模块）

easysave 是**类型保留**序列化库，原生支持 pydantic BaseModel。

- **机制**：`save(key, path, data)` 用 BFS 遍历对象图，为每个对象记录 `type_token = "module, ClassName"`；`load(key, path)` 会 import 该类并用 `model_construct()` 重建真正的实例（BaseModel / list / dict / Enum 等），而非裸 dict。
- **直接存 BaseModel 实例**：不要在 `save()` 前先 `.model_dump()` 把 BaseModel 降级为 dict —— 这会丢失类型信息，使存储层退化为普通 dict。直接传 `list[LLMProfile]`、`list[Message]` 等给 `save()` 即可，类型由 easysave 保留。参考 `system/session_store.py`、`system/llm_profile_store.py::save_profiles`。
- **load() 返回即类型实例**：对新格式文件直接复用，无需再 `model_validate`；为兼容旧版误存的 dict 文件，加载侧可用 `isinstance` 短路 + `model_validate` 兜底（见 `load_profiles`）。

## Windows 细节

- Python 命令是 `python`（非 python3）；原生可执行文件调用 `pnpm.cmd` 或 `npm.cmd`（由 `system/pkgmgr.py` 检测，优先 pnpm）；进程树终止用 `taskkill /T /F`；沙盒子进程用 `CREATE_NEW_PROCESS_GROUP`；`add_signal_handler` 不可用，回退 `signal.signal`。
