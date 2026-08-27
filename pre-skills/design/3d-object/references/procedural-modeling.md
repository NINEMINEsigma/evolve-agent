# Procedural Modeling in Three.js

Build 3D geometry entirely from code. No external model files, no loading, no copyright issues.

## 1. LatheGeometry — Rotational Profiles

Best for: chess pieces, vases, goblets, pillars, knobs, any object with radial symmetry.

### Profile DSL

A chainable API for building 2D profiles that are revolved around the Y axis:

```js
const V2 = (x, y) => new THREE.Vector2(x, y);
const lerp = THREE.MathUtils.lerp;

function lathe() {
  const pts = [];
  const api = {
    pts,
    at(r, y) { pts.push(V2(r, y)); return api; },
    line(r, y, n = 1) {
      const a = pts[pts.length - 1];
      for (let i = 1; i <= n; i++) pts.push(V2(lerp(a.x, r, i / n), lerp(a.y, y, i / n)));
      return api;
    },
    quad(cr, cy, r, y, n = 8) {
      const a = pts[pts.length - 1].clone();
      for (let i = 1; i <= n; i++) {
        const t = i / n, s = 1 - t;
        pts.push(V2(s*s*a.x + 2*s*t*cr + t*t*r, s*s*a.y + 2*s*t*cy + t*t*y));
      }
      return api;
    },
    arc(cx, cy, radius, from, to, n = 16) {
      for (let i = 1; i <= n; i++) {
        const a = lerp(from, to, i / n) * Math.PI / 180;
        pts.push(V2(cx + Math.cos(a) * radius, cy + Math.sin(a) * radius));
      }
      return api;
    },
    build() { return new THREE.LatheGeometry(pts, 44); }
  };
  return api;
}
```

### Reusable Foot (Base)

Most chess-style pieces share a weighted circular base:

```js
function foot(p, r) {
  return p.at(0, 0).line(r * 0.55, 0, 2).line(r, 0, 2)
    .line(r, 0.028, 1)
    .quad(r, 0.056, r * 0.88, 0.066, 5)
    .quad(r * 0.76, 0.072, r * 0.74, 0.088, 4)
    .quad(r * 0.56, 0.100, r * 0.42, 0.122, 6);
}
```

### Example: Pawn

```js
function pawn() {
  const p = foot(lathe(), 0.232);
  p.quad(0.098, 0.150, 0.082, 0.205, 7)
    .quad(0.076, 0.238, 0.086, 0.256, 5)
    .quad(0.128, 0.268, 0.130, 0.282, 5)
    .quad(0.104, 0.296, 0.072, 0.306, 5)
    .arc(0, 0.398, 0.110, -60, 90, 18)
    .at(0, 0.508);
  return p.build();
}
```

### Example: Rook (Lathe + Boxes)

```js
function rook() {
  const p = foot(lathe(), 0.252);
  p.quad(0.112, 0.150, 0.104, 0.230, 7)
    .quad(0.104, 0.290, 0.126, 0.318, 6)
    .quad(0.176, 0.336, 0.178, 0.360, 6)
    .line(0.170, 0.470, 2)
    .quad(0.172, 0.500, 0.196, 0.512, 5)
    .line(0.196, 0.548, 1)
    .line(0.150, 0.548, 1)
    .line(0.150, 0.516, 1)
    .line(0, 0.516, 3);
  const parts = [p.build()];

  // merlons (crenellations) around the top
  const merlon = new THREE.BoxGeometry(0.086, 0.082, 0.062);
  for (let i = 0; i < 6; i++) {
    const a = (i / 6) * Math.PI * 2;
    const m = merlon.clone();
    m.rotateY(-a);
    m.translate(Math.sin(a) * 0.156, 0.578, Math.cos(a) * 0.156);
    parts.push(m);
  }
  merlon.dispose();
  return mergeGeometries(parts, false);
}
```

## 2. ExtrudeGeometry + Shape — Profiles with Thickness

Best for: knight heads, emblems, shields, any object where a 2D profile needs depth.

```js
const head = new THREE.Shape();
head.moveTo(-0.150, 0.264);
head.bezierCurveTo(-0.196, 0.362, -0.186, 0.478, -0.154, 0.560);
head.bezierCurveTo(-0.138, 0.606, -0.114, 0.646, -0.094, 0.672);
head.lineTo(-0.116, 0.732);
// ... more curves ...
head.closePath();

const geom = new THREE.ExtrudeGeometry(head, {
  depth: 0.18,
  bevelEnabled: true,
  bevelSize: 0.012,
  bevelThickness: 0.012,
  bevelSegments: 4
});
// Center the extrusion around the Z axis
geom.translate(0, 0, -0.09);
```

**Critical**: The `Shape` defines the side profile. `ExtrudeGeometry` gives it thickness along Z. Rotate the final mesh to face the desired direction (e.g. `rotation.y` to orient the knight forward).

## 3. Merging Geometries

When a single object is composed of multiple primitive parts, merge them into one `BufferGeometry` for better performance:

```js
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

const merge = parts => {
  const flat = parts.map(g => (g.index ? g.toNonIndexed() : g));
  const out = mergeGeometries(flat, false);
  flat.forEach((g, i) => { if (g !== parts[i]) g.dispose(); });
  parts.forEach(g => g.dispose());
  return out;
};
```

## 4. InstancedMesh — Forests, Crowds, Particles

For thousands of identical objects (trees, rocks, grass blades), use `InstancedMesh`:

```js
const geometry = conifer(5, 6.4, 1.15);  // merged tree geometry
const material = new THREE.MeshStandardMaterial({ color: 0x24443c });
const mesh = new THREE.InstancedMesh(geometry, material, 420);

const dummy = new THREE.Object3D();
for (let i = 0; i < 420; i++) {
  dummy.position.set(x, y, z);
  dummy.scale.setScalar(scale);
  dummy.rotation.y = spin;
  dummy.updateMatrix();
  mesh.setMatrixAt(i, dummy.matrix);
}
mesh.instanceMatrix.needsUpdate = true;
```

**With custom vertex shader**: Instanced meshes work with `onBeforeCompile`. Use `instanceMatrix` in the vertex shader to transform `transformed` before displacement.

## 5. CanvasTexture — Procedural 2D Textures

For labels, borders, or complex flat patterns, draw on a 2D canvas and convert:

```js
function frameTexture() {
  const S = 1024;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = S;
  const ctx = canvas.getContext('2d');

  // draw gradient background
  const grad = ctx.createLinearGradient(0, 0, S, S);
  grad.addColorStop(0, '#2a3040');
  grad.addColorStop(1, '#252b39');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, S, S);

  // draw noise speckles
  for (let i = 0; i < 2600; i++) {
    ctx.fillStyle = `rgba(200,210,255,${Math.random() * 0.05})`;
    ctx.fillRect(Math.random() * S, Math.random() * S, Math.random() * 40 + 2, 1);
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 8;
  return texture;
}
```
