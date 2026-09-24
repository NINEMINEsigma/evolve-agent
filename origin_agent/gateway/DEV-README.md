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
| `INTERRUPT` | `handle_interrupt` | WS 兼容中断入口；后台调用统一 `request_interrupt()` 并通过 done callback 观察异常，前端权威交互使用 HTTP |
| `FILE_UPLOAD` | `handle_file_upload` | 文件上传：硬链接优先 → 复制 fallback → base64 解码 |
| `HANDSFREE_MODE` | `handle_handsfree_mode` | 切换手动/脱手/YOLO 模式；服务端实际模式先更新内存，再尽力原子写入会话文件并回送权威值 |
| `PING` | `handle_ping` | 心跳响应 |
| `SYSTEM` | `handle_system_message` | 系统消息（仅记录日志；多模态块使用占位符，不改变既有无截断约定） |
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
- 带 `resume`：只恢复已有会话，重放历史。这里的 `resume` 是 WebSocket 连接恢复参数，不等同于下方 REST `/api/sessions/{id}/resume` 的“恢复工具链执行”操作；两者都不会因为前端当前选择了新的 Profile 而自动更新会话配置。显式目标处于删除中或从内存、磁盘均不存在时，Gateway 拒绝握手，不再创建随机替代会话。

永久删除已建立连接时，Gateway 使用关闭码 `WEBSOCKET_CLOSE_SESSION_DELETED`（4004）使连接失效；前端收到后停止按旧会话 ID自动重连并切换到“随意聊聊”。握手前的拒绝可能被浏览器报告为 1006，前端因此通过 `/api/sessions/{id}/status` 的 `exists`再次确认；删除中的会话也按 `exists=false`返回。

连接建立后，服务端发送：

- `build_hash`：当前前端构建哈希，变化时前端提示刷新。
- `server_info`：服务端信息。
- `handsfree_mode`：每次连接都会主动发送的当前会话权威审批模式，包含兼容布尔字段 `handsfree_mode` 与三态字段 `approval_mode`。已有会话由 `ApprovalModeStore` 从 `approval_mode.es` 的 easysave `v1` key惰性重建 `SessionApprovalModeState`；新建普通主会话、派生主会话和首次创建的“随意聊聊”默认手动模式。前端不持久化该值。
- `history_sync`：新建/恢复连接以及每轮正典 History 写入完成后发送；顶层携带 `history_count`、`processing`、`token_usage`、`context_tokens` 和可选 `agents`，不携带正文。前端随后通过 History REST 按需加载。
- `agentspace_event` 初始序列：`resync`、`locks`及 watcher不可用时的 `watcher_error`；随后复用同一 EventHub订阅转发文件变化。事件突发时允许折叠为 `resync`，连接断开时取消转发 task并注销订阅；自动旋转复用同一物理连接和订阅。

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
| `client_diagnostic` | 前端关键请求等待超过15秒时上报的脱敏客户端传输诊断；Gateway只记录 warning，不调用 Agent Loop、不写 History |

### 下行消息类型

| 类型 | 说明 |
|---|---|
| `system` | 系统通知；可选 JSON `stream_meta`携带 `stream_id`、`history_index`、`live_history_links`（实时行到正典行的明确关联），或顶层携带 system status 的 `index`/`is_system_status`。关联只在对应 History 写入后发送；前端不得按正文、顺序或实时版本猜测映射。多Agent模式继续携带可见性/响应角色。 |
| `user_message` | 用户消息回显 |
| `assistant_message` | 完整助手消息 |
| `stream_delta` | LLM 流式文本块 |
| `stream_done` | 流式生成结束 |
| `tool_call` | 工具调用开始 |
| `tool_result` | 工具执行结果 |
| `task_progress` | 任务进度更新 |
| `clipboard_display` | 剪贴板展示更新 |
| `subagent_update` | 子会话状态更新 |
| `history_sync` | 正典历史同步元数据；正文通过 REST 加载 |
| `agentspace_event` | 聊天页会话视觉使用的 typed Agentspace事件；载荷沿用既有文件、锁和重同步元数据范围 |
| `llm_profile_changed` | Profile 重命名/删除通知；顶层携带 `operation`、`old_name`、`new_name` |
| `metadata_profile_changed` | 全局元数据 Profile 状态通知；显式携带可空名称、模型和可用性 |
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
| GET | `/api/sessions/{id}/status` | 返回内存索引中的存在状态与 WebSocket 占用状态；删除中按 `exists=false`处理 |
| GET | `/api/tags` | 全局标签列表 |
| PUT | `/api/sessions/{id}/tags` | 更新会话标签 |
| PUT | `/api/sessions/{id}/title` | 手动设置标题 |
| POST | `/api/sessions/{id}/auto-title` | 自动生成标题 |
| POST | `/api/sessions/{id}/auto-tags` | 自动生成标签 |
| POST | `/api/sessions/{id}/terminate` | 终结会话；元数据生成失败不阻止归档，响应通过 `metadata_warnings`返回警告 |
| POST | `/api/sessions/{id}/pin` | 置顶切换 |
| POST | `/api/sessions/{id}/branch` | 从会话创建分支；缺摘要时保底生成，失败不创建延续会话 |
| POST | `/api/sessions/merge` | 合并多个已归档会话；所有父摘要必须齐备，任一失败则整体失败 |
| DELETE | `/api/sessions/{id}` | 永久删除会话；拒绝“随意聊聊”、不存在目标和重复删除 |

永久删除先建立进程内删除中标记以阻止新连接重建 Loop，再关闭现有 WebSocket、停止子Agent、回收活动回复/消息队列/客户端信息/Cron 注册，随后删除会话索引与目录并清理 Shell、Cron 和动态端点。删除中并发请求对已移除的 Loop返回未找到或未就绪；附带资源清理失败不回滚已经完成的永久删除。

### 聊天 History 按需读取

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/sessions/{id}/history/skeleton?start_index=` | 返回全历史骨架或 append-only 后缀，不含正文 |
| GET | `/api/sessions/{id}/history/page?start_index=&limit=` | 按 History 消息索引范围返回完整前端投影行 |
| GET | `/api/sessions/{id}/history/resources` | 返回完整 History 的图片与下载资源索引 |

骨架与历史内容页只是 Gateway 读取视图，不改变 `History` / `history.es` 整体存储。工具请求和匹配的 ToolResultMessage 在前端投影为一个 `tool_card` 行，结果按 `tool_call_id` 配对并可跨 History 内容页返回；只有孤立结果保留为独立降级行。编辑、按轮删除、单条删除和重新生成在 Agent 处理期间统一返回 HTTP 409；结构修改后前端取消旧页请求并重取骨架。前端对会话状态预检、History骨架和历史内容页设置15秒硬截止；超时显示持久通知和局部重试，WebSocket可用时发送不含正文、工具参数、附件或密钥的 `client_diagnostic`。

### 消息编辑

| 方法 | 端点 | 说明 |
|------|------|------|
| PUT | `/api/sessions/{id}/messages/{index}` | 编辑历史消息 |
| DELETE | `/api/sessions/{id}/messages` | 清空历史消息 |
| POST | `/api/sessions/{id}/regenerate` | 重新生成最后一条回复；请求体必须携带 `llm_profile_name`，可同时更新本次生成使用的 Profile |
| POST | `/api/sessions/{id}/resume` | 从当前历史状态恢复工具链执行；不追加用户消息、不截断历史，也不更新 LLM Profile |
| POST | `/api/sessions/{id}/regenerate-summary` | 重新生成会话摘要 |

`/regenerate` 与 `/resume` 不在 Gateway 重复登记活动 task；对应 Loop 在取得 `_process_lock` 后自行登记当前回复，并在完整收尾后注销。

### 工具资源与子代理

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/sessions/{id}/tool-resources` | 工具资源 |
| GET | `/api/sessions/{id}/subagents` | 当前会话的子代理状态 |
| POST | `/api/confirm/{request_id}` | 审批响应 |
| POST | `/api/ask/{request_id}` | 提问响应 |
| POST | `/api/interrupt/{session_id}` | 强制中断已经取得处理锁的主会话当前回复 task；按活动 task 判定 idle，返回权威结果（cancelled / timeout / failed / not_found），不取消长期消息 consumer |
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

### 审批 Profile

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/approval/profile` | 返回项目级审批 Profile 的名称、模型和可用性 |
| PUT | `/api/approval/profile` | 按 Profile 名称设置或以 `null`清空审批 Profile引用 |

审批 Profile设置、清空、编辑失效或删除只更新 Profile根对象、审批后端缓存和 `approval_profile_changed` 广播；广播不携带审批模式重置字段，也不改写任何会话的手动/脱手/YOLO 模式。已恢复的脱手模式在审批后端不可用时保持不变，实际审批按既有失败路径拒绝；YOLO不依赖审批 Profile。PUT响应中的 `disabled_sessions` 仅为兼容字段，固定为空列表。

### 全局元数据 Profile

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/metadata/profile` | 返回全局元数据 Profile 的可空名称、模型与配置可用性 |
| PUT | `/api/metadata/profile` | 按 Profile 名称设置或以 `null`清空全局元数据 Profile |

自动标题、自动标签和摘要直接调用 Application 持有的 `SessionMetadataService`，不要求目标会话存在运行时 Loop。全局元数据 Profile未配置时按目标会话自己的活动 Profile回退；明确配置但不可用时返回失败，不静默回退。配置变化通过 `metadata_profile_changed`广播。删除当前元数据 Profile只清空全局引用，不自动采用删除请求中的替换 Profile。

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

Agentspace mutation body 均携带 `operation_id`；`write` 另携带 `expected_version`，`rename` 只接收 `path + new_name`。错误 `detail` 为机器可读对象：无效路径 400、不存在 404、目标或版本冲突 409、非 UTF-8 文本 415、命中 Agent 回复轮次文件锁 423、内部错误 500。该 SSE 只服务独立 Agentspace 编辑器：使用 `event: agentspace`，`id` 为进程内递增 sequence，连接后先发送 `resync` 与完整 `locks`，心跳为注释帧；断线重连后前端重新取得 REST 权威快照。聊天页视觉不再创建此 EventSource，而从已有会话 WebSocket接收 `agentspace_event`。

Agentspace SSE 长连接在 Gateway 收到关闭信号时主动结束；`main.py::App._stop_gateway()` 会等待 uvicorn 完成正常关闭，仅在超时后强制取消。`AgentspaceService` 的订阅在响应结束时由 `finally` 释放。

### 技能与动态端点

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/skills/list` | 技能列表 |
| POST | `/dynamic/{session_id}/{agent_name}/{endpoint_name}` | 动态端点调用 |

---

## 会话持久化

单个会话的数据持久化到 `workspace/sessions/<session_id>/`。History等内容由 `system/session_store.py` 管理，审批模式由 Application持有的 `ApprovalModeStore` 管理：

| 文件 | 说明 |
|---|---|
| `history.es` | 新版消息历史（v1，easysave 多态序列化） |
| `summary.txt` | 会话摘要 |
| `token_usage.json` | token 消耗 |
| `tool_resources.json` | 任务进度、剪贴板展示等 |
| `approval_mode.es` | easysave `v1` key保存的 `SessionApprovalModeState`；BaseModel直接保存并通过 stable type token重建，缺失、缺 key、损坏或类型错误时回退手动模式；模式变更先更新内存再尽力保存，安全写入与 `.bak`由 easysave负责 |

归档保留 `approval_mode.es`；永久删除会话目录时一并删除，随后清理 Store缓存。自动延续、单源分支和多父合并不会复制该文件，新会话统一写入手动模式。

全局会话索引：`workspace/sessions/_index.json`。