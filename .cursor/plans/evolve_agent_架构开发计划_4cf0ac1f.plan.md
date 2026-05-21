---
name: Evolve Agent 架构开发计划
overview: 基于现有的 fast-slow-fallback 编排器 (run.py) 和第三方库 (filesystem, easysave)，设计并实现一个完整的自我进化 agent，包含异步核心、Web 聊天网关、管理仪表盘、代码进化与提示词工程自我优化能力。
todos:
  - id: stage-1-skeleton
    content: "Stage 1: 项目骨架 — CLI 参数, 运行时上下文, asyncio 生命周期, requirements.txt"
    status: pending
  - id: stage-2-gateway
    content: "Stage 2: Gateway — FastAPI WebSocket 聊天接口, 消息协议"
    status: pending
  - id: stage-3-agent-loop
    content: "Stage 3: Agent Loop — LLM 客户端, 工具系统, 消息处理循环"
    status: pending
  - id: stage-4-tools
    content: "Stage 4: 工具系统 — 文件系统工具, 代码自省工具, 安全约束"
    status: pending
  - id: stage-5-code-evolve
    content: "Stage 5: 代码进化 — evolve_code 编排, 代码验证, fast-slow-fallback 联动"
    status: pending
  - id: stage-6-self-evolve
    content: "Stage 6: 自我演化 — 记忆存储, 技能管理, prompt 注入"
    status: pending
  - id: stage-7-dashboard
    content: "Stage 7: Dashboard — 管理仪表盘, 监控 API, 进化历史可视化"
    status: pending
isProject: false
---

# Evolve Agent 完整架构开发计划

## 总体架构

```
┌──────────────────────────────────────────────────────────┐
│                    Orchestrator (run.py)                   │
│   ┌──────────┐   exit -1   ┌──────────┐   exit 0/err   │
│   │  fast    │◄──────────►│  slow    │                  │
│   │ (运行中) │──backup──►│ (进化中)  │                  │
│   └────┬─────┘  fallback  └──────────┘                  │
│        │ err                                              │
│   ┌────▼─────┐                                           │
│   │ fallback │──restore──►│ fast                         │
│   └──────────┘                                           │
└──────────────────────────────────────────────────────────┘
         │  subprocess
         ▼
┌──────────────────────────────────────────────────────────┐
│                    Agent 进程                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐               │
│  │ Gateway  │  │Dashboard │  │  Agent   │               │
│  │(WS/REST) │  │  (HTTP)  │  │  Core    │               │
│  │◄─Web用户─│  │◄─管理员─│  │          │               │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘               │
│       │              │              │                      │
│       └──────┬───────┘              │                      │
│              │  FastAPI             │                      │
│              ▼                      ▼                      │
│        ┌────────────────────────────────┐                  │
│        │       LLM Client (OpenAI)       │                │
│        │   Tool System (FS/Code/Chat)    │                │
│        │   Memory / Skill Engine         │                │
│        └────────────────────────────────┘                  │
└──────────────────────────────────────────────────────────┘
```

## 模块依赖关系

```
origin_agent/__main__.py
      │
      ▼
origin_agent/main.py              ─── App 生命周期 (asyncio)
      │
      ├── entry/lifecycle.py      ─── 启动/停止/重启
      ├── entry/agent.py          ─── Agent 主循环
      │
      ├── gateway/server.py       ─── FastAPI + WebSocket
      ├── dashboard/server.py     ─── 管理仪表盘
      │
      ├── system/context.py       ─── 运行时上下文 + argv 解析
      │
      ├── component/
      │     ├── llm.py            ─── OpenAI-compatible LLM 客户端
      │     ├── tool.py           ─── 工具系统 (注册/调度/执行)
      │     ├── tool_fs.py        ─── 文件系统工具
      │     ├── tool_code.py      ─── 代码进化工具 (写 fork 目录)
      │     └── tool_chat.py      ─── 聊天交互工具
      │
      ├── memory/
      │     ├── store.py          ─── 持久化 (基于 easysave)
      │     └── schema.py         ─── 记忆数据结构
      │
      ├── skill/
      │     ├── manager.py        ─── 技能 CRUD
      │     └── schema.py         ─── 技能数据结构
      │
      └── evolve/
            ├── code.py           ─── 代码进化编排
            └── validator.py      ─── 代码验证 (语法/导入/测试)

third/
  filesystem/   ─── File 抽象 (供 tool_fs 和 agent 自身使用)
  easysave/     ─── 持久化引擎 (供 memory/skill 使用)
```

## 数据流

### 1) 用户聊天流
```
Web User ──WebSocket──► Gateway ──► Agent Loop
                                          │
                                    ┌─────▼──────┐
                                    │ LLM Client  │
                                    │ + Tool Exec │
                                    └─────┬──────┘
                                          │
                                    Gateway ──WebSocket──► Web User
```

### 2) 代码进化流
```
Agent (fast 目录) ──调用 evolve_code 工具──► 读取自己源码 (fast)
                                                  │
                                          写进化代码到 (slow 目录)
                                                  │
                                          验证 (语法/导入/单元测试)
                                                  │
                                          exit(-1) ──► Orchestrator
                                                            │
                                                  slow → fast (替换)
                                                  fast → fallback (备份)
                                                            │
                                                  重新启动 Agent
```

### 3) 自我演化流
```
Agent 运行中 ──► 更新记忆 (memory/store.py)
                   │
             更新技能 (skill/manager.py)
                   │
             重启 Agent 后行为已优化
```

## 分阶段实施

### Stage 1: 项目骨架与 Agent 运行时基础

**目标**: 搭建完整的项目结构, 实现 CLI 参数解析、运行时上下文、基础 asyncio 生命周期。

**新增核心文件**:
- `origin_agent/__main__.py` — CLI 入口, 解析 `--workspace`, `--self`, `--fork`, `--log`, `--console_log` 等参数
- `origin_agent/main.py` — async App 类, 管理生命周期 (init → run → shutdown)
- `origin_agent/system/context.py` — RuntimeContext dataclass: workspace, self_path, fork_path, log_path, llm_config
- `origin_agent/system/argv.py` — CLI 参数解析, 与 `config.py` 联动
- `root/requirements.txt` — 依赖清单: `fastapi`, `uvicorn`, `websockets`, `openai`, `pydantic`, `jinja2`

**依赖**: `third/filesystem` (已有), `third/easysave` (已有)

**产出**: Agent 进程可以启动、解析参数、优雅退出 (exit 0), 日志正常写入。

---

### Stage 2: Gateway — WebSocket 聊天接口

**目标**: 用户通过浏览器 WebSocket 与 Agent 交互。

**新增文件**:
- `origin_agent/gateway/server.py` — FastAPI 应用实例, WebSocket endpoint `/ws/chat`
- `origin_agent/gateway/chat.py` — 聊天消息协议: `{type: "user_message", content: "..."}`, 内部路由到 agent loop, 返回 `{type: "agent_message", content: "..."}`

**消息协议**:
```
Client → Server:  { type: "user_message", session_id: str, content: str }
Server → Client:  { type: "agent_message", session_id: str, content: str }
Server → Client:  { type: "tool_call",     session_id: str, tool: str, args: object }
Server → Client:  { type: "tool_result",   session_id: str, result: object }
Server → Client:  { type: "error",         session_id: str, message: str }
```

**产出**: 浏览器可通过 WebSocket 连接到 Agent 并收发消息。

---

### Stage 3: Agent 核心循环与 LLM 集成

**目标**: 实现完整的 Agent 主循环: 接收消息 → 构造 Prompt → 调用 LLM → 执行工具 → 返回结果。

**新增文件**:
- `origin_agent/entry/agent.py` — AgentLoop 类
- `origin_agent/entry/lifecycle.py` — 生命周期管理 (集成 Gateway + Dashboard 启动/停止)
- `origin_agent/component/llm.py` — 基于 `openai` SDK 的 LLM 客户端, 支持 streaming, 支持 system/user/assistant/tool roles
- `origin_agent/component/tool.py` — Tool 基类 + ToolRegistry: `name`, `description`, `parameters` (JSON Schema), `execute(ctx, **kwargs)`

**Agent Loop 伪代码**:
```
class AgentLoop:
    async def start(self):
        self.running = True
        self.llm = LLMClient(api_key, base_url, model)
        self.tools = ToolRegistry()
        self.tools.register(ToolFilesystem(self.ctx))
        self.tools.register(ToolChat(self.ctx))

    async def process_message(self, session_id, message):
        history = self.messages[session_id]
        history.append({"role": "user", "content": message})
        while self.running:
            response = await self.llm.chat(history, self.tools.schemas())
            if response.tool_call:
                result = await self.tools.execute(response.tool_call)
                history.append(response.message)
                history.append({"role": "tool", "content": result})
            else:
                history.append(response.message)
                return response.content
```

**产出**: Agent 可以接收用户消息, 通过 LLM 理解并执行文件系统工具, 返回结果。

---

### Stage 4: 工具系统 — 文件系统与代码自省

**目标**: 完善工具系统, 使 Agent 能读写文件系统并自省自身源码。

**新增文件**:
- `origin_agent/component/tool_fs.py` — 基于 `third/filesystem.File` 的工具集:
  - `read_file(path)` — 读取文件内容
  - `write_file(path, content)` — 写入文件内容
  - `list_directory(path)` — 列出目录
  - `create_file(path)` / `delete_file(path)` — 创建/删除
- `origin_agent/component/tool_code.py` — 代码相关工具:
  - `read_own_source(path_rel)` — 读取自己源代码 (限制在 `self_path` 内)
  - `write_fork_source(path_rel, content)` — 写入进化代码到 `fork_path`
  - `validate_code(path_rel)` — 验证代码: `compile()` 语法检查 + `import` 检查

**关键安全约束**:
- `read_own_source`: 拒绝 `path_rel` 包含 `..` 穿越
- `write_fork_source`: 只允许写入 `fork_path` (slow 目录), 不允许修改 `self_path` (fast 目录)
- `validate_code`: 在子进程执行 `compile()` + 尝试 `import`, 捕获所有异常

**产出**: Agent 拥有完整的文件系统能力和自省能力。

---

### Stage 5: 代码进化 (Fast-Slow-Fallback Cycle)

**目标**: Agent 能主动进化自身代码并通过 orchestrator 的热替换完成更新。

**新增文件**:
- `origin_agent/evolve/code.py` — 代码进化编排:
  1. 读取自身源码 (fast 目录)
  2. 确定进化目标 (改进/新增模块)
  3. 生成进化代码并写入 fork (slow 目录)
  4. 对 fork 目录执行验证
  5. 向 orchestrator 发送 `exit(-1)`
- `origin_agent/evolve/validator.py` — 代码验证器:
  - `syntax_check(path)` — `compile()` 语法验证
  - `import_check(path)` — 尝试以子进程 `import` 模块
  - `test_check(path)` — 运行 `__test__` 中的单元测试

**修改文件**:
- `origin_agent/component/tool_code.py` — 加入 `evolve_code` 工具, 调用 `evolve/code.py`
- `origin_agent/__main__.py` — 修改 exit code 逻辑:
  - `exit(0)`: 正常完成
  - `exit(-1)`: 代码已进化, 请求热替换
  - `exit(1)`: 不可恢复错误

**Orchestrator (run.py) 逻辑** (已有, 需确认)：
```
exit(-1) → copy slow → fast,  fast → fallback,  restart fast
exit(0)  → 停止
exit(1)  → 回滚 (fallback → fast), 尝试修复
```

**产出**: Agent 能完整走通"自省源码 → 生成改进 → 写入 fork → 验证 → 热替换"的循环。

---

### Stage 6: 自我演化 — 记忆与技能系统

**目标**: Agent 能在运行中积累经验, 调整自身行为。

**新增文件**:
- `origin_agent/memory/schema.py`:
  ```python
  class MemoryEntry(BaseModel):
      id: str           # uuid
      created: datetime
      type: str         # "observation" | "lesson" | "pattern"
      content: str
      tags: list[str]
      relevance: float  # 0.0 - 1.0
  ```
- `origin_agent/memory/store.py`:
  - `save(entry)` / `load(id)` / `search(query, k)` — 基于 `easysave` + 关键词匹配
  - `get_relevant(context, limit=5)` — 获取当前上下文相关的记忆
- `origin_agent/skill/schema.py`:
  ```python
  class Skill(BaseModel):
      id: str
      name: str
      description: str
      prompt_template: str   # 插入到 system prompt 的模板
      enabled: bool
  ```
- `origin_agent/skill/manager.py`:
  - `register(skill)` / `unregister(id)` / `list()` / `enable(id, bool)`
  - `inject_to_prompt()` — 将所有 enabled 的 skill prompt 注入到 system message

**Agent Loop 修改**:
- `entry/agent.py`: 构造 system prompt 时注入 memory + skills
- 工具 `remember(content, tags)` — 添加记忆
- 工具 `forget(id)` — 删除记忆
- 工具 `learn_skill(name, template)` — 创建新技能

**产出**: Agent 可以从交互中学习, 积累记忆和技能, 并在后续对话中自动应用。

---

### Stage 7: Dashboard — 管理仪表盘

**目标**: 提供 Web 界面供管理员监控 Agent 状态和进化历史。

**新增文件**:
- `origin_agent/dashboard/server.py` — 挂载到 FastAPI 的 dashboard 路由
- `origin_agent/dashboard/templates/` — Jinja2 模板:
  - `index.html` — 总览面板: 当前状态, Uptime, 最近消息
  - `logs.html` — 日志查看器
  - `evolution.html` — 进化历史时间线
  - `memory.html` — 记忆浏览器
  - `skills.html` — 技能管理
- `origin_agent/dashboard/static/` — CSS/JS

**API (Gateway 侧)**:
- `GET /api/status` — Agent 状态
- `GET /api/logs?lines=100` — 日志
- `GET /api/evolution/history` — 进化历史
- `GET /api/memory` — 记忆列表
- `GET /api/skills` — 技能列表
- `PATCH /api/skills/{id}` — 启用/禁用技能

**产出**: 管理员可通过浏览器全面监控 Agent。

---

## 边界案例与错误处理策略

| 场景 | 处理方式 |
|---|---|
| LLM API 不可用 | 指数退避重试 (3次), 之后 `exit(1)` |
| 进化代码语法错误 | `validator.py` 捕获, 工具返回错误信息, 不写 fork |
| 进化代码导入错误 | 子进程 `import`, 捕获 ImportError, 回滚 |
| fork 写入失败 (磁盘满) | 捕获 IOError, 返回工具错误, 不 exit(-1) |
| WebSocket 断线 | Gateway 保持 session, 重连后恢复上下文 |
| 多个用户同时连接 | Gateway session_id 隔离, 每个 session 独立消息队列 |
| Agent 启动时 memory 损坏 | `easysave.load` 异常 → 清空 memory, 记录警告, 继续启动 |

## 实施顺序依赖

```
Stage 1 (骨架) ──► Stage 2 (Gateway) ──► Stage 3 (Agent Loop)
                        │                       │
                        │                 Stage 4 (工具系统)
                        │                       │
                        │                 Stage 5 (代码进化)
                        │                       │
                        │                 Stage 6 (记忆/技能)
                        │                       │
                        └────────── Stage 7 (Dashboard)
```

Stage 2 (Gateway) 与 Stage 3-6 可部分并行。Stage 1 是所有后续的前置依赖。
