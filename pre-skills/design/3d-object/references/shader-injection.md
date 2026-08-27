# Shader Injection via onBeforeCompile

Extend Three.js PBR materials (`MeshPhysicalMaterial`, `MeshStandardMaterial`) without rewriting the entire shader. This preserves built-in lighting, shadow mapping, tone mapping, and PBR calculations while adding custom surface effects.

## Pattern

```js
const uniforms = { uTime: { value: 0 }, uHover: { value: -1 } };

const material = new THREE.MeshPhysicalMaterial({
  color: 0xffffff,
  roughness: 0.26,
  metalness: 0.0,
  clearcoat: 0.42,
  clearcoatRoughness: 0.30
});

material.onBeforeCompile = shader => {
  Object.assign(shader.uniforms, uniforms);

  // --- Vertex shader: declare varyings and compute world position ---
  shader.vertexShader = shader.vertexShader
    .replace('#include <common>', `#include <common>
      varying vec3 vWorld;`)
    .replace('#include <begin_vertex>', `#include <begin_vertex>
      vWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;`);

  // --- Fragment shader: inject uniforms, varyings, noise, and custom color logic ---
  shader.fragmentShader = shader.fragmentShader
    .replace('#include <common>', `#include <common>
      uniform float uTime;
      uniform float uHover;
      varying vec3 vWorld;
      ${NOISE}`)
    .replace('#include <color_fragment>', `#include <color_fragment>
      // procedural checkerboard + ice/stone variation
      vec2 local = vWorld.xz + 4.0;
      vec2 cell = clamp(floor(local), 0.0, 7.0);
      float dark = mod(cell.x + cell.y, 2.0);
      float vein = ridged(vWorld.xz * 2.6);
      float grain = fbm(vWorld.xz * 9.0);
      vec3 pale = mix(vec3(0.86,0.91,0.97), vec3(0.97,0.99,1.00), vein * 0.8);
      vec3 slate = mix(vec3(0.085,0.108,0.150), vec3(0.19,0.23,0.30), pow(vein,1.7));
      diffuseColor.rgb *= mix(pale, slate, dark);

      // seam grooves between cells
      vec2 f = fract(local);
      vec2 edge = min(f, 1.0 - f);
      float seam = 1.0 - smoothstep(0.0, 0.022, min(edge.x, edge.y));
      diffuseColor.rgb *= 1.0 - seam * 0.45;`)
    .replace('#include <roughnessmap_fragment>', `#include <roughnessmap_fragment>
      roughnessFactor = mix(0.23, 0.44, dark) + fbm(vWorld.xz * 14.0) * 0.12;`)
    .replace('#include <opaque_fragment>', `
      {
        vec4 mk = texture2D(uMarks, (cell + 0.5) / 8.0);
        vec2 c = f - 0.5;
        float d = length(c);
        float pulse = 0.5 + 0.5 * sin(uTime * 2.6);
        vec3 glow = vec3(0.0);

        // legal move dot
        float disc = smoothstep(0.19, 0.11, d);
        float rim = smoothstep(0.215, 0.185, d) - smoothstep(0.185, 0.155, d);
        glow += mk.g * disc * 0.5 + rim * 1.35 * vec3(0.52, 0.79, 1.00);

        // capture / check ring
        float ring = smoothstep(0.46, 0.42, max(abs(c.x), abs(c.y))) - smoothstep(0.42, 0.37, max(abs(c.x), abs(c.y)));
        glow += mk.b * ring * (0.9 + 0.5 * pulse) * vec3(1.00, 0.48, 0.40);

        // selected square breath
        glow += mk.r * (0.30 + 0.18 * pulse) * vec3(0.88, 0.94, 1.00);

        outgoingLight += glow;
      }
      #include <opaque_fragment>`);
};
```

## Injection Points Reference

| Hook | Shader Stage | Variables Available | Typical Use |
|------|-------------|---------------------|-------------|
| `#include <common>` | vertex + fragment | Add uniforms, varyings, helper functions | Declare `vWorld`, `uTime`, import noise |
| `#include <begin_vertex>` | vertex | `transformed`, `position` | Compute world position, displacement |
| `#include <beginnormal_vertex>` | vertex | `objectNormal` | Compute displaced normals |
| `#include <color_fragment>` | fragment | `diffuseColor` | Procedural albedo, checkerboards, masks |
| `#include <roughnessmap_fragment>` | fragment | `roughnessFactor` | Vary roughness per pixel |
| `#include <metalnessmap_fragment>` | fragment | `metalnessFactor` | Vary metalness per pixel |
| `#include <opaque_fragment>` | fragment | `outgoingLight`, `diffuseColor` | Emissive glow, edge lighting, overlay marks |

## Uniform Update

`onBeforeCompile` runs once per material compilation. To animate, update the uniform object in the render loop:

```js
function animate(time) {
  uniforms.uTime.value = time;
  renderer.render(scene, camera);
  requestAnimationFrame(animate);
}
```

## Per-Instance vs Shared Shaders

When multiple meshes need the same shader modifications but different uniform values (e.g. each chess piece needs its own `uLift`):

1. Create one base material with `onBeforeCompile`
2. Clone it for each instance: `const mat = material.clone()`
3. Each clone shares the compiled shader program but has its own uniform values

This is efficient because Three.js deduplicates shader programs via hash.

## Pitfalls

- **Do not** use `material.needsUpdate = true` after `onBeforeCompile` — it triggers recompilation and wipes your injection
- **Do not** modify `shader.vertexShader` or `shader.fragmentShader` outside the `onBeforeCompile` callback
- `#include <opaque_fragment>` must end with `#include <opaque_fragment>` (self-reference) or the actual built-in code won't be inserted
- When injecting before `#include <opaque_fragment>`, write your block then end with `#include <opaque_fragment>` on its own line
