---
name: design-to-webgame
description: 将游戏设计文档（GDD）开发成可玩网页游戏的完整方法论与流程：环境预检、设计文档拆解、视觉定向、数据驱动的游戏架构、数值审校、浏览器全流程回归、交付与迭代。当用户给出游戏策划案/设计文档（txt/md 等）并要求"根据设计开发网页游戏/HTML 游戏"、或将已有玩法规则实现为浏览器游戏时使用。典型触发语："这是一份游戏设计，帮我开发成网页游戏"、"按照这个策划案做个 HTML 小游戏"、"把这套玩法规则做成能玩的网页版"。
---

# 从设计文档到可玩网页游戏

## 核心流程（按顺序执行）

0. **环境预检**：在动手写任何代码之前，先检查环境，确定技术栈路线。详见下方「环境预检清单」。
1. **拆解文档**：通读设计文档，产出系统清单（核心循环、数值表、触发条件、UI 布局）。原则：文档每张数值表对应一个常量表，每个"当 X 触发 Y"对应一条触发逻辑。
2. **视觉定向**：用浏览器搜索设计参考（如搜索"pixel game UI"、"retro game interface"、"经营游戏界面"等关键词）确定配色/字体/面板质感。可配合 `aesthetic-style-library` skill 获取风格模板。再生成关键美术（标题横幅、角色头像）。**生成后如需读图目检，先 `probe_modality_capability` 确认视觉能力；无视觉（`vision_capable=false`）时不自行 Read 读图，直接把图片展示给用户判断。** 中文游戏必须配置中文字体回退栈，像素字体只管拉丁与数字。
3. **搭建架构**：根据环境预检结果选择技术栈，按 types → data → engine → scenes → state → sections 的顺序写代码。详见 [references/architecture.md](references/architecture.md)。
4. **数值审校**：构建前做量级自洽性检查（用文档自己的经济节奏反推核心数值交叉验证）。发现矛盾时引入单一缩放系数、保留其余数值原样，并主动告知用户。详见 [references/methodology.md](references/methodology.md) 阶段四。
5. **全流程回归**：构建通过后用浏览器按真实玩家路径逐步验证（标题→开场剧情→主玩法一轮→每个标签页→一笔完整交易→存档读档），DOM 文本与截图双重核对（**截图核对依赖视觉：先 `probe_modality_capability`；无视觉时跳过自主看截图，把截图展示给用户核对**）。完整检查清单见 [references/methodology.md](references/methodology.md) 阶段五。
6. **交付**：手动版本管理——在 `ws:output/` 下按版本号组织目录，或用 `Compress` 打包压缩备份。单机存档用 localStorage，必须明确告知用户存档边界。交付说明中列出偏离设计的改动及理由。

## 环境预检清单（必须在阶段零完成）

在开始任何开发工作之前，用 `run_command` 执行以下检查，根据结果决定技术路线：

```bash
# 1. 检查 Node.js 版本
node --version

# 2. 检查 pnpm（首选）
pnpm --version

# 3. 如果 pnpm 不可用，检查 npm（回退）
npm --version
```

### 决策树

| 检查结果 | 技术路线 | 说明 |
|:---------|:---------|:-----|
| Node.js ✓ + pnpm ✓ | **React + TypeScript + Vite + pnpm** | 完整分层架构 |
| Node.js ✓ + pnpm ✗ + npm ✓ | **React + TypeScript + Vite + npm** | 完整分层架构 |
| Node.js ✗ | **纯 HTML + JavaScript + CSS** | 零依赖，双击即可运行 |

**重要**：一旦确定技术路线，在整个项目中保持一致，不要中途切换。如果预检发现环境不符合预期，应提前告知用户，而不是写完代码才发现编译不了。

### 检查 ComfyUI（可选，美术资源用）

```bash
# 检查 ComfyUI 是否运行
curl -s http://localhost:8188/system_stats || echo "ComfyUI not available"
```

如果 ComfyUI 不可用，美术资源使用 SVG 代码生成方案。

## 美术资源生成策略

1. **检测本机 ComfyUI**——检查是否有可用的 ComfyUI 接口（如 `http://localhost:8188`）
2. **ComfyUI 自建工作流**——如有可用接口，根据游戏需求自建生图工作流（注意：当前 comfyui-image-gen-workflow skill 不是通用 skill，需要按需构建专用工作流）
3. **SVG 代码生成**——如无 ComfyUI 可用，用 SVG 代码绘制游戏美术（像素风、矢量风均可）
4. **占位图**——极端情况下用纯色 + 文字占位，优先保证游戏可玩性

## 三条不可妥协的架构纪律

- **数值全部入 data 表**，组件里不出现魔法数字；
- **对话场景数据化**（Scene 结构 + 统一播放器 + 队列），日常闲聊也要有场景演出而非只写日志；
- **剧情触发收口**到统一的 checkTriggers，在每个改变营收/好感的 action 末尾调用。

## 样例

`assets/sample-blacksmith-game/` 是一个完整可运行的样例（锻造经营+恋爱养成+多结局游戏《铁匠恋歌：真心之锤》），包含：

- `设计文档原文.txt` —— 输入的原始 GDD
- `src/game/`（types/data/engine/scenes/state）+ `src/sections/` + `src/components/` —— 分层架构的完整实现
- `BUILD_NOTES.md` —— 该样例的构建思路、设计文档→代码映射表、数值矛盾处理、测试过程与迭代修复记录
- `public/assets/` —— AI 生成的像素风美术

开发同类游戏时，先读 `BUILD_NOTES.md` 建立整体认识，再按需对照样例源码；数值表结构参考 `src/game/data.ts`，状态与触发收口参考 `src/game/state.tsx`，对话系统参考 `src/game/scenes.ts` + `src/components/SceneModal.tsx`。

## 详细参考

- [references/methodology.md](references/methodology.md) —— 六阶段方法论全文 + 常见陷阱清单
- [references/architecture.md](references/architecture.md) —— 分层架构模式详解（GameState 设计、场景系统、触发检查器、reducer 模式、存档、界面约定）
