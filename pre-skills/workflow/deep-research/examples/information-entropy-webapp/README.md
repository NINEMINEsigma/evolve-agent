# 案例：信息熵交互式讲义（Information Entropy Interactive Lecture）

> 这是 deep-research「可视化交互式网页」产出路径的**完整案例源码**。
> 由 deep-research 最早的本体 agent（Kimi Agent）产出，作为该产出路径的标准参考实现。

## 这个案例示范了什么

一个深度研究/知识主题如何做成**可交互、渐进式阅读**的网页版本：

- **渐进式章节叙事**：从直觉（信息量）→ 定义（熵）→ 实验（分布）→ 推导（公式）→ 进阶概念（条件熵/交叉熵）→ 应用（压缩、大模型），8 个章节构成完整学习路径
- **交互式可视化**：每个核心概念配一个可操作的交互（滑块调节参数、实时重算、随机实验模拟、温度参数调 softmax）
- **组件化架构**：章节壳（Section）、滚动入场（Reveal）、数学公式渲染（Math）、通用布局全部抽象为可复用组件
- **深色琥珀主题**：统一视觉系统，canvas 生成式动画背景

## 技术栈

- Vite 7 + React 19 + TypeScript
- Tailwind CSS v3 + shadcn/ui（40+ 组件）
- recharts（图表）
- 构建产物：`npm run build` → `dist/`（base: './'，可直接静态部署）

## 目录结构

```
information-entropy-webapp/
├── src/
│   ├── pages/Home.tsx          ← 单页入口：顶部导航（滚动进度条）+ 8 章节编排
│   ├── sections/               ← 每章一个交互组件（Hero, S1~S8）
│   │   ├── Hero.tsx            ← canvas 生成式动画背景
│   │   ├── S1Surprise.tsx      ← 信息量 h(p) = -log2p 曲线 + 滑块
│   │   ├── S2Coin.tsx          ← 二元熵曲线 + 抛硬币随机实验
│   │   ├── S3Distribution.tsx  ← 概率分布交互实验
│   │   ├── S4Derivation.tsx    ← 公式推导
│   │   ├── S5Conditional.tsx   ← 条件熵
│   │   ├── S6CrossEntropy.tsx  ← 交叉熵 / KL 散度
│   │   ├── S7Compression.tsx   ← 压缩极限
│   │   └── S8LLM.tsx           ← softmax 温度与 LLM
│   ├── components/
│   │   ├── Section.tsx         ← 章节统一外壳（编号/kicker/标题/lead）
│   │   ├── Reveal.tsx          ← 滚动入场动画
│   │   ├── Math.tsx            ← 数学公式组件（Formula/M/Sub）
│   │   └── ui/                 ← shadcn/ui 组件
│   ├── lib/entropy.ts          ← 信息论数学工具（surprise/entropy/crossEntropy/klDivergence/softmaxTemp）
│   └── hooks/
├── dist/                       ← 已构建产物（可直接部署）
├── index.html
├── package.json
├── vite.config.ts              ← base: './'，@ 别名指向 src
├── tailwind.config.js
└── components.json             ← shadcn 配置
```

## 复用方式

1. **当产出路径需要「可视化交互式网页」时**：参考本案例的章节编排方式（渐进式叙事）、交互模式（滑块/实验/参数调节）、组件拆分（Section/Reveal/Math）
2. **快速起步**：复制本目录为模板，改 `src/sections/` 下的内容与 `src/lib/` 的领域逻辑，替换主题色即可
3. **构建**：`npm install && npm run build` → 部署 `dist/`

## 来源

- 原始结果包：Kimi Agent 深度研究产出的「信息熵交互页」zip
- 对应深度研究报告主题：信息熵从直觉到大模型（香农信息论）
