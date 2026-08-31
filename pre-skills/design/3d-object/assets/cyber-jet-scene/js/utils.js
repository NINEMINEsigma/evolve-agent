import * as THREE from 'three';

// ---------- deterministic RNG ----------
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
export function hash2i(x, y) { // stable 2-int hash -> [0,1)
  let h = (x * 374761393 + y * 668265263) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

export const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
export const lerp = (a, b, t) => a + (b - a) * t;
export const damp = (a, b, l, dt) => lerp(a, b, 1 - Math.exp(-l * dt));
export const smoothstep = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };

export function pick(rng, arr) { return arr[Math.floor(rng() * arr.length) % arr.length]; }

// ---------- shared city fog (GLSL) ----------
// One fog model for every material in the scene, driven by shared uniforms.
export const FogUniforms = {
  uFogDensity: { value: 0.0027 },
  uFogHeightFall: { value: 0.012 },
  uFogLow: { value: new THREE.Color(0x13212f) },   // street-level neon haze (dark, wet-night)
  uFogHigh: { value: new THREE.Color(0x0b1220) },  // upper ink
  uFogGlow: { value: new THREE.Color(0x2c5478) },  // light-pollution bounce
  uCamY: { value: 40 },
};

export const FOG_PARS = /* glsl */`
  uniform float uFogDensity, uFogHeightFall, uCamY;
  uniform vec3 uFogLow, uFogHigh, uFogGlow;
  vec3 cityFog(vec3 col, vec3 wpos, vec3 camPos) {
    float dist = distance(wpos, camPos);
    // height-dependent density: thicker soup near the street, thinner up high
    float hAvg = max(0.5 * (wpos.y + camPos.y), 0.0);
    float dens = uFogDensity * (1.0 + 1.1 * exp(-hAvg * uFogHeightFall * 3.2));
    float f = 1.0 - exp(-dist * dens);
    f = clamp(f, 0.0, 1.0);
    vec3 fogCol = mix(uFogLow, uFogHigh, clamp(wpos.y / 130.0, 0.0, 1.0));
    // near the ground the city glow tints the murk
    fogCol += uFogGlow * exp(-max(wpos.y, 0.0) * 0.02) * 0.4;
    return mix(col, fogCol, f);
  }
`;

// Patch a built-in three material (Standard/Phong/etc) to use cityFog.
export function patchStdMaterial(mat, opts = {}) {
  mat.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, FogUniforms);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vFogWorldPos;')
      .replace('#include <worldpos_vertex>', '#include <worldpos_vertex>\nvFogWorldPos = (modelMatrix * instancedMaybe(vec4(transformed,1.0))).xyz;');
    // instanced-safe world position
    shader.vertexShader = shader.vertexShader.replace('#include <common>',
      `#include <common>
       vec4 instancedMaybe(vec4 p){
         #ifdef USE_INSTANCING
           return instanceMatrix * p;
         #else
           return p;
         #endif
       }`);
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vFogWorldPos;\n' + FOG_PARS)
      .replace('#include <dithering_fragment>',
        'gl_FragColor.rgb = cityFog(gl_FragColor.rgb, vFogWorldPos, cameraPosition);\n#include <dithering_fragment>');
    if (opts.uniforms) Object.assign(shader.uniforms, opts.uniforms);
    if (opts.edit) opts.edit(shader);
    mat.userData.shader = shader;
  };
  mat.customProgramCacheKey = () => 'cityfog1' + (opts.key || '');
  return mat;
}

// Convenience: build a ShaderMaterial with fog uniforms merged in.
export function cityShaderMaterial(def) {
  const mat = new THREE.ShaderMaterial({
    ...def,
    uniforms: THREE.UniformsUtils.merge([{}, def.uniforms || {}]),
  });
  // merge() clones — rebind shared fog uniforms so they stay live
  for (const k in FogUniforms) mat.uniforms[k] = FogUniforms[k];
  return mat;
}

export const V3 = () => new THREE.Vector3();

// Shared per-frame uniforms (time, rain amount, hero light positions for the wet street)
export const GlobalUniforms = {
  uTime: { value: 0 },
  uRainAmt: { value: 1 },
  // 4 dynamic street lights: xyz = position, w = intensity; colors alongside
  uDynPos: { value: [new THREE.Vector4(0, -100, 0, 0), new THREE.Vector4(0, -100, 0, 0), new THREE.Vector4(0, -100, 0, 0), new THREE.Vector4(0, -100, 0, 0)] },
  uDynCol: { value: [new THREE.Color(0), new THREE.Color(0), new THREE.Color(0), new THREE.Color(0)] },
};

export function bindGlobal(mat, names) {
  for (const n of names) mat.uniforms[n] = GlobalUniforms[n];
  return mat;
}
