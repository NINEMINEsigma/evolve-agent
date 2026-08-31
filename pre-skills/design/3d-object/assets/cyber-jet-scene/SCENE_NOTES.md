# 场景规模化模板说明 · 赛博战机场景

本目录是 `3d-object` skill 的**规模化程序化场景进阶模板**（赛博战机 — 霓虹峡谷之雨的渲染层），
收录为「从单对象展示 → 大规模程序化场景」的完整可运行范例。

它与 Mode B 的区别：Mode B 聚焦**单个对象/氛围场景**；这里展示的是**数百到数千个同类对象的
规模化渲染 + 游戏化调度**，是「一个有大量程序化发光体的沉浸式场景」。

## 运行

无构建步骤。任意静态服务器（ES 模块需要 `http://`）：

```bash
python3 -m http.server 8000
# http://localhost:8000/
```

WebGL2 + 桌面浏览器。入口 `index.html`。

## 本模板强调的 5 个进阶技巧（Mode B 未覆盖）

### 1. InstancedMesh 实例化规模
城市用 `InstancedMesh` 装载数千实例（建筑 ×44、混凝土 ×104、招牌 ×64 每区块；远景 170、
信标 420、光柱 128）。每个实例用**顶点属性**（`aSeed`、`aKind`、`aTile/aTint/aFlick`）派生
随机差异，一次 draw call 渲染整片城市。

```js
const m = new THREE.InstancedMesh(boxGeo, material, 44);
m.geometry.setAttribute('aSeed', new THREE.InstancedBufferAttribute(new Float32Array(44), 1));
m.instanceMatrix.setUsage(THREE.DynamicDrawUsage); // 需要逐帧更新时
```

### 2. 全手写 ShaderMaterial（而非 onBeforeCompile）
建筑的窗户网格、霓虹招牌、湿滑街面反射都是**纯 `ShaderMaterial`**，不依赖 three 的 PBR 光照。
在片元里用 `h21(seed)` 派生窗户密度/发光色/楼型，面着色器按 `vSize`（实例尺寸）做米制 UV。

### 3. 平面反射（mirror camera）
湿滑街面用**平面反射通道**：把关于 `y=0` 镜像的几何渲进带 mipmap 的 RT，街面着色器用镜像
视图投影矩阵采样。背景 `sky` 刻意**不在** layer-1，让街面只反射城市灯光而非明亮地平线。

```js
engine.renderReflection(scene, camera);        // 渲染镜像几何到 reflRT
city.groundMat.uniforms.uMirrorVP = engine.mirrorVP; // 街面用同一矩阵采样
```

### 4. canvas 程序化图集
霓虹招牌（中英文词库）、字符条纹无需外部图片，用 `document.createElement('canvas')` 生成
`CanvasTexture`，含边框/阴影/发光。`makeSignAtlas` 把 8×4 词库平铺成图集，招牌材质按
`aTile` 的 uv 偏移采样。

### 5. GPU 粒子 + 共享辉光池
雨丝用 `InstancedBufferGeometry`（≤7000，相机环绕），每帧在顶点着色器位移。火花/弹痕/爆炸
走一个共享 `GlowPool`（预分配 cap），`begin()/end()` 批量提交 `instanceMatrix`，避免逐帧造对象。

### 6. 周期种子无缝大世界
给区块种子做周期性（`seed = f(idx % loopChunks)`），地图数学意义上重复，实现**无需 reload 的
无限循环**。适合开放世界/竞技场/长距离飞行的场景。

## 与 Mode B 的结构对应

| Mode B 结构 | 本模板对应实现 |
|:-----------|:---------------|
| `src/scene/post.js`（EffectComposer→Bloom） | `js/engine.js`（自研 HDR 合成 + 平面反射） |
| `src/world/`（环境） | `js/city.js` + `js/life.js`（程序化城市 + 氛围粒子） |
| `src/materials/`（共享 GLSL） | `js/utils.js`（cityFog + GlobalUniforms） |
| `src/core/config.js`（画质预设） | `js/config.js`（QUALITY_PRESETS 驱动规模） |

## 改造方向

- 换场景内容：改 `js/city.js`（程序化几何）+ `js/utils.js`（雾/全局 uniform）+ `js/config.js`（尺寸）
- 换氛围：改 `js/life.js`（雨/蒸汽/车流/行人）+ `js/sky.js`（天穹 + PMREM 环境）
- 换后处理：改 `js/engine.js` 的合成 pass（ACES/色差/雨/暗角/颗粒）
