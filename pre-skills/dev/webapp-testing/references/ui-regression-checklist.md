# UI regression checklist

Use this checklist after the initial boot test and after meaningful interaction changes.

## Visibility and overlays

- Verify elements with `hidden` are actually not displayed. If CSS assigns `display: grid` or `display: flex` to the same element, add an explicit `[hidden] { display: none !important; }` rule.
- Confirm loader opacity, pointer-events, and z-index no longer block the application after boot.
- Check that fallback/error panels are hidden on the success path and visible only when their trigger condition is intentional.
- Look for duplicate overlays, duplicate controls, and stale labels after a refresh.

## Controls

For each important button, range input, route, or gesture:

1. record its initial value/class/aria state;
2. perform the action using a discovered selector;
3. verify an observable state change in DOM, URL, text, class, attribute, canvas status, or screenshot;
4. repeat the boot assertion if the action changes a major view.

A control that changes its appearance without changing the underlying scene is not functioning.

## Canvas and responsive layout

- Confirm canvas CSS size and drawing-buffer size are non-zero.
- Resize the viewport and verify renderer size and camera aspect update.
- Check desktop and narrow layouts for clipped controls, unreadable text, or overlays covering the scene.
- Capture screenshots only after asynchronous rendering has settled.

## 3D-specific state

When toggling a 3D layer, verify all coupled objects: architecture, furniture, lights, roof/upper cutaway groups, landscape, and labels. When moving an object or camera, check that dependent props remain aligned and that no object is visibly floating, inside a wall, or inside a pool.
