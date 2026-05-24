---
name: Bug 修复与架构加固计划（Review + 日志分析 + 中断/fork 编辑反馈修订）
overview: 基于日志分析 + 用户反馈（中断不实时、fork 缺增量编辑），在原有计划基础上新增中断响应延迟问题和 fork 编辑能力增强，展开 P2 全部 7 条内容。
todos:
  - id: p00
    content: "P0-0: sandbox.py — fork: 加 READ 权限，解锁 evolve_code 和 edit_file 对 fork 的操作"
    status: pending
  - id: p01
    content: "P0-1: agent.py — _get_full_history 补全上下文 + user_message 写入 histories"
    status: pending
  - id: p02new
    content: "P0-2: agent.py — for 循环内每个工具执行前加中断检查（实时中断）"
    status: pending
  - id: p03
    content: "P0-3: shell.py — ws.send_text 失败时立即 deny 而非阻塞 3600s"
    status: pending
  - id: p04
    content: "P0-4: gateway/server.py — sessions.remove 移到正确位置"
    status: pending
  - id: p05
    content: "P0-5: frontend App.tsx — send() 加 readyState 守卫"
    status: pending
  - id: p16
    content: "P1-6: agent.py — 会话历史截断防溢出"
    status: pending
  - id: p17
    content: "P1-7: agent.py — 技能加载加缓存"
    status: pending
  - id: p18
    content: "P1-8: skills.py — remember 的 facts 加入 recall 搜索范围"
    status: pending
  - id: p19
    content: "P1-9: shell.py — _save_allowlist 失败记 warning 日志"
    status: pending
  - id: p110
    content: "P1-10: validator.py — 空 fork 目录返回 valid=false"
    status: pending
  - id: p111
    content: "P1-11: validator.py — validate_compile 加 errors=replace"
    status: pending
  - id: p112
    content: "P1-12: memory/provider.py — prefetch 截断追加 [truncated]"
    status: pending
  - id: p113
    content: "P1-13: prompt.py — _read_soul 统一路径策略"
    status: pending
  - id: p114
    content: "P1-14: frontend App.tsx — 重连加最大次数限制"
    status: pending
  - id: p115
    content: "P1-15: agent.py — memory 初始化改为 per-session"
    status: pending
  - id: p116
    content: "P1-16: agent.py — _execute_tool 同步工具改用 asyncio.to_thread"
    status: pending
  - id: p117
    content: "P1-17: code.py — write_fork schema 提示 LLM 可用 edit_file 做增量编辑"
    status: pending
  - id: p218
    content: "P2-18: run.py — CLI 参数空格不兼容"
    status: pending
  - id: p219
    content: "P2-19: main.py — Gateway 初始化失败导致进程永久挂起"
    status: pending
  - id: p220
    content: "P2-20: sandbox.py — Sandbox.run 路径参数死代码"
    status: pending
  - id: p221
    content: "P2-21: filesystem.py — _handle_exists 缺 SandboxError 捕获"
    status: pending
  - id: p222
    content: "P2-22: filesystem.py — _handle_edit 有 TOCTOU 竞态"
    status: pending
  - id: p223
    content: "P2-23: memory/provider.py — sys.path 重复累积污染"
    status: pending
  - id: p224
    content: "P2-24: gateway/chat.py — 会话无过期机制"
    status: pending
isProject: false
---

# Bug 修复与架构加固计划（Review + 日志分析 + 中断/fork 编辑反馈修订）

## 日志分析概要

- **evolve_code 永远返回 evolved: false**：sandbox 中 fork: 只有 WRITE，resolve_read("fork:") → SandboxError
- **_get_full_history 丢上下文**：LLM 在循环中重复创建文件、触发方式摇摆
- **中断不实时**：中断标志只在 while 顶部检查，for 循环内同步工具逐个执行时无法响应
- **fork 只有 full-write 无增量编辑**：edit_file 已存在但 fork 缺 READ 权限被阻断
- **memory 延迟初始化**：重连场景 `_memory_initialized` 不重置

---

## P0（崩溃/数据丢失/进化阻塞/用户体验）

### 0. sandbox.py — fork: 仅有 WRITE 权限，evolve_code 失败 + edit_file 被阻断

**文件**：`system/sandbox.py:55`

**双重症状**：
1. `evolve/code.py:48` 的 `resolve_read("fork:")` 抛 SandboxError → evolve_code 永远失败
2. `filesystem.py:198-224` 的 `_handle_edit` 需要先 `read()` 再 `write()` → `edit_file` 操作 fork 文件时也因缺 READ 被阻断

用户反馈：当前只有 `write_fork` 能做全量写入，无法对 fork 做 old_string/new_string 增量编辑。

**现状**：`edit_file`（filesystem 工具集）schema 已声明支持 `fork:` 路径，但权限不足。修完权限后即可用。

**修复**：`fork` 改为 `[Access.READ, Access.WRITE]`。同时更新 `write_fork` 的 schema description，提示 LLM：对于少量修改，可以用 `edit_file`（filesystem 工具）操作 `fork:` 路径做增量编辑。

---

### 1. agent.py — `_get_full_history` 丢失用户消息和上下文

**文件**：`entry/agent.py:219-228`

`_get_full_history` 只重建 `[system_prompt, history]`，缺失 user_message（从未写入 `_histories`）、memory_ctx、skill_blocks。第一轮 tool call 之后的所有 LLM 调用都看不到原始用户输入和记忆上下文。

**日志症状**：validate_fork.py 验证通过后被重新创建不同版本；trigger_restart.py 创建后又切换回 evolve_code。

**修复**：user_message 存入 `_histories`（role: "user"），`_get_full_history` 传入 memory_ctx 和 skill_blocks；或废弃 `_get_full_history`，改为在 messages 上增量追加。

---

### 2. agent.py — 中断响应延迟

**当前**：中断检查只在 while 顶部，for 循环内同步工具阻塞 event loop 时无法响应。

**修复**：for 循环内每个 `_execute_tool` 前加中断检查：

```python
for tc in resp.tool_calls:
    if self._interrupted.pop(session_id, False):
        return "已中断。"
    tool_msg = await self._execute_tool(tc, session_id)
```

---

### 3. shell.py — ws.send_text() 失败被静默吞掉

`_request_user_confirm` 中 `except Exception: pass` 吞掉 WS 发送失败。Future 永远不 resolve，agent 阻塞 3600 秒。

**修复**：发送失败时立即 `_pending_confirms.pop(request_id, None)` 并 return `"deny"`。

---

### 4. gateway/server.py — sessions.remove 破坏 session resume

`ws_chat` 的 `finally` 无条件执行 `sessions.remove(sid)`。页面刷新时先断连再重连，resume 的 session 在重新连接前已被销毁。

**修复**：`sessions.remove(sid)` 移到连接时，finally 中只清理 `_tool_ws_sinks` 和 pending confirms。

---

### 5. frontend App.tsx — send() 不检查 ws.readyState

`send()` 直接调 `wsRef.current.send(...)` 而不检查 `readyState === WebSocket.OPEN`。断连时调用抛未处理异常。

**修复**：加 `if (wsRef.current.readyState !== WebSocket.OPEN) return;` 前置守卫。

---

## P1（功能缺陷/逻辑错误）

### 6. agent.py — 会话历史无限增长

`_append` 无截断逻辑，长会话超出 LLM 上下文窗口。日志确认 8 分钟内 30+ 轮交互。

**修复**：在 `_build_messages` 中估算 token 数，超过阈值时丢弃最早的非 system 消息，或限制 `_histories` 最大长度。

### 7. agent.py — 每轮都重新加载技能

`_collect_skill_prompts` 每轮调 `list_skills()` + `load_skill()`，不必要的 IO。

**修复**：缓存技能列表和内容，仅在 `learn_skill`/`forget_skill` 被调用时失效缓存。

### 8. skills.py — remember 存储的 facts 无法检索

`remember` 将 facts 存入 `data["facts"]`，但 `recall_memory` 只搜 turns 不搜 facts。

**修复**：`_handle_recall` 在搜索时也匹配 `facts` 数组中的内容。

### 9. shell.py — _save_allowlist 失败静默丢失

`_save_allowlist` 中 `except Exception: pass`，"始终允许" 的写入失败被吞掉。

**修复**：至少记录 warning 日志，或返回写入状态给调用方。

### 10. validator.py — 空 fork 目录通过验证

空目录返回 `{valid: true, total: 0}`，evolve_code 会错误地触发 swap。

**修复**：`validate_directory` 返回 0 个文件时标记 `valid: false`。

### 11. validator.py — validate_compile 编码崩溃

`subprocess.run(encoding="utf-8")` 无 `errors="replace"`，Windows GBK 输出会导致崩溃。

**修复**：加 `errors="replace"`。

### 12. memory/provider.py — prefetch 截断无指示

`assistant[:500]` 截断无 `...` 后缀，LLM 收到不完整序列。

**修复**：截断时追加 `...[truncated]`。

### 13. prompt.py — _read_soul 用相对路径

`Path("SOUL.md")` 依赖 CWD，与 `_read_gene` 的 `_find_repo_root()` 不一致。

**修复**：改为 `_find_repo_root() / "workspace" / "SOUL.md"` 或统一策略。

### 14. frontend App.tsx — 重连无最大次数

指数退避无限重试，服务器永久宕机时浏览器一直重连。

**修复**：最大重试 10 次后停止，显示 "连接失败"。

### 15. agent.py — memory lazy-init 在 session 重连时失效

`_memory_initialized` 只设一次 bool，断连重连产生新 session_id 时不会重新初始化。

**修复**：改为 per-session 字典 `_memory_initialized: Dict[str, bool]`。

### 16. agent.py — 同步工具用 asyncio.to_thread 彻底解除 event loop 阻塞

与 P0-2 互补：P0-2 解决多工具之间能中断，P1-16 让单个工具执行不阻塞 event loop。

```python
if entry.is_async:
    result = await entry.handler(args)
else:
    result = await asyncio.to_thread(tool_registry.dispatch, tc.name, args)
```

注意：Python 不支持强制终止线程，cancel Future 时线程仍会跑完。但对于快速工具（文件读写）瞬间完成；慢速工具可通过共享取消标志做 cooperative cancellation。

### 17. code.py — write_fork schema 增加增量编辑提示

P0-0 修完权限后 `edit_file` 可用。在 `write_fork` 的 description 末尾追加：

> "For small targeted changes, prefer `edit_file` from the filesystem toolset with `fork:` paths — it allows old_string/new_string replacement without re-sending the entire file."

---

## P2（架构/健壮性）

### 18. run.py — CLI 参数空格不兼容

`--workspace /path/with spaces` 被拼成单个 argv，解析时按第一个空格拆分，路径含空格时错误。

**修复**：改用 `subprocess.run` 的 list 形式传参，每个 key 和 value 作为独立 argv 元素。

---

### 19. main.py — Gateway 初始化失败导致进程永久挂起

`_start_gateway` 失败后直接 return，`_shutdown_event` 永不被 set，`app.run()` 永久阻塞。

**修复**：失败时 `self._shutdown_event.set()` 使进程退出，或设置超时。

---

### 20. sandbox.py — Sandbox.run 路径参数死代码

`insert(0, ...)` 后紧跟 `raise`——路径替换功能未完成。

**修复**：实现路径替换逻辑或删除死代码，添加注释说明暂不支持。

---

### 21. filesystem.py — _handle_exists 缺 SandboxError 捕获

其他所有 handler 都有 `try/except SandboxError`，`_handle_exists` 没有。

**修复**：加 try/except。

---

### 22. filesystem.py — _handle_edit 有 TOCTOU 竞态

读和写之间文件可能被修改。

**修复**：读后对 old_string 做二次校验（写前再读一次确认匹配），或用文件锁。

---

### 23. memory/provider.py — sys.path 重复累积污染

`sys.path.insert(0, ...)` 在模块导入时执行，重复导入会累积污染。

**修复**：加 `if str(_THIRD) not in sys.path:` 守卫。

---

### 24. gateway/chat.py — 会话无过期机制

`SessionManager._sessions` 无限增长，无 TTL。

**修复**：加时间戳，定期清理超时会话。

---

## 实施顺序

```
P0-0（sandbox 权限 → 同时解锁 evolve_code 和 edit_file 对 fork 的操作）
→ P0-1（上下文丢失）→ P0-2（中断实时）→ P0-3（WS 阻塞）→ P0-4（session 销毁）→ P0-5（frontend 守卫）
→ P1-6（历史溢出）→ P1-7（技能缓存）→ P1-8（facts 检索）→ P1-9（allowlist 日志）
→ P1-10（空目录）→ P1-11（编码崩溃）→ P1-12（截断指示）→ P1-13（soul 路径）
→ P1-14（重连限制）→ P1-15（memory init）→ P1-16（asyncio.to_thread）→ P1-17（edit_file 提示）
→ P2-18→P2-19→P2-20→P2-21→P2-22→P2-23→P2-24
```
