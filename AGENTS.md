# Evolve Agent — AGENTS.md

## 启动

```bash
python run.py
```

运行前需设置环境变量 `OPENAI_API_KEY`。如需覆盖默认模型地址，设 `OPENAI_BASE_URL`。修改 `config.py` 中的 `llm_*` 字段可调整模型、温度、上下文窗口等。

启动后 Web 界面在 `http://127.0.0.1:8765`。

## 铁律：origin_agent 不可直接执行

`origin_agent/` 下的源代码**必须经过 `run.py` 复制到 `workspace/fast_agent_space/` 后才能运行**。严禁：

- 直接执行 `origin_agent/__main__.py`
- 在 `origin_agent/frontend/` 目录下运行 `pnpm install`、`pnpm run dev`、`pnpm run build`
- 将 `origin_agent/` 中任何路径作为 `sys.path` 或 `cwd` 来运行代码

前端构建由 `origin_agent/__main__.py::_build_frontend()` 在 fast_agent_space 中自动完成。如需手动构建，先确定已复制到 `workspace/` 下再操作。构建失败会返回 exit code 1，触发 fallback 模式。

## 铁律：永不修改 workspace 下的文件

`workspace/` 下的代码文件（`.py`, `.js`, `.ts`, `.jsx`, `.tsx` 等）是 `origin_agent` 的运行时副本，**修改不会被持久化**。日志和 JSON 等非代码文件可读但不可写。

`.cursorignore` 和 `.cursor/rules/protect-workspace.mdc` 已实施此约束。

## 架构要点

```
origin_agent/         ← 代码真相来源（唯一需编辑的地方）
workspace/            ← 运行时副本 + 日志 + skill 文件
  fast_agent_space/     正在运行的 agent 代码（origin_agent 的副本）
  slow_agent_space/     LLM 写进化代码的目标目录
  .fallback/            上一次 fast 的备份
third/                ← 供应商第三方模块（easysave, filesystem）
```

- `origin_agent/` 是**唯一**需要编辑源码的位置。
- 无 CI/CD、无测试框架、无 lint/typecheck 配置。项目纯运行时代码演化，无构建工具（前端除外）。

## 生命周期（run.py）

`run.py` 是编排器：

1. 首次运行或 `fouce_init=True` 时：删 `workspace/*`，将 `origin_agent/` **完整复制**到 `fast_agent_space/` 和 `slow_agent_space/`，写锁文件。
2. 运行 `fast_agent_space/__main__.py`。
3. **退出码 0** = 正常退出，停止。
4. **退出码 -1** = 演化交换：fast → .fallback, slow → fast, 重启。
5. **其他退出码** = fallback 模式：运行 `.fallback/__main__.py` 修复 `fast_agent_space/`。

## 路径沙盒（Sandbox）

所有文件操作必须使用逻辑路径前缀，不能使用裸路径：

| 前缀 | 映射 | 权限 | 用途 |
|------|------|------|------|
| `self:` | `fast_agent_space/` | 只读 | 读自身源码 |
| `fork:` | `slow_agent_space/` | 读写 | 写进化代码 |
| `ws:` | `workspace/` | 读写 | 通用工作空间 |
| `fix:` | 仅 fallback 模式 | 只写 | 修复目标 |

不允许 `..` 遍历、绝对路径、裸路径。

## 工具系统

工具在 `component/tools/*.py` 中通过 `registry.register()` **模块导入时**注册。修改工具注册需编辑对应文件。

## 模板系统

System prompt 由 `system/prompt.py` 从 `templates/`（英文）或 `templates/zh/`（中文）拼接。检测到 `templates/zh/` 目录存在时默认用中文模板。层次：GENE > SOUL > base > modes/{fast,fallback} > tools > memory > skills。

## 进化流程（LLM 调用链）

`read_own_source` → `write_fork`/`edit_file` → `validate_code` → `evolve_code`

退出码 -1 → run.py 执行 slow→fast 交换。

## 前端

在 `origin_agent/frontend/`（React + Vite + TypeScript）。使用 **pnpm**（不是 npm）。启动时自动执行 `pnpm install && pnpm run build`，产物打入 `frontend/dist/`。失败时 agent 不启动。

Windows 上调用的是 `pnpm.cmd`。

## 杂项

- Windows 平台 Python 命令为 `python`（非 `python3`），原生命令需 `cmd /c <cmd>`。
- 历史消息持久化在 `workspace/logs/sessions/`（JSONL），会话元数据在 `_index.json`。
- LLM API key 从 `OPENAI_API_KEY` 环境变量读取，**永远不可写入代码**。
- 无 `pyproject.toml`。依赖仅有 `requirements.txt`：fastapi, uvicorn, websockets, openai, pydantic, tiktoken, dirtyjson。
- 进化状态日志写入 `workspace/logs/evolution.status`（JSON 数组，供前端展示）。
- `config.py` 中 `fouce_init` 是故意拼写（非 `force_init`）。
