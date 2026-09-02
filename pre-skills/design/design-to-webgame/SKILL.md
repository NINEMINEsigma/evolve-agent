---
name: design-to-webgame
description: 将游戏设计文档（GDD）开发成可玩网页游戏的完整方法论与流程：环境预检、设计文档拆解、视觉定向、数据驱动的游戏架构、数值审校、浏览器全流程回归、交付与迭代。当用户给出游戏策划案/设计文档（txt/md 等）并要求"根据设计开发网页游戏/HTML 游戏"、或将已有玩法规则实现为浏览器游戏时使用。典型触发语："这是一份游戏设计，帮我开发成网页游戏"、"按照这个策划案做个 HTML 小游戏"、"把这套玩法规则做成能玩的网页版"。
---

# 从设计文档到可玩网页游戏

## 核心流程（按顺序执行）

0. **环境预检**：在动手写任何代码之前，先检查环境，确定技术栈路线。详见下方「环境预检清单」。
1. **拆解文档**：通读设计文档，产出系统清单（核心循环、数值表、触发条件、UI 布局）。原则：文档每张数值表对应一个常量表，每个"当 X 触发 Y"对应一条触发逻辑。
2. **视觉定向**：用浏览器搜索设计参考（如搜索“pixel game UI”“retro game interface”“经营游戏界面”等关键词）确定配色、字体和面板质感。可配合 `aesthetic-style-library` skill 获取风格模板。生成关键美术后，如需视觉判断，使用 `BrowserScreenshot` 获取证据并交由用户做最终判断，不要把截图当作绝对质量证明。中文游戏必须配置中文字体回退栈，像素字体只管拉丁与数字。
3. **搭建架构**：根据环境预检结果选择技术栈，按 types → data → engine → scenes → state → sections 的顺序写代码。详见 [references/architecture.md](references/architecture.md)。
4. **数值审校**：构建前做量级自洽性检查（用文档自己的经济节奏反推核心数值交叉验证）。发现矛盾时引入单一缩放系数、保留其余数值原样，并主动告知用户。详见 [references/methodology.md](references/methodology.md) 阶段四。
5. **全流程回归**：构建通过后，用当前 Browser 工具按真实玩家路径逐步验证（标题→开场剧情→主玩法一轮→每个标签页→一笔完整交易→存档读档）。DOM 文本断言用于客观状态，截图通过 `BrowserScreenshot` 获取并交由用户做最终视觉判断，不把截图当作绝对质量证明。完整检查清单见 [references/methodology.md](references/methodology.md) 阶段五。
6. **交付**：手动版本管理——在 `output/` 下按版本号组织目录，或用 `Compress` 打包压缩备份。单机存档用 localStorage，必须明确告知用户存档边界。交付说明中列出偏离设计的改动及理由。

## 环境预检清单（必须在阶段零完成）

在开始任何开发工作之前，用 `RunCommand` 执行以下检查，根据结果决定技术路线：

```bash
# 1. 检查 Node.js 版本
node --version

# 2. 检查 pnpm（首选）
pnpm --version

# 3. 如果 pnpm 不可用，检查 npm（回退）
npm --version

# 4. 检查浏览器 WebGL 支持（仅当游戏需要 3D 渲染时）
# 通过代码检测：创建 WebGL context，检查是否非 null
```

### 决策树

| 检查结果 | 技术路线 | 说明 |
|:---------|:---------|:-----|
| Node.js ✓ + pnpm ✓ | **路线A：React + TypeScript + Vite + pnpm** | 完整分层架构，首选 |
| Node.js ✓ + pnpm ✗ + npm ✓ | **路线B：React + TypeScript + Vite + npm** | 完整分层架构 |
| Node.js ✗ + WebGL ✓ | **路线C：Three.js + ES Modules（无构建）** | 3D 游戏，无构建步骤，importmap + `src/` 模块 |
| Node.js ✗ + WebGL ✗ | **路线D：纯 HTML + JavaScript + CSS** | 2D 游戏，零依赖，双击即可运行 |

**重要**：一旦确定技术路线，在整个项目中保持一致，不要中途切换。如果预检发现环境不符合预期，应提前告知用户，而不是写完代码才发现编译不了。

### 路线C：Three.js + ES Modules（无构建）

适用于 3D 策略/棋牌/环境探索类游戏。不依赖 Node.js，仅需浏览器支持 WebGL。

```
project/
├── index.html              # canvas, UI skeleton, importmap
├── package.json            # { "scripts": { "dev": "npx serve . -l 5173" } }
├── vendor/
│   ├── three.module.min.js
│   └── addons/
└── src/
    ├── main.js             # 入口：初始化、事件循环
    ├── core/               # 音频、配置、输入
    ├── scene/              # 渲染器、相机、后处理
    ├── game/               # 棋盘/场景、棋子、特效、对局逻辑
    ├── chess/              # （棋类）规则引擎、AI、Worker
    ├── world/              # 环境：天空、地面、粒子、道具
    └── ui/                 # HUD、菜单、CSS
```

架构纪律与路线A/B相同：types → data → engine → scenes → state → ui。所有逻辑通过 ES Modules 分散在 `src/` 中，`index.html` 只包含骨架和 `importmap`。

关键技术点：
- `onBeforeCompile` 材质注入 — 在标准 PBR 材质上叠加自定义效果
- 程序化建模 — `LatheGeometry`、`ExtrudeGeometry`、`mergeGeometries`
- 后处理管线 — `EffectComposer` → `Bloom` → `OutputPass` → 自定义 `ShaderPass`
- 顶点着色器粒子系统 — 降雪、爆发效果全部在 GPU 完成
- 共享 GLSL 噪声库 — `fbm`、`ridged`、`vnoise` 注入到所有材质

详见 `references/threejs-game-architecture.md`。

#### 路线C进阶：高性能实时 3D 游戏

当目标是**规模化 + 性能化**（大量程序化发光体、开放场景、需要 60fps 的对抗/空战/竞速），
不要只用基础的 `EffectComposer→Bloom`，参考本 skill 自带的完整高性能模板：

- **完整可运行范例**：`assets/cyber-jet-game/`（赛博战机 — 霓虹峡谷之雨，一场浏览器实时 3D 空战，
  自研 HDR 后处理链 + 程序化霓虹城市 + 玩家/AI 共用物理）。说明与技术点清单见
  `assets/cyber-jet-game/BUILD_NOTES.md`。
- **架构方法论**：`references/cyber-jet-game-architecture.md`（自研 HDR 合成、InstancedMesh 程序化城市、
  周期种子无缝循环、受击方权威判定、共享雾与全局 uniform、GPU 粒子 + 辉光池、状态机 + 调试钩子、
  画质预设与自动降档）。

**如何选**：
- 场景规模小、氛围简单 → 用 `threejs-game-architecture.md` 的 EffectComposer 路线。
- 场景有数百+程序化发光体、需要无缝大世界、玩家/AI 要用同一套物理 → 读
  `references/cyber-jet-game-architecture.md`，并对照 `assets/cyber-jet-game/` 源码。

#### 路线C进阶2：程序化世界渲染（滚动 / 状态驱动）

当游戏世界目标是**纯程序化、零素材、形态随进度 / 状态连续变形**（开放地形、程序化生态、
滚动式环境叙事），参考 `assets/field-world-render/`（「场」程序化落地页，说明见
`assets/field-world-render/BUILD_NOTES.md`）。它覆盖地图级程序化渲染的一套干净契约：

- **状态驱动**：页面只产 `travel`(0..1 进度)+`phase`(0..n 阶段)，场景据此推导一切
- **计算通道多态**：每帧派发 N 线程重写存储缓冲，描述每个实例「此刻是什么」，状态切换零加载
- **高度场脊柱**：一张共享高度场同时位移地形、定位生态，永不穿模
- **CPU 混色 + uniform 驱动**：整组艺术方向按权重混合，推给 GPU
- **自适应降档 + 降级页**：低端自动减实例 / DPR，不支持 GPU 显说明页

具体源码在 `assets/field-world-render/src/` 下读（`scroll.js` / `field.js` / `tsl-common.js` /
`palette.js` / `stage.js`）。若目标是**可玩对抗**而非滚动叙事，回到上一条 cyber-jet-game 路线。

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
- [references/threejs-game-architecture.md](references/threejs-game-architecture.md) —— Three.js 无构建路线：目录结构、渲染管线、材质注入、程序化建模、后处理、粒子系统
- [references/ai-engine.md](references/ai-engine.md) —— 棋类/策略游戏 AI 设计：0x88 棋盘、Negamax + Alpha-Beta + PVS + LMR、评估函数、难度控制、Web Worker 异步
- [references/tween-animation.md](references/tween-animation.md) —— 游戏动画时序系统：Tween 队列、缓动函数库、Three.js 对象动画、粒子爆发
