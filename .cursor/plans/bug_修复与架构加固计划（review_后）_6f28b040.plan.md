---
name: Bug 修复与架构加固计划（Review 后）
overview: 基于 Stages 1-6 Review 发现的 bug 和架构问题，按优先级组织修复计划。run.py 的 f-string 语法错误已由用户修复，不再列入。
todos:
  - id: p01
    content: "P0-1: agent.py — 修复 _get_full_history 丢失用户消息和上下文"
    status: pending
  - id: p02
    content: "P0-2: shell.py — ws.send_text 失败时立即 deny 而非阻塞 3600s"
    status: pending
  - id: p03
    content: "P0-3: gateway/server.py — sessions.remove 破坏 resume，移到正确位置"
    status: pending
  - id: p04
    content: "P0-4: frontend App.tsx — send() 加 readyState 守卫"
    status: pending
  - id: p15
    content: "P1-5: agent.py — 会话历史截断防溢出"
    status: pending
  - id: p16
    content: "P1-6: agent.py — 技能加载加缓存"
    status: pending
  - id: p17
    content: "P1-7: skills.py — remember 的 facts 加入 recall 搜索范围"
    status: pending
  - id: p18
    content: "P1-8: shell.py — _save_allowlist 失败记 warning 日志"
    status: pending
  - id: p19
    content: "P1-9: validator.py — 空 fork 目录返回 valid=false"
    status: pending
  - id: p110
    content: "P1-10: validator.py — validate_compile 加 errors=replace"
    status: pending
  - id: p111
    content: "P1-11: memory/provider.py — prefetch 截断追加 [truncated]"
    status: pending
  - id: p112
    content: "P1-12: prompt.py — _read_soul 统一路径策略"
    status: pending
  - id: p113
    content: "P1-13: frontend App.tsx — 重连加最大次数限制"
    status: pending
  - id: p2-group
    content: "P2-14~20: 架构加固（CLI 空格/Sandbox 死代码/filesystem 竞态/session TTL 等）"
    status: pending
isProject: false
---

# Bug 修复与架构加固计划（Review 后）

## P0（崩溃/数据丢失/不可用）

### 1. agent.py — 工具调用循环丢失用户消息和上下文

`_get_full_history()` 只重建 `[system_prompt, history]`，不包含用户消息、memory_context、skill_blocks。第一个 tool call 之后的所有 LLM 调用都看不到原始用户输入和记忆上下文。

`agent.py:208`:
```python
def _get_full_history(self, session_id):
    system_prompt = build_system_prompt(mode=self._ctx.mode, lang="zh")
    # ❌ 缺 user_message, memory_ctx, skill_blocks
```

修复：让 `_get_full_history` 接受与 `_build_messages` 相同的参数（`user_message`, `memory_ctx`, `skill_blocks`），或在 tool-calling loop 中不重建 messages，改为在现有 messages 上直接追加 tool 结果。

### 2. shell.py — ws.send_text() 失败被静默吞掉

`_request_user_confirm` 中 `except Exception: pass` 会吞掉 WS 发送失败。Future 永远不 resolve，agent 阻塞 3600 秒。

修复：发送失败时立即 `_pending_confirms.pop(request_id, None)` 并 return `"deny"`。

### 3. gateway/server.py — sessions.remove 破坏 session resume

`ws_chat` 的 `finally` 无条件执行 `sessions.remove(sid)`。页面刷新时先断连再重连，resume 的 session 在重新连接前已被销毁。

修复：`sessions.remove(sid)` 移到连接时（如果 resume 成功则不 create 新 session，如果不 resume 则正常 create），finally 中只清理 `_tool_ws_sinks` 和 pending confirms。

### 4. frontend/src/App.tsx — send() 不检查 ws.readyState

`send()` 直接调 `wsRef.current.send(...)` 而不检查 `readyState === WebSocket.OPEN`。断连时调用抛未处理异常。

修复：加 `if (wsRef.current.readyState !== WebSocket.OPEN) return;` 前置守卫。

---

## P1（功能缺陷/逻辑错误）

### 5. agent.py — 会话历史无限增长

`_append` 无截断逻辑，长会话超出 LLM 上下文窗口。

修复：在 `_build_messages` 中估算 token 数，超过阈值时丢弃最早的非 system 消息，或限制 `_histories` 最大长度。

### 6. agent.py — 每轮都重新加载技能

`_collect_skill_prompts` 每轮调 `list_skills()` + `load_skill()`，不必要的 IO。

修复：缓存技能列表和内容，仅在 `learn_skill`/`forget_skill` 被调用时失效缓存。

### 7. skills.py — remember 存储的 facts 无法检索

`remember` 将 facts 存入 `data["facts"]`，但 `recall_memory` 只搜 turns 不搜 facts。

修复：`_handle_recall` 在搜索时也匹配 `facts` 数组中的内容。

### 8. shell.py — _save_allowlist 失败静默丢失

`_save_allowlist` 中 `except Exception: pass`，"始终允许" 的写入失败被吞掉。

修复：至少记录 warning 日志，或返回写入状态给调用方。

### 9. validator.py — 空 fork 目录通过验证

空目录返回 `{valid: true, total: 0}`，evolve_code 会错误地触发 swap。

修复：`validate_directory` 返回 0 个文件时标记 `valid: false`。

### 10. validator.py — validate_compile 编码崩溃

`subprocess.run(encoding="utf-8")` 无 `errors="replace"`，Windows GBK 输出会导致崩溃。

修复：加 `errors="replace"`。

### 11. memory/provider.py — prefetch 截断无指示

`assistant[:500]` 截断无 `...` 后缀，LLM 收到不完整序列。

修复：截断时追加 `...[truncated]`。

### 12. prompt.py — _read_soul 用相对路径

`Path("SOUL.md")` 依赖 CWD，与 `_read_gene` 的 `_find_repo_root()` 不一致。

修复：改为 `_find_repo_root() / "workspace" / "SOUL.md"` 或同样用 CWD（统一策略）。

### 13. frontend/App.tsx — 重连无最大次数

指数退避无限重试，服务器永久宕机时浏览器一直重连。

修复：最大重试 10 次后停止，显示 "连接失败"。

---

## P2（架构/健壮性）

### 14. run.py — CLI 参数空格不兼容

`--workspace /path/with spaces` 被拼成单个 argv，解析时按第一个空格拆分，路径含空格时错误。

修复：改用 `subprocess.run` 的 list 形式传参，每个 key 和 value 作为独立 argv 元素。

### 15. main.py — Gateway 初始化失败导致进程永久挂起

`_start_gateway` 失败后直接 return，`_shutdown_event` 永不被 set，`app.run()` 永久阻塞。

修复：失败时 `self._shutdown_event.set()` 使进程退出，或设置超时。

### 16. sandbox.py — Sandbox.run 路径参数死代码

`insert(0, ...)` 后紧跟 `raise`——路径替换功能未完成。

修复：实现路径替换逻辑或删除死代码，添加注释说明暂不支持。

### 17. filesystem.py — _handle_exists 缺 SandboxError 捕获

其他所有 handler 都有 `try/except SandboxError`，`_handle_exists` 没有。

修复：加 try/except。

### 18. filesystem.py — _handle_edit 有 TOCTOU 竞态

读和写之间文件可能被修改。

修复：读后对 old_string 做二次校验（写前再读一次确认匹配），或用文件锁。

### 19. memory/provider.py — sys.path 重复累积

`sys.path.insert(0, ...)` 在模块导入时执行，重复导入会累积污染。

修复：加 `if str(_THIRD) not in sys.path:` 守卫（easysave 子路径同样需要）。

### 20. gateway/chat.py — 会话无过期机制

`SessionManager._sessions` 无限增长，无 TTL。

修复：加时间戳，定期清理超时会话。

---

## 实施顺序

```
P0 (1→2→3→4) → P1 (5→6→7→8→9→10→11→12→13) → P2 (14→15→16→17→18→19→20)
```