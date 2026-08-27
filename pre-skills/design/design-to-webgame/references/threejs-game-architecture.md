# Three.js Game Architecture (No-Build Route)

Complete architecture for 3D browser games using Three.js with ES Modules — no bundler, no transpilation, no Node.js required.

## Directory Structure

```
project/
├── index.html              # Canvas, UI skeleton, importmap only
├── package.json            # { "scripts": { "dev": "npx serve . -l 5173" } }
├── vendor/
│   ├── three.module.min.js
│   └── addons/
│       ├── controls/OrbitControls.js
│       ├── postprocessing/
│       ├── utils/BufferGeometryUtils.js
│       └── ...
└── src/
    ├── main.js             # Entry: imports, init, game loop
    ├── core/
    │   ├── audio.js        # Web Audio wrapper (optional)
    │   └── config.js       # Quality presets, settings load/save
    ├── scene/
    │   ├── stage.js        # Renderer, camera, controls, resize
    │   ├── lighting.js     # Sun, fill, spots, hemispheres
    │   ├── post.js         # EffectComposer → Bloom → GradeShader
    │   └── glsl.js         # Shared GLSL noise library
    ├── game/
    │   ├── board.js        # Game board / play area
    │   ├── pieces.js       # Piece geometry factories
    │   ├── materials.js    # PBR materials with onBeforeCompile
    │   ├── table.js        # Piece placement, movement, animation
    │   ├── match.js        # Game state machine, rules, history
    │   ├── fx.js           # Particle bursts, ambient effects
    │   └── badges.js       # Optional piece labels
    ├── chess/              # (for chess-like games)
    │   ├── engine.js       # Board representation, move gen, rules
    │   ├── ai.js           # Search + evaluation
    │   └── worker.js       # Web Worker entry for AI search
    ├── world/              # Environment
    │   ├── sky.js          # Sky dome shader
    │   ├── ground.js       # Terrain with displacement
    │   ├── forest.js       # Instanced trees
    │   ├── snowfall.js     # Vertex-shader particles
    │   └── props.js        # Decorative objects
    └── ui/
        ├── hud.js          # In-game HUD (clocks, eval, ledger)
        ├── menu.js         # Screen navigation
        └── ui.css          # All styling
```

## Module Conventions

Every module exports a factory function `createXxx(scene, ...)` returning an object with at minimum an `update(dt, time)` method:

```js
export function createSky(scene, sunDir) {
  const uniforms = { uTime: { value: 0 } };
  // ... setup dome mesh ...
  return {
    dome,
    uniforms,
    update(_dt, time) { uniforms.uTime.value = time; }
  };
}
```

Main loop calls all updaters:

```js
const systems = [sky, ground, forest, snowfall, table, lighting, post];
function loop(time) {
  const dt = Math.min((time - last) / 1000, 0.1);
  last = time;
  systems.forEach(s => s.update?.(dt, time / 1000));
  post.render(dt);
  requestAnimationFrame(loop);
}
```

## State Machine + Callback Hooks

Decouple game logic from rendering via hooks:

```js
const match = createMatch({
  onReset: () => { table.sync(match.state.pos); board.clearMarks(); },
  onTurn: (color, check) => { hud.setTurn(color); if (check) audio.check(); },
  onMove: (move, { san, captured }) => {
    table.playMove(move);
    audio.place();
    markLastMove(move);
  },
  onEnd: over => endGame(over),
  onThink: color => hud.setTurn(color, { thinking: true })
});
```

The match object owns the game state; the main loop and UI only react through hooks.

## Renderer Setup

```js
const renderer = new THREE.WebGLRenderer({
  canvas, antialias: true, powerPreference: 'high-performance', stencil: false
});
renderer.setPixelRatio(Math.min(devicePixelRatio, cfg.pixel));
renderer.setSize(innerWidth, innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.94;
renderer.shadowMap.enabled = cfg.shadow > 0;
renderer.shadowMap.type = THREE.PCFShadowMap;
```

## Quality Presets

Define three tiers upfront; everything reads from the same config:

```js
const QUALITY = {
  ultra: { pixel: 2, shadow: 2560, snow: 9000, trees: 420, bloom: true, grade: true },
  high:  { pixel: 1.75, shadow: 1792, snow: 5200, trees: 300, bloom: true, grade: true },
  low:   { pixel: 1.15, shadow: 0, snow: 2200, trees: 170, bloom: false, grade: true }
};
```

Auto-downgrade when sustained frame time > 33ms.

## Key Techniques

See `3d-object` skill references for deep documentation on:
- `onBeforeCompile` material injection
- Procedural modeling (LatheGeometry, ExtrudeGeometry, merge)
- Shared GLSL noise library
- Post-processing pipeline
- Environment map generation
