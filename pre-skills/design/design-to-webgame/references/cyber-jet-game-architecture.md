# 高性能实时 3D 游戏架构（路线C进阶）

本参考提炼自 `assets/cyber-jet-game/`（赛博战机）模板，用于把「能玩的 3D 网页游戏」提升到
「高性能实时 3D 游戏」。它覆盖的是 `references/threejs-game-architecture.md` 基础路线之上、
**需要规模化 + 性能化**的场景。

核心思路：**渲染与玩法彻底解耦**。`engine` 只负责画（HDR 后处理 + 反射），`arena` 只负责规则，
两者靠共享 uniform 和粒子池沟通。做法是「**只写一次物理，AI 和玩家共用**」+「**程序化是核心，
零外部素材**」。

---

## 1. 自研 HDR 后处理链 vs EffectComposer

`EffectComposer → UnrealBloomPass → OutputPass` 适合中低负载。当场景有大量程序化发光体
（霓虹、粒子、自发光材质）且目标是 60fps 时，自研链更可控：

```
场景 → [半浮点 RT]
     → 亮部提取 pass（阈值 + NaN/萤火虫防护）
     → 亮度加权 mip 降采样 / 升采样 泛光（bloomMips 由画质驱动）
     → 合成 pass（单 pass 内完成）：
         ACES 色调映射
         + 程序化镜头雨（uv 折射：running drips + static condensation）
         + 边缘色差（边缘强、雨滴下更强、warp 时减弱）
         + 径向 boost warp（加速速度线，采样 tColor 4 次拉伸）
         + 暗角 + 动态颗粒（hash + time）
         + sRGB 编码
     → FXAA（防细霓虹爬行）
```

关键 uniform 用**一个 `params` 对象**聚合（`bloom/exposure/rain/warp/flash/grain`），
每帧通过 `damp` 平滑过渡（如 boost 时 warp 渐入、被击中时 flash 脉冲）。

**为什么要单 pass 合成**：把 ACES/色差/雨/暗角/颗粒合成到一个 fragment，避免多次 RT 往返。

---

## 2. 大规模程序化场景 + 实例化

当城市/场景有数百到数千个同类物体时，**不要用独立 Mesh，用 `InstancedMesh`**：

- 每个区块用固定数量的 `InstancedMesh`（如建筑 44 / 混凝土 104 / 招牌 64），一次 draw call
- 用**顶点属性**携带每实例的随机种子（`aSeed`）和类型（`aKind`），在顶点/片元着色器里
  用 `h21(seed)` 派生窗户密度、发光色、楼型——**零额外贴图、零额外几何**
- 招牌用 `aTile/aTint/aFlick` 3 个实例属性，从 canvas 图集采样 + 着色器闪烁

**无缝循环（关键技巧）**：给区块种子做**周期性**（`seed = f(chunkIndex % loopChunks)`），
让地图数学意义上重复。这样游戏地图可以无限循环，无需 reload、无需预制超大地图。

**程序化图集**：霓虹招牌/字符/纹理用 `document.createElement('canvas')` 生成 `CanvasTexture`，
可含中英文、边框、阴影。比外部图片更可控，且随语言切换。

---

## 3. 玩家 / AI 共用物理（核心模式）

最省事且最公平的做法：**物理写成纯函数，AI 和玩家调用同一份**。

```js
function stepShip(P, dt, input) {
  // P: 状态对象（pos/vel/speed/heat/bank/overheated...）
  // input: { keys, mx, my, burn }
  // 只依靠 damp/lerp/clamp 做平滑，不产生副作用
}
```

玩家传真实输入（键盘 + 鼠标），AI 传**计算出的输入**（油门/避障/提前量瞄准）。这样：
- AI 的坠毁/眩晕/重生/计分走玩家完全相同的代码路径，无需特判
- 调整物理参数时，玩家和 AI 同步生效
- AI 只做「决策层」（生成 input），不做「执行层」（不重写物理）

**受击方权威判定（victim-authoritative）**：命中判定放在「被击者一方」的代码路径上。
玩家自己的弹丸永远打不到自己；AI 弹丸是否命中玩家、是否命中其他 AI，都在各自受害者侧判定。
常见实现：弹丸池共享，弹丸带 `owner`，判定时只用 `owner != victim` 的弹丸。

---

## 4. 共享雾 / 全局 uniform（渲染规模化）

全场景共用一份雾和逐帧数据，避免每材质重复采样：

- **共享雾 GLSL**（`cityFog`）：高度相关密度 + 底层颜色混合，通过 `onBeforeCompile` 注入
  所有 Standard/Phong 材质；同时为 ShaderMaterial 提供一份 `cityShaderMaterial` 包装
- **全局 uniform 对象**（`GlobalUniforms`）：`uTime`、雨量、一组动态光源（xyz + intensity + color）。
  所有材质引用**同一个** uniform 对象，逐帧只更新一次，所有材质自动同步
- 注意：`UniformsUtils.merge()` 会克隆 uniform，所以对 ShaderMaterial 需要在 merge 后**重新绑定**
  共享对象（`mat.uniforms.uTime = GlobalUniforms.uTime`），否则会失去实时同步

---

## 5. GPU 粒子 + 共享辉光池

- **GPU 雨/火花**：`InstancedBufferGeometry` + 顶点着色器在 GPU 位移，避免 CPU 逐粒子更新。
  每帧只需更新一个 `uTime`（或少量实例属性）
- **共享辉光池 `GlowPool`**：所有火花/弹痕/爆炸共用一个池（预分配 cap），`begin()/end()`
  批量 `setMatrixAt` 后 `instanceMatrix.needsUpdate = true` 一次性提交。避免每帧新建/销毁对象

---

## 6. 游戏状态机 + 测试钩子

游戏对局收口到一个**状态机**：`menu / countdown / playing / paused / over`。
每帧 `frame(now)` 按 mode 分支：

- `paused`：冻结模拟，只渲染（暂停菜单浮在定格的画面上）
- `countdown`：倒计时并推进 `matchStartAt`
- `over`：玩家巡航直飞，同时弹结算
- 启动/暂停/重生都只是**切换 mode + 重置参数**，不散落逻辑

**调试表面**（对 Playwright 回归极重要）：暴露 `window.__arena`：
`P`（玩家状态）、`mode`、`bots()`、`startMatch`、`endNow()`、`step(now)`（手动驱动帧，供无头测试）。
这是「状态机收口 + 可测性」的体现。

---

## 7. 画质预设 + 自动性能管理

游戏在启动时读 `localStorage` 的画质档，**一个 config 对象驱动所有负载相关参数**：

```js
const QUALITY_PRESETS = {
  影院级: { scale: 1.45, reflScale: 0.5, rain: 7000, bloomMips: 6, steam: 110, peds: 16, fxaa: true },
  均衡:   { scale: 1.0,  reflScale: 0.33, rain: 3600, bloomMips: 5, steam: 56,  peds: 9,  fxaa: true },
};
```

渲染分辨率（renderer.setPixelRatio + scale）、泛光 mip 数、反射分辨率、雨/蒸汽/行人数量
全部从同一个对象读。切档即 `applyQuality()` 重建相关资源。

---

## 8. 可复用模式清单

| 模式 | 适用场景 | 实现要点 |
|:-----|:---------|:---------|
| 自研 HDR 合成 | 大量发光体的夜景/霓虹 | 单 pass 合成 + 半浮点 RT + mip 泛光 |
| InstancedMesh + 顶点属性 | 城市/植被/人群 | 每实例 `aSeed/aKind` + 着色器派生 |
| 周期种子无缝循环 | 开放世界/竞技场 | `seed = f(idx % loopChunks)` |
| 玩家/AI 共用物理 | 任何多人/对抗游戏 | 物理纯函数，AI 只决策 |
| 受击方权威 | 射击/对战 | 弹丸带 owner，victim 侧判定 |
| 共享雾 + 全局 uniform | 大场景统一氛围 | onBeforeCompile 注入 + 重新绑定共享对象 |
| GPU 粒子 + 辉光池 | 粒子密集 | InstancedBufferGeometry + 预分配池 |
| 状态机 + 调试钩子 | 任何有流程的游戏 | mode 收口 + window.__game 暴露 |

> 直接对着 `assets/cyber-jet-game/` 源码读这些模式的真实实现效果最好。
> 先读 `js/engine.js`（后处理链）+ `js/city.js`（程序化城市）+ `js/arena/ship.js`（共用物理）。
