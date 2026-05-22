---
name: Evolve Agent 架构开发计划 v2
overview: 基于已有的 fast-slow-fallback 编排器 (run.py)、abstract 基础层（tools/memory/skills/plugins）和第三方库（filesystem/easysave），设计并实现完整的自我进化 agent。
todos:
  - id: stage-1-skeleton
    content: "Stage 1: 项目骨架 — CLI 参数解析，运行时上下文，asyncio 生命周期，requirements.txt"
    status: completed
  - id: stage-2-gateway
    content: "Stage 2: Gateway — FastAPI WebSocket 聊天接口，消息协议"
    status: completed
  - id: stage-3-agent-loop
    content: "Stage 3: Agent Loop — LLM 客户端，基于 abstract/tools 的工具集成，基于 abstract/memory 的记忆集成"
    status: completed
  - id: stage-4-tools
    content: "Stage 4: 具体工具实现 — 文件系统工具，代码自省工具，在 abstract/tools 的 ToolRegistry 上注册"
    status: completed
  - id: stage-5-code-evolve
    content: "Stage 5: 代码进化 — evolve_code 编排，代码验证，fast-slow-fallback 联动"
    status: pending
  - id: stage-6-self-evolve
    content: "Stage 6: 自我演化 — 实现 MemoryProvider 具体类，基于 abstract/skills 的技能管理，prompt 注入"
    status: pending
  - id: stage-7-dashboard
    content: "Stage 7: Dashboard — 管理仪表盘，监控 API，进化历史可视化"
    status: pending
isProject: false
---

# Evolve Agent 完整架构开发计划 v2

## 总体架构（更新）

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
│                    Agent 进程 (origin_agent)               │
│                                                           │
│  ┌─ Gateway (WS/REST) ─┐  ┌─ Dashboard (HTTP) ─┐        │
│  │   ┌─ Agent Loop ──────────────────────┐      │        │
│  │   │  LLM Client  │  Tool Executor      │      │        │
│  │   │  MemoryManager (abstract/memory)   │      │        │
│  │   │  SkillManager (abstract/skills)    │      │        │
│  │   └───────────────────────────────────┘      │        │
│  └──────────────────────────────────────────────┘        │
│                                                           │
│  ┌─ abstract/ (可复用基础层) ──────────────────────────┐ │
│  │  tools/registry.py  — ToolRegistry 单例              │ │
│  │  memory/manager.py  — MemoryManager + Provider ABC   │ │
│  │  skills/manager.py  — Skill CRUD + SKILL.md 加载     │ │
│  │  plugins/discover.py — 插件目录扫描                   │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                           │
│  ┌─ 具体实现 (基于 abstract) ───────────────────────────┐ │
│  │  tools/    — 文件系统工具、代码工具（注册到 Registry）  │ │
│  │  memory/   — 具体 MemoryProvider（基于 easysave）      │ │
│  │  skills/   — 技能目录 + SKILL.md 文件（由 abstract 管理）│ │
│  │  evolve/   — 代码进化编排 + 验证（独立模块）           │ │
│  └──────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

## 关键架构决策

### abstract/ 层的定位
`abstract/` 下的四个子模块（tools、memory、skills、plugins）是**纯 Python 标准库、零外部依赖**的可复用基础库，从 Hermes Agent 项目移植。它们提供的是**抽象/框架**而非具体实现：
- `tools/` 提供 `ToolRegistry` + AST 自动发现，但**不注册任何工具** — 具体工具由上层注册
- `memory/` 提供 `MemoryProvider` ABC + `MemoryManager` 编排器，但**不包含任何具体 provider** — 具体实现由上层提供
- `skills/` 提供完整的 SKILL.md 生命周期管理，可直接使用
- `plugins/` 提供目录扫描 + 类型检测，可用于发现外部插件

### 与旧规划的差异
| 旧规划 | 新规划 |
|---|---|
| 自建 Tool 基类 `origin_agent/component/tool.py` | 直接使用 `abstract.tools.ToolRegistry`，具体工具文件注册到 registry |
| `origin_agent/memory/store.py` (基于 easysave) | 实现 `MemoryProvider` 子类，通过 `MemoryManager` 编排 |
| `origin_agent/skill/schema.py` + `manager.py` | 直接使用 `abstract.skills`，上层仅管理技能目录 |
| 无插件系统 | 可选集成 `abstract.plugins` 用于发现外部扩展 |
| 模块路径扁平在 `origin_agent/` 下 | 分层：`abstract/` (基础) + `origin_agent/` (业务) |

## 模块依赖关系（更新）

```
origin_agent/__main__.py              ─── CLI 入口，解析参数
      │
      ▼
origin_agent/main.py                  ─── App 生命周期 (asyncio)
      │
      ├── entry/lifecycle.py          ─── 启动/停止/重启
      ├── entry/agent.py              ─── Agent 主循环
      │
      ├── gateway/server.py           ─── FastAPI + WebSocket
      ├── dashboard/server.py         ─── 管理仪表盘
      │
      ├── system/context.py           ─── RuntimeContext dataclass
      │
      ├── component/
      │     ├── llm.py                ─── OpenAI-compatible LLM 客户端
      │     └── tools/                ─── 具体工具实现
      │           ├── __init__.py      ─── 导入所有工具模块（触发注册）
      │           ├── filesystem.py    ─── 文件系统工具 → registry.register()
      │           └── code.py          ─── 代码自省工具 → registry.register()
      │
      ├── memory/
      │     └── provider.py           ─── EasysaveMemoryProvider(MemoryProvider)
      │
      ├── skills/
      │     └── (技能 SKILL.md 文件目录)
      │
      └── evolve/
            ├── code.py               ─── 代码进化编排
            └── validator.py          ─── 代码验证 (语法/导入)

抽象层 (abstract/)                     ─── 可复用基础库（不修改）
  ├── tools/registry.py                ─── ToolRegistry 单例
  ├── memory/manager.py                ─── MemoryManager + Provider ABC
  ├── skills/manager.py                ─── Skill CRUD
  └── plugins/discover.py              ─── 插件发现

第三方库 (third/)                       ─── 已有
  ├── filesystem/                      ─── File 抽象
  └── easysave/                        ─── 持久化引擎
```

## 数据流

### 1) 用户聊天流
```
Web User ──WebSocket──► Gateway ──► Agent Loop
                                        │
                                  ┌─────▼──────┐
                                  │ LLM Client  │
                                  │ + Tool Exec │ (通过 registry.dispatch)
                                  └─────┬──────┘
                                        │
                                  Gateway ──WebSocket──► Web User
```

### 2) 工具注册流
```
工具文件 (component/tools/filesystem.py)
      │ 顶层调用 registry.register()
      ▼
abstract.tools.registry (ToolRegistry 单例)
      │
      ▼
Agent Loop 调用 registry.get_definitions() → LLM tool schemas
Agent Loop 调用 registry.dispatch(name, args) → 执行工具
```

### 3) 记忆系统流
```
Agent Loop 初始化
      │ MemoryManager.add_provider(EasysaveMemoryProvider())
      ▼
每轮对话前: MemoryManager.prefetch_all(query) → 注入 system prompt
每轮对话后: MemoryManager.sync_all(user_msg, asst_resp)
```

### 4) 代码进化流
```
Agent (fast 目录) ──调用 evolve_code 工具──► 读取自己源码 (从 component/tools/code.py)
                                                  │
                                          写进化代码到 fork (slow 目录)
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

### 5) 技能加载流
```
abstract.skills.manager.create_skill() / load_skill() / list_skills()
      │ 直接操作磁盘上的 SKILL.md 文件
      ▼
Agent Loop 通过 SkillManager.inject_to_prompt() 注入 system prompt
```

---

## 分阶段实施

### Stage 1: 项目骨架与 Agent 运行时基础

**目标**: 完善 CLI 参数解析、运行时上下文、基础 asyncio 生命周期。

**新增/修改文件**:
- `origin_agent/__main__.py` — 重写为完整 CLI 入口，解析 `--workspace`, `--self`, `--evolve` (fork), `--log`, `--console_log`, `--mode` 参数
- `origin_agent/main.py` — async App 类，管理生命周期 (init → run → shutdown)
- `origin_agent/system/context.py` — RuntimeContext dataclass 聚合所有配置
- `root/requirements.txt` — 依赖清单：`fastapi`, `uvicorn`, `websockets`, `openai`, `pydantic`, `jinja2`

**关键点**:
- `__main__.py` 需要正确路由 `--mode` (fast/fallback) 的两种行为模式
- `--mode fast`：正常运行
- `--mode fallback`：读取 `--fix` 指定的错误日志，尝试修复 `--fix_fork` 指定的 fast 目录，exit(0) 表示修复成功

**产出**: Agent 进程可启动、解析参数、优雅退出 (exit 0)。

---

### Stage 2: Gateway — WebSocket 聊天接口

**目标**: 用户通过浏览器 WebSocket 与 Agent 交互。

**新增文件**:
- `origin_agent/gateway/server.py` — FastAPI 应用实例，WebSocket endpoint `/ws/chat`
- `origin_agent/gateway/chat.py` — 聊天消息协议

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

**目标**: 实现完整的 Agent 主循环，集成 LLM 客户端和 abstract 层的工具/记忆系统。

**新增文件**:
- `origin_agent/entry/agent.py` — AgentLoop 类
- `origin_agent/entry/lifecycle.py` — 生命周期管理
- `origin_agent/component/llm.py` — OpenAI-compatible LLM 客户端

**Agent Loop 伪代码**:
```python
class AgentLoop:
    def __init__(self, ctx: RuntimeContext):
        self.ctx = ctx
        self.llm = LLMClient(ctx.llm_config)
        self.registry = ToolRegistry()  # 来自 abstract.tools
        self.memory_manager = MemoryManager()  # 来自 abstract.memory

    async def start(self):
        # 注册工具（通过 import 触发工具模块的 registry.register()）
        from .component.tools import filesystem, code
        # 注册记忆 provider
        self.memory_manager.add_provider(EasysaveMemoryProvider(self.ctx))

    async def process_message(self, session_id, message):
        # 注入记忆上下文
        memory_ctx = self.memory_manager.prefetch_all(message, session_id=session_id)
        history = self._build_history(session_id, message, memory_ctx)
        while self.running:
            response = await self.llm.chat(history, self.registry.get_definitions())
            if response.tool_call:
                result = self.registry.dispatch(response.tool_call.name, response.tool_call.args)
                # 如果是记忆相关工具，路由到 memory_manager
                if self.memory_manager.has_tool(response.tool_call.name):
                    result = self.memory_manager.handle_tool_call(...)
                history.append(...)
            else:
                history.append(response.message)
                # 同步到记忆系统
                self.memory_manager.sync_all(message, response.content, session_id=session_id)
                return response.content
```

**关键点**:
- 工具调用路由：先在 `registry` 中查找，如果属于 memory 工具则委托给 `memory_manager.handle_tool_call()`
- 每轮对话后自动同步到记忆系统
- system prompt 注入：LLM 客户端启动时的 system prompt 由 `memory_manager.build_system_prompt()` + `skill_manager.inject_to_prompt()` 组成

**产出**: Agent 可接收消息，通过 LLM 理解并执行工具，返回结果。

---

### Stage 4: 具体工具实现

**目标**: 在 abstract 的 ToolRegistry 上注册文件系统和代码自省工具。

**新增文件**:
- `origin_agent/component/tools/__init__.py` — 导入所有工具模块（触发注册）
- `origin_agent/component/tools/filesystem.py` — 基于 `third/filesystem.File` 的工具集
- `origin_agent/component/tools/code.py` — 代码自省工具

**工具注册方式**（每个工具文件顶层调用 registry.register）:
```python
# origin_agent/component/tools/filesystem.py
from origin_agent.abstract.tools.registry import registry

def handle_read_file(args: dict) -> str:
    path = args["path"]
    # 安全限制：只允许在 workspace 内
    content = File(path).read()
    return json.dumps({"content": content})

registry.register(
    name="read_file",
    toolset="filesystem",
    schema={
        "description": "读取文件内容",
        "parameters": {"type": "object", "properties": {...}},
    },
    handler=handle_read_file,
)
```

**关键安全约束**:
- `read_file` / `write_file`: 拒绝路径穿越 (`..`)
- `read_own_source`: 仅允许 `self_path`（fast 目录）内的文件
- `write_fork_source`: 仅允许写入 `fork_path`（slow 目录），禁止修改 `self_path`
- `validate_code`: 在子进程执行 `compile()` + `import` 检查

**产出**: Agent 拥有完整的文件系统能力和自省能力，通过标准化的 ToolRegistry 管理。

---

### Stage 5: 代码进化 (Fast-Slow-Fallback Cycle)

**目标**: Agent 能主动进化自身代码并通过 orchestrator 的热替换完成更新。

**新增文件**:
- `origin_agent/evolve/code.py` — 代码进化编排
- `origin_agent/evolve/validator.py` — 代码验证器

**进化流程**:
1. Agent 通过 `evolve_code` 工具触发进化（或 LLM 自主决定）
2. `evolve/code.py` 读取 fast 目录源码
3. LLM 生成改进代码
4. 写入 slow 目录（通过 `component/tools/code.py` 的 `write_fork_source`）
5. 对 slow 目录执行验证 (`validator.py`)
6. 验证通过后 `exit(-1)` 通知 orchestrator
7. Orchestrator 将 slow 替换 fast，备份 fast 到 fallback，重启

**修改文件**:
- `origin_agent/__main__.py` — 完善 exit code 逻辑：
  - `exit(0)`: 正常完成
  - `exit(-1)`: 代码已进化，请求热替换
  - `exit(1)`: 不可恢复错误
- `origin_agent/component/tools/code.py` — 添加 `evolve_code` 工具

**orchestrator 行为** (run.py 已有，确认匹配):
```
exit(-1) → copy slow → fast,  fast → fallback,  restart fast
exit(0)  → 停止
exit(1+) → fallback 运行，尝试修复 fast，修复成功 restart
```

**产出**: Agent 能完整走通"自省源码 → 生成改进 → 写入 fork → 验证 → 热替换"的循环。

---

### Stage 6: 自我演化 — 记忆与技能系统

**目标**: Agent 能在运行中积累经验，调整自身行为。

**新增文件**:
- `origin_agent/memory/provider.py` — `EasysaveMemoryProvider(MemoryProvider)`
- `origin_agent/skills/` — 技能 SKILL.md 文件目录（可选初始技能）

**EasysaveMemoryProvider 要点**:
- 继承 `abstract.memory.provider.MemoryProvider` ABC
- 使用 `third/easysave` 作为持久化引擎
- 实现所有抽象方法：`initialize`, `system_prompt_block`, `prefetch`, `sync_turn`, `get_tool_schemas`, `handle_tool_call`, `shutdown`
- 对外暴露工具：`remember(content, tags)`, `forget(id)`, `recall(query)` — 通过 `get_tool_schemas()` 返回 OpenAI 格式 schema
- `prefetch()` 基于关键词匹配召回相关记忆
- `sync_turn()` 在每轮对话后自动存储对话摘要

**技能系统**:
- 直接使用 `abstract.skills` 的 `create_skill`、`load_skill`、`list_skills`、`update_skill`、`delete_skill`
- Agent Loop 通过 `list_skills()` 获取所有 enabled 技能
- 通过 `load_skill()` 渲染技能内容（支持 `{{ var }}` 模板变量）
- 渲染后的技能 prompt 注入 system prompt
- 工具 `learn_skill(name, template)` 使用 `create_skill()` 创建新技能
- 技能存储在 `skills/` 目录（由 abstract.skills 管理目录结构）

**Agent Loop 修改**:
- `entry/agent.py`: 构造 system prompt 时注入 memory + skills
- system prompt = `memory_manager.build_system_prompt()` + 所有 enabled 技能的渲染内容

**产出**: Agent 可以从交互中学习，积累记忆和技能，并在后续对话中自动应用。

---

### Stage 7: Dashboard — 管理仪表盘

**目标**: 提供 Web 界面供管理员监控 Agent 状态和进化历史。

**新增文件**:
- `origin_agent/dashboard/server.py` — FastAPI dashboard 路由
- `origin_agent/dashboard/templates/` — Jinja2 模板
- `origin_agent/dashboard/static/` — CSS/JS

**API**:
- `GET /api/status` — Agent 状态
- `GET /api/logs?lines=100` — 日志
- `GET /api/evolution/history` — 进化历史
- `GET /api/memory` — 记忆列表（通过 MemoryManager）
- `GET /api/skills` — 技能列表（通过 abstract.skills）
- `PATCH /api/skills/{id}` — 启用/禁用技能

**产出**: 管理员可通过浏览器全面监控 Agent。

---

## 边界案例与错误处理策略

| 场景 | 处理方式 |
|---|---|
| LLM API 不可用 | 指数退避重试 (3次)，之后 `exit(1)` |
| 进化代码语法错误 | `validator.py` 捕获，工具返回错误信息，不写 fork |
| 进化代码导入错误 | 子进程 `import`，捕获 `ImportError`，回滚 |
| fork 写入失败 (磁盘满) | 捕获 IOError，返回工具错误，不 exit(-1) |
| WebSocket 断线 | Gateway 保持 session，重连后恢复上下文 |
| 多个用户同时连接 | Gateway session_id 隔离 |
| Agent 启动时记忆数据损坏 | `easysave.load` 异常 → 清空 memory，记录警告，继续启动 |
| MemoryProvider 故障 | 一个 provider 失败不影响其他 provider（MemoryManager 隔离） |
| abstract 模块导入失败 | 启动时检查，记录错误并 exit(1) |

## 实施顺序依赖

```
Stage 1 (骨架) ──► Stage 2 (Gateway) ──► Stage 3 (Agent Loop)
       │                    │                    │
       │                    │              Stage 4 (具体工具实现)
       │                    │                    │
       │                    │              Stage 5 (代码进化)
       │                    │                    │
       │                    │              Stage 6 (记忆/技能)
       │                    │                    │
       │                    └────── Stage 7 (Dashboard)
       │
       └── abstract/ 四模块已就绪，是所有后续的底层依赖
```

Stage 2 与 Stage 3-6 可部分并行。Stage 1 是所有后续的前置依赖。abstract/ 已在代码库中，无需额外工作。
