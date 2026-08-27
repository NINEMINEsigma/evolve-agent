# Shared GLSL Noise Library

A single reusable GLSL string for procedural noise. Import once, inject into every `onBeforeCompile` shader.

## Source

```glsl
float hash11(float p){
  p = fract(p * 0.1031);
  p *= p + 33.33;
  p *= p + p;
  return fract(p);
}

float hash21(vec2 p){
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}

vec2 hash22(vec2 p){
  vec3 p3 = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973));
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.xx + p3.yz) * p3.zy);
}

float hash31(vec3 p){
  p = fract(p * 0.1031);
  p += dot(p, p.zyx + 31.32);
  return fract((p.x + p.y) * p.z);
}

float vnoise(vec2 p){
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash21(i), hash21(i + vec2(1,0)), u.x),
             mix(hash21(i + vec2(0,1)), hash21(i + vec2(1,1)), u.x), u.y);
}

float vnoise3(vec3 p){
  vec3 i = floor(p), f = fract(p);
  vec3 u = f * f * (3.0 - 2.0 * f);
  float n000 = hash31(i),       n100 = hash31(i + vec3(1,0,0));
  float n010 = hash31(i + vec3(0,1,0)), n110 = hash31(i + vec3(1,1,0));
  float n001 = hash31(i + vec3(0,0,1)), n101 = hash31(i + vec3(1,0,1));
  float n011 = hash31(i + vec3(0,1,1)), n111 = hash31(i + vec3(1,1,1));
  return mix(mix(mix(n000, n100, u.x), mix(n010, n110, u.x), u.y),
             mix(mix(n001, n101, u.x), mix(n011, n111, u.x), u.y), u.z);
}

float fbm(vec2 p){
  float v = 0.0, a = 0.5;
  mat2 rot = mat2(0.86, 0.51, -0.51, 0.86);
  for (int i = 0; i < 5; i++){
    v += a * vnoise(p);
    p = rot * p * 2.03;
    a *= 0.5;
  }
  return v;
}

float fbm3(vec3 p){
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 4; i++){
    v += a * vnoise3(p);
    p *= 2.07;
    a *= 0.5;
  }
  return v;
}

float ridged(vec2 p){
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 4; i++){
    v += a * (1.0 - abs(vnoise(p) * 2.0 - 1.0));
    p *= 2.11;
    a *= 0.5;
  }
  return v;
}
```

## Usage in JavaScript

```js
// src/scene/glsl.js
export const NOISE = `float hash21(vec2 p){ ... } ...`;
```

```js
// In any material's onBeforeCompile
import { NOISE } from '../scene/glsl.js';

shader.fragmentShader = shader.fragmentShader
  .replace('#include <common>', `#include <common>
    ${NOISE}`);
```

## Function Reference

| Function | Input | Output | Use Case |
|----------|-------|--------|----------|
| `hash11` | `float` | `[0,1]` | 1D random |
| `hash21` | `vec2` | `[0,1]` | 2D random (grid-based) |
| `hash22` | `vec2` | `vec2` | 2D random vector |
| `hash31` | `vec3` | `[0,1]` | 3D random (stars, particles) |
| `vnoise` | `vec2` | `[0,1]` | 2D value noise (smooth) |
| `vnoise3` | `vec3` | `[0,1]` | 3D value noise |
| `fbm` | `vec2` | `[0,1]` | 2D fractal Brownian motion (terrain, grain) |
| `fbm3` | `vec3` | `[0,1]` | 3D fbm (3D textures, volume) |
| `ridged` | `vec2` | `[0,1]` | Ridged multifractal (mountains, shell cracks) |

## Patterns

**Terrain height**: `fbm(p * 0.048) * 3.1 + fbm(p * 0.17) * 0.46 + ridged(p * 0.09) * 0.55`

**Procedural checkerboard**: `mod(floor(x) + floor(y), 2.0)`

**Ice veins**: `ridged(vWorld.xz * 2.6 + vec2(0.0, dark * 11.0))`

**Grain texture**: `fbm(vWorld.xz * 9.0)`

**Sparkle grid** (for snow crystals):
```glsl
vec2 gp = vWorld.xz * 13.0;
vec2 cell = floor(gp);
vec2 jit = hash22(cell) - 0.5;
float d = length(fract(gp) - 0.5 - jit * 0.72);
float flake = smoothstep(0.13, 0.01, d);
```
