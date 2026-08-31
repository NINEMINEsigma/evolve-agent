import * as THREE from 'three';
import { WORLD } from './config.js';
import { mulberry32, hash2i, FogUniforms, FOG_PARS, GlobalUniforms } from './utils.js';

const L = WORLD.chunkLen;

// ============================================================ sign atlas ====
const SIGN_WORDS = [
  ['RAMEN', 'v'], ['HOTEL', 'h'], ['TAVERN', 'v'], ['NIGHT CITY', 'h'],
  ['CYBER CITY', 'h'], ['24H', 'h'], ['BAR', 'h'], ['SUSHI', 'v'],
  ['TAXI', 'h'], ['NIGHT MARKET', 'h'], ['PAWN', 'v'], ['GRID-7', 'h'],
  ['CLUB X', 'h'], ['DINER', 'h'], ['KARAOKE', 'h'], ['PHARMACY', 'v'],
  ['NO SIGNAL', 'h'], ['CYBERNETIC', 'h'], ['OLD BAR', 'h'], ['DATA◢', 'h'],
  ['AKIRA', 'v'], ['MOTEL', 'h'], ['TEA HOUSE', 'h'], ['CHARGE', 'h'],
  ['◣◤◢◥', 'h'], ['EXIT', 'h'], ['777', 'h'], ['FUTURE', 'v'],
  ['LIVE', 'h'], ['SOBA', 'h'], ['◉ SCAN', 'h'], ['HEAVEN', 'v'],
];
export function makeSignAtlas() {
  const cols = 8, rows = 4, T = 256;
  const cv = document.createElement('canvas');
  cv.width = cols * T; cv.height = rows * T;
  const ctx = cv.getContext('2d');
  ctx.clearRect(0, 0, cv.width, cv.height);
  const fonts = '"Hiragino Sans", "PingFang SC", "Heiti SC", sans-serif';
  for (let i = 0; i < SIGN_WORDS.length; i++) {
    const [word, orient] = SIGN_WORDS[i];
    const cx = (i % cols) * T, cy = Math.floor(i / cols) * T;
    ctx.save();
    ctx.translate(cx + T / 2, cy + T / 2);
    ctx.fillStyle = '#fff';
    ctx.strokeStyle = '#fff';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.shadowColor = 'rgba(255,255,255,0.9)';
    const boxed = (i % 3 === 0);
    if (boxed) {
      ctx.lineWidth = 7; ctx.shadowBlur = 10;
      ctx.strokeRect(-T / 2 + 18, -T / 2 + 18, T - 36, T - 36);
    }
    ctx.shadowBlur = 12;
    if (orient === 'v') {
      const chars = [...word];
      const fs = Math.min(78, (T - 60) / chars.length);
      ctx.font = `700 ${fs}px ${fonts}`;
      const total = chars.length * (fs + 8);
      chars.forEach((ch, k) => {
        ctx.fillText(ch, 0, -total / 2 + (fs + 8) * (k + 0.5));
        ctx.fillText(ch, 0, -total / 2 + (fs + 8) * (k + 0.5));
      });
    } else {
      let fs = 66;
      ctx.font = `700 ${fs}px ${fonts}`;
      while (ctx.measureText(word).width > T - 50 && fs > 20) { fs -= 4; ctx.font = `700 ${fs}px ${fonts}`; }
      ctx.fillText(word, 0, 0);
      ctx.fillText(word, 0, 0); // double for glow punch
    }
    ctx.restore();
  }
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  tex.wrapS = tex.wrapT = THREE.ClampToEdgeWrapping;
  return { tex, cols, rows };
}

export function makeGlyphStrip() {
  const cv = document.createElement('canvas');
  cv.width = 1024; cv.height = 64;
  const ctx = cv.getContext('2d');
  const glyphs = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789◢◣◤◥▲△▌▐GRIDCITYACCESSREVOKED';
  ctx.fillStyle = '#fff';
  ctx.font = '700 44px "Hiragino Sans", monospace';
  ctx.textBaseline = 'middle';
  let x = 8;
  let i = 0;
  while (x < 1000) {
    const ch = glyphs[(i * 7 + 3) % glyphs.length];
    ctx.globalAlpha = 0.55 + 0.45 * ((i * 37 % 10) / 10);
    ctx.fillText(ch, x, 34);
    x += 44 + (i * 13 % 3) * 10; i++;
  }
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = THREE.RepeatWrapping; tex.wrapT = THREE.ClampToEdgeWrapping;
  return tex;
}

// ========================================================== materials =======

function buildingMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: { uTime: GlobalUniforms.uTime, ...FogUniforms },
    vertexShader: /* glsl */`
      attribute float aSeed;
      attribute float aKind;
      varying vec3 vW, vN, vLocal, vSize;
      varying float vSeed, vKind;
      void main(){
        vSeed = aSeed; vKind = aKind;
        vLocal = position;
        #ifdef USE_INSTANCING
          vSize = vec3(length(instanceMatrix[0].xyz), length(instanceMatrix[1].xyz), length(instanceMatrix[2].xyz));
          vec4 wp = modelMatrix * instanceMatrix * vec4(position, 1.0);
          vN = normalize(mat3(instanceMatrix) * normal);
        #else
          vSize = vec3(1.0);
          vec4 wp = modelMatrix * vec4(position, 1.0);
          vN = normal;
        #endif
        vW = wp.xyz;
        gl_Position = projectionMatrix * viewMatrix * wp;
      }
    `,
    fragmentShader: /* glsl */`
      varying vec3 vW, vN, vLocal, vSize;
      varying float vSeed, vKind;
      uniform float uTime;
      ${FOG_PARS}
      float h21(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7)))*43758.5453); }
      void main(){
        vec3 n = normalize(vN);
        float seed = vSeed;
        // face-space meters
        vec2 fuv; float faceSel;
        if (abs(n.y) > 0.5) { fuv = (vLocal.xz + 0.5) * vSize.xz; faceSel = 2.0; }
        else if (abs(n.x) > 0.5) { fuv = vec2((vLocal.z + 0.5) * vSize.z, (vLocal.y + 0.5) * vSize.y); faceSel = 0.0; }
        else { fuv = vec2((vLocal.x + 0.5) * vSize.x, (vLocal.y + 0.5) * vSize.y); faceSel = 1.0; }

        float tone = 0.75 + 0.5 * h21(vec2(seed, 7.7));
        vec3 base = mix(vec3(0.012, 0.016, 0.026), vec3(0.03, 0.034, 0.05), tone);
        vec3 col = base * (0.35 + 0.25 * max(n.y, 0.0));
        vec3 emis = vec3(0.0);

        if (faceSel < 1.5) {
          // window grid
          vec2 cellSize = vec2(2.0 + h21(vec2(seed, 1.0)) * 1.0, 2.65);
          vec2 cid = floor(fuv / cellSize);
          vec2 cuv = fract(fuv / cellSize);
          float rnd = h21(cid + seed * 113.0 + faceSel * 31.0);
          float rowRnd = h21(vec2(cid.y, seed * 57.0));
          float density = 0.16 + 0.3 * h21(vec2(seed, 3.3));
          float lit = step(rnd, density) * step(0.2, rowRnd);
          float wx = step(0.22, cuv.x) * step(cuv.x, 0.82);
          float wy = step(0.3, cuv.y) * step(cuv.y, 0.78);
          float win = wx * wy;
          // border of building: no windows within 1.2m of edges / top
          vec2 tot = (faceSel < 0.5) ? vec2(vSize.z, vSize.y) : vec2(vSize.x, vSize.y);
          float inset = step(1.0, fuv.x) * step(fuv.x, tot.x - 1.0) * step(0.5, fuv.y) * step(fuv.y, tot.y - 2.0);
          float warm = h21(cid + seed * 7.0);
          vec3 wcol = mix(vec3(0.45, 0.75, 1.0), vec3(1.0, 0.75, 0.42), step(0.45, warm));
          wcol = mix(wcol, vec3(0.75, 0.95, 1.1), step(0.9, warm));
          float bright = 0.30 + 1.0 * h21(cid + seed * 19.0);
          // sparse animated flicker
          float fl = 1.0;
          if (h21(cid + seed) > 0.97) fl = 0.4 + 0.6 * step(0.5, fract(uTime * (1.0 + rnd * 3.0) + rnd * 9.0));
          emis += wcol * win * lit * inset * bright * fl;
          // dark glass sheen for unlit
          col += vec3(0.015, 0.02, 0.03) * win * inset * (1.0 - lit);

          // storefront band on street level (presence + stripe rhythm vary per building)
          if (vW.y < 10.0 && vKind > 0.5 && vKind < 1.5 && h21(vec2(seed, 92.0)) > 0.38) {
            float band = smoothstep(8.5, 6.0, vW.y) * step(2.5, vW.y);
            float hue = h21(vec2(seed, 91.0));
            vec3 scol = hue < 0.4 ? vec3(0.2, 0.85, 1.0) : (hue < 0.7 ? vec3(1.0, 0.25, 0.5) : vec3(1.0, 0.65, 0.25));
            float sfreq = 0.18 + h21(vec2(seed, 93.0)) * 0.62;
            float stripes = 0.55 + 0.45 * step(0.35, fract(fuv.x * sfreq + seed));
            emis += scol * band * (0.45 + 0.7 * h21(vec2(seed, 94.0))) * stripes;
          }
          // vertical neon edge strip on some towers
          float edgeD = min(fuv.x, tot.x - fuv.x);
          if (h21(vec2(seed, 5.0)) > 0.72) {
            float strip = smoothstep(0.3, 0.12, edgeD) * step(3.0, fuv.y);
            vec3 ncol = h21(vec2(seed, 6.0)) > 0.5 ? vec3(0.2, 0.8, 1.0) : vec3(1.0, 0.2, 0.45);
            emis += ncol * strip * 1.0;
          }
        } else if (n.y > 0.5) {
          // roof: edge trim glow on some
          vec2 tot = vSize.xz;
          vec2 d2 = min(fuv, tot - fuv);
          float rim = smoothstep(0.55, 0.25, min(d2.x, d2.y));
          if (h21(vec2(seed, 11.0)) > 0.5) emis += vec3(0.25, 0.8, 1.0) * rim * 1.35;
          col *= 0.75;
        }
        col += emis;
        col = cityFog(col, vW, cameraPosition);
        gl_FragColor = vec4(col, 1.0);
      }
    `,
  });
}

function concreteMaterial() {
  // decks, pylons, bridges, poles, billboard frames — aKind selects trim style
  return new THREE.ShaderMaterial({
    uniforms: { uTime: GlobalUniforms.uTime, ...FogUniforms },
    vertexShader: /* glsl */`
      attribute float aSeed;
      attribute float aKind;
      varying vec3 vW, vN, vLocal, vSize;
      varying float vSeed, vKind;
      void main(){
        vSeed = aSeed; vKind = aKind; vLocal = position;
        #ifdef USE_INSTANCING
          vSize = vec3(length(instanceMatrix[0].xyz), length(instanceMatrix[1].xyz), length(instanceMatrix[2].xyz));
          vec4 wp = modelMatrix * instanceMatrix * vec4(position, 1.0);
          vN = normalize(mat3(instanceMatrix) * normal);
        #else
          vSize = vec3(1.0); vec4 wp = modelMatrix * vec4(position, 1.0); vN = normal;
        #endif
        vW = wp.xyz;
        gl_Position = projectionMatrix * viewMatrix * wp;
      }
    `,
    fragmentShader: /* glsl */`
      varying vec3 vW, vN, vLocal, vSize;
      varying float vSeed, vKind;
      uniform float uTime;
      ${FOG_PARS}
      float h21(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7)))*43758.5453); }
      void main(){
        vec3 n = normalize(vN);
        vec3 col = vec3(0.020, 0.023, 0.030) * (0.5 + 0.4 * max(n.y, 0.0));
        col *= 0.8 + 0.4 * h21(floor(vW.xz * 0.5));
        vec3 emis = vec3(0.0);
        float k = vKind;
        if (k < 0.5) {
          // highway deck
          if (n.y > 0.5) {
            // seam strips across the segment ends
            float seam = min(vLocal.z + 0.5, 0.5 - vLocal.z) * vSize.z;
            emis += vec3(0.15, 0.75, 1.0) * smoothstep(0.42, 0.18, seam) * 1.4;
            // long-edge guide lines
            float ex = (0.5 - abs(vLocal.x)) * vSize.x;
            emis += vec3(0.12, 0.55, 0.9) * smoothstep(0.3, 0.1, ex) * 0.9;
            // lane dashes
            float lx = abs(vLocal.x) * vSize.x;
            float dash = smoothstep(0.22, 0.09, abs(lx - 2.3)) * step(0.5, fract(vW.z * 0.16));
            emis += vec3(0.55, 0.62, 0.7) * dash * 0.55;
          }
          // side skirt light-line
          if (abs(n.y) < 0.5) {
            float band = smoothstep(0.34, 0.5, vLocal.y);
            emis += vec3(1.0, 0.45, 0.15) * band * 0.5;
          }
        } else if (k < 1.5) {
          // pylon: hazard glow band near base
          float hb = smoothstep(7.0, 2.0, vW.y) * step(0.5, fract(vW.y * 0.8));
          emis += vec3(1.0, 0.55, 0.1) * hb * 0.5;
          col *= 0.85;
        } else if (k < 2.5) {
          // skybridge: lit window band
          float band = step(abs(vLocal.y), 0.18);
          float win = step(0.35, fract((vLocal.x + 0.5) * vSize.x * 0.6 + vSeed));
          emis += vec3(0.55, 0.8, 1.0) * band * win * 1.0;
        } else if (k < 3.5) {
          col *= 0.7; // plain pole / frame
        } else if (k < 4.5) {
          // guardrail: dark body, bright top lip
          col *= 0.55;
          float lip = smoothstep(0.30, 0.48, vLocal.y);
          emis += vec3(0.18, 0.75, 1.0) * lip * 1.7;
        }
        col += emis;
        col = cityFog(col, vW, cameraPosition);
        gl_FragColor = vec4(col, 1.0);
      }
    `,
  });
}

function signMaterial(atlas) {
  return new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, side: THREE.FrontSide, blending: THREE.AdditiveBlending,
    uniforms: { tAtlas: { value: atlas.tex }, uTime: GlobalUniforms.uTime, ...FogUniforms },
    vertexShader: /* glsl */`
      attribute vec4 aTile;    // uv offset+scale
      attribute vec3 aTint;
      attribute vec2 aFlick;   // rate, style
      varying vec2 vUv; varying vec4 vTile; varying vec3 vTint; varying vec2 vFlick;
      varying vec3 vW;
      void main(){
        vUv = uv; vTile = aTile; vTint = aTint; vFlick = aFlick;
        #ifdef USE_INSTANCING
          vec4 wp = modelMatrix * instanceMatrix * vec4(position, 1.0);
        #else
          vec4 wp = modelMatrix * vec4(position, 1.0);
        #endif
        vW = wp.xyz;
        gl_Position = projectionMatrix * viewMatrix * wp;
      }
    `,
    fragmentShader: /* glsl */`
      uniform sampler2D tAtlas; uniform float uTime;
      varying vec2 vUv; varying vec4 vTile; varying vec3 vTint; varying vec2 vFlick;
      varying vec3 vW;
      ${FOG_PARS}
      void main(){
        vec4 t = texture2D(tAtlas, vTile.xy + vUv * vTile.zw);
        float a = t.a;
        // buzz / flicker styles
        float f = 1.0;
        if (vFlick.y > 1.5) {           // dying sign
          f = 0.25 + 0.75 * step(0.42, fract(sin(floor(uTime * 9.0 + vFlick.x) * 91.7) * 43758.0));
        } else if (vFlick.y > 0.5) {    // gentle mains hum
          f = 0.82 + 0.18 * sin(uTime * 55.0 + vFlick.x);
        }
        vec3 col = vTint * a * f * 2.9;
        float fade = exp(-distance(vW, cameraPosition) * uFogDensity * 1.35);
        col *= fade;
        gl_FragColor = vec4(col, a);
      }
    `,
  });
}

function holoMaterial(atlas, glyphs) {
  return new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending,
    uniforms: {
      tAtlas: { value: atlas.tex }, tGlyphs: { value: glyphs },
      uTime: GlobalUniforms.uTime, ...FogUniforms,
      uTile: { value: new THREE.Vector4(0, 0, 0.125, 0.25) },
      uTint: { value: new THREE.Color(0x53d5fd) },
      uKind: { value: 0 },
      uSeed: { value: 0 },
      uPanel: { value: 0 },
    },
    vertexShader: /* glsl */`
      varying vec2 vUv; varying vec3 vW; varying vec3 vN;
      void main(){
        vUv = uv;
        vec4 wp = modelMatrix * vec4(position, 1.0);
        vW = wp.xyz;
        vN = normalize(mat3(modelMatrix) * normal);
        gl_Position = projectionMatrix * viewMatrix * wp;
      }
    `,
    fragmentShader: /* glsl */`
      uniform sampler2D tAtlas, tGlyphs;
      uniform float uTime, uKind, uSeed, uPanel;
      uniform vec4 uTile; uniform vec3 uTint;
      varying vec2 vUv; varying vec3 vW; varying vec3 vN;
      ${FOG_PARS}
      float h11(float p){ return fract(sin(p * 127.1) * 43758.5453); }
      void main(){
        vec2 uv = vUv;
        float t = uTime + uSeed * 40.0;
        // rolling glitch band
        float band = fract(uv.y * 1.0 - t * 0.11);
        float glitch = step(0.965, h11(floor(t * 13.0) + floor(uv.y * 24.0)));
        uv.x += glitch * (h11(floor(t * 17.0)) - 0.5) * 0.09;
        vec3 col = vec3(0.0);
        float alpha = 0.0;
        if (uKind < 0.5) {
          // billboard: atlas tile + frame + scanlines (optional dark glass backing
          // so it silhouettes against the sky instead of reading transparent)
          vec4 s = texture2D(tAtlas, uTile.xy + uv * uTile.zw);
          float frame = max(step(0.975, max(abs(uv.x - 0.5), abs(uv.y - 0.5)) * 2.05), 0.0);
          vec3 panel = (vec3(0.015, 0.022, 0.038) + uTint * 0.06) * uPanel;
          col = uTint * (s.a * 1.6 + frame * 0.9) + panel;
          alpha = max(s.a * 0.8 + frame * 0.5 + 0.10, uPanel * 0.38);
        } else if (uKind < 1.5) {
          // rotating glyph ring
          vec2 guv = vec2(uv.x * 3.0 + t * 0.06, uv.y);
          float g = texture2D(tGlyphs, guv).a;
          col = uTint * g * 2.8;
          alpha = g * 0.9 + 0.02;
        } else {
          // mega screen "video": sweeping gradients + glyph rows + pulse logo
          float rows = 6.0;
          vec2 guv = vec2(uv.x * 2.2 + t * (0.05 + 0.13 * h11(floor(uv.y * rows))), uv.y * rows);
          float g = texture2D(tGlyphs, vec2(guv.x, fract(guv.y))).a;
          float sweep = 0.5 + 0.5 * sin(uv.x * 4.0 - t * 1.7 + sin(uv.y * 9.0 + t));
          vec3 c2 = mix(uTint, vec3(1.0, 0.25, 0.55), 0.5 + 0.5 * sin(t * 0.23));
          col = c2 * (g * 1.3 + sweep * 0.25);
          float logoR = distance(uv, vec2(0.5, 0.52));
          float logo = smoothstep(0.16, 0.15, logoR) * smoothstep(0.10, 0.11, logoR);
          col += vec3(1.0) * logo * (0.7 + 0.6 * sin(t * 2.2));
          alpha = 0.72;
        }
        // scanlines + vertical fade + flicker
        float scan = 0.72 + 0.28 * sin(vW.y * 14.0 - t * 8.0);
        float edgeFade = smoothstep(0.0, 0.09, uv.x) * smoothstep(1.0, 0.91, uv.x)
                       * smoothstep(0.0, 0.09, uv.y) * smoothstep(1.0, 0.91, uv.y);
        float fl = 0.9 + 0.1 * sin(t * 37.0 + uv.y * 40.0);
        col *= scan * fl * 1.15;
        alpha *= edgeFade * scan;
        // fresnel-ish: brighter edge-on
        vec3 V = normalize(cameraPosition - vW);
        float fres = pow(1.0 - abs(dot(V, normalize(vN))), 2.0);
        col += uTint * fres * 0.35;
        // close-range rolloff: a wall-sized screen shouldn't bloom-blast the frame
        float dist = distance(vW, cameraPosition);
        col *= mix(1.0, 0.5, smoothstep(75.0, 25.0, dist));
        float fade = exp(-dist * uFogDensity * 1.2);
        gl_FragColor = vec4(col * fade, alpha * fade);
      }
    `,
  });
}

function beaconMaterial() {
  // billboarded glow points: streetlight heads, roof strobes, deck lights
  return new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uTime: GlobalUniforms.uTime, ...FogUniforms },
    vertexShader: /* glsl */`
      attribute vec3 aPos;
      attribute vec3 aCol;
      attribute vec2 aBlink; // rate, size
      varying vec3 vCol; varying vec2 vUv; varying float vBlink; varying vec3 vW;
      uniform float uTime;
      void main(){
        vUv = uv;
        float blink = 1.0;
        if (aBlink.x > 0.0) blink = 0.15 + 0.85 * pow(0.5 + 0.5 * sin(uTime * aBlink.x + aPos.x * 3.1 + aPos.z), 6.0);
        vBlink = blink;
        vCol = aCol;
        vW = aPos;
        vec4 mv = viewMatrix * vec4(aPos, 1.0);
        mv.xy += (uv - 0.5) * aBlink.y;
        gl_Position = projectionMatrix * mv;
      }
    `,
    fragmentShader: /* glsl */`
      varying vec3 vCol; varying vec2 vUv; varying float vBlink; varying vec3 vW;
      ${FOG_PARS}
      void main(){
        float d = length(vUv - 0.5) * 2.0;
        float g = exp(-d * d * 4.2) * (1.0 - smoothstep(0.7, 1.0, d));
        float fade = exp(-distance(vW, cameraPosition) * uFogDensity * 1.15);
        vec3 col = vCol * g * vBlink * fade;
        gl_FragColor = vec4(col, g * vBlink * fade);
      }
    `,
  });
}

function shaftMaterial() {
  // vertical light shafts hanging from streetlight heads: cheap volumetric cue
  return new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uTime: GlobalUniforms.uTime, ...FogUniforms },
    vertexShader: /* glsl */`
      attribute vec3 aPos;
      attribute float aWarm;
      varying vec2 vUv; varying float vFade; varying float vWarm;
      void main(){
        vUv = uv; vWarm = aWarm;
        vec3 toCam = cameraPosition - aPos;
        vec3 right = normalize(cross(vec3(0.0, 1.0, 0.0), normalize(toCam)) + vec3(1e-4, 0.0, 0.0));
        float w = 2.8, h = 8.4;
        vec3 wp = aPos + right * (uv.x - 0.5) * w - vec3(0.0, 1.0 - uv.y, 0.0) * h;
        float d = distance(aPos, cameraPosition);
        vFade = (1.0 - smoothstep(70.0, 300.0, d)) * smoothstep(3.0, 14.0, d);
        gl_Position = projectionMatrix * viewMatrix * vec4(wp, 1.0);
      }
    `,
    fragmentShader: /* glsl */`
      varying vec2 vUv; varying float vFade; varying float vWarm;
      uniform float uTime;
      void main(){
        float x = abs(vUv.x - 0.5) * 2.0;
        float core = exp(-x * x * 5.0);
        float fall = pow(vUv.y, 2.4);
        float flick = 0.88 + 0.12 * sin(uTime * 6.0 + vUv.y * 26.0);
        vec3 col = mix(vec3(0.45, 0.75, 1.0), vec3(1.0, 0.72, 0.4), vWarm);
        float a = core * fall * 0.16 * vFade * flick;
        gl_FragColor = vec4(col * a * 2.2, a);
      }
    `,
  });
}

function groundMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: {
      uTime: GlobalUniforms.uTime,
      uRainAmt: GlobalUniforms.uRainAmt,
      uDynPos: GlobalUniforms.uDynPos,
      uDynCol: GlobalUniforms.uDynCol,
      tRefl: { value: null },
      uMirrorVP: { value: new THREE.Matrix4() },
      ...FogUniforms,
    },
    vertexShader: /* glsl */`
      varying vec3 vW;
      void main(){
        vec4 wp = modelMatrix * vec4(position, 1.0);
        vW = wp.xyz;
        gl_Position = projectionMatrix * viewMatrix * wp;
      }
    `,
    fragmentShader: /* glsl */`
      varying vec3 vW;
      uniform sampler2D tRefl;
      uniform mat4 uMirrorVP;
      uniform float uTime, uRainAmt;
      uniform vec4 uDynPos[4];
      uniform vec3 uDynCol[4];
      ${FOG_PARS}
      float h21(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7)))*43758.5453); }
      float vnoise(vec2 p){
        vec2 i = floor(p), f = fract(p);
        f = f*f*(3.0-2.0*f);
        return mix(mix(h21(i), h21(i+vec2(1,0)), f.x), mix(h21(i+vec2(0,1)), h21(i+vec2(1,1)), f.x), f.y);
      }
      float fbm(vec2 p){
        float a = 0.5, s = 0.0;
        for (int i=0;i<4;i++){ s += a * vnoise(p); p = p * 2.13 + 17.0; a *= 0.5; }
        return s;
      }
      // expanding rain rings -> normal xz perturbation
      vec2 ripple(vec2 p, float t){
        vec2 acc = vec2(0.0);
        for (int i = 0; i < 2; i++) {
          vec2 sp = p * (0.55 + float(i) * 0.31) + float(i) * 31.7;
          vec2 id = floor(sp), f = fract(sp) - 0.5;
          float rnd = h21(id + float(i) * 71.0);
          float ph = fract(t * (0.7 + rnd * 0.6) + rnd * 11.0);
          vec2 dc = f - (vec2(rnd, h21(id + 3.0)) - 0.5) * 0.6;
          float r = length(dc);
          float ring = sin((r - ph * 0.55) * 40.0) * exp(-r * 5.0) * (1.0 - ph) * step(r, ph * 0.6);
          acc += normalize(dc + 1e-4) * ring;
        }
        return acc;
      }
      void main(){
        vec2 p = vW.xz;
        float t = uTime;

        // ---- base asphalt
        float n0 = fbm(p * 0.13);
        float n1 = fbm(p * 0.55);
        vec3 alb = mix(vec3(0.012, 0.014, 0.02), vec3(0.028, 0.03, 0.038), n0);
        alb *= 0.8 + 0.4 * n1;
        float ax = abs(p.x);
        // sidewalk beyond curb: lighter slabs
        if (ax > 21.0) {
          float slab = step(0.06, fract(p.x * 0.33)) * step(0.06, fract(p.y * 0.0)); // placeholder keep
          alb = mix(vec3(0.03, 0.032, 0.04), vec3(0.045, 0.048, 0.06), n1) * (0.85 + 0.3 * slab);
        }

        // ---- markings (emissive-ish)
        vec3 emis = vec3(0.0);
        // curb guide lines (the canyon rails)
        float curb = smoothstep(0.34, 0.12, abs(ax - 25.6));
        emis += vec3(0.12, 0.75, 1.0) * curb * 1.6;
        float curb2 = smoothstep(0.22, 0.08, abs(ax - 21.0));
        emis += vec3(0.9) * curb2 * 0.10;
        // lane dashes
        float laneX = min(abs(ax - 7.0), abs(ax - 14.0));
        float dash = smoothstep(0.14, 0.05, laneX) * step(0.45, fract(vW.z * 0.14));
        emis += vec3(0.65, 0.7, 0.75) * dash * 0.28;
        // center amber
        float ctr = smoothstep(0.3, 0.1, ax);
        emis += vec3(1.0, 0.6, 0.15) * ctr * 0.16;
        // crosswalks at chunk seams
        float zc = fract(vW.z / ${L.toFixed(1)});
        float cross = step(zc, 0.045) * step(ax, 20.0) * step(0.4, fract(p.x * 0.8)) ;
        emis += vec3(0.8) * cross * 0.22 * (0.4 + 0.6 * n1);

        // ---- wet reflection
        float puddle = smoothstep(0.5, 0.78, fbm(p * 0.09 + 3.7));
        puddle = max(puddle, smoothstep(0.55, 0.9, fbm(p * 0.045 + 9.1)));
        vec2 rip = ripple(p, t) * (0.35 + 0.65 * uRainAmt);
        vec2 flow = vec2(vnoise(p * 0.7 + t * 0.35), vnoise(p * 0.7 - t * 0.29)) - 0.5;
        vec2 nrm = rip * 1.7 + flow * 0.22;

        vec3 V = normalize(cameraPosition - vW);
        float fres = pow(1.0 - max(V.y, 0.0), 3.0);
        float reflAmt = mix(0.09, 0.98, puddle) * mix(0.5, 1.0, fres);

        vec3 wpos = vW + vec3(nrm.x, 0.0, nrm.y) * (0.5 + 1.6 * puddle);
        vec4 mp = uMirrorVP * vec4(wpos, 1.0);
        vec2 ruv = mp.xy / mp.w * 0.5 + 0.5;
        float lod = mix(4.0, 0.0, puddle);
        vec3 refl = vec3(0.0);
        if (ruv.x > 0.0 && ruv.x < 1.0 && ruv.y > 0.0 && ruv.y < 1.0) {
          refl = textureLod(tRefl, ruv, lod).rgb;
          refl += textureLod(tRefl, ruv + vec2(0.0, 0.012), lod + 1.2).rgb * 0.6;
          refl += textureLod(tRefl, ruv + vec2(0.0, 0.03), lod + 2.2).rgb * 0.35;
          refl /= 1.95;
        }
        vec3 col = alb * (0.35 + 0.3 * puddle);
        col += refl * reflAmt * 1.15;
        // markings dim inside deep puddles (painted under water)
        col += emis * mix(1.0, 0.45, puddle);

        // ---- dynamic hero lights (taxi + pursuers) pooling on the street
        for (int i = 0; i < 4; i++) {
          float inten = uDynPos[i].w;
          if (inten > 0.001) {
            vec3 lp = uDynPos[i].xyz;
            vec3 dl = lp - vW;
            float d2 = dot(dl, dl);
            float att = inten / (1.0 + d2 * 0.02);
            // wet streak toward viewer
            vec3 H = normalize(normalize(dl) + V);
            float spec = pow(max(H.y, 0.0), 24.0 + 60.0 * puddle);
            col += uDynCol[i] * att * (0.12 + spec * (0.6 + 1.6 * puddle));
          }
        }

        col = cityFog(col, vW, cameraPosition);
        gl_FragColor = vec4(col, 1.0);
      }
    `,
  });
}

// ============================================================== chunks ======

const tmpM = new THREE.Matrix4();
const tmpP = new THREE.Vector3(), tmpQ = new THREE.Quaternion(), tmpS = new THREE.Vector3();
const YAXIS = new THREE.Vector3(0, 1, 0);

class Chunk {
  constructor(city) {
    this.city = city;
    this.group = new THREE.Group();
    const boxGeo = city.boxGeo, quadGeo = city.quadGeo;

    this.buildings = new THREE.InstancedMesh(boxGeo.clone(), city.buildingMat, 44);
    this.concrete = new THREE.InstancedMesh(boxGeo.clone(), city.concreteMat, 104);
    this.signs = new THREE.InstancedMesh(quadGeo.clone(), city.signMat, 64);
    for (const m of [this.buildings, this.concrete]) {
      m.geometry.setAttribute('aSeed', new THREE.InstancedBufferAttribute(new Float32Array(m.count), 1));
      m.geometry.setAttribute('aKind', new THREE.InstancedBufferAttribute(new Float32Array(m.count), 1));
    }
    const sg = this.signs.geometry;
    sg.setAttribute('aTile', new THREE.InstancedBufferAttribute(new Float32Array(64 * 4), 4));
    sg.setAttribute('aTint', new THREE.InstancedBufferAttribute(new Float32Array(64 * 3), 3));
    sg.setAttribute('aFlick', new THREE.InstancedBufferAttribute(new Float32Array(64 * 2), 2));
    for (const m of [this.buildings, this.concrete, this.signs]) {
      m.frustumCulled = false;
      m.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      this.group.add(m);
      m.layers.enable(1);
    }
    this.signs.layers.enable(1);
    this.holos = [];
    for (let i = 0; i < 3; i++) {
      const h = new THREE.Mesh(quadGeo, city.holoMatProto.clone());
      // rebind shared uniforms after clone
      h.material.uniforms.uTime = GlobalUniforms.uTime;
      for (const k in FogUniforms) h.material.uniforms[k] = FogUniforms[k];
      h.visible = false; h.frustumCulled = false;
      h.layers.enable(1);
      this.group.add(h); this.holos.push(h);
    }
    this.ring = new THREE.Mesh(city.ringGeo, city.holoMatProto.clone());
    this.ring.material.uniforms.uTime = GlobalUniforms.uTime;
    for (const k in FogUniforms) this.ring.material.uniforms[k] = FogUniforms[k];
    this.ring.material.uniforms.uKind.value = 1;
    this.ring.visible = false; this.ring.frustumCulled = false;
    this.ring.layers.enable(1);
    this.group.add(this.ring);

    this.obstacles = [];   // {min:{x,y,z}, max:{x,y,z}, kind, id}
    this.holoVolumes = []; // pass-through score volumes
    this.beacons = [];     // {x,y,z, r,g,b, rate, size}
    this.shafts = [];      // {x,y,z, warm} streetlight shaft anchors
    this.steam = [];       // {x,y,z, s}
    this.ci = -1;
  }

  build(ci) {
    this.ci = ci;
    // ARENA: periodic seeds make the canyon repeat every loopChunks chunks,
    // so the loop is visually seamless.
    const li = WORLD.loopChunks ? ((ci % WORLD.loopChunks) + WORLD.loopChunks) % WORLD.loopChunks : ci;
    const rng = mulberry32(li * 2654435761 + 12345);
    const z1 = -ci * L, z0 = z1 - L; // chunk covers [z0, z1)
    this.obstacles.length = 0; this.holoVolumes.length = 0;
    this.beacons.length = 0; this.steam.length = 0; this.shafts.length = 0;

    let bi = 0, ki = 0, si = 0;
    const B = this.buildings, C = this.concrete, S = this.signs;
    const bSeed = B.geometry.getAttribute('aSeed'), bKind = B.geometry.getAttribute('aKind');
    const cSeed = C.geometry.getAttribute('aSeed'), cKind = C.geometry.getAttribute('aKind');
    const sTile = S.geometry.getAttribute('aTile'), sTint = S.geometry.getAttribute('aTint'), sFlick = S.geometry.getAttribute('aFlick');

    const putBox = (mesh, x, y, z, sx, sy, sz, seed, kind, rotY = 0) => {
      const i = mesh === B ? bi++ : ki++;
      tmpP.set(x, y, z); tmpQ.setFromAxisAngle(YAXIS, rotY); tmpS.set(sx, sy, sz);
      tmpM.compose(tmpP, tmpQ, tmpS);
      mesh.setMatrixAt(i, tmpM);
      if (mesh === B) { bSeed.setX(i, seed); bKind.setX(i, kind); }
      else { cSeed.setX(i, seed); cKind.setX(i, kind); }
      return i;
    };
    const putSign = (x, y, z, w, h, rotY, tile, tint, flickStyle) => {
      if (si >= 64) return;
      tmpP.set(x, y, z); tmpQ.setFromAxisAngle(YAXIS, rotY); tmpS.set(w, h, 1);
      tmpM.compose(tmpP, tmpQ, tmpS);
      S.setMatrixAt(si, tmpM);
      const tc = this.city.atlas;
      const tx = (tile % tc.cols) / tc.cols, ty = 1 - (Math.floor(tile / tc.cols) + 1) / tc.rows;
      sTile.setXYZW(si, tx, ty, 1 / tc.cols, 1 / tc.rows);
      sTint.setXYZ(si, tint.r, tint.g, tint.b);
      sFlick.setXY(si, rng() * 40, flickStyle);
      si++;
    };

    const NEON = [
      new THREE.Color(0x37d5ff), new THREE.Color(0xff3d7f), new THREE.Color(0xffb54d),
      new THREE.Color(0x7dffc7), new THREE.Color(0xc27bff), new THREE.Color(0xff6b4d),
      new THREE.Color(0xfff06b),
    ];
    const signCol = () => NEON[Math.floor(rng() * NEON.length)];

    // ---------------- buildings, two rows per side
    for (const side of [-1, 1]) {
      // row 1 (canyon wall)
      let z = z0 + rng() * 4;
      while (z < z1 - 8) {
        const w = 18 + rng() * 20;           // along z
        const depth = 16 + rng() * 22;       // along x
        const face = WORLD.canyonHalf + rng() * 12;   // face distance
        const hCat = rng();
        const h = hCat < 0.42 ? 45 + rng() * 60 : hCat < 0.85 ? 105 + rng() * 90 : 200 + rng() * 120;
        const cx = side * (face + depth / 2);
        const cz = z + w / 2;
        const seed = rng() * 100;
        putBox(B, cx, h / 2, cz, depth, h, w, seed, 1);
        // stacked crown
        if (rng() < 0.4) {
          const ch = 15 + rng() * 40;
          putBox(B, cx + (rng() - 0.5) * 3 * side, h + ch / 2, cz, depth * (0.45 + rng() * 0.25), ch, w * (0.45 + rng() * 0.3), seed + 3, 0);
        }
        // antenna
        if (h > 100 && rng() < 0.7) {
          const ah = 10 + rng() * 22;
          const ax = cx + (rng() - 0.5) * depth * 0.5, az = cz + (rng() - 0.5) * w * 0.5;
          putBox(C, ax, h + ah / 2, az, 0.6, ah, 0.6, seed, 3);
          this.beacons.push({ x: ax, y: h + ah + 0.5, z: az, r: 1, g: 0.12, b: 0.1, rate: 2.1, size: 2.4 });
        } else if (h > 90) {
          this.beacons.push({ x: cx, y: h + 1, z: cz, r: 1, g: 0.12, b: 0.1, rate: 1.4, size: 2.0 });
        }
        // collision only matters near the corridor
        this.obstacles.push({
          min: { x: cx - depth / 2, y: 0, z: cz - w / 2 },
          max: { x: cx + depth / 2, y: h, z: cz + w / 2 },
          kind: 'tower', id: `b${ci}_${side}_${z.toFixed(0)}`,
        });

        // facade signs facing the street
        const nSigns = 1 + Math.floor(rng() * 3);
        for (let s = 0; s < nSigns; s++) {
          const sw = 4 + rng() * 8;
          const sh = sw * (0.5 + rng() * 0.5);
          const sy = 6 + rng() * Math.min(h - 12, 70);
          const sz = cz + (rng() - 0.5) * (w - sw);
          putSign(side * (face - 0.35), sy, sz, side > 0 ? -sw : sw, sh, side > 0 ? -Math.PI / 2 : Math.PI / 2, Math.floor(rng() * 32), signCol(), rng() < 0.16 ? 2 : rng() < 0.4 ? 1 : 0);
        }
        // vertical banner sign sticking out (readable flying down the canyon,
        // two back-to-back faces so it never shows mirrored text)
        if (rng() < 0.85) {
          const bw = 3.2 + rng() * 2.6, bh = 14 + rng() * 20;
          const sy = 8 + rng() * 30;
          const szz = cz + (rng() - 0.5) * w * 0.6;
          const tile = Math.floor(rng() * 32);
          const col = signCol();
          const flick = rng() < 0.2 ? 2 : 0;
          putSign(side * (face - 1.9), sy, szz - 0.03, bw, bh, 0, tile, col, flick);
          putSign(side * (face - 1.9), sy, szz + 0.03, bw, bh, Math.PI, tile, col, flick);
        }
        z += w + 3 + rng() * 7;
      }
      // row 2 (background mass)
      z = z0 + rng() * 10;
      while (z < z1 - 10) {
        const w = 24 + rng() * 26, depth = 22 + rng() * 26;
        const face = 78 + rng() * 40;
        const h = 90 + rng() * 190;
        const cx = side * (face + depth / 2), cz = z + w / 2;
        putBox(B, cx, h / 2, cz, depth, h, w, rng() * 100, 0);
        if (h > 150) this.beacons.push({ x: cx, y: h + 1, z: cz, r: 1, g: 0.12, b: 0.1, rate: 1.7, size: 2.2 });
        z += w + 6 + rng() * 10;
      }
    }

    // ---------------- side highway decks (twisting, longitudinal)
    const SEG = 8, segL = L / SEG;
    for (const side of [-1, 1]) {
      for (let s = 0; s < SEG; s++) {
        const zc = z0 + (s + 0.5) * segL;
        const xA = this.city.deckX(side, zc - segL / 2), xB = this.city.deckX(side, zc + segL / 2);
        const yA = this.city.deckY(side, zc - segL / 2), yB = this.city.deckY(side, zc + segL / 2);
        const xm = (xA + xB) / 2, ym = (yA + yB) / 2;
        const ang = Math.atan2(xB - xA, segL);
        const len = Math.hypot(segL, xB - xA) + 0.6;
        putBox(C, xm, ym, zc, 9.5, 1.1, len, rng() * 10, 0, -ang);
        // guardrails along both long edges (deck-local x = ±4.55 → world offset)
        const cax = Math.cos(ang), sax = Math.sin(ang);
        for (const rs of [-1, 1]) {
          putBox(C, xm + rs * 4.55 * cax, ym + 0.85, zc + rs * 4.55 * sax, 0.22, 0.8, len, rng() * 10, 4, -ang);
        }
        // deck obstacle (fat AABB approximation per segment, covers the rails)
        this.obstacles.push({
          min: { x: xm - 5.2, y: ym - 0.8, z: zc - segL / 2 },
          max: { x: xm + 5.2, y: ym + 1.35, z: zc + segL / 2 },
          kind: 'deck', id: `d${ci}_${side}_${s}`,
        });
      }
      // support pylon every chunk
      const zp = z0 + 30 + rng() * (L - 60);
      const px = this.city.deckX(side, zp), py = this.city.deckY(side, zp);
      putBox(C, px, py / 2, zp, 2.4, py, 2.4, rng() * 10, 1);
      this.obstacles.push({
        min: { x: px - 1.4, y: 0, z: zp - 1.4 },
        max: { x: px + 1.4, y: py, z: zp + 1.4 },
        kind: 'pylon', id: `p${ci}_${side}`,
      });
      this.beacons.push({ x: px, y: py + 1.4, z: zp, r: 0.2, g: 0.9, b: 1, rate: 3.2, size: 1.6 });
    }

    // ---------------- crossing deck (gameplay obstacle) + hanging sign
    this.crossDecks = [];
    if (rng() < 0.72) {
      const zc = z0 + 24 + rng() * (L - 48);
      const yc = [17, 24, 32, 41, 50][Math.floor(rng() * 5)];
      putBox(C, 0, yc, zc, 120, 1.2, 10, rng() * 10, 0); // spans the canyon along X
      this.obstacles.push({
        min: { x: -60, y: yc - 0.9, z: zc - 5.2 },
        max: { x: 60, y: yc + 0.9, z: zc + 5.2 },
        kind: 'deck', id: `x${ci}`,
      });
      this.crossDecks.push({ z: zc, y: yc });
      // pylon pair under it sometimes
      if (rng() < 0.6) {
        for (const px of [-12 - rng() * 6, 12 + rng() * 6]) {
          putBox(C, px, yc / 2, zc, 2.2, yc, 2.2, rng() * 10, 1);
          this.obstacles.push({
            min: { x: px - 1.3, y: 0, z: zc - 1.3 },
            max: { x: px + 1.3, y: yc, z: zc + 1.3 },
            kind: 'pylon', id: `xp${ci}_${px.toFixed(0)}`,
          });
        }
      }
      // hanging sign under deck
      putSign(0, yc - 2.6, zc - 5.4, 9, 3.4, 0, Math.floor(rng() * 32), signCol(), 1);
      this.beacons.push({ x: -55, y: yc + 1.6, z: zc, r: 0.2, g: 0.9, b: 1, rate: 2.6, size: 1.8 });
      this.beacons.push({ x: 55, y: yc + 1.6, z: zc, r: 0.2, g: 0.9, b: 1, rate: 2.6, size: 1.8 });
    }

    // ---------------- skybridge high up
    if (rng() < 0.4) {
      const zc = z0 + 20 + rng() * (L - 40);
      const yc = 58 + rng() * 34;
      putBox(C, 0, yc, zc, 92, 3.2, 5, rng() * 10, 2); // wall-to-wall along X
      this.obstacles.push({
        min: { x: -46, y: yc - 1.8, z: zc - 2.8 },
        max: { x: 46, y: yc + 1.8, z: zc + 2.8 },
        kind: 'bridge', id: `sb${ci}`,
      });
    }

    // ---------------- protruding solid billboard (collision) with bright sign face
    if (rng() < 0.65) {
      const side = rng() < 0.5 ? -1 : 1;
      const zc = z0 + 20 + rng() * (L - 40);
      const yc = 14 + rng() * 40;
      const bw = 10 + rng() * 8, bh = bw * 0.62;
      const bx = side * (WORLD.roadHalf - 2.2 - bw * 0.0);
      // frame juts from the wall into the canyon
      putBox(C, side * (WORLD.roadHalf + 2.5), yc, zc, 12, 1.0, 1.0, rng() * 10, 3, 0);
      putBox(C, bx, yc, zc, 0.7, bh, bw, rng() * 10, 3);
      putSign(bx - side * 0.6, yc, zc, side > 0 ? -bw : bw, bh, side > 0 ? -Math.PI / 2 : Math.PI / 2, Math.floor(rng() * 32), signCol(), 0);
      this.obstacles.push({
        min: { x: bx - 0.8, y: yc - bh / 2, z: zc - bw / 2 },
        max: { x: bx + 0.8, y: yc + bh / 2, z: zc + bw / 2 },
        kind: 'billboard', id: `bb${ci}`,
      });
    }

    // ---------------- street lights + steam vents + ground props
    for (let sl = 0; sl < 4; sl++) {
      const zc = z0 + (sl + 0.5) * (L / 4);
      for (const side of [-1, 1]) {
        const x = side * 20.4;
        putBox(C, x, 4.5, zc, 0.28, 9, 0.28, rng() * 10, 3);
        putBox(C, x - side * 1.6, 8.9, zc, 3.4, 0.22, 0.22, rng() * 10, 3);
        this.beacons.push({ x: x - side * 2.9, y: 8.7, z: zc, r: 1.0, g: 0.72, b: 0.4, rate: 0, size: 1.9 });
        this.shafts.push({ x: x - side * 2.9, y: 8.5, z: zc, warm: rng() < 0.75 ? 1 : 0 });
      }
    }
    for (let sv = 0; sv < 4 + Math.floor(rng() * 3); sv++) {
      // vents hug the curbs and sidewalks where the pipes run
      const side = rng() < 0.5 ? -1 : 1;
      this.steam.push({
        x: side * (15 + rng() * 9), y: 0.3, z: z0 + rng() * L,
        s: 1.1 + rng() * 1.8,
      });
    }
    if (rng() < 0.35) { // median grate
      this.steam.push({ x: (rng() - 0.5) * 6, y: 0.3, z: z0 + rng() * L, s: 1.0 + rng() * 1.2 });
    }
    if (rng() < 0.5) { // rooftop steam
      this.steam.push({ x: (rng() < 0.5 ? -1 : 1) * (30 + rng() * 14), y: 46 + rng() * 40, z: z0 + rng() * L, s: 2.0 + rng() * 2 });
    }

    // ---------------- holograms (pass-through volumes)
    let hi = 0;
    if (rng() < 0.8) { // big floating holo billboard over the street
      const h = this.holos[hi++];
      const w = 16 + rng() * 12, hh = w * 0.55;
      const xc = (rng() - 0.5) * 24;
      const yc = 26 + rng() * 42;
      const zc = z0 + 20 + rng() * (L - 40);
      h.position.set(xc, yc, zc);
      h.rotation.set(0, (rng() - 0.5) * 0.7, 0);
      h.scale.set(w, hh, 1);
      h.material.uniforms.uKind.value = 0;
      h.material.uniforms.uSeed.value = rng() * 10;
      h.material.uniforms.uTint.value = signCol();
      h.material.uniforms.uPanel.value = 1;
      h.material.blending = THREE.NormalBlending;
      const tc = this.city.atlas;
      const tile = Math.floor(rng() * 32);
      h.material.uniforms.uTile.value.set((tile % tc.cols) / tc.cols, 1 - (Math.floor(tile / tc.cols) + 1) / tc.rows, 1 / tc.cols, 1 / tc.rows);
      h.visible = true;
      h.userData.baseY = yc; h.userData.bobAmp = 0.8 + rng() * 0.8; h.userData.bobRate = 0.4 + rng() * 0.5;
      this.holoVolumes.push({
        min: { x: xc - w / 2, y: yc - hh / 2, z: zc - 2 },
        max: { x: xc + w / 2, y: yc + hh / 2, z: zc + 2 },
        id: `h${ci}_a`,
      });
    }
    if (rng() < 0.5) { // mega screen on a wall
      const h = this.holos[hi++];
      const side = rng() < 0.5 ? -1 : 1;
      const w = 24 + rng() * 14, hh = w * 0.6;
      const face = WORLD.canyonHalf - 0.5;
      const zc = z0 + 30 + rng() * (L - 60);
      h.position.set(side * face, 22 + rng() * 30, zc);
      h.rotation.set(0, side > 0 ? -Math.PI / 2 : Math.PI / 2, 0);
      h.scale.set(w, hh, 1);
      h.material.uniforms.uKind.value = 2;
      h.material.uniforms.uSeed.value = rng() * 10;
      h.material.uniforms.uTint.value = signCol();
      h.material.uniforms.uPanel.value = 0;
      h.material.blending = THREE.AdditiveBlending;
      h.visible = true;
      h.userData.baseY = h.position.y; h.userData.bobAmp = 0; h.userData.bobRate = 0;
    }
    for (; hi < this.holos.length; hi++) this.holos[hi].visible = false;

    // glyph ring around a spire
    if (rng() < 0.45) {
      const side = rng() < 0.5 ? -1 : 1;
      const x = side * (WORLD.canyonHalf + 14 + rng() * 12);
      const y = 40 + rng() * 55, zc = z0 + rng() * L;
      this.ring.position.set(x, y, zc);
      this.ring.scale.setScalar(7 + rng() * 8);
      this.ring.material.uniforms.uSeed.value = rng() * 10;
      this.ring.material.uniforms.uTint.value = signCol();
      this.ring.visible = true;
      this.ring.userData.spin = (rng() < 0.5 ? -1 : 1) * (0.1 + rng() * 0.2);
    } else this.ring.visible = false;

    // finalize instanced buffers
    B.count = bi; C.count = ki; S.count = si;
    B.instanceMatrix.needsUpdate = true;
    C.instanceMatrix.needsUpdate = true;
    S.instanceMatrix.needsUpdate = true;
    bSeed.needsUpdate = bKind.needsUpdate = true;
    cSeed.needsUpdate = cKind.needsUpdate = true;
    sTile.needsUpdate = sTint.needsUpdate = sFlick.needsUpdate = true;
  }

  animate(time) {
    for (const h of this.holos) {
      if (h.visible && h.userData.bobRate) {
        h.position.y = h.userData.baseY + Math.sin(time * h.userData.bobRate + h.userData.baseY) * h.userData.bobAmp;
      }
    }
    if (this.ring.visible) this.ring.rotation.y = time * this.ring.userData.spin;
  }
}

// ================================================================ city ======

export class City {
  constructor(scene) {
    this.scene = scene;
    this.atlas = makeSignAtlas();
    this.glyphs = makeGlyphStrip();

    this.boxGeo = new THREE.BoxGeometry(1, 1, 1);
    this.quadGeo = new THREE.PlaneGeometry(1, 1);
    this.ringGeo = new THREE.CylinderGeometry(1, 1, 0.34, 40, 1, true);

    this.buildingMat = buildingMaterial();
    this.concreteMat = concreteMaterial();
    this.signMat = signMaterial(this.atlas);
    this.holoMatProto = holoMaterial(this.atlas, this.glyphs);
    this.groundMat = groundMaterial();
    this.beaconMat = beaconMaterial();

    // ground plane follows the camera
    this.ground = new THREE.Mesh(new THREE.PlaneGeometry(560, 2200, 1, 1), this.groundMat);
    this.ground.rotation.x = -Math.PI / 2;
    this.ground.frustumCulled = false;
    scene.add(this.ground);

    // far skyline (instanced, wraps around camera)
    this.skyline = new THREE.InstancedMesh(this.boxGeo, this.buildingMat, 170);
    this.skyline.frustumCulled = false;
    {
      const g = this.skyline.geometry = this.skyline.geometry.clone();
      g.setAttribute('aSeed', new THREE.InstancedBufferAttribute(new Float32Array(170), 1));
      g.setAttribute('aKind', new THREE.InstancedBufferAttribute(new Float32Array(170), 1));
      const rng = mulberry32(777);
      this.skySpots = [];
      for (let i = 0; i < 170; i++) {
        const side = i % 2 ? -1 : 1;
        const x = side * (170 + rng() * 420);
        const w = 40 + rng() * 60, d = 40 + rng() * 60;
        const h = 120 + rng() * 260;
        this.skySpots.push({ x, w, d, h, z0: (rng() - 0.5) * 3000, seed: rng() * 100 });
        g.getAttribute('aSeed').setX(i, rng() * 100);
        g.getAttribute('aKind').setX(i, 0);
      }
      this.skyline.layers.enable(1);
      scene.add(this.skyline);
    }

    // beacons (global instanced billboards)
    this.beaconCap = 420;
    this.beaconGeo = new THREE.InstancedBufferGeometry();
    this.beaconGeo.index = this.quadGeo.index;
    this.beaconGeo.setAttribute('position', this.quadGeo.getAttribute('position'));
    this.beaconGeo.setAttribute('uv', this.quadGeo.getAttribute('uv'));
    this.beaconGeo.setAttribute('aPos', new THREE.InstancedBufferAttribute(new Float32Array(this.beaconCap * 3), 3));
    this.beaconGeo.setAttribute('aCol', new THREE.InstancedBufferAttribute(new Float32Array(this.beaconCap * 3), 3));
    this.beaconGeo.setAttribute('aBlink', new THREE.InstancedBufferAttribute(new Float32Array(this.beaconCap * 2), 2));
    this.beaconMesh = new THREE.Mesh(this.beaconGeo, this.beaconMat);
    this.beaconMesh.frustumCulled = false;
    this.beaconMesh.layers.enable(1);
    scene.add(this.beaconMesh);

    // streetlight shafts (same rebuild cadence as beacons)
    this.shaftCap = 128;
    this.shaftGeo = new THREE.InstancedBufferGeometry();
    this.shaftGeo.index = this.quadGeo.index;
    this.shaftGeo.setAttribute('position', this.quadGeo.getAttribute('position'));
    this.shaftGeo.setAttribute('uv', this.quadGeo.getAttribute('uv'));
    this.shaftGeo.setAttribute('aPos', new THREE.InstancedBufferAttribute(new Float32Array(this.shaftCap * 3), 3));
    this.shaftGeo.setAttribute('aWarm', new THREE.InstancedBufferAttribute(new Float32Array(this.shaftCap), 1));
    this.shaftMesh = new THREE.Mesh(this.shaftGeo, shaftMaterial());
    this.shaftMesh.frustumCulled = false;
    this.shaftMesh.renderOrder = 12;
    scene.add(this.shaftMesh);

    // chunk ring buffer
    this.chunks = [];
    for (let i = 0; i < WORLD.chunkCount + 2; i++) {
      const c = new Chunk(this);
      this.chunks.push(c);
      scene.add(c.group);
      c.build(i - 1 < 0 ? 0 : i - 1);
    }
    this._beaconsDirty = true;
    this.frontCi = 0;
  }

  // decks weave gently; inner edge stays ≥ ~10m from canyon center so the
  // attract camera (|x| ≤ 9.5) never clips them and the flight path pinches fairly
  deckX(side, z) { return side * 21.5 + Math.sin(z * 0.0052 + side * 2.0) * 5.0 + Math.sin(z * 0.013 + side * 5.0) * 1.6; }
  deckY(side, z) { return (side < 0 ? 13 : 31) + Math.sin(z * 0.003 + side) * (side < 0 ? 3.0 : 5.5); }

  update(camZ, time) {
    // required chunk window
    const front = Math.max(0, Math.floor(-camZ / L) - 2);
    const n = this.chunks.length;
    for (let k = 0; k < n; k++) {
      const ci = front + k;
      const slot = ci % n;
      if (this.chunks[slot].ci !== ci) {
        this.chunks[slot].build(ci);
        this._beaconsDirty = true;
      }
      this.chunks[slot].animate(time);
    }

    // ground follows (markings are world-space)
    this.ground.position.z = Math.round(camZ / 8) * 8 - 900;

    // far skyline wrap
    {
      const arr = this.skyline;
      for (let i = 0; i < this.skySpots.length; i++) {
        const s = this.skySpots[i];
        let z = s.z0 + camZ - (((s.z0 + camZ) % 3000 + 4500) % 3000 - 1500) * 0 ; // placeholder
        // wrap into [camZ-2200, camZ+800]
        z = s.z0;
        const rel = ((z - (camZ - 2200)) % 3000 + 3000) % 3000;
        z = camZ - 2200 + rel;
        tmpP.set(s.x, s.h / 2, z); tmpQ.identity(); tmpS.set(s.d, s.h, s.w);
        tmpM.compose(tmpP, tmpQ, tmpS);
        arr.setMatrixAt(i, tmpM);
      }
      arr.instanceMatrix.needsUpdate = true;
    }

    if (this._beaconsDirty) this._rebuildBeacons();
  }

  _rebuildBeacons() {
    this._beaconsDirty = false;
    const aPos = this.beaconGeo.getAttribute('aPos');
    const aCol = this.beaconGeo.getAttribute('aCol');
    const aBlink = this.beaconGeo.getAttribute('aBlink');
    let i = 0;
    for (const c of this.chunks) {
      for (const b of c.beacons) {
        if (i >= this.beaconCap) break;
        aPos.setXYZ(i, b.x, b.y, b.z);
        aCol.setXYZ(i, b.r * 2.0, b.g * 2.0, b.b * 2.0);
        aBlink.setXY(i, b.rate, b.size);
        i++;
      }
    }
    this.beaconGeo.instanceCount = i;
    aPos.needsUpdate = aCol.needsUpdate = aBlink.needsUpdate = true;

    const sPos = this.shaftGeo.getAttribute('aPos');
    const sWarm = this.shaftGeo.getAttribute('aWarm');
    let si = 0;
    for (const c of this.chunks) {
      for (const s of c.shafts) {
        if (si >= this.shaftCap) break;
        sPos.setXYZ(si, s.x, s.y, s.z);
        sWarm.setX(si, s.warm);
        si++;
      }
    }
    this.shaftGeo.instanceCount = si;
    sPos.needsUpdate = sWarm.needsUpdate = true;
  }

  // gameplay queries -----------------------------------------------------
  obstaclesNear(zMin, zMax) {
    const out = [];
    for (const c of this.chunks) {
      const cz1 = -c.ci * L, cz0 = cz1 - L;
      if (cz1 < zMin || cz0 > zMax) continue;
      for (const o of c.obstacles) out.push(o);
      for (const h of c.holoVolumes) { h.isHolo = true; out.push(h); }
    }
    return out;
  }
  steamSpots() {
    const out = [];
    for (const c of this.chunks) for (const s of c.steam) out.push(s);
    return out;
  }
  crossDeckList() {
    const out = [];
    for (const c of this.chunks) if (c.crossDecks) for (const d of c.crossDecks) out.push(d);
    return out;
  }
}
