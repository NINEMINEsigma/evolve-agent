---
name: animated-video
description: "Create an animated video or motion design piece as a self-contained HTML file with a vanilla JS timeline engine, scene sequencing, playback controls, and an Easing library."
category: design
tags:
  - animation
  - video
  - html
  - canvas
  - design
---

# Animated Video

Create an animated video or motion design piece as a self-contained HTML file with a vanilla JS timeline engine, playback controls, and scene sequencing.

## Quick Start

1. Copy the stage template: `templates/animation_stage.html` → your output file (e.g. `output/my-animation.html`)
2. Open the copied file, find the `SCENES` array (clearly marked with `// ===== Scene Definitions — REPLACE THIS =====`)
3. Replace the example scenes with your own
4. Save the file
5. **Display via inline iframe** in the chat bubble — do NOT open a browser. Use this exact format:
   ```html
   <iframe src="/files/ws/output/my-animation.html" style="width:640px;height:420px;border:none;border-radius:8px;overflow:hidden;display:block;margin:0 auto"></iframe>
   ```

### Display Convention

- **Always** present the result as an inline `<iframe>` in the assistant message, never via `browser_open_tab` or asking the user to open a URL.
- **Fixed resolution**: `width:640px;height:420px` for 16:9 animations (canvas + progress bar).
- The iframe gives the user full playback control (play/pause, scrubber) without leaving the chat.

The template provides: a canvas-based timeline engine (1280×720, 16:9), scene sequencing, playback controls (play/pause button, scrubber bar, time display), an Easing library, interpolation helpers, and auto-fit canvas scaling. You only write the scene `draw()` functions.

## Scene Structure

Each scene is an object with a `name`, `duration` (seconds), and a `draw` function:

```js
{
  name: "Scene Name",
  duration: 3,  // seconds
  draw(ctx, progress, localTime, width, height) {
    // ctx:        Canvas 2D rendering context
    // progress:   0 → 1 across this scene's duration
    // localTime:  seconds since this scene started
    // width:      canvas width  (1280)
    // height:     canvas height (720)
  }
}
```

Scenes play in order. The total duration is the sum of all scene durations.

## Available APIs

The template provides these utilities available inside each scene's `draw()`:

### Easing Functions
```js
Easing.linear(t)
Easing.easeInQuad(t) / Easing.easeOutQuad(t) / Easing.easeInOutQuad(t)
Easing.easeInCubic(t) / Easing.easeOutCubic(t) / Easing.easeInOutCubic(t)
Easing.easeInExpo(t) / Easing.easeOutExpo(t) / Easing.easeInOutExpo(t)
Easing.easeOutBounce(t)
Easing.easeOutBack(t)
Easing.easeOutElastic(t)
```

### Helpers
```js
lerp(a, b, t)                       // linear interpolation
clamp(v, min, max)                  // clamp value
interpolate(t, start, end, easing)  // eased interpolation
lerpColor(c1, c2, t)               // interpolate between two [r,g,b] arrays → "rgb(r,g,b)"
```

### Canvas
The canvas is 1280×720 (16:9). Use the `ctx` (Canvas 2D context) for all drawing — fillRect, arc, fillText, save/restore, transforms, etc.

## Animation Tips

- **Storytelling is KEY!** Before you create ANYTHING, identify the story arc, key tensions, characters. Align on the message you want to convey.
- **Use good animation principles**: anticipation, easing, follow-through, exaggeration — the Disney animator principles.
- **Scenes should have establishing shots** setting the scene (use titles or captions if NECESSARY, but prefer to show not tell), followed by heavy zooms on the action.
- **Most scenes should exist in a realistic context**: they should have a background, or exist in the UI of a computer or phone. Elements should not float in the aether.
- **Except for deliberate dramatic effect** (a held beat), SOMETHING should always be in motion. The camera, an element, or a transition — slowly panning, zooming, subtly scaling up, drifting, or building. A truly static frame reads as a bug.
- **Whenever you show text or images**, remember pauses for it to sink in — on the order of seconds — before showing something else.
- **Use delays**: stagger element entrances with `delay` offsets so elements don't all appear at once:
  ```js
  const delay = i * 0.15;
  const localP = clamp((progress - delay) / (1 - delay), 0, 1);
  const eased = Easing.easeOutBounce(localP);
  ```
- **Easing matters**: never use `linear` for organic motion. Use `easeOutCubic` for natural arrivals, `easeOutBounce` for playful entrances, `easeOutBack` for slight overshoot.
- **Make reusable drawing functions** for repeated visual elements — a `drawCircle(ctx, x, y, r, color)` helper keeps scene code clean.

## Canvas Dimensions

Fixed at 1280×720 (16:9). The template auto-scales the canvas to fit the browser window while maintaining aspect ratio. All drawing coordinates should use the 1280×720 coordinate space.

## File Paths

- Template: `skills:design/animated-video/templates/animation_stage.html`
- Read the template via: `Read(path="skills:design/animated-video/templates/animation_stage.html")`
- Write output to: `output/<name>.html`
- Display: inline iframe, `width:640px;height:420px` — see Display Convention above