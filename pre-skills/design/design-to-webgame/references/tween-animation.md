# Game Animation & Timing Systems

Patterns for smooth in-game animations: piece movement, UI transitions, particle effects, camera glides.

## 1. Tween Queue

A minimal animation system without external libraries:

```js
const tweens = [];

function tween(dur, update, done) {
  tweens.push({ t: 0, dur, update, done });
}

function updateTweens(dt) {
  for (let i = tweens.length - 1; i >= 0; i--) {
    const tw = tweens[i];
    tw.t = Math.min(1, tw.t + dt / tw.dur);
    tw.update(tw.t);
    if (tw.t >= 1) { tweens.splice(i, 1); tw.done?.(); }
  }
}
```

## 2. Easing Functions

```js
const easeOut     = t => 1 - (1 - t) ** 3;
const easeInOut   = t => t < 0.5 ? 4 * t ** 3 : 1 - ((-2 * t + 2) ** 3) / 2;
const easeOutBack = t => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2; };
```

## 3. Piece Movement Sequence

Lift → Travel (arc) → Land, with particle bursts at start and end:

```js
function playMove(move, { onDone } = {}) {
  const mover = bySquare.get(move.from);
  const start = mover.mesh.position.clone();
  const end = squareToWorld(move.to, new THREE.Vector3());
  const hop = mover.type === KNIGHT ? 1.05 : 0.0;
  const travel = 0.14 + Math.min(0.34, start.distanceTo(end) * 0.055);

  // Lift
  tween(0.13, k => { mover.mesh.position.y = easeOut(k) * LIFT; }, () => {
    // Travel
    tween(travel, k => {
      const e = easeInOut(k);
      mover.mesh.position.x = start.x + (end.x - start.x) * e;
      mover.mesh.position.z = start.z + (end.z - start.z) * e;
      mover.mesh.position.y = LIFT + Math.sin(k * Math.PI) * hop;
    }, () => {
      // Land
      tween(0.12, k => { mover.mesh.position.y = LIFT * (1 - easeOut(k)); }, () => {
        mover.mesh.position.copy(end);
        bursts.emit(end.clone().setY(0.03), 16, { color: SNOW, spread: 0.9, rise: 0.7 });
        onDone?.();
      });
    });
  });
}
```

## 4. Camera Glide

Smooth camera transitions between preset views:

```js
const VIEWS = {
  seat: { radius: 12.6, polar: 1.04, yaw: 0.30, label: '对坐' },
  high: { radius: 15.2, polar: 0.80, yaw: 0.16, label: '高位' },
  over: { radius: 12.6, polar: 0.14, yaw: 0,    label: '俯瞰' }
};

let glide = null;

function moveTo(view, { instant = false } = {}) {
  const preset = VIEWS[view];
  const azimuth = preset.yaw + (flipped ? Math.PI : 0);
  const target = new THREE.Vector3(
    Math.sin(azimuth) * Math.sin(preset.polar),
    Math.cos(preset.polar),
    Math.cos(azimuth) * Math.sin(preset.polar)
  ).multiplyScalar(preset.radius).add(controls.target);
  if (instant) { camera.position.copy(target); return; }
  glide = { from: camera.position.clone(), to: target, t: 0, dur: 1.05 };
}

function updateCamera(dt) {
  if (glide) {
    glide.t = Math.min(1, glide.t + dt / glide.dur);
    const e = glide.t < 0.5 ? 4 * glide.t ** 3 : 1 - (-2 * glide.t + 2) ** 3 / 2;
    camera.position.lerpVectors(glide.from, glide.to, e);
    if (glide.t >= 1) glide = null;
  }
}
```

## 5. Particle Burst System

Recycle a fixed-size buffer for all particle effects:

```js
const MAX = 900;
const positions = new Float32Array(MAX * 3);
const velocity  = new Float32Array(MAX * 3);
const colors    = new Float32Array(MAX * 3);
const params    = new Float32Array(MAX * 3);  // birth, life, size

const geometry = new THREE.BufferGeometry();
geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
geometry.setAttribute('aVel',     new THREE.BufferAttribute(velocity, 3));
geometry.setAttribute('aColor',   new THREE.BufferAttribute(colors, 3));
geometry.setAttribute('aParam',   new THREE.BufferAttribute(params, 3));
geometry.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 40);

const material = new THREE.ShaderMaterial({
  transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  uniforms: { uTime: { value: 0 }, uPixel: { value: Math.min(devicePixelRatio, 2) } },
  vertexShader: `...`,
  fragmentShader: `...`
});

let cursor = 0;
let time = 0;

function emit(origin, count, { spread = 1.4, rise = 1.5, color, size = 5, life = 0.85 } = {}) {
  for (let i = 0; i < count; i++) {
    const k = cursor;
    cursor = (cursor + 1) % MAX;
    // set position, velocity, color, birth time, life, size
    positions[k * 3] = origin.x + (Math.random() - 0.5) * 0.36;
    // ... etc ...
    params[k * 3] = time;                    // birth
    params[k * 3 + 1] = life * (0.6 + Math.random() * 0.7);  // life
    params[k * 3 + 2] = size * (0.5 + Math.random());        // size
  }
  geometry.attributes.position.needsUpdate = true;
  // ... mark other attributes dirty ...
}
```

Vertex shader computes position from `origin + velocity * age - gravity * age²`. Particles that exceed their lifetime are moved offscreen (`gl_Position = vec4(2,2,2,1)`).

## 6. Selection Glow (Smooth Value Tracking)

Animate material properties without tweens by lerping toward target values:

```js
// In update loop
for (const entry of pieces) {
  const glow = entry.mesh.material.userData.uniforms.uLift;
  glow.value += ((entry.selected ? 0.55 : 0) - glow.value) * Math.min(1, dt * 8);

  const want = entry.selected ? 0.30 + Math.sin(time * 2.6 + entry.bob) * 0.035 : 0;
  entry.lift += (want - entry.lift) * Math.min(1, dt * 11);
  entry.mesh.position.y = entry.lift;
}
```
