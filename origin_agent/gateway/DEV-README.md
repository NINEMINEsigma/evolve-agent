# gateway/ — WebSocket / HTTP 网关与会话管理

`gateway/` 负责 Evolve Agent 对外的所有网络交互：前端 WebSocket 长连接、REST API、会话生命周期管理以及 Dashboard。

---

## 文件结构

```
gateway/
├── server.py                ← FastAPI 应用本体：静态资源、REST API、WS 路由
├── chat.py                  ← ChatSessionManager：会话索引、归档、合并、分支
├── session_manager.py       ← SessionManager：session_id → ParentAgentLoop 映射
└── __init__.py

dashboard/
└── server.py                ← Web 管理面板（被 gateway/server.py 挂载）
```

---

## 分层职责

| 文件 | 职责 |
|---|---|
| `server.py` | FastAPI 应用：挂载前端静态文件、注册 REST 路由、运行 `WS /ws/chat`、把前端消息路由给 `ParentAgentLoop`、把后端事件推回前端。 |
| `chat.py` | `ChatSessionManager`：维护会话元数据索引（`_index.json`），提供会话的创建、归档、删除、合并、分支、标签、标题等操作。 |
| `session_manager.py` | `SessionManager`：在 `ChatSessionManager` 之上维护 `session_id → ParentAgentLoop` 映射，负责创建/恢复会话、终止会话、会话旋转后的 Loop 切换。 |

---

## WebSocket 协议

### 端点

```
WS /ws/chat?resume=<sid>
```

- 不带 `resume`：创建新会话。
- 带 `resume`：恢复已有会话，重放历史。

连接建立后，服务端发送：

- `build_hash`：当前前端构建哈希，变化时前端提示刷新。
- `server_info`：服务端信息。
- `session_history`：恢复会话时回放历史消息。

### 上行消息类型

| 类型 | 说明 |
|---|---|
| `user_message` | 用户发送的文本/图片消息 |
| `confirm_response` | 审批确认/拒绝 |
| `ask_response` | ask_question 回答 |
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
| `subagent_update` | 子代理状态更新 |
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
| POST | `/api/sessions/{id}/regenerate` | 重新生成最后一条回复 |

### 工具资源与子代理

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/sessions/{id}/tool-resources` | 工具资源 |
| GET | `/api/sessions/{id}/subagents` | 当前会话的子代理状态 |
| POST | `/api/confirm/{request_id}` | 审批响应 |
| POST | `/api/ask/{request_id}` | 提问响应 |
| POST | `/api/interrupt/{session_id}` | 中断会话 |
| POST | `/api/file-picker` | 系统文件选择器 |
| POST | `/api/shutdown-approval-model` | 卸载审批模型服务 |

### 后台任务

| 方法 | 端点 | 说明 |
|------|------|------|
| GET/POST | `/api/sessions/{id}/background-tasks` | 后台任务列表/停止 |
| GET/POST | `/api/sessions/{id}/cron-tasks/...` | Cron 任务列表/触发/取消 |

### 静态文件

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/uploads/{path}` | 静态文件访问 |
| GET | `/downloads/{path}` | 文件下载 |

---

## 会话持久化

单个会话的数据由 `system/session_store.py` 持久化到 `workspace/sessions/<session_id>/`：

| 文件 | 说明 |
|---|---|
| `history.es` | 新版消息历史（v1，easysave 多态序列化） |
| `messages.jsonl` | 旧版消息历史（v0，兼容/迁移用） |
| `summary.txt` | 会话摘要 |
| `token_usage.json` | token 消耗 |
| `tool_resources.json` | 任务进度、剪贴板展示等 |

全局会话索引：`workspace/sessions/_index.json`。

