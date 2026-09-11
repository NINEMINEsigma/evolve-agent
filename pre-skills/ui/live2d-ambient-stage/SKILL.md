---
name: live2d-ambient-stage
description: "把 Live2D Cubism 4 模型部署为 Session Stage 的透明背景待机动画：角色自动循环待机动作并随机播放自带动作与表情，不响应鼠标、不依赖外部服务。当用户要求「把 Live2D 放到 stage/聊天背景」「让角色在聊天区随机动起来」「部署 Live2D 桌宠/看板娘到会话背景」「复制 Open-LLM-VTuber 的 live2d 到会话」时使用。内置 mao_pro 与 shizuku 两套官方样例模型模板，可移植到任意会话。"
version: 1.0.0
author: Evolve-Agent
category: ui
tags:
  - live2d
  - stage
  - session-stage
  - ambient
  - avatar
  - pixi
  - cubism
  - animation
---

# Live2D Ambient Stage

把 Live2D Cubism 4 模型部署为 Session Stage（聊天区透明背景层）的自动待机动画。模型循环播放待机动作，并以随机间隔播放该模型自带的其他动作与表情。

运行特征：

- 不响应鼠标、点击、拖动（Stage 层本身 `pointer-events: none`）
- 不依赖后端服务、不需要联网（渲染库与模型资源全部本地化）
- 不修改原始模型项目，只复制运行时资源
- 页面隐藏时暂停渲染与调度，恢复后重新排期

适用场景：聊天背景里出现一个「活着的」角色，作为氛围层、桌宠或看板娘。

## 目录结构

```
live2d-ambient-stage/
├── SKILL.md
├── assets/
│   ├── libs/                      # 共享渲染库，全部模型复用
│   │   ├── live2dcubismcore.min.js
│   │   ├── pixi.min.js
│   │   └── cubism4.min.js
│   ├── models/
│   │   ├── mao_pro/               # Live2D 官方样例模型 Mao（PRO 版）
│   │   └── shizuku/               # Live2D 官方样例模型 Shizuku（PRO 版）
│   ├── backgrounds/               # 14 张内置背景模板（来源见 ATTRIBUTION.md）
│   ├── LICENSE-Live2D.md          # Live2D 样例数据使用条款（必须随交付保留）
│   ├── LICENSE-Open-LLM-VTuber    # 背景图来源项目的 MIT 许可
│   └── ATTRIBUTION.md             # 版权与来源说明
├── templates/
│   ├── stage.template.html        # 配置驱动的通用模板
│   ├── backgrounds.json           # 内置背景清单
│   └── models/
│       ├── mao_pro.json
│       └── shizuku.json
├── scripts/
│   └── install_live2d_stage.py    # 部署脚本：复制资产 + 渲染 index.html
└── references/
    ├── model-manifest.md          # 模型动作/表情/许可清单，新增模型方法
    └── technical-notes.md         # 实现细节与排查表
```

## 前置条件

1. 目标会话需有 stage 目录 `ws:sessions/<session_id>/stage/`，会话 ID 见系统提示的 Session Stage 段。
2. 脚本只用 Python 标准库，无第三方依赖。Windows 下解释器为 `python`（不是 `python3`）。
3. 目标 stage 目录若已有 `index.html`，脚本默认拒绝覆盖，需显式 `--force`。覆盖不可逆——先确认是否会破坏用户既有舞台内容，必要时先备份或询问用户。

## 部署流程

### 1. 查看可用模型

```bash
python <skill_dir>/scripts/install_live2d_stage.py --list-models
```

`<skill_dir>` 取自 `RecallSkill` 返回的 `skill_dir` 绝对路径，不要假设目录名固定。

### 2. 部署

```bash
python <skill_dir>/scripts/install_live2d_stage.py --model mao_pro --stage-dir "D:/.../agentspace/sessions/<session_id>/stage"
```

脚本会：

- 复制 `assets/libs/` 三个渲染库到 `<stage>/assets/libs/`
- 复制 `assets/models/<model>/` 到 `<stage>/assets/models/<model>/`
- 复制 `assets/LICENSE-Live2D.md` 到 `<stage>/assets/`
- 由模板 + 模型配置渲染出 `<stage>/index.html`

`--dry-run` 只打印计划不写文件；`--force` 覆盖已存在文件；`--model` 可接受 `assets/models/` 下任意目录名。

### 2b. 可选背景层

`--background` 接受**内置模板 id**（如 `room-interior`）或**图片绝对路径**。脚本会把图片复制到 `<stage>/assets/backgrounds/` 并写入 `CONFIG.background`，角色叠在背景之上。不加则保持全透明。

内置背景模板共 14 张，来源于 Open-LLM-VTuber 项目，清单在 `templates/backgrounds.json`：

```bash
python <skill_dir>/scripts/install_live2d_stage.py --list-backgrounds
```

也可以用中文别名（如 `房间室内`）或原始文件名指定。

Stage 层位于**聊天气泡之下**，不透明背景会替换聊天区原有背景（气泡本身仍可见），但花哨的图会降低整体可读性。默认保持透明，仅在用户明确要求时加背景，并在交付时说明如何换图或去掉。

### 3. 验证

静态检查（无需浏览器）：

- `<stage>/index.html` 存在且包含 `const CONFIG =`
- `<stage>/assets/libs/` 三个文件齐全
- 模型目录含 `.moc3`、`.model3.json`、贴图目录、动作目录

需要浏览器验证时（用户明确要求时）打开 `/files/ws/sessions/<session_id>/stage/index.html`，检查 `document.documentElement.dataset.stageStatus === 'ready'`。默认不要主动做浏览器验证——用户通常希望直接查看效果。

## 模型配置

配置存放在 `templates/models/<model>.json`，脚本将其注入模板：

| 字段 | 含义 |
|:-----|:-----|
| `label` | 出错提示中显示的名字 |
| `modelUrl` | 相对 stage 根目录的模型入口路径 |
| `actions` | 随机动作池。`group` 为 `model3.json` 中 Motions 的组名（空字符串代表默认组），`index` 为组内序号，`duration` 为动作时长（毫秒） |
| `expressionCount` | 可用表情数量，`0` 表示模型无表情、跳过表情调度 |
| `motionPriority` | `model.motion()` 优先级，`3` 可打断待机动作 |
| `motionPause` / `expressionPause` | 两次动作/表情之间的随机间隔范围（毫秒） |
| `firstMotionDelay` / `firstExpressionDelay` | 首次动作/表情的随机延迟范围 |
| `hiddenRetry` | 页面重新可见后延迟多久恢复调度 |
| `layout.*` | 缩放与定位比例，`bottomY` 略大于 1 让模型底部略低于画布下沿，避免脚部悬浮 |

动作时长取自对应 `.motion3.json` 的 `Meta.Duration`（秒）× 1000。随机调度按「动作时长 + 随机间隔」排下一次，避免上一次动作播到一半就叠加新动作。

新增模型的完整步骤见 `references/model-manifest.md`。

## 关键技术点

1. **非待机动作必须关闭 Loop**：样例模型的非 Idle 动作常为 `"Loop": true`，保持循环会让模型被永久占据，看起来像卡住。把随机动作池里的动作文件改为 `"Loop": false`，只让 Idle 组保持循环。
2. **动作组名必须与 `model3.json` 完全一致**：Mao 的额外动作在空字符串组 `""` 下，调用 `motion('', 0, 3)`；Shizuku 使用 `FlickUp` / `Tap` / `Flick3` 具名组。
3. **禁止交互**：除宿主统一设置的 `pointer-events: none`，模型实例还要设 `autoInteract: false` 与 `eventMode: 'none'`。
4. **透明背景**：`html` / `body` / canvas 均透明，`PIXI.Application` 用 `transparent: true` 与 `backgroundAlpha: 0`。
5. **资源本地化**：渲染库与模型全部放在 stage 目录内、用相对路径引用，不要引用 CDN 或原始项目服务路径。
6. **背景层可选，且必须排在 canvas 之前**：`#stage-bg` 用 `position: fixed` + `object-fit: cover` 铺满视口；没有 `src` 时靠 `#stage-bg[src]` 选择器自动隐藏，因此不加背景时行为与纯透明完全一致。
7. **就绪后淡入**：背景层与 canvas 默认 `opacity: 0`，分别在图片 `load` 与模型加载完成后打上 `data-loaded` / `data-ready` 标记再淡入。iframe 每次打开都要重新加载 10 MB 量级资源，淡入能显著改善"从无到有"的跳变观感。

更多实现细节与排查表见 `references/technical-notes.md`。

## 许可证与版权提示（必须遵守）

`assets/models/` 下两个模型均为 **Live2D 官方样例数据**，受《Live2D Cubism 样例数据使用条款》与《无偿提供素材使用许可协议》约束：

- 一般用户与小规模事业者可商用，需同意条款；中大规模事业者仅限内部/监修用途
- **不得再分发**模型素材；不得修改角色设定（Shizuku 要求直接使用、不改名不改设定）
- 使用样例数据创作的作品**必须标注版权提示**

因此：

1. 交付物必须保留 `assets/LICENSE-Live2D.md`
2. stage 页面必须显示版权提示（模板底部默认显示 `This content uses sample data owned and copyrighted by Live2D Inc.`，不要移除）
3. 不要把本 skill 的 `assets/models/` 直接公开发布给第三方

## 资源来源

- 模型与渲染库来自本地克隆的 [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)：`live2d-models/` 与前端 `libs/`
- `pixi.min.js` 来自 `pixi.js@6.5.10`（MIT）
- `cubism4.min.js` 来自 `pixi-live2d-display@0.4.0`（MIT）
- `live2dcubismcore.min.js` 为 Live2D Cubism Core，按 Live2D 专有软件许可协议分发