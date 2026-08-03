# Evolve Agent — AGENTS.md

> 本文件只收录硬性警告与严禁事项，是唯一可信的仓库指引。任何其他描述性文档/段落都可能严重过时，一律以源码为准，不要依赖历史文档中的架构说明。

## 硬性警告（违反会破坏构建或丢失工作）

- **严禁在 `origin_agent/frontend/` 运行 pnpm/npm。** 前端构建只发生在运行时 `workspace/fast_agent_space/frontend/` 内。在 `origin_agent/` 运行 pnpm 会生成 `node_modules/`/`dist/`，`--fouce_init` 会把它们复制进 workspace 并破坏构建。
- **严禁替用户运行任何校验命令。** 包括 `npx tsc`、`pnpm exec tsc`、`npm run typecheck`、`npm run lint`、`pnpm build`、`python check_env.py` 等。用户报告构建错误时只修改源码，不得通过运行命令复现或验证。
- **严禁未经用户明确授权运行 `python run.py` / `python check_env.py` 或启动应用。**
- **严禁直接执行 `origin_agent/`。** `run.py` 会将其复制到 `workspace/fast_agent_space/` 并运行那个副本。禁止 `python origin_agent/__main__.py`，禁止任何通过 `sys.path`/`cwd` 技巧指向 `origin_agent/` 的做法。
- **严禁读取、搜索或修改 `workspace/` 下的代码文件。** 它们是 `origin_agent/` 的可丢弃运行时副本。非代码文件（日志、JSON、`.lock`）只读不写。
- **Git 只读。** 只允许 `git diff` 和 `git log`。所有写操作（`add`、`commit`、`push`、`checkout`、`branch` 等）必须由用户本人执行。
- **严禁批量编辑脚本。** 只做有针对性的、可逐条审查的修改。
- **未经明确批准不得切换 RIPER-5 模式。** 尤其严禁未经用户许可从 RESEARCH/PLAN 跳到 EXECUTE。

## 仓库布局

```
origin_agent/        ← 唯一源码真相源（编辑这里）
workspace/
  fast_agent_space/  ← 当前运行的 agent 副本
  slow_agent_space/  ← 进化目标（fork:）
  .fallback/         ← 上一次 fast 的备份 / fallback 修复体（fix:）
  agentspace/        ← agent 通用 I/O（ws:），含 SOUL.md、uploads/
  sessions/          ← 会话历史与索引
  logs/              ← 运行日志、evolution.status
third/               ← git 子模块（easysave、llamaapis），只读
custom_*、skills/    ← 根目录扩展点；skills/ 运行时生成
```

## 启动与生命周期

- `python run.py --load <config_key>`（config.py 中 `--load`/`--save`/`--interactive` 互斥；无参数时交互式提示）。`config.json` 存密钥且被 gitignore。
- **`--fouce_init` 是故意拼错的**（force）：`true` 时 run.py 删除三个 workspace 空间并重拷 `origin_agent/`，同时**删除 `origin_agent/frontend/pnpm-lock.yaml`**（run.py:131-133）。持久化开发用 `fouce_init: false`。
- run.py 永不执行 `origin_agent/`，而是循环运行 `workspace/fast_agent_space/__main__.py`：
  - 退出码 `0` → 正常停止
  - 退出码 `-1` / `4294967295` → 进化成功：fast→.fallback 备份、slow→fast 交换、重启
  - 其他 → 进入 fallback：运行 `.fallback/__main__.py --mode fallback --fix_fork <fast>` 修复
- 入口链：`__main__.py`（CLI 解析 + 前端构建 + 日志）→ `main.py::App`（uvicorn gateway）→ `system/application.py::Application`（单例，初始化各子系统）。
- 前端在 agent 目录内由 `_build_frontend()` 用 `pnpm install && pnpm run build`（`CI=true`，`pnpm.cmd` on Windows）构建；构建失败返回退出码 1 触发 fallback。构建结果按 `.frontend_build_signature.json` 签名缓存跳过。

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

- 模块级 `registry.register()` 调用由 AST 扫描自动发现（`abstract/tools/discover.py`，main.py:187-194）。
- 内置来源：`component/tools/`（核心）、`component/extools/`（web/ssh/cron/…）、`component/multiagenttools/`（多代理 / 子代理工具）、`component/automation/`（桌面自动化）、`component/browser/`（浏览器控制）+ 根目录 `custom_tools/`（存在即加载）+ MCP 桥接（`component/mcp_tools.py`，配置在 `workspace/mcp_config.json`）。
- 工具 schema 的 `description` 用英文，紧邻其上注释为中文。

## 模板系统（system/prompt.py）

组装顺序：根目录 `GENE.md`（不可变身份）→ `agentspace/SOUL.md`（可编辑个性，run.py 首次启动时创建/复制）→ `templates/base.txt` → `templates/modes/{fast,fallback}.txt` → `templates/tools.txt` → `tools_subagent.txt`（仅 MAIN scope）→ 额外块。

## 审批（脱手模式）

- 正常模式：前端 WebSocket 弹窗确认。
- 脱手模式：本地 GGUF 自动审批。启动时自动检测 `custom_models/*.gguf`（跳过 mmproj 文件）；`--approval_model` 只存文件名。无本地模型时 fallback 到远程端点（`--approval_remote_*`），两者皆无时脱手模式不可用。
- 实现：`component/approval/`（core/backend/executor/allowlist/handsfree）+ `system/application.py` 的 `ApprovalBackendManager`。

## 会话与记忆

- 会话持久化在 `workspace/sessions/`（不是 logs/）：每会话 `history.es`（easysave 序列化）+ `summary.txt`/`token_usage.json`/`tool_resources.json`；元数据索引 + `tags.json` 由 `gateway/chat.py::SessionManager` 管理。
- 记忆系统在 `custom_tools/memory_tools/`（remember/forget 工具），`custom_hooks/memory_hook.py` 在每轮注入上下文；`custom_hooks/` 还含 time、session_track、recent_uploads、agentspace_changes 钩子。

## Windows 细节

- Python 命令是 `python`（非 python3）；原生可执行文件调用 `pnpm.cmd`；进程树终止用 `taskkill /T /F`；沙盒子进程用 `CREATE_NEW_PROCESS_GROUP`；`add_signal_handler` 不可用，回退 `signal.signal`。
