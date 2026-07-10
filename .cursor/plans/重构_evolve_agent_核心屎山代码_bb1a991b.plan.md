---
name: 重构 Evolve Agent 核心屎山代码
overview: 基于 `shitscan_report.md` 的验证结果，按风险优先级分四阶段消除核心模块的技术债务：先止血（致命问题），再消除重复，再拆分上帝类，最后重构前端状态管理。
todos:
  - id: p0-sys-exit
    content: 修复 gateway/server.py index() 路由的 sys.exit(0)，改为返回 HTTP 500 错误响应
    status: completed
  - id: p0-mcp-logging
    content: 为 abstract/mcp/client.py 核心调用链的裸 except Exception 补充上下文日志，拆分 CancelledError 与业务异常
    status: pending
  - id: p1-approval
    content: 新建 entry/approval_executor.py，提取并统一 parent_agent_loop.py 与 multi_agent_loop.py 的审批逻辑
    status: completed
  - id: p1-cron
    content: 重构 component/extools/cron_tools.py，提取公共 task 操作函数，消除 API 层与 Handler 层重复
    status: pending
  - id: p1-gui
    content: 重构 component/extools/gui_windows.py，用模块级导入或装饰器消除 13 段重复导入块
    status: pending
  - id: p1-mcp-handlers
    content: 重构 abstract/mcp/client.py，用通用工厂函数替代四个重复的 handler 工厂
    status: pending
  - id: p2-ws-chat
    content: 拆分 gateway/server.py 的 ws_chat，新建 gateway/message_router.py 处理消息路由
    status: pending
  - id: p2-parent-loop
    content: 拆分 entry/parent_agent_loop.py 的 ParentAgentLoop，提取 session_manager/tool_executor/stream_consumer
    status: pending
  - id: p2-mcp-task
    content: 拆分 abstract/mcp/client.py 的 MCPServerTask，新建 transport 抽象层和 auth_recovery 模块
    status: pending
  - id: p3-websocket
    content: 拆分 frontend/src/hooks/useWebSocket.ts 为 connection/session/upload/subagent 四个独立 hook
    status: pending
  - id: p3-app
    content: 拆分 frontend/src/App.tsx，提取 Layout 和 ChatContextMenu 组件
    status: pending
  - id: p3-message
    content: 拆分 frontend/src/components/MessageItem.tsx，提取 MessageBody/MessageEditor/MessageAttachments 并补全类型
    status: pending
  - id: p3-header-dialog
    content: 简化 Header.tsx props，将 ConfirmDialog.tsx 的 toolTitle IIFE 改为查表映射
    status: pending
isProject: false
---

# 重构 Evolve Agent 核心屎山代码

## 背景

`shitscan_report.md` 指出的核心问题已验证属实。本计划按 **P0 止血 → P1 消除重复 → P2 拆分上帝类 → P3 前端重构** 分阶段推进，每个阶段独立可交付，降低对运行时的影响。

---

## 阶段 1：止血（致命级修复）

目标：消除会直接导致进程崩溃或关键错误被静默吞掉的缺陷。

### 1.1 修复 `gateway/server.py` 运行时 `sys.exit(0)`

- **文件**：[origin_agent/gateway/server.py](origin_agent/gateway/server.py)
- **位置**：`index()` 路由约 499-512 行
- **问题**：当前逻辑在 `index.html` 不存在时直接 `sys.exit(0)`，一个 HTTP 请求即可杀死 gateway 进程。
- **方案**：改为返回 HTTP 500 并附带可读错误信息；仅在前端构建缺失时记录 FATAL 日志，不终止进程。
- **预期结果**：未构建前端时返回 `500 Internal Server Error`，gateway 保持运行。

### 1.2 为 `abstract/mcp/client.py` 的关键裸异常补充日志

- **文件**：[origin_agent/abstract/mcp/client.py](origin_agent/abstract/mcp/client.py)
- **位置**：连接、RPC 调用、工具发现等路径（约 24 处 `except Exception`）
- **问题**：核心调用链大量 `except Exception: pass` 或 `except Exception: logger.warning(...)`，调试困难。
- **方案**：
  - 将 `except Exception` 拆分为 `except asyncio.CancelledError`、业务异常和兜底异常。
  - 在兜底分支记录 `logger.exception(...)`，包含 server_name、tool_name、method 等上下文。
  - 保留现有重试逻辑不变，仅改善可观测性。
- **预期结果**：关键路径至少输出异常栈，便于后续阶段定位问题。

---

## 阶段 2：消除重复代码

目标：将报告中高度重复的代码提取为公共模块，降低维护成本。

### 2.1 提取公共审批逻辑到 `entry/approval_executor.py`

- **文件**：
  - [origin_agent/entry/parent_agent_loop.py](origin_agent/entry/parent_agent_loop.py) `_execute_tool` 637-796 行
  - [origin_agent/entry/multi_agent_loop.py](origin_agent/entry/multi_agent_loop.py) `_execute_tool` 312-395 行
- **问题**：两套 `_execute_tool` 中 dangerous/write 判断、白名单检查、脱手模式、正常审批、拒绝结果构建、`allow_always` 加白名单的逻辑几乎完全相同。
- **方案**：
  - 新建 `entry/approval_executor.py`，定义 `ApprovalExecutor` 类或纯函数 `execute_with_approval(...)`。
  - 输入参数：tool_name、args、工具元数据、当前模式（handsfree/whitelist/normal）、审批回调。
  - 输出：`ToolResult` 或审批等待状态。
  - 替换 `parent_agent_loop.py` 和 `multi_agent_loop.py` 中的重复审批代码为统一调用。
- **预期结果**：审批规则变更只需改一处；两个 loop 的 `_execute_tool` 长度显著缩短。

### 2.2 统一 `component/extools/cron_tools.py` 的 API 层与 Handler 层

- **文件**：[origin_agent/component/extools/cron_tools.py](origin_agent/component/extools/cron_tools.py)
- **位置**：`_handle_list_cron_jobs` 657-697 行 vs `list_cron_tasks_for_session` 937-970 行等
- **问题**：两套函数构建相同的 task 字典、操作相同全局状态，只是参数来源不同。
- **方案**：
  - 提取公共函数 `_build_task_info(task, include_logs=False)`、`list_tasks_for_session(session_id)`、`cancel_task(session_id, task_id)`、`trigger_task(session_id, task_id)`。
  - Handler 仅做参数校验并调用公共函数；API 函数直接复用公共函数。
- **预期结果**：消除约 120-150 行重复代码。

### 2.3 用装饰器消除 `component/extools/gui_windows.py` 的重复导入块

- **文件**：[origin_agent/component/extools/gui_windows.py](origin_agent/component/extools/gui_windows.py)
- **位置**：13 个 `_handle_gui_*` 函数头部（66-475 行）
- **问题**：每个 handler 都重复 `try: import pyautogui as _pyautogui ...`。
- **方案**：
  - 在模块顶部统一导入 `pyautogui`，若不可用则在模块级提供统一的 `tool_error` 兜底。
  - 或新增装饰器 `@require_pyautogui`，在装饰器中统一处理导入失败和返回 `tool_error`。
- **预期结果**：13 段重复导入块压缩为 1 处。

### 2.4 通用化 `abstract/mcp/client.py` 的四个 handler 工厂

- **文件**：[origin_agent/abstract/mcp/client.py](origin_agent/abstract/mcp/client.py)
- **位置**：`_make_list_resources_handler`、`_make_read_resource_handler`、`_make_list_prompts_handler`、`_make_get_prompt_handler` 约 2500-2740 行
- **问题**：四个工厂 90% 结构相同，仅中间 MCP RPC 调用和结果解析不同。
- **方案**：
  - 定义通用工厂 `_make_mcp_request_handler(server, make_request: Callable, parse_result: Callable, method_name: str)`。
  - 原四个工厂变为对该通用工厂的闭包调用，只传入差异化的 `make_request` 和 `parse_result`。
- **预期结果**：四个工厂从约 240 行压缩到 80 行以内。

---

## 阶段 3：拆分上帝类/函数

目标：将承担过多职责的核心类/函数拆分为可独立测试的协作模块。

### 3.1 拆分 `gateway/server.py` 的 `ws_chat`

- **文件**：[origin_agent/gateway/server.py](origin_agent/gateway/server.py)
- **位置**：`ws_chat` 1364-1777 行；嵌套 `_handle_user_message` 1497-1665 行
- **问题**：单个函数负责 session 生命周期、消息路由、子 Agent 转发、历史回放、断开清理等 8 种消息类型。
- **方案**：
  - 新建 `gateway/message_router.py`，定义 `MessageRouter` 类。
  - 将 8 种消息类型的处理逻辑拆分为独立方法：`handle_user_message`、`handle_interrupt`、`handle_approval_response`、`handle_subagent_message`、...。
  - 将 `_handle_user_message` 提升为 `MessageRouter` 的方法，拆出子 Agent 转发、主会话处理、session 旋转等子方法。
  - `ws_chat` 仅保留 WebSocket 连接生命周期管理，调用 `MessageRouter` 处理消息。
- **预期结果**：`ws_chat` 长度从 414 行降至 100 行以内；消息处理可独立单元测试。

### 3.2 拆分 `entry/parent_agent_loop.py` 的 `ParentAgentLoop`

- **文件**：[origin_agent/entry/parent_agent_loop.py](origin_agent/entry/parent_agent_loop.py)
- **位置**：`ParentAgentLoop` 82-1456 行
- **问题**：类内同时管理 LLM 调用、Memory、Session 旋转、工具审批、前端事件、Token 追踪、工具统计、子 Agent、Hooks/Skills、消息编辑、自动标题。
- **方案**：
  - 新增 `entry/session_manager.py`：封装 session 创建、归档、旋转、历史消息追加、token 超限检查。
  - 新增 `entry/tool_executor.py`：基于阶段 2.1 的 `ApprovalExecutor`，封装工具分发、结果转换、UI 事件路由。
  - 新增 `entry/stream_consumer.py`：封装 LLM 流消费、tool_calls 收集、内容/推理内容分发、取消检查。
  - `ParentAgentLoop` 保留高层编排，将具体职责委托给上述三个模块。
- **预期结果**：`parent_agent_loop.py` 从 1456 行降至 400 行以内；职责边界清晰。

### 3.3 拆分 `abstract/mcp/client.py` 的 `MCPServerTask`

- **文件**：[origin_agent/abstract/mcp/client.py](origin_agent/abstract/mcp/client.py)
- **位置**：`MCPServerTask` 约 1074-1780 行
- **问题**：一个类管理 stdio/HTTP/SSE 三种传输、OAuth、重连、keepalive、RPC 锁、子进程 PID、工具刷新。
- **方案**：
  - 新增 `abstract/mcp/transport/` 包，定义 `McpTransport` 抽象基类。
  - 实现 `StdioTransport`、`HttpTransport`、`SseTransport` 三个子类，各自管理连接、重连、断开。
  - `MCPServerTask` 仅保留工具发现、认证恢复、生命周期协调，通过组合使用具体 Transport。
  - 将 OAuth/session 恢复逻辑提取到 `abstract/mcp/auth_recovery.py`。
- **预期结果**：`MCPServerTask` 长度减半；新增 transport 类型无需修改核心类。

---

## 阶段 4：前端状态管理与组件重构

目标：消除 `useWebSocket.ts` 状态黑洞和超级组件，提升可维护性。

### 4.1 拆分 `frontend/src/hooks/useWebSocket.ts`

- **文件**：[origin_agent/frontend/src/hooks/useWebSocket.ts](origin_agent/frontend/src/hooks/useWebSocket.ts)
- **位置**：全文件约 1510 行，35 个 `useState`、21 个 `useRef`、80+ 返回值
- **问题**：一个 hook 管理 WebSocket 连接、HTTP fetch、消息列表、输入、上传、滚动、子 Agent 面板、会话合并等。
- **方案**：
  - 新建 `frontend/src/hooks/useWebSocketConnection.ts`：仅负责 WebSocket 连接状态、重连、心跳、原始消息收发。
  - 新建 `frontend/src/hooks/useSessionStore.ts`：管理 messages、session、history、pendingConfirm 等会话状态。
  - 新建 `frontend/src/hooks/useUploadManager.ts`：管理文件上传队列和进度。
  - 新建 `frontend/src/hooks/useSubagentManager.ts`：管理子 Agent 面板和倒计时。
  - 原 `useWebSocket.ts` 变为组合上述 hook 的薄 facade，保持现有组件调用接口不变。
- **预期结果**：`useWebSocket.ts` 降至 200 行以内；状态变更影响范围可预测。

### 4.2 拆分 `frontend/src/App.tsx`

- **文件**：[origin_agent/frontend/src/App.tsx](origin_agent/frontend/src/App.tsx)
- **位置**：全文件 621 行，16 个 `useState`、6 个 `useEffect`
- **问题**：超级组件包含 tooltip、子面板、上下文菜单、路由状态、IIFE 渲染菜单项。
- **方案**：
  - 新建 `frontend/src/components/Layout.tsx`：包含 Header、Sidebar、Main、Panel 布局骨架。
  - 新建 `frontend/src/components/ChatContextMenu.tsx`：将 IIFE 渲染的右键菜单项提取为独立组件。
  - `App.tsx` 仅保留顶层状态组合和渲染 `Layout`。
- **预期结果**：`App.tsx` 降至 150 行以内。

### 4.3 拆分 `frontend/src/components/MessageItem.tsx`

- **文件**：[origin_agent/frontend/src/components/MessageItem.tsx](origin_agent/frontend/src/components/MessageItem.tsx)
- **位置**：全文件约 491 行
- **问题**：同一组件承担编辑、折叠、reasoning、markdown、附件、代码块、可见性切换等 8 个职责。
- **方案**：
  - 新建 `frontend/src/components/MessageBody.tsx`：负责 markdown/code/reasoning 渲染。
  - 新建 `frontend/src/components/MessageEditor.tsx`：负责消息编辑 UI 和回调。
  - 新建 `frontend/src/components/MessageAttachments.tsx`：负责附件展示。
  - `MessageItem.tsx` 保留容器职责，组合上述子组件。
  - 将 `markdownComponentsBase` 中所有 `: any` 替换为具体 props 类型。
- **预期结果**：`MessageItem.tsx` 降至 150 行以内；前端类型安全提升。

### 4.4 治理 `frontend/src/components/Header.tsx` 和 `ConfirmDialog.tsx`

- **文件**：
  - [origin_agent/frontend/src/components/Header.tsx](origin_agent/frontend/src/components/Header.tsx)
  - [origin_agent/frontend/src/components/ConfirmDialog.tsx](origin_agent/frontend/src/components/ConfirmDialog.tsx)
- **问题**：`Header.tsx` 20 个 props 且 ref drilling；`ConfirmDialog.tsx` 22 个 if 分支硬编码 toolTitle。
- **方案**：
  - `Header.tsx`：引入 React Context 传递连接诊断状态，移除 ref props；`DebugBadges` 使用自定义 hook 订阅心跳，替换 `forceRender`。
  - `ConfirmDialog.tsx`：将 toolTitle 映射提取为 `frontend/src/utils/toolLabels.ts` 的对象映射表，IIFE 改为查表函数。

---

## 验证与检查点

每个阶段结束后应满足：

1. **阶段 1 结束**：gateway 在未构建前端时返回 500 且不崩溃；MCP 关键路径异常可被日志捕获。
2. **阶段 2 结束**：`parent_agent_loop.py` 与 `multi_agent_loop.py` 中不再存在重复审批代码；`cron_tools.py`、`gui_windows.py`、MCP handler 工厂代码量显著下降。
3. **阶段 3 结束**：`ws_chat`、`ParentAgentLoop`、`MCPServerTask` 长度降至原长度的 1/3 以内；新增模块职责单一。
4. **阶段 4 结束**：`useWebSocket.ts` 返回值数量降至 20 个以内；`App.tsx`、`MessageItem.tsx` 拆分出独立组件。

## 不触碰的边界

- 不改 `workspace/` 目录下的任何文件（运行时副本）。
- 不改业务语义：审批通过/拒绝规则、MCP 工具调用协议、WebSocket 消息格式保持与原代码一致。
- 不引入新的构建工具或依赖（除阶段内必要的重构外）。
- 不运行 `python run.py`、不运行 `pnpm` 构建，仅通过源码编辑实现。