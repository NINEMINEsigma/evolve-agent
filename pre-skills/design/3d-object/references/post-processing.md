# Post-Processing Pipeline

Build a film-grade post-processing chain using Three.js `EffectComposer`.

## Pipeline

```
RenderPass → UnrealBloomPass → OutputPass → ShaderPass(GradeShader)
```

| Pass | Purpose |
|------|---------|
| `RenderPass` | Renders the scene to an offscreen buffer |
| `UnrealBloomPass` | Extracts bright areas and blurs them for glow |
| `OutputPass` | Applies tone mapping (ACES) and color space conversion |
| `ShaderPass(GradeShader)` | Custom: chromatic aberration, color grading, vignette, grain |

## Setup

```js
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';

const size = new THREE.Vector2(innerWidth, innerHeight);
const composer = new EffectComposer(renderer, new THREE.WebGLRenderTarget(size.x, size.y, {
  type: THREE.HalfFloatType,
  samples: 4
}));

composer.addPass(new RenderPass(scene, camera));

const bloom = new UnrealBloomPass(size.clone(), 0.42, 0.72, 0.86);
composer.addPass(bloom);

composer.addPass(new OutputPass());

const grade = new ShaderPass(GradeShader);
grade.uniforms.uResolution.value.copy(size);
composer.addPass(grade);

// In the render loop:
composer.render(dt);
```

## GradeShader — Custom Color Grading

```js
const GradeShader = {
  uniforms: {
    tDiffuse: { value: null },
    uTime: { value: 0 },
    uAmount: { value: 1 },
    uResolution: { value: new THREE.Vector2(1, 1) }
  },
  vertexShader: /* glsl */`
    varying vec2 vUv;
    void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
  `,
  fragmentShader: /* glsl */`
    uniform sampler2D tDiffuse;
    uniform float uTime;
    uniform float uAmount;
    uniform vec2 uResolution;
    varying vec2 vUv;

    void main(){
      vec2 uv = vUv;
      vec2 off = (uv - 0.5);
      float r2 = dot(off, off);

      // chromatic aberration at screen edges
      float disp = 0.0016 * uAmount * r2;
      vec3 col;
      col.r = texture2D(tDiffuse, uv + off * disp).r;
      col.g = texture2D(tDiffuse, uv).g;
      col.b = texture2D(tDiffuse, uv - off * disp).b;

      // color grading: shadows cool, highlights warm
      float luma = dot(col, vec3(0.2126, 0.7152, 0.0722));
      col = mix(col, col * vec3(0.90, 0.97, 1.12), (1.0 - luma) * 0.42 * uAmount);
      col = mix(col, col * vec3(1.05, 1.01, 0.94), smoothstep(0.62, 1.0, luma) * 0.32 * uAmount);
      col = mix(vec3(luma), col, 1.04);

      // vignette
      float vig = smoothstep(1.05, 0.14, r2 * 1.7);
      col *= mix(1.0, vig, 0.42 * uAmount);

      // film grain
      float grain = fract(sin(dot(uv * uResolution + uTime * 41.0, vec2(12.9898, 78.233))) * 43758.5453);
      col += (grain - 0.5) * 0.018 * uAmount;

      gl_FragColor = vec4(col, 1.0);
    }
  `
};
```

## Quality Switching

```js
function applyQuality(cfg) {
  bloom.enabled = cfg.bloom;
  grade.uniforms.uAmount.value = cfg.grade ? 1 : 0.45;
}
```

## Resize

```js
function onResize() {
  const w = innerWidth, h = innerHeight;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
  composer.setSize(w, h);
  bloom.setSize(w, h);
  grade.uniforms.uResolution.value.set(w, h);
}
addEventListener('resize', onResize);
```
