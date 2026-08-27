---
name: 3d-object
description: "Build a 3D object as a self-contained HTML file using three.js. The user can inspect it from every angle and download as OBJ+MTL or GLB."
version: 1.0.0
author: Evolve-Agent
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
