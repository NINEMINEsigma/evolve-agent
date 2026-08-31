# Field「场」— WebGPU / TSL 程序化渲染层（SKILL_NOTES）

本目录是「场」程序化落地页的**渲染层完整源码**（不含第三方 vendor，需自行 vendored
three webgpu + tsl 版本，可参考 `cyber-jet-scene/vendor` 或官方 webgpu build）。
它演示的是**程序化多变场景**：滚动只产两个数，其余全由渲染器推导。

## 目录结构

- `src/site/scroll.js` — 滚动编排：Lenis 平滑滚动 + `travel`(0..1) + `phase`(0..3)
- `src/main.js` — 启动：requestAdapter → createStage → createScroll → 预热帧 → chrome
- `src/scene/stage.js` — 渲染器 / 相机 / 后期链 / 自适应降档 / 帧循环
- `src/scene/field.js` — 主角：一根实例化草叶 + 每帧重写 4 段存储缓冲的计算通道
- `src/scene/tsl-common.js` — 共享 TSL 积木：状态混合、逐实例随机、高度场、风场、雾
- `src/scene/terrain.js` — 地面：一张平面共用高度场位移，四套着色 cross-fade
- `src/scene/sky.js` — 程序化天穹：渐变 / 太阳 / 云 / 星空，无 HDRI
- `src/scene/palette.js` — 四状态完整调色板 + CPU 混色（`blendInto` / `createBlend`）
- `src/scene/uniforms.js` — 驱动全局的 uniform 集合
- `index.html` / `styles/main.css` — 骨架 + 版式 / 配色变量 / 降级页

## 核心方法论（可迁移）

### 滚动只给两个数
页面产 `travel`（0..1 文档进度）+ `phase`（0..3 当前状态），其余一切（相机位置、光色、
泛光强度、色差）由渲染器内部从这两个数推导。这是「数据驱动场景」的最简契约——页面
不知道 3D 世界，只告诉渲染器「用户滚到哪、处于哪一态」。

### 一次计算通道，多状态
每帧一次 `renderer.compute()` 派发 N 线程（此处 262,144）重写多段 `vec4` 存储缓冲
（root/axis/tint/misc），描述每个实例**此刻是什么**。顶点着色只做一件事：按这些数字弯
一条带子。状态之间不换模型——同一批数字被写成别的值（草/潮汐/余烬/晶格），零加载、零
二次 draw。

### 状态 = 缓冲值不同
- meadow（草场）：根扎地形，风场弯曲，光透叶片
- tide（潮汐）：沿波梯度躺平，浪尖泡沫
- ember（余烬）：离地上升，屏幕空间定尺寸，热色
- lattice（晶格）：吸附网格，格子属性决定亮否，自发光

### 高度场脊柱
`surfaceHeight()`（`tsl-common.js`）被地面网格位移和实例定位共用，所以草永不穿模/浮空；
`surfaceNormal()` 用 central difference 求地面法线。

### TSL 节点图着色
用 `three/tsl` 的 `Fn/If/instanceIndex/instancedArray/uniform/...` 拼节点图，不写 WGSL
字符串；`blendStates` 惰性求值（只对有权重的状态求值，最多 2 态/帧）。

### CPU 混色推 uniform
palette 中每态一整组艺术方向（天空/太阳/雾/地面/相机/泛光/曝光/颗粒/暗角），
`blendInto` 用 tent 权重混合，`createBlend` 复用目标零分配，再 `applyPalette` 推 uniform。

### 沃格尔螺旋盘 + 镜头加权 + 中心空场
实例用 Vogel disc 分布，`skip` 让最内环远离镜头（防怼脸），`place()` exponent 控制密度
偏向镜头（近处密/远处疏按屏幕尺寸收敛）。

### 自适应降档 + 降级页
`TIERS`（262144→150000→80000 实例 + DPR），按帧预算自动升降档；无 WebGPU 显示说明页
而非白屏；`prefers-reduced-motion` 关滚动动效。

### 透光 translucency
草像草的唯一原因是光穿过叶片（backlit）而非反射——`through=pow(back,3)*...` 在
`field.js` 的 colorNode 中。

### 后期链
`scenePass → bloom(强度随 warp) → 色差(仅 morph 横向 RGB split) → 暗角 → grain`；
`warp` 是形态能量（phase 变化速度），morphing 时画面撕裂感。

## 复用方式
复制本目录到项目，vendored `three.webgpu.js` / `three.tsl.js` / `three/addons/`（参考
`cyber-jet-scene/vendor` 或官方 webgpu build），改 `src/scene/palette.js` 与
`field.js` 即可换世界观。`index.html` 的 importmap 指向本地 vendor。

## 需知
- 需要支持 WebGPU 的浏览器（Chrome / Edge / Safari 26+）
- vendor 未包含：需自行提供 three webgpu/tsl 构建
- 这是「滚动驱动」场景；若改成实时游戏可参考 design-to-webgame 的 `cyber-jet-game`
