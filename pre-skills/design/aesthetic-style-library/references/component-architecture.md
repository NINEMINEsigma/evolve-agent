# 组件架构参考

> 从 Kimi Agent 多风格审美站项目（kimi-agent-website）源码提取。
> 项目为 React + Vite + Tailwind CSS + Framer Motion / GSAP。

## 页面结构

每个风格展厅（页面）遵循统一布局模式：

```
Page
├── CursorEffect*          ← 自定义光标（仅部分风格）
├── Nav                    ← 页内导航
├── Hero                   ← 首屏着陆
├── SpecimenMeta*          ← 风格档案卡（统一 §6 标准）
├── Sections...            ← 内容区域，每个风格 4-6 个独立 section
└── ExitFooter             ← 底部退场 + 下一展厅链接
```

`*` 可选组件

## 组件分层

```
components/{style}/
├── tokens.ts / decor.ts   ← 设计令牌 + SVG 装饰原语
├── shared.tsx             ← 共享工具函数
├── CrosshairCursor.tsx    ← 光标效果（若存在）
├── Nav.tsx                ← 导航
├── Hero.tsx               ← 英雄区
├── SectionTitle.tsx       ← 节标题
├── Blueprint.tsx          ← 各内容区块
├── Gallery.tsx
├── ...
└── ExitFooter.tsx         ← 页脚
```

## 动画库使用策略

| 风格 | 主动画库 | 原因 |
|:----|:---------|:-----|
| Home | Framer Motion + GSAP | GSAP 用于长卷滚动叙事（pin/scrub） |
| Industrial | Framer Motion | Spring 弹性物理 + 交互动画 |
| Graphic | Framer Motion + GSAP | GSAP 用于 pinned 色块区 |
| Kawaii | Framer Motion | Spring 弹性 + 果冻效果 |
| Minimalism | Framer Motion + GSAP | GSAP 用于 scroll storytelling |
| Glass | Framer Motion | 3D 鼠标跟随 + 滚动插值 |
| Brutalism | Framer Motion | 线性交互动画 |

## 设计令牌体系

每个风格导出统一变量对象，供所有子组件引用：

```ts
// tokens.ts — 例: Graphic 风格
export const GX = {
  bg: '#F4F1EA',
  fg: '#111111',
  red: '#E30613',
  blue: '#0047FF',
  yellow: '#FFD500',
}
```

对应 CSS 变量通过 `:root` 或 `style` prop 注入到页面容器。

## 光标效果列表

| 风格 | 组件 | 机制 | 源码位置 |
|:----|:-----|:-----|:---------|
| Industrial | CrosshairCursor | 弹簧跟随 + 寻像器括号 | `components/industrial/CrosshairCursor.tsx` |
| Kawaii | StarCursor | 星星粒子拖尾 + 渐隐 | `components/kawaii/StarCursor.tsx` |
| Glass | (Hero 内联) | 3D tilt + 镜面高光跟随 | `components/glass/Hero.tsx` |

其他风格使用系统默认光标。
