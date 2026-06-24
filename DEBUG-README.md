# Evolve Agent 前端消息/审批停滞调试说明

## 追踪的 Bug

**症状**：前端在运行过程中突然不刷新后端的新消息和审批等内容；刷新页面后可能暂时恢复，但随后再次卡住。后端的 Agent 实际上已经响应，但前端看不到，导致工具调用审批超时。

**触发特点**：
- 不需要手动刷新或断开 WebSocket。
- 出现时机未知，无明显错误提示。
- 之前通过 `ignoreStaleRef` 重置修复过一次，但问题复现。

## 本次改动（仅增加观测点，未修改业务逻辑）

### 1. 顶部 Header 新增调试徽章

文件：`origin_agent/frontend/src/components/Header.tsx`、`origin_agent/frontend/src/styles/header.css`

在会话 ID 右侧增加一组状态徽章：

| 徽章 | 含义 | 颜色 | 诊断价值 |
|------|------|------|----------|
| 处理中 ⚡ | `waiting=true`，前端认为后端正在处理 | 脉冲白色 | 卡住时如果还亮，说明前端知道自己在等 |
| 流式 ✍️ | 当前存在 `streamingMessage` | 绿色 | 卡住时如果一直亮但内容不刷新，说明 `stream_delta` 没触发渲染 |
| 待审批 ⏳ | `pendingConfirm` 存在，弹窗应显示 | 红色 | 卡住时如果不亮但后端已发审批，说明审批消息没推到前端 |
| IGN | `ignoreStaleRef.current=true` | 黄色 | 中断后状态机未恢复，会丢弃后续 delta/工具事件 |
| 接收正常 / 接收停滞 🛑 | 距离上次收到 WS 消息的时间 | 绿/红 | 变红说明后端没推消息 |
| 心跳异常 | 距离上次收到 `pong` 超过 35 秒 | 橙色 | WebSocket 可能半开 |

**阈值说明**：
- 空闲状态（无 `waiting`、无流式）：30 秒没收到消息才标“接收停滞”。
- 活跃状态（`waiting` 或流式中）：2 秒没收到消息就标“接收停滞”。
- 心跳异常阈值 35 秒，覆盖前端 20 秒 ping 间隔，避免误报。

### 2. 前端 WebSocket hook 暴露状态并记录日志

文件：`origin_agent/frontend/src/hooks/useWebSocket.ts`

- 新增 `lastRecvAtRef`、`lastPongAtRef`、`recvTick`。
- 每次收到 WS 消息更新 `lastRecvAtRef`，收到 `pong` 更新 `lastPongAtRef`。
- 在 `console.debug` 打印每次接收的消息类型和长度（默认不显示，需开启 Verbose 级别）。
- 在 `types.ts` 中补上 `ping` / `pong` 消息类型。

### 3. 后端推送日志

文件：`origin_agent/gateway/server.py`

- `_send_tool_event` 增加 `logger.info` 记录发送事件：`session_id`、`event_type`、`tool_name`、`payload_len`。
- 成功/失败分别记录 `ws push ok` / `ws push fail`。
- 为避免日志淹没，**`stream_delta` 和 `usage_update` 不打印**。

### 4. App 透传状态

文件：`origin_agent/frontend/src/App.tsx`

- 将 `waiting`、`pendingConfirm`、`streamingMessage`、`ignoreStaleRef`、`lastRecvAtRef`、`lastPongAtRef`、`recvTick` 透传给 `Header`。

## 如何根据徽章定位根因

### 场景 A：徽章显示“接收停滞 🛑”变红
- 说明 WebSocket 已经很久没有收到任何消息。
- 查看后端日志：
  - 如果日志还在正常打印 `[ws push] ...` → 后端发了但前端没收到，可能是网络/浏览器事件循环阻塞/WebSocket 半开。
  - 如果日志停止打印 `[ws push]` → 后端自身卡住，可能是 `await ws.send_text()` 阻塞，或 Agent 循环没有继续推进。

### 场景 B：“接收正常”但消息/审批不刷新
- 说明 WS 消息到达了前端，但 React 状态机或渲染没更新。
- 打开浏览器 Console → Verbose，看 `[ws recv]` 是否打印了 `agent_message` / `confirm_request`。
- 如果日志收到但界面没变化 → 渲染层问题（如 `MessageItem` memo 条件、state 更新闭包 stale）。
- 如果 `confirm_request` 收到但 `待审批` 徽章不亮 → `pendingConfirm` 设置失败或组件未渲染。

### 场景 C：IGN 徽章亮起时卡住
- 说明 `ignoreStaleRef.current` 仍为 `true`。
- 这会导致所有 `stream_delta`、`tool_call`、`tool_result` 被丢弃。
- 根因：某个路径触发了中断但 `stream_done` 没有正确重置，或后续消息在中断状态被错误忽略。

### 场景 D：心跳异常亮起
- 说明超过 35 秒没收到 `pong`。
- 此时 WebSocket 可能已经半开（能发不能收），需要查看 Network → WS 里连接是否还在 `101` 状态。

## 下一步建议

1. 复现 bug 时截图顶部徽章状态。
2. 同时截取后端日志中该 session 的 `[ws push]` / `[ws push ok]` / `[ws push fail]` 输出。
3. 打开浏览器 Console → Verbose，看 `[ws recv]` 在卡住期间是否继续打印。
4. 根据上述场景定位到具体阶段后，再进入修复阶段。

## 文件变更清单

- `origin_agent/frontend/src/hooks/useWebSocket.ts`
- `origin_agent/frontend/src/components/Header.tsx`
- `origin_agent/frontend/src/App.tsx`
- `origin_agent/frontend/src/styles/header.css`
- `origin_agent/frontend/src/types.ts`
- `origin_agent/gateway/server.py`
- `DEBUG-README.md`（本文件）
