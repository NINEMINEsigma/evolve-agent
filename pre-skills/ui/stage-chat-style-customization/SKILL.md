---
name: "stage-chat-style-customization"
description: 为 Evolve Agent 会话定制 Session Stage 与 Chat Style：部署透明 Live2D/氛围背景，编写作用域安全的聊天气泡 CSS，并排查背景模糊、文字可读性、reasoning、toolbar、Hover/同角色聚焦状态和热加载问题。用户提到 stage、site、聊天背景、Live2D、气泡样式、会话级 CSS 或聊天视觉适配时应使用本技能。
version: 1.0.0
author: "Evolve-Agent"
category: ui
tags:
  - stage
  - site
  - "chat-style"
  - live2d
  - css
  - ui
  - "session-customization"
---

# Session Stage 与 Chat Style 自定义开发手册

本技能指导 Evolve Agent 会话级视觉定制。先选择正确扩展点，再读取现有文件和前端契约，最后以小步修改、静态校验和视觉反馈闭环完成交付。

## 快速决策

| 用户目标 | 扩展点 | 入口文件 |
|---|---|---|
| 聊天气泡下方的动画、Live2D、粒子、场景 | Session Stage | `ws:sessions/<session_id>/stage/index.html` |
| 右侧抽屉中的完整交互网页 | Session Site | `ws:sessions/<session_id>/site/index.html` |
| 气泡、正文、reasoning、工具块、toolbar、字体 | Session Chat Style | `ws:sessions/<session_id>/chat-style/index.css` |

Stage 和 Site 不可混称。Stage 显示在聊天背景，Site 显示在右侧资源抽屉。需要点击、输入或拖拽的内容使用 Site；Stage 默认鼠标穿透。

## 依赖边界

本技能包自带流程、参考文档、模板和校验脚本；技能目录本身不携带第三方包。Chat Style 的宿主前端需要提供运行时 `postcss` 依赖，不能把该功能视为完全无第三方依赖。

| 自带内容 | 说明 |
|---|---|
| `SKILL.md` | 流程与规范 |
| `references/runtime-contract.md` | 运行时契约（基于源码的实测结论） |
| `references/chat-style-guide.md` | 样式设计与排障 |
| `templates/readable-glass.css` | 气泡样式模板，纯 CSS，无外部资源 |
| `templates/minimal-stage.html` | 无依赖 Stage 模板，纯内联 CSS/JS |
| `scripts/validate_session_visuals.py` | 仅用 Python 标准库 |

以下内容**不在**本技能包内，属于外部引用。使用时先确认可用，不可用则按说明降级：

| 外部引用 | 性质 | 缺失时的处理 |
|---|---|---|
| `fork:frontend/src/...` | 运行时代码空间中的前端源码 | 不猜选择器；改用实际 DOM 或只用公开 `data-*` 契约 |
| `/skill:live2d-ambient-stage` | 独立技能，提供 Live2D 运行时/模型/脚本 | 改用 `templates/minimal-stage.html` 做非 Live2D 氛围层 |
| `ws:sessions/<session_id>/...` | 宿主会话目录约定 | 从系统提示取得真实 session ID，不要复用旧 ID |

本技能的校验脚本、模板、参考文档均可独立使用，不读取上述外部内容的运行结果。只有流程第 2 步的"读源码确认"和 Live2D 部署需要外部资源，且都写了降级路径。

## 工作流

### 1. 确认会话和目标

从当前系统提示取得 `<session_id>`，不要复用旧会话 ID。明确用户要修改：

- Stage 内容
- Chat Style
- 两者协同
- 或实际需要的是 Site

读取目标目录，确认是否已有 `index.html` / `index.css`。已有内容时先理解，不要直接覆盖。目录替换优先备份到 `ws:tmp/` 或 `ws:.trash/`。

### 2. 读取源码或现状，不凭记忆写选择器

下文的 `frontend/src/...` 指 Evolve Agent 自身的运行时前端源码，不在本技能包内，需要从运行时代码空间读取（通常为只读的 `fork:` 命名空间，例如 `fork:frontend/src/...`）。先确认该路径在当前环境可读。

- 能读到源码：以源码为准，不要凭记忆写选择器。
- 读不到源码：不要猜测类名和层级，改为观察实际渲染 DOM，或只使用本技能列出的公开 `data-*` 契约。

Chat Style 至少读取：

- 现有 `chat-style/index.css`
- `frontend/src/constants/chatStyle.ts`
- `frontend/src/components/MessageItem.tsx`
- `frontend/src/components/MessageBody.tsx`
- `frontend/src/styles/messages.css`
- `frontend/src/hooks/useSessionChatStyle.ts`

Stage 至少读取：

- 现有 `stage/index.html`
- `frontend/src/hooks/useSessionStage.ts`
- `frontend/src/components/AgentStageLayer.tsx`
- `frontend/src/styles/agent-stage.css`

运行时契约见 `references/runtime-contract.md`；样式层级和排障见 `references/chat-style-guide.md`。

### 3. 先做最小版本

- Stage：先保证透明、资源本地化、无鼠标依赖，再加动画和背景。
- Chat Style：一次只调一类变量，例如背景透明度、模糊、文字阴影或状态差异。
- 不要同时在 `bubble`、`reasoning`、`toolbar`、`tool-detail` 上叠加背景模糊。

### 4. 每次修改后重新读取最终文件

检查：

- 是否残留旧规则
- 后置规则是否覆盖新规则
- Hover 与非 Hover 的几何属性是否一致
- 资源相对路径是否存在
- CSS 是否包含被禁止的规则

小改动使用 `PatchEdit`。区间替换时结束标记必须唯一；若用单个 `}` 作结束标记，容易只替换第一段并留下旧规则。修改后必须重新 `Read`。

### 5. 校验

本技能提供静态校验脚本：

```text
python <skill_dir>/scripts/validate_session_visuals.py \
  --stage-dir ws:sessions/<session_id>/stage \
  --chat-style ws:sessions/<session_id>/chat-style/index.css
```

`RunCommand` 会解析命令参数中的逻辑路径。`--stage-dir` 既接受 Stage 目录（会自动查找 `index.html`），也接受单个 Stage HTML 文件；`--chat-style` 接受 CSS 文件。脚本只使用 Python 标准库，无外部依赖。

两个参数都可单独使用，例如只校验 CSS：`--chat-style ws:sessions/<session_id>/chat-style/index.css`。

静态校验通过不等于视觉效果已验证。只有真正打开页面或收到用户截图后，才能确认观感。

## Stage 开发

### 目录约定

```text
stage/
├── index.html
└── assets/
    ├── libs/
    ├── models/
    ├── backgrounds/
    └── licenses/
```

大资源放入 `assets/`，HTML 仅使用相对路径。可从 `templates/minimal-stage.html` 开始。

### 透明与交互约束

必须保持：

```html
<html style="background: transparent;">
<body style="background: transparent;">
```

Canvas/WebGL 也必须透明。不要依赖点击、Hover、拖动或鼠标位置。宿主 iframe 使用：

```text
sandbox="allow-scripts allow-same-origin"
pointer-events: none
```

因此表单、弹窗和交互式控件不属于 Stage 的正确用途。

### Live2D

Live2D 属于可选增强。本技能包**不包含** Live2D 运行时、模型素材和部署脚本；这些由另一个独立技能提供：

```text
/skill:live2d-ambient-stage
```

若该技能可用，使用它的部署脚本，不要重新手写整套运行时：

```text
python <live2d_skill_dir>/scripts/install_live2d_stage.py \
  --model mao_pro \
  --stage-dir <absolute-stage-dir>
```

`<live2d_skill_dir>` 以 `RecallSkill` 返回的 `skill_dir` 为准。可先执行 `--list-models`、`--list-backgrounds`、`--dry-run`。目标已有 `index.html` 时脚本默认拒绝覆盖；不要未经确认使用 `--force`。

若该技能不可用：

- 不要伪造模型路径或凭空声称已部署 Live2D。
- 纯氛围背景不依赖 Live2D，可直接使用本技能的 `templates/minimal-stage.html` 完成 Stage。
- 若用户坚持要 Live2D，说明需要该技能或其素材，然后再决定从何处获取。

手动部署仅作为脚本不可用时的后备方案。必须复制渲染库、完整模型目录、许可证并按模板生成配置。保留 Live2D 版权提示，不公开再分发模型素材。

### 背景图

背景图放在 `assets/backgrounds/`，排在角色 Canvas 之前：

```html
<img id="stage-bg" alt="" />
<canvas id="stage-canvas"></canvas>
```

使用 `object-fit: cover`。背景会替换聊天区原有底图，高对比插画可能降低可读性；这通常需要配套 Chat Style，而不是用 Stage 遮罩把角色和背景一起压暗。

### 生命周期

- 页面隐藏时暂停动画或渲染
- 页面恢复时重新排期
- 卸载前清理定时器和监听器
- 限制高 DPI 分辨率，避免 GPU 浪费
- 给页面写入可诊断状态，例如 `data-stage-status="ready"`

## Chat Style 开发

### Chat Style 公开选择器

当前实现实际提供的稳定选择器只有：

```css
[data-chat-scope="message"]
[data-message-role="user"]
[data-message-role="assistant"]
[data-message-role="tool"]
[data-message-role="system"]
[data-character-hovered="true"]
[data-chat-scope="bubble"]
[data-chat-scope="content"]
[data-chat-scope="reasoning"]
[data-chat-scope="tool-call"]
[data-chat-scope="tool-detail"]
[data-chat-scope="toolbar"]
[data-chat-scope="waiting"]
```

当前 `code`、`attachments`、`meta` 没有稳定的 `data-chat-scope` 属性。代码块、附件和消息元数据如需调整，只能先读取实际 DOM，再谨慎使用当前版本的内部类名；不能把这些内部类名写成跨版本保证。

宿主会给普通 CSS 规则自动添加 `.chat-area` 前缀，通常无需自行添加。

### 实际 DOM 关系

普通助手消息：

```text
message
└─ bubble
   ├─ content
   │  ├─ reasoning
   │  └─正文 / 附件
   └─ toolbar
```

工具消息：

```text
message
└─ bubble
   ├─ tool-call
   │  └─ tool-detail（展开时）
   └─ toolbar
```

因此：

- `bubble` 是统一可读性背景的首选层
- `reasoning` 位于 `content` 内
- `toolbar` 是 `bubble` 的直接子元素
- 工具块与普通正文走不同分支

### 推荐玻璃气泡策略

从 `templates/readable-glass.css` 复制后调整。推荐原则：

- 非 Hover：轻底色 + 小模糊
- Hover、`[data-character-hovered="true"]`、`:focus-within`：增强底色和模糊
- 两种状态保持相同的边框、圆角和阴影，避免轮廓跳变
- `reasoning`、`toolbar` 自身保持透明，继承所在 `bubble` 的背景效果
- 给工具消息单独覆盖时，注意默认 `.message-tool .message-bubble` 规则

不要把 `backdrop-filter` 加到横向铺满的每个内部元素上。即使 `background: transparent`，它仍会模糊元素背后的整片区域，产生“深色大块”或多层模糊。

### 文字可读性

调节顺序：

1. 少量气泡底色
2. 气泡背景模糊
3. 文字阴影
4. 必要时提高文字颜色对比度

不要先用高不透明黑底。双层文字阴影可提升复杂背景上的字形分离度：

```css
[data-chat-scope="content"] {
  text-shadow:
    0 1px 2px rgba(0, 0, 0, 0.90),
    0 0 3px rgba(0, 0, 0, 0.58);
}
```

代码块通常已有独立深色背景，不要继承强文字阴影。

### 字体来源与回退

- 会话目录下的相对字体路径可由 `/files/ws/...` 访问。
- 本地绝对路径或 `file://` 字体需要改写为宿主提供的 `/local-font/` HTTP 路径；浏览器直接读取 `file://` 并不保证成功。
- 远程 `http://` / `https://` 字体由浏览器直接加载，跨域、网络错误或加载失败时由浏览器使用 `font-family` 后备字体。
- 当前宿主不会可靠地把远程字体加载超时转换为单独的界面状态；不要向用户承诺已经实现固定的 5 秒字体超时提示。
- `@font-face` 的 `font-family` 应以 `ChatStyle-` 开头；当前解析器会检查带有 `font-family` 声明的规则。
- 必须始终写后备字体栈，例如 `"ChatStyle-MyFont", "Segoe UI", sans-serif`。
- `data:` URI 当前不支持。

### CSS 安全限制

整份 CSS 最大 256 KiB。禁止或避免：

- `@import`：当前宿主会拒绝整份 CSS
- 未以 `ChatStyle-` 开头的自定义字体名：带有 `font-family` 声明时会触发拒绝
- `:root`、`html`、`body` 等全局选择器：当前处理器不会把它们作为稳定公开接口，避免依赖它们
- 不可安全作用域化的 at-rule：会触发整份 CSS 拒绝
- 依赖 `!important` 改写宿主范围外的元素：作用域处理不会授予越界权限，但可能造成聊天区内部覆盖过强

允许 `@media`、`@supports`、`@container`、`@keyframes` 和符合规范的 `@font-face`。解析失败时，前端会移除整份会话样式并回退默认样式。

## 热加载和暂停

Stage 与 Chat Style 都监听 Agentspace 文件事件并在约 300ms 后刷新：

- 修改 `stage/` 下任意资源可能重建 iframe，动画状态会重置
- 修改 `chat-style/` 会重新抓取、解析和注入 CSS
- watcher 异常时自动刷新可能停止
- 用户可在顶部命令菜单分别暂停 Stage 和 Chat Style
- 暂停状态按会话持久化；写文件不会自动恢复被暂停的层

样式未变化时按顺序检查：

1. 顶部菜单是否显示“已暂停”或“加载失败”
2. 路径和当前 session ID 是否正确
3. CSS 是否有语法或安全规则错误
4. 是否等待了热加载防抖
5. 是否需要刷新页面
6. 是否存在后置重复规则覆盖

## 常见故障

| 现象 | 优先检查 |
|---|---|
| Stage 空白 | `index.html`、资源 404、脚本加载顺序、透明度、页面状态 |
| Stage 能直接打开但聊天里没有 | 当前会话 ID、Stage 暂停状态、宿主探测状态 |
| 角色能显示但不动 | 动作组、Loop、调度、页面可见性、模型配置 |
| CSS 完全不生效 | Chat Style 暂停、解析失败、禁止规则、错误路径 |
| reasoning/toolbar 是黑色横块 | 父级 bubble 与内部块是否重复设背景/模糊 |
| `background: transparent` 仍像块 | `backdrop-filter` 是否仍在该元素或父级上 |
| Hover 出现边框跳变 | 基态和所有状态是否固定相同边框、圆角、阴影 |
| 文字仍看不清 | 轻底色 → 小模糊 → 阴影，逐项增加并截图评估 |
| 修改后仍是旧效果 | 查重复规则、后置覆盖、热加载状态和缓存 |

## 交付要求

交付时明确说明：

- 修改的是 Stage、Site 还是 Chat Style
- 实际文件路径
- 是否覆盖或保留已有内容
- 非 Hover 与 Hover 的差异
- reasoning、toolbar、工具块如何处理
- 是否完成静态校验和浏览器验证
- 用户可在顶部命令菜单暂停或恢复视觉层

不要把“文件已写入”描述成“视觉效果已验证”。没有浏览器检查或用户截图时，只能报告静态部署完成。