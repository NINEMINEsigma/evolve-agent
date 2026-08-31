# 赛博战机 · 高性能实时 3D 游戏模板说明

本目录是一份**可运行的完整**高性能实时 3D 空战游戏模板（「赛博战机 — 霓虹峡谷之雨」），
被收录为 `design-to-webgame` skill 的路线C（Three.js + ES Modules 无构建）**高级范例**。

它展示了「从能玩的网页游戏 → 高性能实时 3D 空战」的台阶：不是简单用 `EffectComposer→Bloom`，
而是**自研 HDR 后处理链 + 大规模程序化城市 + 玩家/AI 共用同一套物理**。

## 如何运行

无构建步骤、无服务端。任意静态文件服务器即可（ES 模块需要 `http://`，不能用 `file://`）：

```bash
python3 -m http.server 8000
# 打开 http://localhost:8000/
```

需要 WebGL2 + 桌面浏览器（Chrome / Edge / Safari）。画质与声音在「设置」里，存 `localStorage`。
用 `index.html` 作为唯一入口。

## 目录结构

```
index.html                  入口：HUD + 菜单标记、全部菜单 CSS、import map
package.json                纯元信息（无依赖、无脚本）
README.md                   项目说明
info.md                     交付说明书（换文案/配色/接后端/改模型的指引）
js/
  config.js                 全部调参常量（世界、物理、画质预设、存储键）
  engine.js                 WebGL2 渲染器 + 自研 HDR 后处理链 + 平面反射
  city.js                   程序化霓虹城市：几何、着色器、障碍查询、周期种子
  life.js                   车流、空中出租、行人、GPU 雨、蒸汽、共享辉光池
  sky.js                    暴云天穹 + 程序化 PMREM 环境
  assets.js                 GLTF 加载 / 归一化、动画片段库
  utils.js                  带种子随机数、damp/lerp、共享城市雾 GLSL、全局 uniform
  arena/
    main.js                 游戏编排：启动、对局状态机、相机三态、HUD、调试钩子
    menu.js                 右栏终端菜单（页面、选择、提示音、设置持久化）
    ship.js                 战机构建 + 共享飞行物理 stepShip
    combat.js               池化等离子弹 + 受击方权威判定
    items.js                拾取箱和四种道具（冲击波/电磁脉冲/护盾/疾冲）
    bots.js                 三名 AI 飞行员（与玩家共用物理/战斗代码路径）
assets/models/              5 个小体积原创 GLB（战机、巡逻机、机器人 + 动画），约 1.4 MB
fonts/                      Geist Mono 200/300/400/500（woff2）
vendor/three/               Three.js r170 + GLTFLoader/BufferGeometryUtils/SkeletonUtils
```

## 核心技术点（用来强化同类 3D 游戏）

### 1. 自研 HDR 后处理链（engine.js）
不依赖 `EffectComposer`/`UnrealBloomPass`，而是自己搭：
- 场景渲进**半浮点 RT**
- **亮部提取**（带 NaN/萤火虫防护）→ **亮度加权 mip 降采样/升采样泛光**
- **合成 pass**：ACES 色调映射 + 青色阴影调色 + 程序化镜头雨（`lensRain`，uv 折射）+ 边缘色差 + 径向 boost warp + 暗角 + 动态颗粒
- **FXAA**（防细霓虹边缘爬行）

**为什么值得学**：泛光 mip 数、渲染分辨率、雨密度、粒子数全部由画质预设驱动，可在大规模场景下保持 60fps。

### 2. 大规模程序化城市（city.js / life.js）
- 用 **`InstancedMesh`**：每个 160m 区块容纳 44 栋建筑 + 104 个混凝土装饰 + 64 块霓虹招牌
- **周期性种子**：`mulberry32(li * 2654435761 + 12345)`，种子每 `loopChunks`(3) 个区块重复一次，
  从而数学意义上**无缝的 480m 竞技场循环**（不用 reload，玩家永远飞不出边界）
- 建筑窗户/霓虹招牌/湿滑街面全是**全手写 `ShaderMaterial`**（不是 onBeforeCompile 注入）
- 招牌用 **canvas 程序化图集**（8×4 中英文霓虹词库），字符条纹做全息投影
- 远景天际线 170 实例、信标 420 池、光柱 128 池，全部全局实例化 + 相机环绕

### 3. 玩家/AI 共用物理（arena/ship.js + bots.js）
- **只写一次物理**：`stepShip(P, dt, input)` 是一个纯函数，玩家和 3 名 AI 调用**同一份**代码
- AI 不是黑盒：它们用计算出的输入（油门/避障/提前量瞄准）跑同一套 `stepShip`，
  坠毁/眩晕/重生/计分走玩家完全相同的路径
- 命中判定**以受击方为准**（victim-authoritative）：每颗弹丸在受击方自己的代码路径上判定，
  玩家自己的弹丸永远打不到自己

### 4. 共享雾与全局 uniform（utils.js / sky.js）
- **cityFog**（GLSL）：高度相关密度 + 街面霓虹光污染染色，通过 `onBeforeCompile` 注入**所有**材质，
  全场景共用同一份雾
- **GlobalUniforms**：`uTime`、`uRainAmt`、4 组动态街灯光源（xyz + intensity），逐帧更新一次，
  所有 ShaderMaterial 引用同一对象

### 5. 氛围与粒子（life.js）
- **GPU 雨**：`InstancedBufferGeometry`，≤7000 条相机环绕雨丝，每帧全部在 GPU 位移
- **共享辉光池 `GlowPool`**：所有火花/弹痕/爆炸共用一个批量池，`begin()/end()` 一次性提交
- 148 辆实例化汽车、52 辆空中出租、蒙皮行人池（17 骨人偶 + NLA 动画库）

### 6. 测试友好（arena/main.js）
- 暴露 `window.__arena` 调试钩子：`P`（玩家状态）、`mode`、`bots()`、`startMatch`、`endNow()`、
  `step(now)`（可手动驱动帧，供无头测试）
- 这种「状态机收口 + 调试表面」的做法便于 Playwright 做回归

## 可改造方向

- **换文案/配色**：菜单标签在 `index.html`，HUD 文本在 `index.html` 与 `js/arena/main.js`；
  场景强调色在 `js/config.js` 的 `COLORS` 与 `js/utils.js`
- **改造玩法**：引擎（后处理链/反射/程序化城市/车流）与玩法解耦，只有 `js/arena/*` 是空战专属。
  可改成计时赛、波次生存射击、电影级氛围场景/动态壁纸
- **接后端**：默认 100% 静态（设置存 localStorage）。做成全栈需加服务端 + 数据库
  （在线排行榜/幽灵回放/观战模式）

## 运行说明卡片

- 入口：`index.html`
- 依赖：无（本地 `vendor/three/`）
- 浏览器：WebGL2，桌面 Chrome/Edge/Safari
- 启动失败：页面会显示「渲染器启动失败」而非白屏
