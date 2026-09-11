# Chat Style 设计与排障详解

## 目录

1. [层级模型](#1-层级模型)
2. [状态模型](#2-状态模型)
3. [背景与模糊](#3-背景与模糊)
4. [几何稳定](#4-几何稳定)
5. [文字可读性](#5-文字可读性)
6. [工具消息](#6-工具消息)
7. [响应式样式](#7-响应式样式)
8. [排障流程](#8-排障流程)

## 1. 层级模型

### 普通助手消息

```text
message
├─ avatar-wrapper
└─ bubble
   ├─ content
   │  ├─ reasoning (details)
   │  ├─ markdown / blocks
   │  └─ attachments
   └─ toolbar
```

### 工具消息

```text
message
└─ bubble
   ├─ tool-call
   │  ├─ summary button
   │  └─ tool-detail
   └─ toolbar
```

给 `bubble` 设置背景可覆盖正文、reasoning 和 toolbar 的共同区域。给 `reasoning` 自身设置背景只覆盖 details；给 toolbar 设置背景会形成独立横条。

## 2. 状态模型

至少考虑三种状态：

- 直接 Hover：`[data-message-role="assistant"]:hover`
- 同角色联动：`[data-character-hovered="true"]`
- 键盘或内部控件聚焦：`:focus-within`

同角色联动不是 CSS 推断，而是组件在鼠标进入某角色消息后为同名角色消息写入属性。希望视觉一致时，三类状态应共用一组声明。

不要只覆盖 `:hover`；否则移动到某条角色消息时，其他同角色消息仍可能使用宿主默认状态。

## 3. 背景与模糊

### backdrop-filter 的真实行为

`backdrop-filter` 处理的是元素背后的像素，而不是元素自身。即使：

```css
background: transparent;
```

只要元素覆盖面积很大，仍会看到整片模糊。若 `bubble`、`reasoning`、`toolbar` 同时模糊，会出现叠层、暗块和性能浪费。

### 推荐分工

- `bubble`：背景色、backdrop-filter、圆角、外阴影
- `content`：文字颜色和文字阴影
- `reasoning`：布局与透明背景
- `toolbar`：显隐和操作按钮；通常透明
- `tool-detail`：必要时使用结构线，不再重复玻璃背景

### 参数起点

| 状态 | 背景 alpha | blur | saturate |
|---|---:|---:|---:|
| 非 Hover | 0.16–0.24 | 3–5px | 105–115% |
| Hover / focus | 0.28–0.38 | 8–12px | 120–140% |
| 用户气泡 | 可比助手高 0.05–0.10 | 同上 | 同上 |

这些是起点，不是硬规范。背景越复杂，越需要截图迭代。

## 4. 几何稳定

视觉状态变化应尽量只改变背景和模糊。以下属性在基态和状态态保持一致：

```text
border-width
border-color（若不希望闪动）
border-radius
box-shadow
padding
margin
max-width
```

如果基态 `border: 0`，Hover 变成 `border: 1px`，元素尺寸和轮廓都会跳。更稳妥的是基态就保留一条极淡边框。

不要把 `background` 写成 gradient，再只对 `background-color` 做 transition；渐变通常不能按预期平滑插值。需要顺滑两态时使用纯 rgba 背景。

## 5. 文字可读性

调节顺序：

1. 文字颜色达到足够对比
2. 气泡增加少量底色
3. 气泡增加轻度模糊
4. 添加小范围黑色文字阴影
5. 仍不足时再增加 Hover 状态强度

推荐正文：

```css
[data-chat-scope="content"] {
  color: #f2f3f8;
  text-shadow:
    0 1px 2px rgba(0, 0, 0, 0.90),
    0 0 3px rgba(0, 0, 0, 0.58);
}
```

标题和 strong 可稍强，meta 可提高颜色 alpha。代码块当前没有稳定的 `data-chat-scope` 属性。如需调整代码块，先读取实际 DOM，再使用当前版本的 `.code-block-wrapper` 等内部类名；该类名不保证跨版本兼容。

阴影过大时字形会发糊；不要用 8px 以上的泛光代替背景适配。

## 6. 工具消息

工具消息与普通助手消息使用不同渲染分支。常见问题：

- 只写 `[data-message-role="assistant"]`，工具调用仍沿用默认样式
- tool bubble、tool-call 和 tool-detail 同时加背景，形成三层矩形
- tool-detail 已有左边框，自定义全边框后结构过重

推荐：

```css
[data-message-role="tool"] [data-chat-scope="bubble"] {
  /* 与助手 bubble 共享或单独调节 */
}

[data-chat-scope="tool-call"],
[data-chat-scope="tool-detail"] {
  background: transparent;
  box-shadow: none;
  backdrop-filter: none;
}
```

若需要分隔，保留 tool-detail 的左侧边框，不要再增加完整面板。

## 7. 响应式样式

移动端降低 blur 可以节省渲染开销：

```css
@media (max-width: 760px) {
  [data-message-role="assistant"] [data-chat-scope="bubble"] {
    backdrop-filter: blur(3px) saturate(108%);
    -webkit-backdrop-filter: blur(3px) saturate(108%);
  }
}
```

媒体查询内部仍会被宿主添加 `.chat-area` 作用域。保持选择器简单，避免不必要的特异性竞争。

## 8. 排障流程

### 整份 CSS 不生效

1. 检查顶部菜单是否暂停
2. 检查路径和 session ID
3. 搜索 `@import`、全局选择器、非法 at-rule
4. 检查花括号和注释是否闭合
5. 确认文件小于 256 KiB
6. 查看状态是否“加载失败”

### 仍是深色大块

1. 从内到外搜索所有 `background`
2. 搜索所有 `backdrop-filter`
3. 检查父级 bubble
4. 检查 reasoning / toolbar / tool-detail 是否重复绘制面板
5. 检查后置重复规则
6. 暂时将相关背景、阴影和模糊全部设为 none，逐层恢复

### 文字看不清

1. 增加正文文字阴影
2. 非 Hover bubble 加 0.16–0.24 底色
3. 加 3–5px blur
4. Hover 增强到约 0.3 和 8–12px blur
5. 保持内部 reasoning / toolbar 透明

### Hover 出现边框变化

1. 对照基态与 `:hover`
2. 检查 `[data-character-hovered="true"]`
3. 检查 `:focus-within`
4. 固定边框宽度、颜色、圆角、阴影
5. 检查宿主默认选择器是否因自定义特异性不足而生效

### 修改没有更新

1. 等待 300ms 以上
2. 检查 watcher 状态
3. 确认文件事件发生在当前 session 路径
4. 刷新页面
5. 检查用户是否暂停了 Chat Style

## 调参记录建议

每轮只记录一组差异：

```text
非 Hover alpha: 0.20 → 0.18
非 Hover blur: 4px → 5px
Hover alpha: 0.34（不变）
Hover blur: 10px（不变）
文字阴影: 0.72 → 双层 0.90 / 0.58
视觉反馈: 背景保留更多，正文仍可读
```

这种记录能避免多轮修改后无法判断是哪项设置造成问题。