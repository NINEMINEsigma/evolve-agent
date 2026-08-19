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

# 3D Object

Build a 3D object the user can inspect from every angle and download, as a self-contained HTML file using three.js.

## Quick Start

1. Copy the stage template: `templates/three_d_stage.html` → your output file (e.g. `ws:output/my-model.html`)
2. Open the copied file, find the `buildModel()` function (clearly marked with `// ===== Build Model (REPLACE THIS) =====`)
3. Replace the example model with your own `THREE.Group` of named meshes
4. Save the file
5. **Display via inline iframe** in the chat bubble — do NOT open a browser. Use this exact format:
   ```html
   <iframe src="/files/ws/output/my-model.html" style="width:640px;height:480px;border:none;border-radius:8px;overflow:hidden;display:block;margin:0 auto"></iframe>
   ```

### Display Convention

- **Always** present the result as an inline `<iframe>` in the assistant message, never via `browser_open_tab` or asking the user to open a URL.
- **Fixed resolution**: `width:640px;height:480px` for 3D content (interactive viewport).
- The iframe gives the user full interactivity (drag to rotate, scroll to zoom, export buttons) without leaving the chat.

The template provides everything else: pinned three.js import map (v0.184.0) with SRI integrity hashes, OrbitControls, studio 3-point lighting, ground shadow, auto-framed camera, and an export toolbar (OBJ+MTL / GLB download buttons).

## three.js Import Map

The template loads three.js ONLY through a pinned import map with SRI integrity hashes in `<head>`. Do NOT change versions, URLs, or hashes. Do NOT add other copies of three.js, and do NOT import addons beyond the four listed (three, OrbitControls, OBJExporter, GLTFExporter) — the map is deliberately a closed set, so anything else fails to resolve rather than loading unverified.

## Building the Model

Build the model programmatically as a `THREE.Group` composed of named parts. The `buildModel()` function must return a `THREE.Group`.

- **Compose primitives** (BoxGeometry, CylinderGeometry, SphereGeometry, TorusGeometry, LatheGeometry, ExtrudeGeometry with Shape) before reaching for raw BufferGeometry — real objects decompose into far more primitives than you'd guess.
- **NAME every mesh and every material** ("hull", "walnut", "brass") — the names become the `o` / `usemtl` entries in the exported OBJ and the node names in the GLB, which is what makes the download usable in Blender.
- **Use MeshStandardMaterial** with a small curated palette (3-5 materials, shared across parts). Set `roughness` / `metalness` deliberately. Textures don't survive the OBJ export — prefer geometry and material color over texture detail.
- **Model in real-world meters**, y-up, centered on the origin, base resting at the lowest y. Offset deliberately coplanar faces by ~0.001 so nothing z-fights.
- **Curved surfaces** need enough segments to read as smooth at full screen (32+ radial segments on feature surfaces), but don't tessellate what no one will see.
- Set `castShadow = true` on each mesh so it casts a shadow on the ground plane.

## Export Formats

The template's toolbar gives the user:
- **OBJ + MTL** — universal format, geometry + per-material colors
- **GLB** — modern interchange format, keeps part hierarchy and PBR materials; imports cleanly into Blender, Maya, Cinema 4D, Unity, Unreal

When the user asks for something else (FBX, USDZ, STEP), say plainly that the viewer exports OBJ+MTL and GLB.

## Iterating

After editing the `buildModel()` function, reload the page in the browser to see changes. Look at the object from the default framing and refine silhouette, proportion, and material separation — the silhouette carries the object.

## File Paths

- Template: `skills:design/3d-object/templates/three_d_stage.html`
- Read the template via: `Read(path="skills:design/3d-object/templates/three_d_stage.html")`
- Write output to: `ws:output/<name>.html`
- Display: inline iframe, `width:640px;height:480px` — see Display Convention above