import * as THREE from 'three';
import { WORLD } from './config.js';
import { mulberry32, FogUniforms, FOG_PARS, GlobalUniforms } from './utils.js';
import { makeRobot, makeDrone, robotClipNames } from './assets.js';

const tmpM = new THREE.Matrix4(), tmpP = new THREE.Vector3(), tmpQ = new THREE.Quaternion(), tmpS = new THREE.Vector3();
const YAXIS = new THREE.Vector3(0, 1, 0);

// ----------------------------------------------------------- car bodies ----
function carBodyMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: { uTime: GlobalUniforms.uTime, ...FogUniforms },
    vertexShader: /* glsl */`
      attribute vec3 aTint;
      attribute float aSeed;
      varying vec3 vW, vN, vLocal, vTint; varying float vSeed;
      void main(){
        vTint = aTint; vSeed = aSeed; vLocal = position;
        #ifdef USE_INSTANCING
          vec4 wp = modelMatrix * instanceMatrix * vec4(position, 1.0);
          vN = normalize(mat3(instanceMatrix) * normal);
        #else
          vec4 wp = modelMatrix * vec4(position, 1.0); vN = normal;
        #endif
        vW = wp.xyz;
        gl_Position = projectionMatrix * viewMatrix * wp;
      }
    `,
    fragmentShader: /* glsl */`
      varying vec3 vW, vN, vLocal, vTint; varying float vSeed;
      ${FOG_PARS}
      void main(){
        vec3 n = normalize(vN);
        vec3 col = vTint * (0.25 + 0.35 * max(n.y, 0.0));
        // glass band
        float band = step(abs(vLocal.y - 0.12), 0.14) * step(abs(n.y), 0.5);
        col = mix(col, vec3(0.05, 0.09, 0.13), band * 0.85);
        // front / rear emissive strips
        float front = step(0.49, -vLocal.z);
        float rear = step(0.49, vLocal.z);
        float strip = step(abs(vLocal.y + 0.1), 0.09);
        vec3 emis = front * strip * vec3(1.0, 0.95, 0.8) * 3.2 + rear * strip * vec3(1.0, 0.08, 0.05) * 2.6;
        // roof beacon for taxis
        if (vSeed > 0.75 && vLocal.y > 0.48) emis += vec3(1.0, 0.7, 0.2) * 1.4;
        col += emis;
        col = cityFog(col, vW, cameraPosition);
        gl_FragColor = vec4(col, 1.0);
      }
    `,
  });
}

function glowMaterial() {
  // soft billboarded light blobs (headlights, taillights, strobes)
  return new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uTime: GlobalUniforms.uTime, ...FogUniforms },
    vertexShader: /* glsl */`
      attribute vec3 aPos;
      attribute vec4 aColS;   // rgb + size
      attribute float aBlink;
      varying vec3 vCol; varying vec2 vUv; varying vec3 vW;
      uniform float uTime;
      void main(){
        vUv = uv; vW = aPos;
        float blink = aBlink > 0.0 ? (0.1 + 0.9 * pow(0.5 + 0.5 * sin(uTime * aBlink + aPos.z), 8.0)) : 1.0;
        vCol = aColS.rgb * blink;
        vec4 mv = viewMatrix * vec4(aPos, 1.0);
        mv.xy += (uv - 0.5) * aColS.w;
        gl_Position = projectionMatrix * mv;
      }
    `,
    fragmentShader: /* glsl */`
      varying vec3 vCol; varying vec2 vUv; varying vec3 vW;
      ${FOG_PARS}
      void main(){
        float d = length(vUv - 0.5) * 2.0;
        float g = exp(-d * d * 5.0) * (1.0 - smoothstep(0.6, 1.0, d));
        float fade = exp(-distance(vW, cameraPosition) * uFogDensity * 1.1);
        gl_FragColor = vec4(vCol * g * fade, g * fade);
      }
    `,
  });
}

export class GlowPool {
  constructor(scene, cap) {
    this.cap = cap;
    const quad = new THREE.PlaneGeometry(1, 1);
    const g = new THREE.InstancedBufferGeometry();
    g.index = quad.index;
    g.setAttribute('position', quad.getAttribute('position'));
    g.setAttribute('uv', quad.getAttribute('uv'));
    g.setAttribute('aPos', new THREE.InstancedBufferAttribute(new Float32Array(cap * 3), 3));
    g.setAttribute('aColS', new THREE.InstancedBufferAttribute(new Float32Array(cap * 4), 4));
    g.setAttribute('aBlink', new THREE.InstancedBufferAttribute(new Float32Array(cap), 1));
    this.geo = g;
    this.mesh = new THREE.Mesh(g, glowMaterial());
    this.mesh.frustumCulled = false;
    this.mesh.layers.enable(1);
    scene.add(this.mesh);
    this.i = 0;
  }
  begin() { this.i = 0; }
  push(x, y, z, r, g, b, size, blink = 0) {
    if (this.i >= this.cap) return;
    const i = this.i++;
    this.geo.getAttribute('aPos').setXYZ(i, x, y, z);
    this.geo.getAttribute('aColS').setXYZW(i, r, g, b, size);
    this.geo.getAttribute('aBlink').setX(i, blink);
  }
  end() {
    this.geo.instanceCount = this.i;
    this.geo.getAttribute('aPos').needsUpdate = true;
    this.geo.getAttribute('aColS').needsUpdate = true;
    this.geo.getAttribute('aBlink').needsUpdate = true;
  }
}

// ------------------------------------------------------------------ rain ---
function makeRain(scene, count) {
  const quad = new THREE.PlaneGeometry(1, 1);
  const g = new THREE.InstancedBufferGeometry();
  g.index = quad.index;
  g.setAttribute('position', quad.getAttribute('position'));
  g.setAttribute('uv', quad.getAttribute('uv'));
  const rand = new Float32Array(count * 4);
  const rng = mulberry32(4242);
  for (let i = 0; i < count * 4; i++) rand[i] = rng();
  g.setAttribute('aRand', new THREE.InstancedBufferAttribute(rand, 4));
  g.instanceCount = count;

  const mat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: {
      uTime: GlobalUniforms.uTime,
      uRainAmt: GlobalUniforms.uRainAmt,
      uCamVel: { value: new THREE.Vector3() },
      uBox: { value: new THREE.Vector3(70, 46, 90) },
      ...FogUniforms,
    },
    vertexShader: /* glsl */`
      attribute vec4 aRand;
      varying vec2 vUv; varying float vFade;
      uniform float uTime, uRainAmt;
      uniform vec3 uCamVel, uBox;
      void main(){
        vUv = uv;
        float speed = 14.0 + aRand.z * 9.0;
        vec3 vel = vec3(2.2 + aRand.w * 1.5, -speed, 1.2);
        vec3 base = aRand.xyz * uBox;
        vec3 anchor = cameraPosition + vec3(0.0, 4.0, 0.0);
        vec3 p = mod(base + vel * uTime - anchor, uBox);
        p += anchor - uBox * 0.5;
        // hide a fraction of drops when rain is light
        float on = step(1.0 - uRainAmt, aRand.w * 0.999);
        // streak: stretch along apparent velocity (fall + camera motion)
        vec3 dir = normalize(vel - uCamVel * 0.8);
        vec3 viewFwd = normalize(p - cameraPosition);
        vec3 right = normalize(cross(viewFwd, dir));
        float len = speed * 0.062 * (1.0 + length(uCamVel) * 0.012);
        vec3 wp = p + right * (uv.x - 0.5) * 0.028 + dir * (uv.y - 0.5) * len;
        float d = distance(p, cameraPosition);
        vFade = on * (1.0 - smoothstep(28.0, 46.0, d)) * smoothstep(0.9, 3.2, d);
        gl_Position = projectionMatrix * viewMatrix * vec4(wp, 1.0);
      }
    `,
    fragmentShader: /* glsl */`
      varying vec2 vUv; varying float vFade;
      void main(){
        float a = (1.0 - abs(vUv.x - 0.5) * 2.0) * sin(vUv.y * 3.14159);
        gl_FragColor = vec4(vec3(0.6, 0.72, 0.92) * 0.7, a * 0.5 * vFade);
      }
    `,
  });
  const mesh = new THREE.Mesh(g, mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = 20;
  scene.add(mesh);
  return { mesh, mat };
}

// ----------------------------------------------------------------- steam ---
function makeSteam(scene, count) {
  const quad = new THREE.PlaneGeometry(1, 1);
  const g = new THREE.InstancedBufferGeometry();
  g.index = quad.index;
  g.setAttribute('position', quad.getAttribute('position'));
  g.setAttribute('uv', quad.getAttribute('uv'));
  g.setAttribute('aEmit', new THREE.InstancedBufferAttribute(new Float32Array(count * 4), 4)); // x,y,z, scale
  const rand = new Float32Array(count * 4);
  const rng = mulberry32(999);
  for (let i = 0; i < count * 4; i++) rand[i] = rng();
  g.setAttribute('aRand', new THREE.InstancedBufferAttribute(rand, 4));
  g.instanceCount = count;

  const mat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false,
    uniforms: { uTime: GlobalUniforms.uTime, ...FogUniforms },
    vertexShader: /* glsl */`
      attribute vec4 aEmit;
      attribute vec4 aRand;
      varying vec2 vUv; varying float vAlpha; varying vec3 vW; varying float vSeed;
      uniform float uTime;
      void main(){
        vUv = uv; vSeed = aRand.w;
        float T = 5.0 + aRand.x * 4.0;
        float life = fract(uTime / T + aRand.y);
        float rise = life * (6.5 + aRand.z * 6.0) * aEmit.w;
        vec3 c = aEmit.xyz + vec3((aRand.x - 0.5) * 2.6 * life, rise, (aRand.z - 0.5) * 2.6 * life);
        float scale = aEmit.w * (1.6 + life * 5.6);
        vAlpha = smoothstep(0.0, 0.14, life) * (1.0 - smoothstep(0.45, 1.0, life));
        vW = c;
        vec4 mv = viewMatrix * vec4(c, 1.0);
        mv.xy += (uv - 0.5) * scale;
        gl_Position = projectionMatrix * mv;
      }
    `,
    fragmentShader: /* glsl */`
      varying vec2 vUv; varying float vAlpha; varying vec3 vW; varying float vSeed;
      uniform float uTime;
      ${FOG_PARS}
      float h21(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7)))*43758.5453); }
      float vnoise(vec2 p){
        vec2 i = floor(p), f = fract(p);
        f = f*f*(3.0-2.0*f);
        return mix(mix(h21(i), h21(i+vec2(1,0)), f.x), mix(h21(i+vec2(0,1)), h21(i+vec2(1,1)), f.x), f.y);
      }
      void main(){
        vec2 q = vUv - 0.5;
        float r = length(q) * 2.0;
        float n = vnoise(vUv * 5.0 + vSeed * 37.0 + uTime * 0.22) * 0.6
                + vnoise(vUv * 11.0 - uTime * 0.13 + vSeed * 91.0) * 0.4;
        float body = smoothstep(1.0, 0.22, r + n * 0.55);
        // lit from the street: warm-cyan mix by world x
        vec3 tint = mix(vec3(0.4, 0.72, 0.95), vec3(0.95, 0.5, 0.62), clamp(vW.x * 0.04 + 0.5, 0.0, 1.0));
        vec3 col = mix(vec3(0.1, 0.13, 0.17), tint * 0.5, exp(-max(vW.y, 0.0) * 0.05));
        float fade = exp(-distance(vW, cameraPosition) * uFogDensity * 1.3);
        gl_FragColor = vec4(col * fade, body * vAlpha * 0.42 * fade);
      }
    `,
  });
  const mesh = new THREE.Mesh(g, mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = 18;
  scene.add(mesh);
  return { mesh, geo: g };
}

// ------------------------------------------------------------ pedestrians --
const PED_PATHS = [
  { kind: 'walk', x: -23.4, dir: 1 },
  { kind: 'walk', x: 23.4, dir: -1 },
  { kind: 'walk', x: -19.6, dir: -1 },
  { kind: 'walk', x: 19.6, dir: 1 },
  { kind: 'cross', dir: 1 },
  { kind: 'cross', dir: -1 },
  { kind: 'cross', dir: 1 },
  { kind: 'cross', dir: -1 },
];

function makeUmbrella(rng) {
  const grp = new THREE.Group();
  const canopyGeo = new THREE.ConeGeometry(0.62, 0.28, 8, 1, false);
  const neon = rng() < 0.55;
  const col = neon ? [0x53d5fd, 0xff3d7f, 0xffb54d][Math.floor(rng() * 3)] : 0x39434f;
  const mat = new THREE.MeshStandardMaterial({
    color: col, metalness: neon ? 0.1 : 0.35, roughness: neon ? 0.55 : 0.42,
    emissive: neon ? col : 0x000000, emissiveIntensity: neon ? 0.85 : 0,
  });
  const canopy = new THREE.Mesh(canopyGeo, mat);
  canopy.position.y = 0.05;
  const stick = new THREE.Mesh(new THREE.CylinderGeometry(0.014, 0.014, 0.85, 5), new THREE.MeshStandardMaterial({ color: 0x666a75, metalness: 0.8, roughness: 0.3 }));
  stick.position.y = -0.36;
  grp.add(canopy, stick);
  return grp;
}

// ================================================================== Life ====
const MAXQ = { rain: 7000, steam: 110, peds: 16 };

export class Life {
  constructor(scene, city) {
    this.scene = scene;
    this.city = city;
    this.rng = mulberry32(31337);
    this.pedActive = MAXQ.peds;

    // ---- vehicles
    this.carMat = carBodyMaterial();
    const carGeo = new THREE.BoxGeometry(1, 1, 1);
    this.NCARS = 148;
    this.cars = new THREE.InstancedMesh(carGeo, this.carMat, this.NCARS);
    this.cars.frustumCulled = false;
    this.cars.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.cars.geometry = this.cars.geometry.clone();
    this.cars.geometry.setAttribute('aTint', new THREE.InstancedBufferAttribute(new Float32Array(this.NCARS * 3), 3));
    this.cars.geometry.setAttribute('aSeed', new THREE.InstancedBufferAttribute(new Float32Array(this.NCARS), 1));
    this.cars.layers.enable(1);
    scene.add(this.cars);

    this.glows = new GlowPool(scene, 900);

    const tintA = this.cars.geometry.getAttribute('aTint');
    const seedA = this.cars.geometry.getAttribute('aSeed');
    const bodyCols = [0x1a2028, 0x232b36, 0x2b1f28, 0x1d2b26, 0x30323b, 0x3a2e1e];
    this.carData = [];
    const rng = this.rng;
    for (let i = 0; i < this.NCARS; i++) {
      const r = rng();
      let lane;
      if (r < 0.34) { // street level
        const side = rng() < 0.5 ? -1 : 1;
        const x = side * (rng() < 0.5 ? 7.2 : 14.2);
        lane = { type: 'street', x, y: 0.62, dir: side > 0 ? -1 : 1 };
      } else if (r < 0.78) { // side decks
        const side = rng() < 0.5 ? -1 : 1;
        lane = { type: 'deck', side, off: (rng() < 0.5 ? -2.3 : 2.3), dir: rng() < 0.5 ? -1 : 1 };
      } else { // crossing decks - assigned each frame from city data
        lane = { type: 'cross', slot: rng() };
      }
      const c = new THREE.Color(bodyCols[Math.floor(rng() * bodyCols.length)]);
      tintA.setXYZ(i, c.r, c.g, c.b);
      const taxi = rng();
      seedA.setX(i, taxi);
      this.carData.push({
        lane, s: rng() * 4000, speed: 13 + rng() * 12 + (lane.type === 'deck' ? 9 : 0),
        len: 3.6 + rng() * 1.4, wid: 1.7, hei: 1.15 + rng() * 0.25, taxi: taxi > 0.75,
      });
    }
    tintA.needsUpdate = true; seedA.needsUpdate = true;

    // ---- air taxi swarm (instanced boxes, lights carried by glow pool)
    this.NAIR = 52;
    this.air = new THREE.InstancedMesh(carGeo, this.carMat, this.NAIR);
    this.air.frustumCulled = false;
    this.air.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.air.geometry = this.air.geometry.clone();
    this.air.geometry.setAttribute('aTint', new THREE.InstancedBufferAttribute(new Float32Array(this.NAIR * 3), 3));
    this.air.geometry.setAttribute('aSeed', new THREE.InstancedBufferAttribute(new Float32Array(this.NAIR), 1));
    this.air.layers.enable(1);
    scene.add(this.air);
    const atint = this.air.geometry.getAttribute('aTint');
    const aseed = this.air.geometry.getAttribute('aSeed');
    this.airData = [];
    const AIR_BANDS = [34, 50, 67]; // lane altitudes; direction is uniform per band
    for (let i = 0; i < this.NAIR; i++) {
      const inCanyon = rng() < 0.85;
      const band = i % 3;
      const x = inCanyon ? (rng() - 0.5) * 30 : (rng() < 0.5 ? -1 : 1) * (44 + rng() * 60);
      const y = inCanyon ? AIR_BANDS[band] + rng() * 7 : 62 + rng() * 55;
      const c = new THREE.Color().setHSL(0.55 + rng() * 0.12, 0.4, 0.16);
      atint.setXYZ(i, c.r, c.g, c.b);
      aseed.setX(i, rng());
      this.airData.push({
        x, y, dir: band === 1 ? 1 : -1, s: rng() * 4000,
        speed: 26 + rng() * 18, bob: rng() * 6.28, len: 4.4, wid: 1.9, hei: 1.2,
      });
    }
    atint.needsUpdate = true; aseed.needsUpdate = true;

    // ---- rain, steam
    this.rain = makeRain(scene, MAXQ.rain);
    this.steam = makeSteam(scene, MAXQ.steam);

    // ---- pedestrians with umbrellas (self-made android + hand-keyed Walking clips)
    this.peds = [];
    const clips = robotClipNames('Walking_');
    for (let i = 0; i < MAXQ.peds; i++) {
      const clip = clips[Math.floor(rng() * clips.length)];
      const { group, mixer } = makeRobot({ clipName: clip, timeScale: 0.92 + rng() * 0.2 });
      const umb = makeUmbrella(rng);
      umb.position.set(0.16, 1.96, 0.1);
      umb.rotation.z = -0.12;
      group.add(umb);
      const path = PED_PATHS[Math.floor(rng() * PED_PATHS.length)];
      const ped = {
        group, mixer, path, umb,
        s: rng(), speed: 0.9 + rng() * 0.5, zBase: 0,
        phase: rng() * 6.28,
      };
      group.scale.setScalar(0.97 + rng() * 0.1);
      scene.add(group);
      this.peds.push(ped);
      this._respawnPed(ped, -60 - rng() * 200);
    }

    // ---- hero patrol drones (GLB drone10) with searchlight cones
    this.patrols = [];
    const coneGeo = new THREE.ConeGeometry(1, 1, 18, 1, true);
    coneGeo.translate(0, -0.5, 0);
    const coneMat = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
      uniforms: { uTime: GlobalUniforms.uTime },
      vertexShader: `varying vec2 vUv; varying vec3 vP; void main(){ vUv = uv; vP = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
      fragmentShader: /* glsl */`
        varying vec2 vUv; varying vec3 vP;
        void main(){
          float a = (1.0 - vUv.y) ;
          a = pow(a, 2.2) * 0.16 * (0.6 + 0.4 * sin(vUv.x * 40.0));
          gl_FragColor = vec4(vec3(0.55, 0.85, 1.0) * a, a);
        }
      `,
    });
    for (let i = 0; i < 3; i++) {
      const d = makeDrone('drone10', { emissiveBoost: 2.4 });
      const cone = new THREE.Mesh(coneGeo, coneMat);
      cone.scale.set(7, 26, 7);
      cone.position.y = -0.4;
      d.group.add(cone);
      this.scene.add(d.group);
      this.patrols.push({
        drone: d, cone,
        phase: i * 2.1, xAmp: 13 + i * 4, yBase: 24 + i * 8, zOff: -60 - i * 110,
      });
    }
  }

  applyQuality(q) {
    this.rain.mesh.geometry.instanceCount = Math.min(q.rain, MAXQ.rain);
    this.steam.geo.instanceCount = Math.min(q.steam, MAXQ.steam);
    this.pedActive = Math.min(q.peds, MAXQ.peds);
    this.peds.forEach((p, i) => { p.group.visible = i < this.pedActive; });
  }

  _respawnPed(ped, zAhead) {
    const p = ped.path;
    ped.zBase = zAhead - Math.random() * 40;
    ped.s = Math.random();
  }

  update(dt, time, camZ, camPos, camVel, playing) {
    const rng = this.rng;
    this.glows.begin();

    // ---------- ground / deck / crossing traffic
    const crosses = this.city.crossDeckList();
    for (let i = 0; i < this.NCARS; i++) {
      const cd = this.carData[i];
      cd.s += cd.speed * dt;
      let x, y, z, yaw;
      if (cd.lane.type === 'street') {
        const span = 1400;
        const rel = ((cd.lane.dir > 0 ? cd.s : -cd.s) % span + span) % span;
        z = camZ + 150 - rel;
        x = cd.lane.x; y = cd.lane.y;
        yaw = cd.lane.dir > 0 ? Math.PI : 0;
        // right side of the road by direction
        x += cd.lane.dir > 0 ? -0 : 0;
      } else if (cd.lane.type === 'deck') {
        const span = 1400;
        const rel = ((cd.lane.dir > 0 ? cd.s : -cd.s) % span + span) % span;
        z = camZ + 150 - rel;
        x = this.city.deckX(cd.lane.side, z) + cd.lane.off * 0.55;
        y = this.city.deckY(cd.lane.side, z) + 1.15;
        const x2 = this.city.deckX(cd.lane.side, z - 2);
        yaw = Math.atan2(x2 - x, -2) + (cd.lane.dir > 0 ? Math.PI : 0);
      } else {
        // crossing decks
        if (!crosses.length) { tmpM.makeScale(0, 0, 0); this.cars.setMatrixAt(i, tmpM); continue; }
        const deck = crosses[Math.floor(cd.lane.slot * crosses.length) % crosses.length];
        const span = 130;
        const dir = cd.lane.slot > 0.5 ? 1 : -1;
        const rel = ((cd.s * 0.9) % span + span) % span;
        x = dir > 0 ? -65 + rel : 65 - rel;
        y = deck.y + 1.15;
        z = deck.z + (dir > 0 ? -2.4 : 2.4);
        yaw = dir > 0 ? Math.PI / 2 : -Math.PI / 2;
      }
      tmpP.set(x, y, z);
      tmpQ.setFromAxisAngle(YAXIS, yaw);
      tmpS.set(cd.wid, cd.hei, cd.len);
      tmpM.compose(tmpP, tmpQ, tmpS);
      this.cars.setMatrixAt(i, tmpM);
      // lights (skip far ones for fill-rate)
      const dz = Math.abs(z - camZ);
      if (dz < 420) {
        const fwx = -Math.sin(yaw), fwz = -Math.cos(yaw); // car forward is local -Z
        this.glows.push(x + fwx * cd.len * 0.5, y + 0.35, z + fwz * cd.len * 0.5, 2.4, 2.2, 1.9, 1.9, 0);
        this.glows.push(x - fwx * cd.len * 0.5, y + 0.3, z - fwz * cd.len * 0.5, 2.2, 0.12, 0.06, 1.5, 0);
        if (cd.taxi) this.glows.push(x, y + cd.hei * 0.7, z, 1.8, 1.2, 0.35, 0.9, 0);
      }
    }
    this.cars.instanceMatrix.needsUpdate = true;

    // ---------- air lanes
    for (let i = 0; i < this.NAIR; i++) {
      const ad = this.airData[i];
      ad.s += ad.speed * dt;
      const span = 1600;
      const rel = ((ad.dir > 0 ? ad.s : -ad.s) % span + span) % span;
      const z = camZ + 220 - rel;
      const y = ad.y + Math.sin(time * 0.7 + ad.bob) * 1.6;
      const x = ad.x + Math.sin(time * 0.23 + ad.bob * 2.0) * 3.0;
      tmpP.set(x, y, z);
      tmpQ.setFromAxisAngle(YAXIS, ad.dir > 0 ? Math.PI : 0);
      tmpS.set(ad.wid, ad.hei, ad.len);
      tmpM.compose(tmpP, tmpQ, tmpS);
      this.air.setMatrixAt(i, tmpM);
      const fwz = ad.dir > 0 ? 1 : -1;
      this.glows.push(x, y, z - fwz * ad.len * 0.6, 2.6, 2.4, 2.1, 3.2, 0);
      this.glows.push(x, y, z + fwz * ad.len * 0.6, 2.4, 0.1, 0.08, 2.5, 0);
      this.glows.push(x, y - ad.hei * 0.6, z, 0.5, 1.9, 2.4, 1.9, 2.0 + ad.bob);
    }
    this.air.instanceMatrix.needsUpdate = true;

    // ---------- steam emitters near the camera
    {
      const spots = this.city.steamSpots();
      const g = this.steam.geo;
      const aEmit = g.getAttribute('aEmit');
      const n = Math.min(g.instanceCount, aEmit.count);
      // sort-ish: just pick spots within window ahead of camera
      let si = 0;
      for (const s of spots) {
        if (s.z > camZ + 40 || s.z < camZ - 620) continue;
        // 2-4 particles per spot depending on budget
        const per = Math.max(2, Math.floor(n / Math.max(6, spots.length)));
        for (let k = 0; k < per && si < n; k++) aEmit.setXYZW(si++, s.x, s.y, s.z, s.s);
        if (si >= n) break;
      }
      while (si < n) aEmit.setXYZW(si++, 0, -500, 0, 0.001);
      aEmit.needsUpdate = true;
    }

    // ---------- rain follows camera velocity for streaking
    this.rain.mat.uniforms.uCamVel.value.copy(camVel);

    // ---------- pedestrians
    for (let pi = 0; pi < this.pedActive; pi++) {
      const ped = this.peds[pi];
      ped.mixer.update(dt);
      const p = ped.path;
      if (p.kind === 'walk') {
        const range = 60;
        ped.s += (ped.speed * dt) / range;
        if (ped.s > 1) { ped.s = 0; this._respawnPed(ped, camZ - 90 - Math.random() * 200); }
        const z = ped.zBase + (p.dir > 0 ? ped.s : 1 - ped.s) * range;
        ped.group.position.set(p.x + Math.sin(ped.phase + ped.s * 9.0) * 0.4, 0, z);
        ped.group.rotation.y = p.dir > 0 ? 0 : Math.PI;
      } else {
        const range = 42;
        ped.s += (ped.speed * dt) / range;
        if (ped.s > 1) { ped.s = 0; this._respawnPed(ped, camZ - 90 - Math.random() * 200); }
        const x = (p.dir > 0 ? -21 + ped.s * range : 21 - ped.s * range);
        ped.group.position.set(x, 0, ped.zBase);
        ped.group.rotation.y = p.dir > 0 ? Math.PI / 2 : -Math.PI / 2;
      }
      // recycle if left behind
      const dz = ped.group.position.z - camZ;
      if (dz > 50 || dz < -420) this._respawnPed(ped, camZ - 100 - Math.random() * 240);
      // umbrella sway
      ped.umb.rotation.x = Math.sin(time * 1.7 + ped.phase) * 0.05 + 0.1;
    }

    // ---------- patrols
    for (const pt of this.patrols) {
      pt.drone.mixer && pt.drone.mixer.update(dt);
      const t = time * 0.13 + pt.phase;
      const x = Math.sin(t) * pt.xAmp;
      const y = pt.yBase + Math.sin(t * 1.7) * 4;
      const z = camZ + pt.zOff + Math.sin(t * 0.7) * 30;
      const g = pt.drone.group;
      // face travel direction (smoothed)
      if (pt.lx !== undefined) {
        const vx = x - pt.lx, vz = z - pt.lz;
        if (Math.abs(vx) + Math.abs(vz) > 1e-4) {
          const yaw = Math.atan2(-vx, -vz);
          let d = yaw - (pt.yaw ?? yaw);
          d = ((d + Math.PI) % (Math.PI * 2) + Math.PI * 2) % (Math.PI * 2) - Math.PI;
          pt.yaw = (pt.yaw ?? yaw) + d * Math.min(1, dt * 3);
        }
      }
      pt.lx = x; pt.lz = z;
      g.position.set(x, y, z);
      g.rotation.set(0, pt.yaw ?? 0, Math.sin(t * 1.3) * 0.12);
      pt.cone.rotation.x = Math.sin(t * 2.1) * 0.22;
      pt.cone.rotation.z = Math.cos(t * 1.7) * 0.22;
      // nav strobes
      const wp = g.position;
      this.glows.push(wp.x, wp.y + 0.6, wp.z, 2.2, 0.15, 0.1, 1.1, 3.1);
      this.glows.push(wp.x, wp.y + 0.2, wp.z, 0.2, 0.9, 2.4, 1.0, 4.3);
    }

    this.glows.end();
  }
}
