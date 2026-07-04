---
name: replace-message-system-with-history
overview: 使用 origin_agent/entity/messages.py 中的 History/BaseMessage 模型替换当前 OpenAI dict 运行时历史和 JSONL 持久化，支持多 agent 可见性与响应需求分离，迁移脚本独立运行。
todos:
  - id: define-interfaces
    content: 定义新接口：BaseAgentLoop 引入 History 与 current_character_agent，MemoryProvider 接收 History，messages.py 补充工具方法
    status: completed
  - id: persistence-layer
    content: 升级持久化层：SessionStore 支持 history.es 读写，SessionManager 支持仅移除索引
    status: completed
  - id: parent-loop
    content: 改造 ParentAgentLoop：所有历史操作改用 History，加载失败时标记会话不可用
    status: completed
  - id: message-builders
    content: 改造 entry/agent_support/messages.py：基于 History 构建 LLM 消息，传递 suffix 参数
    status: completed
  - id: subagent-loop
    content: 改造 SubAgentLoop/Orchestrator：使用 History 保存/加载子 agent 历史
    status: completed
  - id: memory-provider
    content: 升级 EasysaveMemoryProvider：从 History 中提取并持久化回合
    status: completed
  - id: startup-format-detection
    content: 改造 gateway/server.py：旧格式会话从索引移除并通知前端
    status: completed
  - id: frontend
    content: 前端改造：新消息类型、头像/可见性展示、输入栏响应状态按钮
    status: completed
  - id: migration-script
    content: 编写 scripts/migrate_messages_jsonl_to_history.py 迁移脚本
    status: completed
  - id: integration-review
    content: 集成验证：检查 tool_calls 配对、visible_characters、session 旋转等边界场景
    status: completed
isProject: false
---

# 替换消息系统为 History 的实施计划

## 1. 概述

采用**自上而下（路径二）**的实施顺序：先定义 `BaseAgentLoop` / `MemoryProvider` 的新接口，再反向实现底层 `History` 模型、`SessionStore`、agent loop、前端与迁移脚本。这样能保证接口倒置的抽象不被破坏，减少防御性代码。

## 2. 分阶段实施

### 阶段 1：定义新接口（`entity/messages.py` + `entry/base_agent_loop.py` + `abstract/memory/provider.py`）

目标：在不修改具体实现的情况下，先把上层抽象定下来。

#### `origin_agent/entity/messages.py`
- 新增 `CharacterConversationMessage.from_text(role, character_name, text, visible_characters=None, **kwargs)` 类方法
- 新增 `CharacterConversationMessage.from_tool_calls(role, character_name, content, tool_calls, reasoning=None)` 类方法
- 新增 `CharacterConversationMessage.with_suffix(message_suffix)` 方法
- `History.get_messages()` 增加 `to_openai()` 别名，语义更明确
- `History.add_message()` 在追加前检查：若新消息是 `ToolResultMessage`，则前一条必须是含对应 `tool_call_id` 的 `CharacterConversationMessage`；若不是，记录 warning 并跳过追加
- 新增 `History.remove_unpaired_tool_calls()`：扫描整个 `messages` 列表，移除没有对应 `ToolResultMessage` 的 `tool_calls`

#### `origin_agent/entry/base_agent_loop.py`
- `_history: list[dict]` → `_history: History`
- 新增抽象属性：
  ```python
  @property
  @abstractmethod
  def current_character_agent(self) -> str: ...
  ```
- `_get_history()` 返回 `History`
- `_append_history(entry: dict)` → `_append_history(message: BaseMessage)`
- `_build_history_messages(user_message: str)` 内部改为：
  ```python
  return self._history.to_openai(
      self.current_character_agent,
      non_persistent_injection_suffix=...,
      message_suffix=...,
  ), fixator_context
  ```
- `_execute_tool()` 返回 `ToolResultMessage` 而不是 dict（具体子类负责包装）

#### `origin_agent/abstract/memory/provider.py`
- `sync_turn` 签名改为：
  ```python
  def sync_turn(self, history: History, *, session_id: str = "") -> None: ...
  ```

#### `origin_agent/abstract/memory/manager.py`
- `sync_all` 签名改为：
  ```python
  def sync_all(self, history: History, *, session_id: str = "") -> None: ...
  ```
- `prefetch_all` 保持字符串 query，但内部可从 `History` 提取最后一条 user 消息文本

### 阶段 2：持久化层（`system/session_store.py` + `gateway/chat.py`）

#### `origin_agent/system/session_store.py`
- 新增：
  ```python
  def history_path(self, session_id: str) -> Path: ...
  def read_history(self, session_id: str) -> History: ...
  def write_history(self, session_id: str, history: History) -> None: ...
  ```
- `history.es` 使用 `third/easysave` 的多态序列化保存/读取 `History` 实例
- 保留 `messages_path` / `read_messages` / `append_message` 等旧接口，仅用于迁移脚本读取

#### `origin_agent/gateway/chat.py` 中的 `SessionManager`
- 新增：
  ```python
  def remove_from_index(self, sid: str) -> None: ...
  ```
  只从 `_index.json` 中移除 session，不删除磁盘目录，保留旧文件

### 阶段 3：主循环适配（`entry/parent_agent_loop.py` + `entry/agent_support/messages.py`）

#### `origin_agent/entry/parent_agent_loop.py`
- 新增 `IncompatibleHistoryError`（可放在本文件或 `entity/exceptions.py`）
- `current_character_agent` 属性返回 `MAIN_AGENT_CHARACTER_NAME`
- `_append()` 改为构造 `CharacterConversationMessage.from_text(...)` 并调用 `_history.add_message()`
- `_store_assistant_with_tools()` 改为 `CharacterConversationMessage.from_tool_calls(...)`
- `_maybe_inject_inbox()` 改为 `CharacterConversationMessage.from_text(role=USER, character_name=USER_CHARACTER_NAME, visible_characters=[MAIN_AGENT_CHARACTER_NAME])`
- `_get_full_history()` 改为 `self._history.to_openai(self.current_character_agent)`
- `_persist_message()` 改为 `self._session_store.write_history(session_id, self._history)`
- `__init__` 中从磁盘加载：
  ```python
  if self._session_store is not None:
      try:
          disk_history = self._session_store.read_history(self.session_id)
          if disk_history:
              self._history = disk_history
      except Exception as exc:
          logger.warning("Session %s history incompatible: %s", self.session_id, exc)
          raise IncompatibleHistoryError(self.session_id) from exc
  ```
- `get_session_messages()` 返回前端格式：
  ```python
  {
      "role": "user" | "agent" | "system" | "tool",
      "content": str,
      "index": int,
      "character_name": str,
      "visible_characters": list[str],
      "requires_response": bool,
      "reasoning_content": str | None,
  }
  ```
- session 旋转后的 summary 注入：
  ```python
  CharacterConversationMessage.from_text(
      role=Role.USER,
      character_name=USER_CHARACTER_NAME,
      content=summary,
      visible_characters=[MAIN_AGENT_CHARACTER_NAME],
  )
  ```
- `_memory.sync_all(...)` 调用改为传入 `self._history`

#### `origin_agent/entry/agent_support/messages.py`
- `build_turn_messages()` 和 `build_full_history_messages()` 的 `history` 参数改为 `History`
- 不再直接修改历史消息的 `content`，而是把 `memory_ctx` 作为 `non_persistent_injection_suffix`、把 `fixator_context` 作为 `message_suffix` 传给 `History.to_openai()`
- 返回值保持 `(messages: list[dict], fixator_context: str)`

### 阶段 4：子 Agent 适配（`subagent/loop.py` + `subagent/orchestrator.py`）

#### `origin_agent/subagent/loop.py`
- `current_character_agent` 属性返回 `self._name`
- `_history` 改为 `History`
- 构造消息时使用 `CharacterConversationMessage.from_text(...)` 或 `from_tool_calls(...)`
- `save_history()` 改为保存 `history.es`（调用 `self._session_store.write_history()` 或直接用 easysave）
- `_get_history_path()` 扩展名改为 `.es`
- `_make_tool_msg()` 返回 `ToolResultMessage`

#### `origin_agent/subagent/orchestrator.py`
- 加载子 agent 历史时从 `.es` 读取 `History`
- `get_snapshot()` 从 `History` 中提取反馈，保留现有 WS 推送格式

### 阶段 5：MemoryProvider 升级（`memory/provider.py`）

#### `origin_agent/memory/provider.py`
- `EasysaveMemoryProvider` 持久化结构从 `{"turns": [{"user": ..., "assistant": ...}]}` 改为保存 `History`（或按 provider 自己的结构）
- `sync_turn(history, session_id)` 从 `History` 中提取最后一条 user 消息和对应的 assistant 消息文本
- `prefetch(query, session_id)` 保持从 provider 自己的存储中搜索

### 阶段 6：启动时旧格式处理（`gateway/server.py`）

#### `origin_agent/gateway/server.py`
- 导入 `IncompatibleHistoryError`
- 在创建 `ParentAgentLoop` 并加载历史时捕获该异常：
  ```python
  try:
      loop = ParentAgentLoop(...)
  except IncompatibleHistoryError as exc:
      logger.warning("Removing incompatible session from index: %s", exc.session_id)
      session_manager.remove_from_index(exc.session_id)
      await ws.send_text(Message(
          type=MessageType.ERROR,
          session_id=sid,
          message=f"会话 {exc.session_id} 的历史格式不兼容，已从索引移除。请运行迁移脚本后重连。",
      ).to_json())
      await ws.close()
      return
  ```

### 阶段 7：前端改造（`origin_agent/frontend/src/`）

#### `origin_agent/frontend/src/types.ts`
- `ChatMessage` 增加字段：
  ```typescript
  character_name?: string;
  visible_characters?: string[];
  requires_response?: boolean;
  ```

#### `origin_agent/frontend/src/hooks/useWebSocket.ts`
- 解析 `session_history` 时映射新字段到 `ChatMessage`
- 保留现有 `role/content/index/reasoning_content` 字段兼容

#### `origin_agent/frontend/src/components/MessageItem.tsx`
- 根据 `character_name` 生成头像（首字母 + 哈希背景色）
- 增加 tooltip 显示全名
- 展示 `visible_characters` 和 `requires_response` 元数据（小标签形式）
- 保持现有消息气泡样式

#### `origin_agent/frontend/src/components/InputBar.tsx`
- 当前子会话 loop 模式下，为每个 active subagent 增加状态按钮：
  - 未选中：消息不可见
  - 选中：消息对该 agent 可见且需要响应（当前阶段只有两种状态）
- 未来多 agent 模式扩展为三种状态：不可见 / 可见 / 需要响应
- 将选择结果通过 `target_sessions` 或新增字段发送给后端

#### `origin_agent/frontend/src/styles/messages.css`
- 增加 `.message-avatar` 的动态背景色类
- 增加可见性/响应需求元数据标签样式

### 阶段 8：迁移脚本（`scripts/migrate_messages_jsonl_to_history.py`）

- 扫描 `workspace/logs/sessions/` 下所有 `messages.jsonl`
- 逐条解析 OpenAI 格式 dict，映射为 `BaseMessage` 子类：
  - `role == "system"` → `CharacterSystemMessage`
  - `role == "user"` → `CharacterConversationMessage(character_name=USER_CHARACTER_NAME)`
  - `role == "assistant"` → `CharacterConversationMessage(character_name=MAIN_AGENT_CHARACTER_NAME)`
  - `role == "tool"` → `ToolResultMessage(character_name=MAIN_AGENT_CHARACTER_NAME)`
- 删除所有已保存的 system prompt
- 从 `origin_agent/templates/messages/` 加载最新 system prompt 并追加到历史头部
- 调用 `History.remove_unpaired_tool_calls()`
- 保存为 `history.es`
- 不删除原 `messages.jsonl`
- 输出迁移报告

### 阶段 9：集成验证

- 验证新会话创建、发送消息、LLM 响应、工具调用、工具结果完整流程
- 验证 session 旋转后 summary 正确注入
- 验证反序列化后 system prompt 更新
- 验证未配对 tool_calls 被清理
- 验证旧格式会话被移除索引且不可用
- 验证前端头像、可见性元数据、输入栏按钮正常

## 3. 关键接口签名汇总

```python
# origin_agent/entry/base_agent_loop.py
@property
@abstractmethod
def current_character_agent(self) -> str: ...

# origin_agent/abstract/memory/provider.py
def sync_turn(self, history: History, *, session_id: str = "") -> None: ...

# origin_agent/abstract/memory/manager.py
def sync_all(self, history: History, *, session_id: str = "") -> None: ...

# origin_agent/system/session_store.py
def history_path(self, session_id: str) -> Path: ...
def read_history(self, session_id: str) -> History: ...
def write_history(self, session_id: str, history: History) -> None: ...

# origin_agent/gateway/chat.py
class SessionManager:
    def remove_from_index(self, sid: str) -> None: ...
```

## 4. 错误处理策略

- `SessionStore.read_history()` 失败时抛出异常
- `ParentAgentLoop` 捕获后包装为 `IncompatibleHistoryError` 并向上抛出
- `gateway/server.py` 捕获后从索引移除 session，关闭 WebSocket，提示用户运行迁移脚本
- 任何单个 provider 的 `sync_turn` 失败只记录日志，不影响主流程

## 5. 测试方法

- 创建新会话，进行多轮对话，确认 `history.es` 正常保存
- 重启服务，确认历史正确恢复
- 人为放置旧 `messages.jsonl`，确认会话被移除索引
- 运行迁移脚本后，确认旧会话可恢复
- 前端检查头像、可见性标签、输入栏按钮

## 6. 实施清单

1. 在 `entity/messages.py` 中补充 `CharacterConversationMessage` 工具方法和 `History` 清理/别名方法。
2. 在 `entry/base_agent_loop.py` 中定义 `current_character_agent`、`_history: History`、`_append_history(BaseMessage)` 和新 `_build_history_messages`。
3. 在 `abstract/memory/provider.py` 和 `abstract/memory/manager.py` 中升级 `sync_turn` / `sync_all` 签名。
4. 在 `system/session_store.py` 中新增 `history_path` / `read_history` / `write_history`。
5. 在 `gateway/chat.py` 的 `SessionManager` 中新增 `remove_from_index`。
6. 在 `entry/parent_agent_loop.py` 中实现 `current_character_agent`、改造所有历史操作、加载失败时抛出 `IncompatibleHistoryError`。
7. 在 `entry/agent_support/messages.py` 中改造 `build_turn_messages` / `build_full_history_messages` 以操作 `History` 并传递 suffix 参数。
8. 在 `subagent/loop.py` 中改用 `History`、设置 `current_character_agent`、保存 `.es`。
9. 在 `subagent/orchestrator.py` 中从 `.es` 加载子 agent 历史。
10. 在 `memory/provider.py` 中升级 `EasysaveMemoryProvider` 接收 `History`。
11. 在 `gateway/server.py` 中捕获 `IncompatibleHistoryError` 并移除索引。
12. 在 `origin_agent/frontend/src/types.ts` 中扩展 `ChatMessage`。
13. 在 `origin_agent/frontend/src/hooks/useWebSocket.ts` 中解析新 `session_history` 字段。
14. 在 `origin_agent/frontend/src/components/MessageItem.tsx` 中实现头像、可见性展示。
15. 在 `origin_agent/frontend/src/components/InputBar.tsx` 中实现响应状态按钮。
16. 在 `origin_agent/frontend/src/styles/messages.css` 中增加头像和元数据样式。
17. 编写 `scripts/migrate_messages_jsonl_to_history.py`。
18. 集成验证并修复边界问题。