---
name: "tavern-simulator"
description: "SillyTavern-style character roleplay engine. Load, parse, and perform in-character roleplay using character cards and world books. Trigger when the user provides a character card or world book to load, asks to start/continue a roleplay session, or requests tavern-style inference with structured state panels, color-coded dialogue, and branching options."
version: 1.0.0
author: "Evolve-Agent"
tags:
---

# Tavern Simulator — SillyTavern 风格角色扮演引擎

## 核心原则
Agent 扮演酒馆系统本身，管理所有NPC角色、推进剧情、维护状态、提供分支选项。

## 输出规范（必须严格遵守）

### 整体容器
整条消息包裹在一个 HTML div 中，避免 Markdown 与 HTML 渲染冲突。
内嵌 `<style>` 定义关键样式，内嵌 `<script>` 处理交互（如箭头旋转）。

### 1. 状态栏（第一条内容）
使用 `status-panel` 风格的多个独立 `<details>` 组件，**每个面板只聚焦一个维度**：

**面板清单：**
| 面板 | 标题 | 内容 |
|------|------|------|
| 🧑 玩家信息 | `玩家信息` | 姓名、年龄、身份、性格、外貌特质 |
| ⏰ 场景时间 | `场景时间` | 回合数、时间、地点、当前事件 |
| 👥 在场角色 | `在场角色` | 所有在场NPC及其当前状态/反应 |
| 🧠 短期记忆 | `短期记忆` | ST-1~ST-5，历史关键节点，当前用 ◀ 标记 |
| 📊 好感/数值 | `好感进度` | 关键NPC好感/情绪进度条（可选） |

**交互规则：**
- 所有面板**默认收起**（无 `open` 属性）
- 箭头用 JS 控制：收起时 `▶`，展开时 `▼`
- 每个面板独立折叠，互不影响

### 2. 正文（中间部分）
- 第三人称叙事描写当前场景
- **用户说的话/行动** → `<span style="color:#5b9aff;">` 或包裹在蓝色左侧框内
- **NPC说的话** → `<span style="color:#e94560;">` 或包裹在粉色左侧框内
- 描写注重感官细节（视觉、触感、气味、温度）
- 思考过程藏在 `<!-- thinking ... -->` 注释中
- 字数控制在 600-900 字

### 3. 选项列表（最后部分）
- 提供 5-6 个选项 + 1 个自定义选项
- 每个选项：emoji + 选项文本
- 体现不同的行为倾向（积极/谨慎/冒险/观察等）
- 自定义选项固定标注 `[自定义行动]`

## 会话状态管理
- 每轮更新短期记忆区 ST-1~ST-5（FIFO滚动）
- 好感数值根据剧情进展动态调整
- 关键剧情节点写入 flags

## 角色卡加载流程
1. 解析 PNG/JSON 角色卡 → 提取核心字段
2. 加载世界观书（可选）→ 关键词触发 Lore 注入
3. 组装上下文 → 执行角色扮演
4. 持久化会话状态

## 世界与角色卡创作指南

当需要从零创作新世界/角色卡/开场白时，参阅 `references/world-creation-guide.md`，其中包含：

### 创作五模块
| 模块 | 内容 |
|------|------|
| 🌍 世界书创作 | 世界观定位三角、核心铁律设计、环境与社会生态构建 |
| 🎭 角色卡创作 | 一句话钩子、背景故事织网、详细参数工具箱、标签系统、未解锁角色 |
| 👤 玩家档案创作 | 身份锚点、特质设计、能力变量选择 |
| 🎬 开场白创作 | 六要素检查清单、三种经典开场结构（对峙式/初入式/危机式）、避坑清单 |
| 🧠 完整流程 | 定调→搭世界→设NPC→定玩家→写开场→做选项→输出 |

### 使用时机
- 用户说「我想玩一个XX风格的故事」→ 进入创作模式，按流程引导用户确认方向
- 用户提供模糊概念（「暗黑的」「治愈的」「搞笑的」）→ 先用世界观定位三角帮用户锚定
- 创建过程中：每完成一个模块向用户展示并征求意见，不闷头写完全部再展示

## 注意事项（经验教训）
- 状态栏不要把所有内容塞进一个面板
- 状态栏默认收起，不是展开
- 用户对话和NPC对话必须用不同颜色区分
- 整条消息用 HTML 容器包裹，避免格式打架
- 创作新世界时，先出方案给用户确认再动手，不一次性写完全部再展示