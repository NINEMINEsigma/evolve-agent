# Evolve Agent 会话视觉运行时契约

本文记录与 Session Stage、Session Site 和 Session Chat Style 相关的源码事实。源码变化后应重新核对，而不是永久依赖本文。

文中 `frontend/src/...` 均为 Evolve Agent 运行时前端源码路径，不在本技能包内。它们通常位于只读的 `fork:` 命名空间（例如 `fork:frontend/src/utils.ts`）。若当前环境无法读取这些文件，本文仍然可作为公开 `data-*` 契约和宿主行为的参考，但涉及具体默认值的结论应视为“可能过期”，并以实际渲染结果为准。

## 1. URL 映射

前端构建的访问地址：

```text
Session Site:  /files/ws/sessions/<encoded-session-id>/site/index.html
Session Stage: /files/ws/sessions/<encoded-session-id>/stage/index.html
Chat Style:    /files/ws/sessions/<encoded-session-id>/chat-style/index.css
```

Site 另有目录 ZIP 地址；Stage 第一版没有 ZIP URL。

## 2. Stage 宿主

相关源码：

```text
frontend/src/utils.ts
frontend/src/hooks/useSessionStage.ts
frontend/src/components/AgentStageLayer.tsx
frontend/src/styles/agent-stage.css
```

宿主行为：

- `useSessionStage` 用 `fetch(..., { cache: "no-store" })` 探测 `stage/index.html`
- 文件存在时状态为 `ready`
- Stage 以 iframe 渲染
- iframe 沙箱为 `allow-scripts allow-same-origin`
- iframe 和容器均 `pointer-events: none`
- 容器绝对定位并覆盖聊天可视区域
- z-index 位于聊天内容下方、基础背景上方
- 监听 `sessions/<session-id>/stage/` 下的 Agentspace 事件
- 文件变化经 300ms 防抖后增加 `reloadKey`，iframe 重新创建
- 删除 `index.html` 或整个 Stage 目录后立即转为 missing
- watcher_error 不改变当前显示，只会使自动刷新失效

推论：

- Stage 页面不能依赖鼠标交互
- 修改任意 Stage 资源可能令动画从头开始
- 同源权限允许加载 `assets/` 和 fetch 本地文件
- 不应依赖表单提交、弹窗或顶层导航

## 3. Chat Style 宿主

相关源码：

```text
frontend/src/constants/chatStyle.ts
frontend/src/hooks/useSessionChatStyle.ts
frontend/src/components/ChatStyleLayer.tsx
frontend/src/styles/chat-style-scope.css
```

加载链：

```text
fetch index.css (no-store)
  → 检查 256 KiB 上限
  → PostCSS 解析
  → 验证 at-rule 与字体名
  → 给普通选择器加 .chat-area 前缀
  → 生成 cssText
  → 动态创建 <style data-chat-style-scope>
  → 注入 document.head
```

非 ready 状态会移除 `<style>`。CSS 语法错误、不支持的 at-rule 或加载失败都会让整份会话样式不生效。

Agentspace 热加载：

- 监听 `sessions/<session-id>/chat-style/`
- 300ms 防抖
- created / modified / moved / deleted 会重新探测
- 删除 `index.css` 或目录后清空样式
- watcher_error 不改变当前状态，但停止可靠热加载

## 4. CSS 作用域规则

普通选择器自动变为：

```css
/* 输入 */
[data-chat-scope="bubble"] { ... }

/* 注入后 */
.chat-area [data-chat-scope="bubble"] { ... }
```

已经以 `.chat-area` 开头的选择器不会重复添加前缀。`@media`、`@supports`、`@container` 的内部规则也会作用域化。

保留：

- `@keyframes`
- `@-webkit-keyframes`
- 合法 `@font-face`

拒绝：

- `@import`
- 未以 `ChatStyle-` 开头的 `@font-face font-family`
- 未知或不可安全处理的 at-rule

注意：ChatStyleLayer 将处理后的样式注入 `document.head`，不是 ChatArea DOM 内；真正的隔离来自 `.chat-area` 前缀。

## 5. 字体行为

- `@font-face` 中带有 `font-family` 声明时，宿主要求其名称以 `ChatStyle-` 开头。
- 会话目录下的相对字体可通过 `/files/ws/...` 访问。
- 本地绝对路径字体应使用 `/local-font/{absolute-path}` 路由；浏览器直接读取 `file://` 不保证成功。
- HTTP/HTTPS 字体由浏览器直接加载，跨域或网络失败时依靠 CSS `font-family` 后备字体。
- 当前实现没有可靠的 5 秒字体超时检测，也不会因为字体加载失败把 Chat Style 状态标记为错误；因此不要把“5 秒超时状态提示”当作现有能力。
- `data:` URI 当前不支持。

## 6. 暂停状态

Stage 和 Chat Style 有独立暂停开关，按 session ID 持久化。顶部命令菜单显示：

- Agent 舞台层：已启用 / 已暂停 / 未配置
- 聊天区样式：已启用 / 已暂停 / 加载失败 / 未配置

写入新文件不会自动取消暂停。排障时先检查菜单状态。

## 7. 消息 DOM 契约

`MessageItem` 当前实际提供：

```text
data-chat-scope="message"
data-message-role="user" / "assistant" / "tool" / "system"
data-character-hovered="true"（同角色联动时）
data-chat-scope="bubble"
data-chat-scope="content"
data-chat-scope="tool-call"
data-chat-scope="tool-detail"
data-chat-scope="toolbar"
data-chat-scope="waiting"（等待状态消息）
```

`MessageBody` 在有思考内容的消息内提供：

```text
details[data-chat-scope="reasoning"]
```

当前没有稳定的 `data-chat-scope="code"`、`"attachments"` 或 `"meta"` 属性。代码块、附件和消息元数据只能通过实际 DOM 中的内部类名调整，不能视为跨版本契约。

真实结构：

```text
普通消息：message > bubble > (content > reasoning) + toolbar
工具消息：message > bubble > tool-call > tool-detail，以及 bubble > toolbar
```

## 8. 默认样式基线

当前源码中的关键默认值：

- Assistant bubble：透明、无边框、padding `12px 16px`
- User bubble：透明、`1px solid var(--border)`、圆角 `16px`
- Message bubble 基态：`backdrop-filter: blur(0px)`，可过渡
- Assistant/tool/system Hover：`rgba(19,19,25,0.35)`，圆角 `var(--radius-sm)`
- User Hover：`rgba(31,31,41,0.35)`
- Hover / 同角色联动：`blur(10px) saturate(150%)`
- Toolbar 基态 opacity 0，message Hover 或 focus-within 时 opacity 1
- Reasoning 默认透明，只定义布局和文字颜色
- Tool-call 默认透明；tool-detail 主要使用左侧结构线

自定义时不要假设默认样式永远不变；需要精确适配时重新读取 `frontend/src/styles/messages.css`。