---
name: aesthetic-style-library
description: 从 Kimi Agent 多风格审美站项目（ws:kimi-agent-website）源码完整提取的七种美学设计风格库，含模板/脚本/资源/参考组件。当用户要求美学风格、视觉设计、前端风格参考、组件设计时使用。
category: design
tags:
  - aesthetic
  - design
  - style
  - components
---

# Aesthetic Style Library · 七种美学设计风格

> 从 Kimi Agent 多风格审美站项目（`ws:kimi-agent-website`）源码完整提取。
> 组件级分解，按模板/脚本/资源/参考分类存放。

---

## 目录结构

```
skills:knowledge/aesthetic-style-library/
├── SKILL.md                          ← 本文件：总览 + 索引
├── assets/                           ← 可复用的 CSS 设计系统
│   ├── industrial-grid.css           ─ 工业风网格背景 + 扫描线
│   ├── glass-panel.css               ─ 玻璃拟态面板 + 按钮
│   └── kawaii-decor.css              ─ 可爱风装饰 + 果冻按钮
├── scripts/                          ← 可复用的 JS 交互模块
│   ├── crosshair-cursor.js           ─ 工业风准星光标（弹簧跟随+寻像器括号）
│   ├── star-cursor.js                ─ 可爱风星星拖尾光标
│   └── glitch-text.js                ─ 工业风 RGB 色差故障文字
├── templates/                        ← 即取即用的 HTML 组件模板
│   ├── home/                         ─ 极简现代风组件
│   │   ├── nav-bar.html              ─ 毛玻璃导航 + 下划线动画
│   │   └── split-chars.html          ─ 字符级入场动画 (y:110%→0, rotate:4°→0)
│   ├── industrial/                   ─ 工业科技风组件
│   │   ├── hud-panel.html            ─ HUD 面板 + 四角括号
│   │   ├── terminal.html             ─ 终端模拟器
│   │   ├── glitch-text.html          ─ 故障文字（自动脉冲 / hover / 偏移）
│   │   ├── blueprint.html            ─ 蓝图标尺板 + 脉冲标注点
│   │   └── particle-grid.html        ─ Three.js 波浪粒子网格地形（~3400点+线框）
│   ├── graphic/                      ─ 平面设计风组件
│   │   ├── masked-word.html          ─ 字符遮罩上升 + 几何色块
│   │   └── section-heading.html      ─ 红色 § 数字章节标题
│   ├── kawaii/                       ─ 二次元可爱风组件
│   │   ├── decor.html                ─ SVG 原语（爱心/星星/四角星/云朵/泡泡）
│   │   ├── polaroid-gallery.html     ─ 拍立得相册卡片
│   │   └── nav-bar.html              ─ 居中胶囊导航栏
│   ├── minimalism/                   ─ 极简主义组件
│   │   ├── hero.html                 ─ 留白 Hero + 呼吸指示线
│   │   └── nav-bar.html              ─ 发丝线导航
│   ├── glass/                        ─ 玻璃拟态组件
│   │   ├── hero-3d-tilt.html         ─ 3D 鼠标跟随倾斜 + 镜面高光
│   │   ├── aurora-background.html    ─ 深空极光背景（120颗星 + 4片极光）
│   │   └── nav-bar.html              ─ 浮空胶囊导航
│   ├── page-transition.html          ─ 全局页面过渡（色彩遮罩翻页）
│   ├── eve-avatar.html               ─ Eve 猫娘头像组件（纯 CSS 猫耳+异色瞳+铃铛）
│   └── brutalism/                    ─ 网页野兽派组件
│       ├── hero.html                 ─ 跑马灯 + 抖动标题 + 闪烁光标
│       ├── nav-bar.html              ─ 默认蓝链接导航
│       └── manifesto.html            ─ 黑色宣言 + 黄色高亮标语
└── references/
    └── component-architecture.md     ─ 组件架构参考文档
```

---

## 七种风格速查

| # | 风格 | bg | fg | Accent | 展示字体 | 圆角 | 关键词 | 独有组件 |
|:-:|:----|:---|:---|:-------|:---------|:----|:-------|:---------|
| 1 | **Home** 极简现代 | #101014 | #EDEDE8 | #C8F04A | Space Grotesk | 16px | 深色·霓虹绿·现代 | 字符入场·年表·宣言滚动叙事 |
| 2 | **Industrial** 工业科技 | #07090D | #C9D4E0 | #00E5FF | JetBrains Mono | 2px | 赛博·网格·HUD·终端 | **准星光标**·故障文字·蓝图·控制台 |
| 3 | **Graphic** 平面设计 | #F4F1EA | #111111 | #E30613 | Archivo | 0 | 瑞士·色块·网格·字体 | 遮罩上升·GSAP 色域·生成海报 |
| 4 | **Kawaii** 二次元可爱 | #FFF3F8 | #6B4A5E | #FF9EC7 | ZCOOL KuaiLe | 24px | 粉彩·圆角·治愈·泡泡 | **星星光标**·拍立得·点击爆爱心 |
| 5 | **Minimalism** 极简主义 | #FAFAF8 | #1A1A1A | #FF4D00 | Inter Tight | 0 | 留白·克制·呼吸 | 呼吸线·GSAP 留白实验·字重滑块 |
| 6 | **Glass** 玻璃拟态 | #0F1226 | #EDEFFF | #7C8CFF | Outfit | 24px | 极光·毛玻璃·通透 | **3D tilt**·极光背景·新拟物 |
| 7 | **Brutalism** 网页野兽派 | #FFFFFF | #000000 | #FFD400 | ZCOOL QingKe HuangYou | 0 | 硬边框·高对比·反设计 | 跑马灯·字符抖动·坏接触红闪 |

---

## 页面过渡效果

| 类型 | 风格 | 文件 | 说明 |
|:----|:-----|:-----|:------|
| **启动序列** | Industrial | `templates/industrial/boot-sequence.html` | 全屏黑色遮罩 + 打字机启动日志（带光标），完成后向上卷起 (y:-100%) |
| **翻页遮罩** | 全局 | `templates/page-transition.html` | 目标风格色块从下往上覆盖 (scaleY 0→1)，切换内容后再从上往下展开 (scaleY 1→0)，中间显示风格英文名 |

### 启动序列用法
```html
<!-- 方法 1：静态 HTML（预置日志行） -->
<div class="boot-overlay" style="--boot-duration: 2.0s;">
  ...日志行...
</div>

<!-- 方法 2：JS 动态生成 -->
<script>
const done = showBootSequence([
  { text: '<span class="ok">[  OK  ]</span> Initializing system...', cls: 'ok', delay: 0 },
  // ...
], { duration: 2000, onComplete: () => { /* 启动完成 */ } });
</script>
```

### 翻页遮罩用法
```js
const t = createPageTransition({ color: '#00E5FF', label: 'INDUSTRIAL TECH' });
await t.start();   // → 遮住页面（0.45s）
// 切换页面内容...
await t.reveal();  // → 展开新页面（0.45s）
```

---

## 光标效果一览

| 风格 | 效果 | 文件 | 说明 |
|:----|:-----|:-----|:------|
| **Industrial** | 🎯 准星光标 | `scripts/crosshair-cursor.js` | 十字线 + 弹簧物理跟随 + hover 出现四角寻像器括号 |
| **Kawaii** | ✦ 星星拖尾 | `scripts/star-cursor.js` | 鼠标移动时留下四角星粒子，渐隐消失，4 色随机切换 |
| **Glass** | ◉ 3D 光晕跟随 | `templates/glass/hero-3d-tilt.html` | 鼠标移动触发卡片 3D tilt + 镜面高光反向偏移 |

---

## 使用方式

### 快速取用组件
直接打开 `templates/{style}/{component}.html`，复制粘贴到你的 HTML 页面中。
每个文件是自包含的 HTML 片段（含 CSS `<style>`，不含外部依赖），可直接使用。

### 引入 CSS 资产
```html
<link rel="stylesheet" href="assets/glass-panel.css">
<link rel="stylesheet" href="assets/industrial-grid.css">
```

### 使用 JS 脚本
```html
<script type="module">
import { createCrosshairCursor } from './scripts/crosshair-cursor.js';
const cleanup = createCrosshairCursor({ color: '#00E5FF' });
</script>
```

```html
<script type="module">
import { createStarCursor } from './scripts/star-cursor.js';
const cleanup = createStarCursor();
</script>
```

---

## 设计令牌对照

每个风格在源码中使用 TS 常量对象（`tokens.ts` / `decor.ts` / `shared.tsx`），在 HTML 中对应的 CSS 变量：

```css
/* Home */
--home-bg: #101014; --home-fg: #EDEDE8; --home-accent: #C8F04A;

/* Industrial */
--ind-bg: #07090D; --ind-fg: #C9D4E0; --ind-accent: #00E5FF;
--ind-magenta: #FF2E88; --ind-amber: #FFB300; --ind-green: #3DFF8C;
--ind-panel: #0C1118;

/* Graphic */
--gx-bg: #F4F1EA; --gx-fg: #111111; --gx-red: #E30613;
--gx-blue: #0047FF; --gx-yellow: #FFD500;

/* Kawaii */
--k-bg: #FFF3F8; --k-fg: #6B4A5E; --k-pink: #FF9EC7;
--k-mint: #A8E6CF; --k-purple: #B8A7F9; --k-yellow: #FFE29A;
--k-titlePink: #FF6BA8;

/* Minimalism */
--min-bg: #FAFAF8; --min-fg: #1A1A1A; --min-accent: #FF4D00;
--min-muted: #9A9A94; --min-hairline: rgba(26,26,26,0.12);

/* Glass */
--gl-bg: #0F1226; --gl-fg: #EDEFFF; --gl-accent: #7C8CFF;
--gl-pink: #FF8FB2; --gl-teal: #5EEAD4; --gl-deepBlue: #3B4ED8;

/* Brutalism */
--br-bg: #FFFFFF; --br-fg: #000000; --br-accent: #FFD400;
--br-link: #0000EE;
```

---

## 源码对应关系

本 skill 所有内容提取自 `ws:kimi-agent-website` 项目（React + Vite + Tailwind CSS），如需查看完整 React 组件实现，请到该目录下查看：

```
ws:kimi-agent-website/app/src/
├── pages/              ← 页面级组件（7 个风格展厅）
│   ├── Home.tsx
│   ├── Industrial.tsx
│   ├── Graphic.tsx
│   ├── Kawaii.tsx
│   ├── Minimalism.tsx
│   ├── Glass.tsx
│   └── Brutalism.tsx
└── components/
    ├── home/           ← 各风格子组件
    ├── industrial/     ├─ 含 CrosshairCursor.tsx 等 13 个组件
    ├── graphic/        ├─ 含 tokens.ts 等 9 个组件
    ├── kawaii/         ├─ 含 StarCursor.tsx、decor.tsx 等 10 个组件
    ├── minimalism/     ├─ 含 8 个组件
    ├── glass/          ├─ 含 shared.tsx、AuroraBackground.tsx 等 10 个组件
    └── brutalism/      ├─ 含 Marquee.tsx 等 8 个组件
```
