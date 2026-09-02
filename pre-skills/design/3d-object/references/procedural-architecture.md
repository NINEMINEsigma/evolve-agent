# Procedural architecture reference

This reference extends the general 3D scene workflow with a reusable method for procedural houses and resort buildings.

## 1. Establish the dimensional scheme

Create one source-of-truth object before placing geometry:

```js
export const D = {
  grade: -0.42,
  fl0: 0.04,
  slab0: [-0.55, 0],
  h0: 3.40,
  slab1: [3.40, 3.76],
  fl1: 3.79,
  h1: 6.60,
  g: { x0: -9, x1: 8.5, z0: -5.8, z1: 4.6, t: 0.32 },
  u: { x0: 1.4, x1: 8.5, z0: -5.8, z1: 4.6, t: 0.30 },
  ti: 0.12,
  ti1: 0.14,
};
```

The exact values are project-specific. The invariant is that levels, envelopes, wall thicknesses, and derived coordinates come from one scheme. If the input is a plan image, record which dimensions were measured and which were estimated.

## 2. Generate walls around openings

Represent each opening as `{ a, b, y0, y1, type, ... }`, where `a/b` are positions along the wall and `y0/y1` are vertical bounds. A wall builder should:

1. collect `0`, wall length, and every opening's horizontal boundary;
2. sort the boundaries;
3. process each horizontal strip independently;
4. split vertically around openings to create wall solids;
5. add a glazing or door assembly inside the opening;
6. add reveal lining unless intentionally disabled.

This avoids runtime boolean operations, keeps geometry predictable, and gives genuine window depth. The glazing should be inset from the exterior face (a typical architectural starting point is around 0.10 m, adjusted for the project).

## 3. Use metric UVs and procedural PBR

A box helper should scale UVs in world metres so changing a wall's size does not change texture density. Build texture families in a canvas at runtime:

- concrete: board seams, tie holes and low-amplitude noise;
- timber: plank joints, grain, rings and knots;
- stone: staggered courses, striation and pitting;
- plaster: trowel-scale mottling;
- grass/gravel: layered noise or distance fields;
- water: physical material plus animated normal offset.

Derive normal maps from the same height field (for example with a Sobel neighborhood) and derive roughness from that field. Cache texture families by their parameter object; generating a 512×512 family per material on every frame is incorrect.

## 4. Separate architecture, furniture and site

Keep the building, furnishings, site and renderer in separate modules. Use groups for:

```text
structure / walls / glazing / circulation / terraces / fixtures
upper / roof / roofTerrace
furnishings / furnishings-upper / roofTerraceFurniture
planting / pool / poolDeck / pavilion
```

Expose only the handles that the renderer and UI need. When an object is animated, register it in a shared state collection rather than searching the entire scene every frame.

## 5. Resort-villa composition

For a courtyard resort villa, a dependable composition is:

- a low open-plan living wing facing the water;
- a partial upper suite wing that gives height and privacy;
- a continuous glazed indoor/outdoor edge;
- a real pool with shell, coping, waterline treatment, animated water surface and entry steps;
- a timber or stone pool deck;
- a freestanding pavilion or pergola outside the building envelope;
- layered planting: palms, broadleaf trees, shrub masses, ornamental grasses and a small number of rocks;
- room-scale furniture inside and sun loungers/outdoor dining beside the pool.

Place the pool, deck, pavilion and planting from shared site bounds rather than unrelated magic coordinates. After moving the pool, recalculate all dependent bounds and camera targets.

## 6. Lighting, environment and viewpoints

Use a sky dome shader for gradient, horizon haze, sun disk and optional stars. Feed a matching sky scene to `PMREMGenerator` so glass and metal reflect the same environment. Rebuild the PMREM render target only when a coarse time-of-day bucket changes, not on every frame.

Represent day/night as keyframes containing sun position, sun color/intensity, sky colors, hemisphere fill, interior-light amount, exposure and fog. Interpolate those values in `applyTOD(t)`. Let interior fixtures cross-fade from daytime fill to warm night light; keep animated fire or water separate from the day-cycle interpolation.

Use named viewpoint records with camera position and target. Ease between records. Include exterior, pool, terrace, interior, suite and aerial views, and test at least one view from each category. A cutaway toggle should change the actual architecture groups and all coupled furniture/roof groups.

## 7. Acceptance checklist

Before delivery:

- parse every module and verify imports;
- check every material property referenced by the scene exists;
- check every renderer/UI handle exists in `userData` or the documented module contract;
- inspect all opening ranges for overlaps and wall-bound violations;
- inspect pool/deck/pavilion bounds for intersections;
- inspect representative viewpoints in a headed browser;
- verify loader, canvas dimensions, FPS/part counters, and fatal errors;
- click a viewpoint, toggle a cutaway or layer, move time of day, and verify observable state changes;
- let the user judge screenshots for composition and structural visual quality.
