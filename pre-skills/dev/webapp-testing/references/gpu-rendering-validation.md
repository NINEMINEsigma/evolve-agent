# GPU and visual rendering validation

Use this reference for Three.js, WebGL, WebGPU, shader, canvas, and other GPU-backed pages.

## Browser choice

Headless DOM checks can confirm markup and controls, but they do not prove GPU rendering. Use a headed browser for WebGL/WebGPU adapter availability, shader compilation, animation, frame rate, and visual composition. If a headed debug browser is already open, connect to it instead of launching another one.

Do not repeatedly retry a GPU scene in a headless environment that lacks the required adapter. Record the limitation and switch to a headed run or ask for a browser intervention.

## Validation order

1. Open the actual delivery URL.
2. Check title, boot text, root/canvas dimensions, loader, and fallback state.
3. Wait for the scene's ready marker or a bounded settling period.
4. Check runtime counters such as FPS, draw/part count, or triangle count when exposed.
5. Inspect console/module errors.
6. Capture a representative screenshot for each major state.
7. Exercise at least one camera/orbit action and one scene-specific control.
8. Re-check that the canvas remains visible and counters continue updating.

## Visual evidence

A screenshot demonstrates what was rendered at one moment; it is not an objective proof that geometry, composition, lighting, or proportions are perfect. Describe observable facts and let the user make the final visual judgment. For structural defects such as extra limbs, floating objects, broken perspective, or wrong camera framing, show the evidence rather than claiming an automated pass.

## Three.js scene checks

For a procedural scene, inspect:

- imported modules and their delivery URLs;
- renderer and camera resize behavior;
- material/shader compile errors;
- scene object counts and visible canvas;
- quality-tier or DPR behavior;
- animation loop and interaction state changes;
- whether toggling a group also handles its related furniture, lights, overlays, and labels.

For a scene with multiple viewpoints, test the initial view plus a representative interior/exterior or high/low camera. For day/night controls, verify both a light and dark endpoint rather than trusting the slider value alone.
