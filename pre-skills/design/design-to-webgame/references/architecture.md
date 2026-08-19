# 网页游戏代码架构模式：数据驱动的分层游戏状态

适用于单机叙事/经营/养成类网页游戏。支持两种技术栈：
- **React + TypeScript**（首选）—— 完整分层架构
- **纯 HTML + JavaScript**（回退）—— 简化但保持相同设计原则

完整可运行样例见 `assets/sample-blacksmith-game/`。

## 目录
1. 分层总览
2. GameState 设计
3. 场景/对话系统
4. 触发检查器
5. reducer 编写模式
6. 存档
7. 界面层约定
8. 纯 HTML 回退方案

---

## 1. 分层总览

### React + TypeScript 架构

```
src/game/types.ts    纯类型定义，零逻辑
src/game/data.ts     纯数值表，零逻辑（改平衡只动这里）
src/game/engine.ts   纯函数（计算/生成/判定），含种子随机，无副作用
src/game/scenes.ts   剧情场景工厂：f(state) => Scene
src/game/state.tsx   唯一可变层：reducer + Context + localStorage
src/sections/*.tsx   界面：只读 state、dispatch action
src/components/      UI 原语 + 场景播放器 + 结局屏
```

依赖方向严格单向：types ← data/engine/scenes ← state ← sections/components。engine 不 import state，scenes 只依赖 types + engine。

### 纯 HTML + JavaScript 架构（回退方案）

```
js/types.js          常量定义（用 Object.freeze 代替 TypeScript）
js/data.js           数值表（同上）
js/engine.js         纯函数
js/scenes.js         场景工厂
js/state.js          状态管理（全局 state 对象 + 简单 pub/sub）
js/app.js            主入口、事件绑定、UI 更新
index.html           结构
style.css            全局样式
```

保持相同的设计原则：数据与逻辑分离、状态集中管理、UI 只做读取和触发。

## 2. GameState 设计

GameState 是一个**纯可序列化对象**（无函数、无类实例、无 Date），这让存档变成一次 JSON.stringify。

先写 GameState 再写任何逻辑——它强迫你通盘决定：资源、库存、订单、顾客、设施、双主角好感、剧情阶段、debuff、队列、结局。

推荐字段分组：经济（gold/totalRevenue）、成长（exp/rep）、物品（materials/inventory）、经营（orders/customers/heat）、剧情（每名角色的子对象 + stage 计数器）、系统（log/scene/pendingScenes/ending）。

## 3. 场景/对话系统

所有对话（主线剧情、事件、日常闲聊、告白）统一为一个数据结构：

```ts
interface Scene {
  id: string
  speaker: 'amei' | 'xiaoling' | 'narrator'   // 决定头像
  lines: string[]                              // 逐行推进
  choices?: SceneChoice[]                      // 末行后的选项
}
interface SceneChoice { label: string; hint?: string; action: SceneAction }
```

- reducer 只负责 `pushScene(state, scene)`：当前有场景则进 `pendingScenes` 队列，否则直接显示；
- 场景选项的 `SceneAction` 是带类型的联合（如 `{type:'ameiAccept'}`），由 reducer 的 `SCENE_CHOICE` 分支统一解释——**选项效果集中在 reducer，场景工厂只产出数据**；
- 日常闲聊用台词库 + 按状态加权（如 debuff 时优先安慰台词、高好感时追加害羞台词），见样例 `sceneXiaoSmalltalk`；
- 收益：后续"给闲聊加对话框"这类需求只需新增工厂函数 + 一行 pushScene。

## 4. 触发检查器

剧情触发统一收口：

```ts
function checkTriggers(s: GameState): GameState {
  // 按顺序检查：主线阈值 → 角色事件（每个带已触发 flag）→ 结局条件
  // 每个触发只做两件事：置 flag、pushScene
}
```

约定：**每个会改变营收/好感/声誉的 action 末尾都 `return checkTriggers(ns)`**。触发条件用布尔 flag 防重复，不用"好感恰好等于 X"这类脆弱条件。

## 5. reducer 编写模式

### React 版本

- action 与玩家操作一一对应（FORGE / SELL / BUY / XIAO_TALK…），UI 不直接改状态；
- 每个 action 开头做合法性检查（材料够吗？金币够吗？），不合法时 `addLog(s, '原因', 'hint')` 返回，UI 无需弹窗；
- 所有随机用 engine 里的种子随机函数，便于测试；
- 经验/声誉跨级检测：记录 before/after 等级对比，升级时追加日志。

### 纯 HTML 版本

- 全局 `state` 对象 + `dispatch(action)` 函数
- dispatch 内部逻辑与 React reducer 相同
- 状态变化后调用 `renderAll()` 更新 UI
- 用发布/订阅模式解耦 UI 更新

## 6. 存档

### React 版本

```ts
useEffect(() => { if (state?.started) localStorage.setItem(KEY, JSON.stringify(state)) }, [state])
```

### 纯 HTML 版本

```js
// 状态变化时自动保存
function saveGame() {
  if (state.started) localStorage.setItem(GAME_KEY, JSON.stringify(state))
}
// 每次 dispatch 后调用 saveGame()
```

- 标题界面提供"继续游戏"，读档后整体替换 state；
- 多周目继承 = 一个 action：从旧 state 挑选继承字段构造新 state（样例见 `NG_PLUS`）；
- 存档是纯 localStorage 时必须告知用户边界：不跨设备、清缓存丢失。

## 7. 界面层约定

- 每个主界面一个 `sections/Xxx.tsx`（React）或一个渲染函数 `renderXxx()`（纯 HTML），对应设计文档 UI 布局章节的一个区域；
- 顶部 HUD 常驻设计文档要求的所有关键数值；
- 小游戏组件参数化：`QTEPanel({ modifier, onFinish })`，同一组件供锻造与比赛复用；
- 视觉原语（Panel/Btn/Bar）封装在 `components/pixel.tsx`（React）或 `style.css`（纯 HTML），全局样式集中管理。

## 8. 纯 HTML 回退方案

当环境无 Node.js 或依赖安装失败时，使用纯 HTML + JavaScript 实现：

**优势**：
- 零构建依赖，双击 index.html 即可运行
- 部署简单，可直接打包为 zip 分享
- 适合小型/中型游戏

**劣势**：
- 无类型检查，大型项目易出错
- 模块化靠 `<script>` 标签顺序，需谨慎组织
- 无热重载，开发效率较低

**最佳实践**：
- 用 ES Modules（`<script type="module">`）实现模块化
- 用 JSDoc 注释补充类型信息
- 数据文件单独存放（`data.js`），方便修改平衡
- 保持与 React 版本相同的架构分层思想
