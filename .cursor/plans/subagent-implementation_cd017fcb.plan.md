---
name: subagent-implementation
overview: 基于 subagent.plan.md 需求文档，分 5 个阶段实现子 Agent 系统：新建 subagent/ 模块（编排器 + SubAgentLoop + SubRuntimeContext），集成到现有 AgentLoop 和 server.py，填充 4 个工具骨架的执行逻辑。
todos:
  - id: phase1-context
    content: 新建 subagent/context.py — SubRuntimeContext
    status: completed
  - id: phase1-report-tool
    content: 新建 subagent/report_tool.py — report_to_parent 工具注册
    status: completed
  - id: phase1-loop
    content: 新建 subagent/loop.py — SubAgentLoop（LLM 循环 + 审批暂停 + 收件箱注入）
    status: completed
  - id: phase1-orchestrator
    content: 新建 subagent/orchestrator.py — SubAgentOrchestrator（并发管理 + 周期定时器 + 消息注入）
    status: completed
  - id: phase1-init
    content: 新建 subagent/__init__.py — 模块导出
    status: completed
  - id: phase2-agent
    content: 修改 entry/agent.py — 加入 _last_idle_time 跟踪
    status: completed
  - id: phase2-server
    content: 修改 gateway/server.py — 初始化编排器 + shutdown 回调
    status: completed
  - id: phase3-tools
    content: 填充 4 个工具骨架执行逻辑（run/chat/approve/stop）
    status: completed
  - id: phase4-injection
    content: 实现 report_to_parent 工具注入到子 Agent 工具集
    status: completed
  - id: phase5-integration
    content: 实现父 Agent 中断/终结回调 + 上下文变量传递
    status: completed
isProject: false
---

# SubAgent 系统实现计划

## 概览

新建 `origin_agent/subagent/` 独立模块（5 个文件），修改 `entry/agent.py` 和 `gateway/server.py` 两处集成点，填充 `mutliagenttools/` 下 4 个工具骨架的执行逻辑。

## 阶段一：新建 subagent/ 模块

### 1.1 `origin_agent/subagent/__init__.py`
- 模块入口，暴露 `SubAgentOrchestrator`、`SubAgentLoop`、`SubRuntimeContext` 等核心导出

### 1.2 `origin_agent/subagent/context.py` — SubRuntimeContext
- `SubRuntimeContext` Pydantic BaseModel，字段：
  - `base_url: str`、`model: str`、`api_key: str | None`
  - `temperature: float`（默认 1.0）
  - `max_output_tokens: int`、`max_context_tokens: int`
  - `system_prompt: str`
- 类方法 `from_registry(profile, temperature, parent_ctx)` 从注册表字典构建

### 1.3 `origin_agent/subagent/loop.py` — SubAgentLoop
- 单个子 Agent 的 LLM 调用 + 工具执行循环，参考 `AgentLoop._process_message_locked` 的结构
- 核心方法：`async run(initial_prompt: str) -> None`
- 内部状态：
  - `_history: list[dict]` — 内存中的消息历史（OpenAI 格式）
  - `_outbox: list[str]` — 发件箱（report_to_parent 消息）
  - `_pending_approvals: list[PendingToolCall]` — 待审批工具调用队列
  - `_inbox: list[str]` — 父 Agent 通过 chat_subagent 发来的收件箱
  - `_cancel_event: asyncio.Event` — 用于强制中断
  - `_paused_event: asyncio.Event` — 审批等待事件
- LLM 循环：
  1. 调用 `LLMClient.chat(messages, tools)`，用 `SubRuntimeContext` 初始化独立的 `LLMClient`
  2. 若文本回复 → 添加到历史，继续循环（除非 report_to_parent 被调用过且 inbox 有消息则注入）
  3. 若工具调用：
     - `report_to_parent` → 写入 `_outbox`，不暂停
     - 其他工具 → 写入 `_pending_approvals`，`await _paused_event.wait()` 阻塞
  4. 工具链结束时注入收件箱消息（若未调用 report_to_parent）
  5. 用 `MAX_TOOL_TURNS` 限制循环防止死循环
- `inject_parent_message(text: str)` — 追加到 `_inbox`
- `approve_tools(decisions)` — 匹配 `_pending_approvals`，执行同意/拒绝，设置 `_paused_event`
- `stop()` — 设置 `_cancel_event`，取消 LLM 调用
- `save_history(path: Path)` — 将 `_history` 写入 JSONL

### 1.4 `origin_agent/subagent/orchestrator.py` — SubAgentOrchestrator
- 全局单例，进程级
- 数据：
  - `_active: dict[str, SubAgentLoop]` — 活跃子 Agent 表
  - `_waiting_queue: deque[WaitingEntry]` — FIFO 等待队列
  - `_agent_loop: AgentLoop | None` — 父 AgentLoop 引用
  - `_background_task: asyncio.Task | None` — 周期检查任务
  - `_parent_session_id: str`
  - `_interrupted: bool` — 父 Agent 中断标记
- 核心方法：
  - `async launch(profile, temperature, authorized_tools, initial_prompt, parent_session_id) -> (session_id, waiting, queue_position)`
  - `async chat(session_id, message) -> dict` — 消息注入到子 Agent 收件箱
  - `async approve(session_id, decisions) -> dict` — 审批子 Agent 工具调用
  - `async stop(session_id) -> dict` — 停止子 Agent（含已完成/等待中判断），处理级联出队
  - `async shutdown()` — 遍历活跃，逐个 stop，清理
  - `interrupt()` / `resume()` — 暂停/恢复周期任务
  - `terminate_parent()` — 停止所有子 Agent
- 周期定时器（后台 asyncio Task）：
  1. 每 1 秒检查 `_agent_loop._processing_sessions` 是否都空闲
  2. 空闲超过 `SUBAGENT_IDLE_TRIGGER_SECONDS` 时收集
  3. 遍历所有 `_active`，收集 `_outbox` 和 `_pending_approvals`
  4. 空周期跳过
  5. 构建 `[subagent-result]` 消息，调用 `_agent_loop.process_message()`
- `_activate_next()` — 从等待队列取一个启动，必要时创建 SubAgentLoop 并 `asyncio.create_task`

### 1.5 `origin_agent/subagent/report_tool.py` — report_to_parent 工具注册
- `_handle_report_to_parent(args)` — 将消息追加到当前 SubAgentLoop 的 `_outbox`
- `registry.register("report_to_parent", ...)` — 不绑定任何 toolset（仅为子 Agent 注入用），danger_level="readonly"
- 通过 `_current_subagent_loop` 上下文变量获取当前运行的 SubAgentLoop 实例

## 阶段二：集成到 AgentLoop

### 2.1 修改 `origin_agent/entry/agent.py`
- 在 `AgentLoop.__init__` 中新增 `self._last_idle_time: float = 0.0`
- 在 `_process_message_locked` 的 finally 块末尾，`_processing_sessions.pop` 之后添加：
  ```python
  self._last_idle_time = time.monotonic()
  ```
- 导入 `time` 模块（如未导入）
- 暴露 `_processing_sessions` 属性供编排器读取（或新增 `is_any_processing() -> bool` 方法）
- 暴露 `process_message` 方法的引用（编排器通过 `_agent_loop.process_message` 调用注入）

### 2.2 修改 `origin_agent/gateway/server.py`
- 导入并初始化 `SubAgentOrchestrator`：
  ```python
  from subagent.orchestrator import SubAgentOrchestrator
  _subagent_orchestrator: SubAgentOrchestrator | None = None
  ```
- 在 `set_agent_loop` 之后调用 `_subagent_orchestrator.set_agent_loop(agent_loop)`
- 暴露 `get_subagent_orchestrator()` 函数供工具层调用
- 注册 shutdown 回调：在 app 的 shutdown 事件中调用 `_subagent_orchestrator.shutdown()`

## 阶段三：填充工具骨架

### 3.1 `run_subagent.py` — 完整实现
- 保留现有参数校验 + multiagent 排除逻辑
- 新增 `system_prompt_path` 校验（若指定则文件必须存在，否则返回失败）
- 调用 `_subagent_orchestrator.launch(...)` 启动子 Agent
- 返回 `{success, session_id, waiting, queue_position}`

### 3.2 `chat_subagent.py` — 完整实现
- 保留现有参数校验
- 调用 `_subagent_orchestrator.chat(session_id, message)`
- 返回 `{success, session_id}`

### 3.3 `approval_subagent.py` — 完整实现
- 保留现有参数校验（decisions 列表）
- 调用 `_subagent_orchestrator.approve(session_id, decisions)`
- 返回 `{success, session_id, processed}`

### 3.4 `stop_subagent.py` — 完整实现
- 保留现有参数校验
- 调用 `_subagent_orchestrator.stop(session_id)`
- 返回 `{success, session_id, session_path, promoted}`

## 阶段四：report_to_parent 工具注入

- 在 `SubAgentLoop` 初始化时构建工具集：
  1. 从 `SUBAGENT_READONLY_WHITELIST` 获取 readonly 工具定义
  2. 追加 `authorized_tools` 中的 write/dangerous 工具定义
  3. 硬排除 multiagent 工具集
  4. 注入 `report_to_parent` 工具定义（从 report_tool.py 的 registry 获取）
- 子 Agent 的 LLMClient 调用时传入该工具集
- `report_to_parent` handler 内部通过上下文变量找到当前 SubAgentLoop，写入 outbox

## 阶段五：边缘情况和测试注意点

### 5.1 上下文变量传递
- `report_to_parent` 工具需要知道是哪个 SubAgentLoop 在调用它
- 方案：在 SubAgentLoop 执行工具调用时设置 `contextvars.ContextVar`，handler 中读取

### 5.2 父 Agent 中断/终结回调
- `AgentLoop.interrupt()` 中调用 `_subagent_orchestrator.interrupt()`
- `terminate_session` API 中调用 `_subagent_orchestrator.terminate_parent()`

### 5.3 父会话旋转
- 父 Agent 的 `_rotate_session_for_continuation` 发生时，子 Agent 的 session_id 中旧父 ID 过时
- 方案：旋转时不关闭子 Agent，允许子会话历史引用旧父 ID（子会话 ID 中的父 ID 部分为历史快照）

### 5.4 安全性
- `approval_subagent` danger_level 为 readonly，父 Agent 调用时不触发用户确认
- `report_to_parent` 不在父 Agent 工具注册表中，仅子 Agent 可用
- 子 Agent 工具集自动排除 multiagent，reject 时会报明确错误
