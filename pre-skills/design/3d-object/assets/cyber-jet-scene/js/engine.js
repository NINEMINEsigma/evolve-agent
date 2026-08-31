import * as THREE from 'three';

// Engine: WebGL2 renderer + custom HDR post chain.
// scene RT (halffloat) -> bright pass -> mip down/up bloom -> composite
// (ACES grade, lens rain droplets, chromatic aberration, vignette, grain,
// radial boost warp) -> FXAA -> canvas.
// Also owns the planar-reflection pass used by the wet street.

const BRIGHT_FRAG = /* glsl */`
  precision highp float;
  varying vec2 vUv;
  uniform sampler2D tColor;
  uniform float uThreshold, uKnee;
  void main(){
    vec3 c = texture2D(tColor, vUv).rgb;
    // NaN / firefly guard: a single bad pixel becomes a giant black square after blur
    c = clamp(c, vec3(0.0), vec3(48.0));
    if (any(isnan(c)) || any(isinf(c))) c = vec3(0.0);
    float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
    float soft = clamp((l - uThreshold + uKnee) / (2.0 * uKnee), 0.0, 1.0);
    float w = max(soft * soft, step(uThreshold, l)) * l / max(l, 1e-4);
    // luminance-weighted average damp
    gl_FragColor = vec4(c * w / (1.0 + l * 0.35), 1.0);
  }
`;

const DOWN_FRAG = /* glsl */`
  precision highp float;
  varying vec2 vUv;
  uniform sampler2D tColor;
  uniform vec2 uTexel;
  void main(){
    vec3 c = texture2D(tColor, vUv).rgb * 4.0;
    c += texture2D(tColor, vUv + uTexel * vec2(-1.0, -1.0)).rgb;
    c += texture2D(tColor, vUv + uTexel * vec2( 1.0, -1.0)).rgb;
    c += texture2D(tColor, vUv + uTexel * vec2(-1.0,  1.0)).rgb;
    c += texture2D(tColor, vUv + uTexel * vec2( 1.0,  1.0)).rgb;
    gl_FragColor = vec4(c / 8.0, 1.0);
  }
`;

const UP_FRAG = /* glsl */`
  precision highp float;
  varying vec2 vUv;
  uniform sampler2D tColor;   // lower mip
  uniform sampler2D tAdd;     // same-size previous
  uniform vec2 uTexel;
  uniform float uMix;
  void main(){
    vec3 c = vec3(0.0);
    c += texture2D(tColor, vUv + uTexel * vec2(-1.0, -1.0)).rgb;
    c += texture2D(tColor, vUv + uTexel * vec2( 0.0, -1.0)).rgb * 2.0;
    c += texture2D(tColor, vUv + uTexel * vec2( 1.0, -1.0)).rgb;
    c += texture2D(tColor, vUv + uTexel * vec2(-1.0,  0.0)).rgb * 2.0;
    c += texture2D(tColor, vUv).rgb * 4.0;
    c += texture2D(tColor, vUv + uTexel * vec2( 1.0,  0.0)).rgb * 2.0;
    c += texture2D(tColor, vUv + uTexel * vec2(-1.0,  1.0)).rgb;
    c += texture2D(tColor, vUv + uTexel * vec2( 0.0,  1.0)).rgb * 2.0;
    c += texture2D(tColor, vUv + uTexel * vec2( 1.0,  1.0)).rgb;
    gl_FragColor = vec4(c / 16.0 + texture2D(tAdd, vUv).rgb * uMix, 1.0);
  }
`;

const COMPOSITE_FRAG = /* glsl */`
  precision highp float;
  varying vec2 vUv;
  uniform sampler2D tColor, tBloom;
  uniform float uTime, uBloom, uExposure, uRain, uWarp, uFlash, uGrain, uAspect;
  uniform vec2 uRes;

  // ---- lens rain -------------------------------------------------------
  float n21(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

  // running drips + static droplets; returns uv offset (xy) and mask (z)
  vec3 lensRain(vec2 uv, float t){
    vec3 acc = vec3(0.0);
    // layer 1+2: trails running down — few big hero drops, not microdots
    for (int L = 0; L < 2; L++) {
      float fl = float(L);
      vec2 gridN = vec2(11.0, 2.6) * (1.0 + fl * 0.72);
      vec2 st = uv * gridN;
      st.y += t * (0.21 + fl * 0.13);
      vec2 id = floor(st);
      float rnd = n21(id + fl * 17.0);
      vec2 f = fract(st) - 0.5;
      // per-cell drop wanders in x, accelerates in y
      float dx = (rnd - 0.5) * 0.7;
      dx += sin(t * (1.5 + rnd * 2.0) + rnd * 40.0) * 0.12;
      float wob = fract(t * (0.4 + rnd * 0.4) + rnd * 8.0);
      float dy = (wob * wob - 0.5) * 0.8;
      vec2 dp = vec2(f.x - dx, (f.y - dy) * (gridN.x / gridN.y) * 0.25);
      float drop = smoothstep(0.15, 0.05, length(dp));
      // thin trail above the drop
      float trail = smoothstep(0.055, 0.02, abs(f.x - dx)) *
                    smoothstep(0.0, 0.5, (f.y - dy)) * smoothstep(1.0, 0.6, wob) * 0.35;
      float on = step(rnd, 0.5); // some cells empty
      acc.xy += (drop * dp * -6.0 + vec2(0.0, trail * -0.4)) * on;
      acc.z += (drop + trail * 0.5) * on;
    }
    // layer 3: small static condensation
    {
      vec2 st = uv * vec2(38.0, 26.0);
      vec2 id = floor(st);
      float rnd = n21(id * 1.7);
      vec2 f = fract(st) - 0.5;
      vec2 dp = f - (vec2(rnd, n21(id + 4.0)) - 0.5) * 0.6;
      float drop = smoothstep(0.12, 0.04, length(dp)) * step(rnd, 0.3);
      float blink = 0.75 + 0.25 * sin(rnd * 100.0 + t * 0.3);
      acc.xy += drop * dp * -2.4 * blink;
      acc.z += drop * 0.6;
    }
    return acc;
  }

  vec3 aces(vec3 x){
    return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
  }

  void main(){
    vec2 uv = vUv;
    vec2 cc = uv - 0.5;
    float r2 = dot(cc, cc);

    // rain on the lens
    vec3 rain = lensRain(uv * vec2(uAspect, 1.0), uTime) * uRain;
    vec2 ruv = uv + rain.xy * 0.021;

    // boost warp: radial streak toward center
    vec3 col = vec3(0.0);
    if (uWarp > 0.003) {
      vec2 dir = cc * uWarp * 0.05;
      col  = texture2D(tColor, ruv).rgb * 0.4;
      col += texture2D(tColor, ruv - dir).rgb * 0.3;
      col += texture2D(tColor, ruv - dir * 2.0).rgb * 0.2;
      col += texture2D(tColor, ruv - dir * 3.0).rgb * 0.1;
    } else {
      col = texture2D(tColor, ruv).rgb;
    }

    // chromatic aberration, stronger at edges & under droplets, muted while warping
    float ca = (0.0016 + rain.z * 0.005) * (0.6 + r2 * 2.2) * (1.0 - uWarp * 0.7);
    col.r = texture2D(tColor, ruv + cc * ca).r;
    col.b = texture2D(tColor, ruv - cc * ca).b;

    vec3 bloom = texture2D(tBloom, ruv).rgb;
    col += bloom * uBloom * (1.0 + rain.z * 1.4);

    col *= uExposure;
    // droplets catch city glow
    col += bloom * rain.z * 0.75;

    col = aces(col);
    // grade: teal shadows, mild lift
    col = pow(col, vec3(1.06, 1.0, 0.94));
    col = mix(col, col * vec3(0.86, 1.0, 1.1), 0.22 * (1.0 - col));
    col += uFlash * vec3(1.0, 0.97, 0.9);

    // vignette
    col *= 1.0 - smoothstep(0.18, 0.62, r2) * 0.42;
    // grain
    float g = n21(uv * uRes.xy * 0.5 + fract(uTime * 13.7) * 91.0) - 0.5;
    col += g * uGrain;

    // sRGB encode
    col = clamp(col, 0.0, 1.0);
    col = mix(col * 12.92, 1.055 * pow(col, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, col));
    gl_FragColor = vec4(col, 1.0);
  }
`;

// compact FXAA (keeps thin neon from crawling)
const FXAA_FRAG = /* glsl */`
  precision highp float;
  varying vec2 vUv;
  uniform sampler2D tColor;
  uniform vec2 uTexel;
  float luma(vec3 c){ return dot(c, vec3(0.299, 0.587, 0.114)); }
  void main(){
    vec3 rgbNW = texture2D(tColor, vUv + uTexel * vec2(-1.0, -1.0)).rgb;
    vec3 rgbNE = texture2D(tColor, vUv + uTexel * vec2( 1.0, -1.0)).rgb;
    vec3 rgbSW = texture2D(tColor, vUv + uTexel * vec2(-1.0,  1.0)).rgb;
    vec3 rgbSE = texture2D(tColor, vUv + uTexel * vec2( 1.0,  1.0)).rgb;
    vec3 rgbM  = texture2D(tColor, vUv).rgb;
    float lNW = luma(rgbNW), lNE = luma(rgbNE), lSW = luma(rgbSW), lSE = luma(rgbSE), lM = luma(rgbM);
    float lMin = min(lM, min(min(lNW, lNE), min(lSW, lSE)));
    float lMax = max(lM, max(max(lNW, lNE), max(lSW, lSE)));
    vec2 dir = vec2(-((lNW + lNE) - (lSW + lSE)), ((lNW + lSW) - (lNE + lSE)));
    float dirReduce = max((lNW + lNE + lSW + lSE) * 0.03125, 1.0 / 128.0);
    float rcp = 1.0 / (min(abs(dir.x), abs(dir.y)) + dirReduce);
    dir = clamp(dir * rcp, -8.0, 8.0) * uTexel;
    vec3 a = 0.5 * (texture2D(tColor, vUv + dir * (1.0/3.0 - 0.5)).rgb +
                    texture2D(tColor, vUv + dir * (2.0/3.0 - 0.5)).rgb);
    vec3 b = a * 0.5 + 0.25 * (texture2D(tColor, vUv + dir * -0.5).rgb +
                               texture2D(tColor, vUv + dir *  0.5).rgb);
    float lB = luma(b);
    gl_FragColor = vec4((lB < lMin || lB > lMax) ? a : b, 1.0);
  }
`;

const QUAD_VERT = /* glsl */`
  varying vec2 vUv;
  void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }
`;

export class Engine {
  constructor(canvas) {
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({
      canvas, antialias: false, alpha: false, stencil: false,
      powerPreference: 'high-performance',
    });
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.NoToneMapping;
    this.renderer.autoClear = true;
    this.renderer.debug.checkShaderErrors = true;

    this.scale = 1.2;
    this.reflScale = 0.42;
    this.bloomMips = 6;
    this.useFxaa = true;

    this.time = 0;
    this.params = { rain: 0.55, bloom: 0.75, exposure: 1.0, warp: 0, flash: 0, grain: 0.025 };

    this._quadScene = new THREE.Scene();
    this._quadCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    this._quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), null);
    this._quad.frustumCulled = false;
    this._quadScene.add(this._quad);

    const uniforms = (o) => o;
    this.brightMat = new THREE.ShaderMaterial({
      vertexShader: QUAD_VERT, fragmentShader: BRIGHT_FRAG, depthTest: false, depthWrite: false,
      uniforms: uniforms({ tColor: { value: null }, uThreshold: { value: 1.2 }, uKnee: { value: 0.55 } }),
    });
    this.downMat = new THREE.ShaderMaterial({
      vertexShader: QUAD_VERT, fragmentShader: DOWN_FRAG, depthTest: false, depthWrite: false,
      uniforms: uniforms({ tColor: { value: null }, uTexel: { value: new THREE.Vector2() } }),
    });
    this.upMat = new THREE.ShaderMaterial({
      vertexShader: QUAD_VERT, fragmentShader: UP_FRAG, depthTest: false, depthWrite: false,
      uniforms: uniforms({ tColor: { value: null }, tAdd: { value: null }, uTexel: { value: new THREE.Vector2() }, uMix: { value: 0.85 } }),
    });
    this.compMat = new THREE.ShaderMaterial({
      vertexShader: QUAD_VERT, fragmentShader: COMPOSITE_FRAG, depthTest: false, depthWrite: false,
      uniforms: uniforms({
        tColor: { value: null }, tBloom: { value: null },
        uTime: { value: 0 }, uBloom: { value: 0.75 }, uExposure: { value: 1.0 },
        uRain: { value: 0.55 }, uWarp: { value: 0 }, uFlash: { value: 0 },
        uGrain: { value: 0.03 }, uAspect: { value: 16 / 9 }, uRes: { value: new THREE.Vector2(1920, 1080) },
      }),
    });
    this.fxaaMat = new THREE.ShaderMaterial({
      vertexShader: QUAD_VERT, fragmentShader: FXAA_FRAG, depthTest: false, depthWrite: false,
      uniforms: uniforms({ tColor: { value: null }, uTexel: { value: new THREE.Vector2() } }),
    });

    this.mirrorCam = new THREE.PerspectiveCamera();
    this.mirrorCam.layers.set(1);
    this.mirrorVP = new THREE.Matrix4();

    this._targets = [];
    this.resize();
    window.addEventListener('resize', () => this.resize());
  }

  applyQuality(q) {
    this.scale = q.scale; this.reflScale = q.reflScale;
    this.bloomMips = q.bloomMips; this.useFxaa = q.fxaa;
    this.resize();
  }

  resize() {
    const w = this.canvas.clientWidth || window.innerWidth;
    const h = this.canvas.clientHeight || window.innerHeight;
    // internal render scale relative to CSS pixels, capped
    let rw = Math.round(w * this.scale), rh = Math.round(h * this.scale);
    const maxPix = 2900 * 1650;
    if (rw * rh > maxPix) { const k = Math.sqrt(maxPix / (rw * rh)); rw = Math.round(rw * k); rh = Math.round(rh * k); }
    this.renderer.setPixelRatio(1);
    this.renderer.setSize(rw, rh, false);
    this.canvas.style.width = '100%';
    this.canvas.style.height = '100%';

    for (const t of this._targets) t.dispose();
    this._targets = [];
    const mk = (sw, sh, opts = {}) => {
      const t = new THREE.WebGLRenderTarget(Math.max(2, sw), Math.max(2, sh), {
        type: THREE.HalfFloatType, format: THREE.RGBAFormat,
        minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter,
        depthBuffer: opts.depth ?? false, stencilBuffer: false, ...opts,
      });
      this._targets.push(t);
      return t;
    };

    this.sceneRT = mk(rw, rh, { depth: true });
    this.sceneRT.depthTexture = new THREE.DepthTexture(rw, rh, THREE.UnsignedIntType);

    this.down = []; this.up = [];
    let bw = rw >> 1, bh = rh >> 1;
    for (let i = 0; i < this.bloomMips; i++) {
      this.down.push(mk(bw, bh));
      bw = Math.max(2, bw >> 1); bh = Math.max(2, bh >> 1);
    }
    for (let i = 0; i < this.bloomMips - 1; i++) {
      const s = this.down[this.bloomMips - 2 - i];
      this.up.push(mk(s.width, s.height));
    }
    this.ldrRT = mk(rw, rh, { type: THREE.UnsignedByteType });

    const rww = Math.max(64, Math.round(rw * this.reflScale));
    const rhh = Math.max(64, Math.round(rh * this.reflScale));
    this.reflRT = new THREE.WebGLRenderTarget(rww, rhh, {
      type: THREE.HalfFloatType, format: THREE.RGBAFormat,
      minFilter: THREE.LinearMipmapLinearFilter, magFilter: THREE.LinearFilter,
      generateMipmaps: true, depthBuffer: true, stencilBuffer: false,
    });
    this._targets.push(this.reflRT);

    this.compMat.uniforms.uRes.value.set(rw, rh);
    this.compMat.uniforms.uAspect.value = rw / rh;
    this.width = rw; this.height = rh;
  }

  _blit(target, mat) {
    this._quad.material = mat;
    this.renderer.setRenderTarget(target);
    this.renderer.render(this._quadScene, this._quadCam);
  }

  // planar reflection about y=0; only layer-1 objects are drawn
  renderReflection(scene, camera) {
    const mc = this.mirrorCam;
    mc.fov = camera.fov; mc.aspect = camera.aspect;
    mc.near = camera.near; mc.far = camera.far;
    mc.updateProjectionMatrix();
    const p = camera.getWorldPosition(new THREE.Vector3());
    const q = camera.getWorldQuaternion(new THREE.Quaternion());
    const fwd = new THREE.Vector3(0, 0, -1).applyQuaternion(q);
    const up = new THREE.Vector3(0, 1, 0).applyQuaternion(q);
    mc.position.set(p.x, -p.y, p.z);
    const target = new THREE.Vector3(p.x + fwd.x, -(p.y + fwd.y), p.z + fwd.z);
    mc.up.set(up.x, -up.y, up.z);
    mc.lookAt(target);
    mc.updateMatrixWorld(true);
    this.mirrorVP.multiplyMatrices(mc.projectionMatrix, mc.matrixWorldInverse);

    this.renderer.setRenderTarget(this.reflRT);
    this.renderer.setClearColor(0x05070e, 1);
    this.renderer.clear(true, true, false);
    this.renderer.render(scene, mc);
  }

  render(scene, camera, dt) {
    this.time += dt;
    const p = this.params;

    // main scene
    this.renderer.setRenderTarget(this.sceneRT);
    this.renderer.setClearColor(0x05070e, 1);
    this.renderer.render(scene, camera);

    // bloom chain
    this.brightMat.uniforms.tColor.value = this.sceneRT.texture;
    this._blit(this.down[0], this.brightMat);
    for (let i = 1; i < this.bloomMips; i++) {
      this.downMat.uniforms.tColor.value = this.down[i - 1].texture;
      this.downMat.uniforms.uTexel.value.set(1 / this.down[i - 1].width, 1 / this.down[i - 1].height);
      this._blit(this.down[i], this.downMat);
    }
    let prev = this.down[this.bloomMips - 1];
    for (let i = 0; i < this.up.length; i++) {
      const dst = this.up[i];
      const skip = this.down[this.bloomMips - 2 - i];
      this.upMat.uniforms.tColor.value = prev.texture;
      this.upMat.uniforms.tAdd.value = skip.texture;
      this.upMat.uniforms.uTexel.value.set(1 / prev.width, 1 / prev.height);
      this._blit(dst, this.upMat);
      prev = dst;
    }

    // composite
    const cu = this.compMat.uniforms;
    cu.tColor.value = this.sceneRT.texture;
    cu.tBloom.value = prev.texture;
    cu.uTime.value = this.time;
    cu.uBloom.value = p.bloom; cu.uExposure.value = p.exposure;
    cu.uRain.value = p.rain; cu.uWarp.value = p.warp;
    cu.uFlash.value = p.flash; cu.uGrain.value = p.grain;

    if (this.useFxaa) {
      this._blit(this.ldrRT, this.compMat);
      this.fxaaMat.uniforms.tColor.value = this.ldrRT.texture;
      this.fxaaMat.uniforms.uTexel.value.set(1 / this.width, 1 / this.height);
      this._blit(null, this.fxaaMat);
    } else {
      this._blit(null, this.compMat);
    }
  }
}
