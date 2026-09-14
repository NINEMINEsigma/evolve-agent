# gateway/ — WebSocket / HTTP 网关与会话管理

`gateway/` 负责 Evolve Agent 对外的所有网络交互：前端 WebSocket 长连接、消息路由、REST API 以及会话生命周期管理。

---

## 文件结构

```
gateway/
├── server.py                ← FastAPI 应用本体：静态资源、REST API、WS 路由
├── message_router.py        ← MessageRouter：WebSocket 消息按类型分发
├── chat.py                  ← SessionManager：会话索引、归档、合并、分支
├── session_manager.py       ← SessionManager：session_id → IMainSessionLoop 映射
└── __init__.py
```

---

## 分层职责

| 文件 | 职责 |
|---|---|
| `server.py` | FastAPI 应用：挂载前端静态文件、注册 REST 路由、运行 `WS /ws/chat`、管理 WebSocket 连接生命周期。消息处理委托给 `MessageRouter`。 |
| `message_router.py` | `MessageRouter`：将 WebSocket 消息按类型分发到对应的处理方法。从 `server.py` 的 `ws_chat` 中拆分，负责所有消息类型的处理逻辑。 |
| `chat.py` | `SessionManager`：维护会话元数据索引（`_index.json`），提供会话的创建、归档、删除、合并、分支、标签、标题等操作。 |
| `session_manager.py` | `SessionManager`：在 `chat.py` 的 `SessionManager` 之上维护 `session_id → IMainSessionLoop` 映射，负责创建/恢复会话、终止会话、会话旋转后的 Loop 切换。通过 `Application.current()` 访问单例。 |

---

## MessageRouter

### `gateway/message_router.py`

`MessageRouter` 从 `server.py` 的 `ws_chat` 中拆分，负责所有 WebSocket 消息类型的分发处理。`ws_chat` 仅保留 WebSocket 连接生命周期管理。

**消息类型与处理方法映射**：

| 消息类型 | 处理方法 | 说明 |
|---|---|---|
| `USER_MESSAGE` | `handle_user_message` | 后台 task 执行：自动标题、归档检查、子 Agent 转发、主会话处理、session 旋转检查 |
| `CONFIRM_RESPONSE` | `handle_confirm_response` | 审批确认/拒绝，解析到 `FrontendSink` |
| `ASK_RESPONSE` | `handle_ask_response` | 提问回答，解析到 `FrontendSink` |
| `INTERRUPT` | `handle_interrupt` | 强制中断主会话当前轮次；与 HTTP 中断统一走 `request_interrupt()`，不乐观声明结果 |
| `FILE_UPLOAD` | `handle_file_upload` | 文件上传：硬链接优先 → 复制 fallback → base64 解码 |
| `HANDSFREE_MODE` | `handle_handsfree_mode` | 切换脱手/免审批模式 |
| `PING` | `handle_ping` | 心跳响应 |
| `SYSTEM` | `handle_system_message` | 系统消息（仅记录日志） |
| 其他 | `handle_unsupported` | 不支持的消息类型 |

**`handle_user_message` 子流程**：

1. `_auto_generate_title()`：首条消息自动生成标题。
2. `_dispatch_subagent_messages()`：转发消息到子 Agent 会话。
3. `_process_main_session()`：主会话消息处理，调用 `loop.process_message()`。
4. `_handle_session_rotation()`：检查 session 旋转，更新 WebSocket 映射。
5. `_emit_assistant_reply()`：发送 assistant 回复到前端。
6. `_send_token_update()`：发送 token 消耗更新。

---

## WebSocket 协议

### 端点

```
WS /ws/chat?resume=<sid>
```

- 不带 `resume`：创建新会话。
- 带 `resume`：恢复已有会话，重放历史。这里的 `resume` 是 WebSocket 连接恢复参数，不等同于下方 REST `/api/sessions/{id}/resume` 的“恢复工具链执行”操作；两者都不会因为前端当前选择了新的 Profile 而自动更新会话配置。

连接建立后，服务端发送：

- `build_hash`：当前前端构建哈希，变化时前端提示刷新。
- `server_info`：服务端信息。
- `handsfree_mode`：每次连接都会主动发送的当前会话权威审批模式，包含兼容布尔字段 `handsfree_mode` 与三态字段 `approval_mode`；新会话和恢复会话行为一致。
- `session_history`：恢复会话时回放历史消息；其中的审批模式字段仅保留作兼容回放，完整连接同步以独立 `handsfree_mode` 消息为准。

### 上行消息类型

| 类型 | 说明 |
|---|---|
| `user_message` | 用户发送的文本/图片消息 |
| `confirm_response` | 审批确认/拒绝 |
| `ask_response` | Ask 回答 |
| `interrupt` | 中断当前处理 |
| `file_upload` | 文件上传 |
| `handsfree_mode` | 切换免审批模式 |
| `ping` | 心跳 |

### 下行消息类型

| 类型 | 说明 |
|---|---|
| `system` | 系统通知 |
| `user_message` | 用户消息回显 |
| `assistant_message` | 完整助手消息 |
| `stream_delta` | LLM 流式文本块 |
| `stream_done` | 流式生成结束 |
| `tool_call` | 工具调用开始 |
| `tool_result` | 工具执行结果 |
| `task_progress` | 任务进度更新 |
| `clipboard_display` | 剪贴板展示更新 |
| `subagent_update` | 子会话状态更新 |
| `llm_profile_changed` | Profile 重命名/删除通知；顶层携带 `operation`、`old_name`、`new_name` |
| `confirm_request` | 请求用户审批 |
| `ask_request` | 请求用户回答 |
| `error` | 错误通知 |
| `pong` | 心跳响应 |

---

## REST API

### 会话管理

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/sessions` | 会话列表 |
| GET | `/api/tags` | 全局标签列表 |
| PUT | `/api/sessions/{id}/tags` | 更新会话标签 |
| PUT | `/api/sessions/{id}/title` | 手动设置标题 |
| POST | `/api/sessions/{id}/auto-title` | 自动生成标题 |
| POST | `/api/sessions/{id}/auto-tags` | 自动生成标签 |
| POST | `/api/sessions/{id}/terminate` | 终结会话（归档+摘要） |
| POST | `/api/sessions/{id}/pin` | 置顶切换 |
| POST | `/api/sessions/{id}/branch` | 从会话创建分支 |
| POST | `/api/sessions/merge` | 合并多个已归档会话 |
| DELETE | `/api/sessions/{id}` | 删除会话 |

### 消息编辑

| 方法 | 端点 | 说明 |
|------|------|------|
| PUT | `/api/sessions/{id}/messages/{index}` | 编辑历史消息 |
| DELETE | `/api/sessions/{id}/messages` | 清空历史消息 |
| POST | `/api/sessions/{id}/regenerate` | 重新生成最后一条回复；请求体必须携带 `llm_profile_name`，可同时更新本次生成使用的 Profile |
| POST | `/api/sessions/{id}/resume` | 从当前历史状态恢复工具链执行；不追加用户消息、不截断历史，也不更新 LLM Profile |
| POST | `/api/sessions/{id}/regenerate-summary` | 重新生成会话摘要 |

### 工具资源与子代理

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/sessions/{id}/tool-resources` | 工具资源 |
| GET | `/api/sessions/{id}/subagents` | 当前会话的子代理状态 |
| POST | `/api/confirm/{request_id}` | 审批响应 |
| POST | `/api/ask/{request_id}` | 提问响应 |
| POST | `/api/interrupt/{session_id}` | 强制中断主会话当前轮次；按活动任务判定 idle，返回权威结果（cancelled / timeout / failed / not_found） |
| POST | `/api/file-picker` | 系统文件选择器 |
| POST | `/api/shutdown-approval-model` | 卸载审批模型服务 |

### Shell会话与 Cron

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/sessions/{id}/shells` | 返回当前主会话全部 Shell会话元数据，不返回终端输出 |
| POST | `/api/sessions/{id}/shells/{shell_id}/stop` | 前端用户直接停止 Shell会话及其进程树 |
| GET/POST | `/api/sessions/{id}/cron-tasks/...` | Cron 任务列表/触发/取消 |

Shell 输出由 Agent 使用 `ReadShell` 拉取，不通过聊天 WebSocket 主动推送。WebSocket 断线不停止 Shell；自动旋转迁移所有权；手动终结、永久删除和应用关闭负责停止。

### LLM Profile

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/llm/profiles` | 返回 v2 `LLMProfileData` 的扁平 Profile 列表 |
| POST | `/api/llm/profiles` | 创建单个 Profile |
| PUT | `/api/llm/profiles` | 按原名称原地更新或重命名单个 Profile |
| DELETE | `/api/llm/profiles` | 删除 Profile，并为当前空闲会话指定替换名称或无配置 |
| GET | `/api/llm/clients` | 返回可用 LLM 客户端实现 |

前端 USER_MESSAGE 与重新生成请求只传 `llm_profile_name`，不传完整 Profile。空字符串表示明确无配置。`/resume` 请求不接收 `llm_profile_name`，始终使用当前 `ParentAgentLoop` 已持有的活动 Profile；前端刚切换但尚未通过 USER_MESSAGE 或重新生成提交的 Profile，不会被 resume 应用。Profile 重命名和删除通过 `llm_profile_changed` 广播；忙碌会话不在删除请求中切换。

### 静态文件

`/files`、`/downloads` 与 `/zip` 均复用 `Application.sandbox`，不再临时构造 Sandbox。因此 fast 模式下可读且当前目录存在的全局动态沙盒空间也遵循同一逻辑前缀解析、遍历防护和权限检查；fallback 不启用动态空间。

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/uploads/{path}` | 静态文件访问 |
| GET | `/downloads/{path}` | 文件下载 |
| GET | `/local-font/{font_path}` | 本地字体文件访问（CSS `@font-face` `src` 用途）；扩展名白名单 `woff2`/`woff`/`ttf`/`otf`，单文件 ≤ 20 MiB，响应 `Access-Control-Allow-Origin: *` |

### Agentspace

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/agentspace/list` | 目录优先自然排序的文件列表（兼容返回 `type`，权威字段为 `kind`） |
| GET | `/api/agentspace/read` | UTF-8 文本快照、SHA-256 version 与修改时间 |
| POST | `/api/agentspace/write` | 独占创建或携带 `expected_version` 的版本化保存 |
| POST | `/api/agentspace/mkdir` | 无覆盖创建目录 |
| POST | `/api/agentspace/delete` | 用户操作：移动到 Agentspace 垃圾桶 |
| POST | `/api/agentspace/rename` | basename-only、无覆盖重命名 |
| GET | `/api/agentspace/trash` | 垃圾桶条目列表 |
| POST | `/api/agentspace/trash/{entry_id}/restore` | 无覆盖恢复，冲突自动改名 |
| DELETE | `/api/agentspace/trash/{entry_id}` | 永久删除单条垃圾桶条目 |
| DELETE | `/api/agentspace/trash` | 清空垃圾桶，返回 partial failure |
| GET | `/api/agentspace/locks` | 当前回复轮次路径锁完整快照 |
| GET | `/api/agentspace/events` | Agentspace `text/event-stream` 实时事件 |

Agentspace mutation body 均携带 `operation_id`；`write` 另携带 `expected_version`，`rename` 只接收 `path + new_name`。错误 `detail` 为机器可读对象：无效路径 400、不存在 404、目标或版本冲突 409、非 UTF-8 文本 415、命中 Agent 回复轮次文件锁 423、内部错误 500。SSE 使用 `event: agentspace`，`id` 为进程内递增 sequence，连接后先发送 `resync` 与完整 `locks`，心跳为注释帧；断线重连后前端重新取得 REST 权威快照。

### 技能与动态端点

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/skills/list` | 技能列表 |
| POST | `/dynamic/{session_id}/{agent_name}/{endpoint_name}` | 动态端点调用 |

---

## 会话持久化

单个会话的数据由 `system/session_store.py` 持久化到 `workspace/sessions/<session_id>/`：

| 文件 | 说明 |
|---|---|
| `history.es` | 新版消息历史（v1，easysave 多态序列化） |
| `summary.txt` | 会话摘要 |
| `token_usage.json` | token 消耗 |
| `tool_resources.json` | 任务进度、剪贴板展示等 |

全局会话索引：`workspace/sessions/_index.json`。