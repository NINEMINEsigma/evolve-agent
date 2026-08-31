---
name: 3d-object
description: "Build a 3D object as a self-contained HTML file using three.js. The user can inspect it from every angle and download as OBJ+MTL or GLB."
category: design
tags:
  - 3d
  - three.js
  - html
  - design
  - export
---

# 3D Object & Scene

Build 3D objects and immersive scenes the user can inspect from every angle, as self-contained projects using three.js.

**Architecture discipline**: Even without a build step, maintain a modular `src/` directory with ES Modules. The single-HTML shortcut is acceptable only for quick previews under 200 lines. Production work must use the modular structure documented below.

---

## Two Work Modes

### Mode A: Quick Preview (single HTML, ≤200 lines)

For rapid iteration or very simple objects. Copy `templates/three_d_stage.html`, replace `buildModel()`, and display via inline iframe.

**Limitations**: No custom shaders, no post-processing, no procedural textures, no particle systems.

### Mode B: Production Scene (modular, no build)

For polished scenes with custom materials, post-processing, procedural geometry, and interactive elements. This is the default for any scene that needs atmosphere beyond a plain studio backdrop.

```
project/
├── index.html              # canvas, UI skeleton, importmap only
├── package.json            # { "scripts": { "dev": "npx serve . -l 5173" } }
├── vendor/
│   ├── three.module.min.js
│   └── addons/             # OrbitControls, EffectComposer, etc.
└── src/
    ├── main.js             # entry: imports, init, render loop
    ├── scene/
    │   ├── stage.js        # renderer, camera, controls, resize
    │   ├── lighting.js     # sun, fill, spots, hemispheres
    │   └── post.js         # EffectComposer → Bloom → GradeShader
    ├── core/
    │   ├── audio.js        # optional Web Audio wrapper
    │   └── config.js       # quality presets, settings load/save
    ├── world/              # environment: sky, ground, particles, props
    └── materials/          # shared GLSL, material factories
```

`index.html` loads everything through `type="module"` and a local `importmap`. No bundler, no transpilation, no `npm install` of dependencies.

**Display**: Inline iframe (`/files/...`) for interactive viewport; `browser_goto` only when the user explicitly asks to open a separate tab.

---

## Core Techniques (from production scenes)

### 1. Shader Injection via `onBeforeCompile`

The recommended way to extend Three.js PBR materials without losing built-in lighting. Inject GLSL snippets into `MeshPhysicalMaterial` or `MeshStandardMaterial` at compile time.

```js
const material = new THREE.MeshPhysicalMaterial({
  color: 0xffffff, roughness: 0.26, clearcoat: 0.42
});

material.onBeforeCompile = shader => {
  shader.uniforms.uTime = { value: 0 };

  shader.vertexShader = shader.vertexShader
    .replace('#include <common>', `#include <common>
      varying vec3 vWorld;`)
    .replace('#include <begin_vertex>', `#include <begin_vertex>
      vWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;`);

  shader.fragmentShader = shader.fragmentShader
    .replace('#include <common>', `#include <common>
      uniform float uTime;
      varying vec3 vWorld;
      ${NOISE_GLSL}`)
    .replace('#include <color_fragment>', `#include <color_fragment>
      float n = fbm(vWorld.xz * 2.0);
      diffuseColor.rgb *= 0.9 + 0.1 * n;`);
};
```

**Key injection points**:
- `color_fragment` — modify `diffuseColor` before lighting
- `roughnessmap_fragment` — modify `roughnessFactor`
- `metalnessmap_fragment` — modify `metalnessFactor`
- `opaque_fragment` — add emissive glow after lighting

See `references/shader-injection.md` for full patterns.

### 2. Procedural Modeling

Build geometry without external model files. Preferred techniques in order:

| Technique | Use for | API |
|-----------|---------|-----|
| **LatheGeometry** | Rotational symmetry (chess pieces, vases, pillars) | `THREE.LatheGeometry(profilePoints, segments)` |
| **ExtrudeGeometry + Shape** | Profiles with thickness (knight head, emblems) | `THREE.ExtrudeGeometry(shape, { depth, bevelEnabled })` |
| **Box/Cylinder/Sphere primitives** | Simple parts, merged into compound objects | `mergeGeometries(parts)` |
| **BufferGeometry** | Custom meshes when primitives are insufficient | Build position/normal/uv buffers directly |

**Lathe profile DSL**: A tiny chainable API for rotational profiles makes code readable:

```js
const profile = lathe().at(0, 0).line(0.5, 0, 2).quad(0.5, 0.05, 0.4, 0.08, 5).arc(0, 0.3, 0.15, -60, 90, 12).build();
```

See `references/procedural-modeling.md` for the full DSL and examples for every chess piece type.

### 3. Shared GLSL Noise Library

Reuse a single GLSL string across all injected shaders. Provides `hash11/21/22/31`, `vnoise`, `vnoise3`, `fbm`, `fbm3`, `ridged`.

```js
// src/scene/glsl.js
export const NOISE = `float hash21(vec2 p){ ... } float fbm(vec2 p){ ... } ...`;
```

Import and interpolate into every `onBeforeCompile` fragment shader. See `references/glsl-noise.md` for the complete source.

### 4. Post-Processing Pipeline

```
RenderPass → UnrealBloomPass → OutputPass → ShaderPass(GradeShader)
```

`GradeShader` (custom) applies: chromatic aberration at edges, cool shadows / warm highlights, vignette, film grain.

See `references/post-processing.md` for the complete shader and composer setup.

### 5. Environment Maps from Scene Geometry

Generate a PMREM environment map from scene elements (e.g. a sky dome) so that PBR materials receive accurate reflections without external HDR files:

```js
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(envScene, 0, 0.5, 60).texture;
scene.environmentIntensity = 0.9;
pmrem.dispose();
```

### 6. Three.js Import Map (local vendor)

```html
<script type="importmap">
{
  "imports": {
    "three": "./vendor/three.module.min.js",
    "three/addons/": "./vendor/addons/"
  }
}
</script>
```

Download three.js release to `vendor/` rather than using a CDN. This makes the project work offline and avoids SRI hash maintenance.

### 7. 规模化程序化场景（进阶，Mode B 之上）

当场景需要**数百到数千个同类对象**、无缝大世界、或大量程序化发光体时，不要用独立 Mesh +
`EffectComposer`。直接参考本 skill 自带的完整场景模板 `assets/cyber-jet-scene/`（赛博战机渲染层，
说明见 `assets/cyber-jet-scene/SCENE_NOTES.md`）。它覆盖 Mode B 未涵盖的进阶技巧：

- **InstancedMesh 实例化**：用顶点属性（`aSeed/aKind/aTile`）携带每实例随机差异，一次 draw call
  渲染整片城市
- **全手写 ShaderMaterial**：窗户/霓虹/湿滑街面是纯 `ShaderMaterial`，片元里用 `h21(seed)`
  派生窗户密度/发光色，按 `vSize` 做米制 UV
- **平面反射**（mirror camera）：渲染关于 `y=0` 镜像的几何到 RT，街面按镜像视图矩阵采样；
  背景层刻意排除使反射只体现光源而非地平线
- **canvas 程序化图集**：用 `document.createElement('canvas')` 生成霓虹招牌/字符 `CanvasTexture`
- **GPU 粒子 + 共享辉光池**：`InstancedBufferGeometry`（≤7000 雨丝）+ 预分配 `GlowPool` 批量提交
- **周期种子无缝大世界**：`seed = f(idx % loopChunks)` 让地图数学意义上重复，无限循环无需 reload

这些的具体实现直接在 `assets/cyber-jet-scene/js/` 下读源码：`engine.js`（后处理）、`city.js`（程序化城市）、
`life.js`（粒子）、`utils.js`（共享雾/全局 uniform）。

### 8. WebGPU / TSL 程序化场景（计算通道多态，Mode B 之上）

当场景目标是**纯程序化、零素材、形态随滚动/时间连续变形**时，参考本 skill 自带的完整渲染层
范例 `assets/field-wgpu/`（「场」程序化落地页渲染层，说明见 `assets/field-wgpu/SKILL_NOTES.md`）。
它在第 7 条 InstancedMesh 之上覆盖 WebGPU 计算通道 + three.js TSL 节点图：

- **滚动只给两个数**：`travel`(0..1)+`phase`(0..3) 驱动一切，相机/光色/泛光/色差全由渲染器推导
- **一次计算通道，多状态**：每帧派发 N 线程重写多段 `vec4` 存储缓冲，顶点着色只弯一条带子
- **状态=缓冲值不同**：同一批数字写成别的值即切换形态（草/潮汐/余烬/晶格），零加载零二次 draw
- **高度场脊柱**：地面位移+实例定位共用同一 `surfaceHeight()`，永不穿模/浮空
- **TSL 节点图**：不写 WGSL 字符串，改材质不碰着色器源码
- **沃格尔螺旋盘 + 镜头加权 + 中心空场**：密度随屏幕尺寸收敛，防怼脸
- **自适应降档 + 降级页**：低端自动减实例/DPR；不支持 GPU 显说明页而非白屏

具体源码在 `assets/field-wgpu/src/` 下读：`scroll.js`（双数驱动）、`field.js`（计算通道）、
`tsl-common.js`（TSL 积木）、`palette.js`（CPU 混色）、`stage.js`（降档+后期链）。

---

## Quality Presets

Define three quality tiers up front. Everything — renderer, shadows, particles, post-processing, instanced mesh counts — reads from the same config object.

```js
const QUALITY = {
  ultra: { pixel: 2, shadow: 2560, bloom: true, grade: true },
  high:  { pixel: 1.75, shadow: 1792, bloom: true, grade: true },
  low:   { pixel: 1.15, shadow: 0, bloom: false, grade: true }
};
```

Auto-downgrade: measure frame times; if sustained < 30fps, switch to the next lower tier and notify the user.

---

## Export

The original `templates/three_d_stage.html` still provides OBJ+MTL and GLB export via `OBJExporter` / `GLTFExporter`. In modular mode, add an export module:

```js
// src/core/export.js
import { OBJExporter } from 'three/addons/exporters/OBJExporter.js';
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js';

export function exportOBJ(scene) { /* ... */ }
export function exportGLB(scene) { /* ... */ }
```

---

## File Reference

| File | Purpose |
|------|---------|
| `SKILL.md` | This file — overview and quick reference |
| `templates/three_d_stage.html` | Quick preview template (single HTML) |
| `references/shader-injection.md` | Complete `onBeforeCompile` patterns |
| `references/procedural-modeling.md` | Lathe DSL, Shape extrusion, merging |
| `references/glsl-noise.md` | Reusable GLSL noise functions |
| `references/post-processing.md` | EffectComposer setup + GradeShader |
