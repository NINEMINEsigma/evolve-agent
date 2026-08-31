// The player's warship: a SciFiDrone06 airframe tinted with the pilot's
// livery color, the pilot orb itself in the seat (white pill eyes forward),
// thruster glows, and a nametag sprite for rival ships.
import * as THREE from 'three';
import { PLAYER } from '../config.js';
import { clamp, damp, GlobalUniforms } from '../utils.js';
import { makeDrone } from '../assets.js';

export const SHIP_RADIUS = 1.8; // hit sphere for bolts

const THRUSTER_VERT = /* glsl */`
  varying vec2 vUv;
  uniform float uPow;
  void main(){
    vUv = uv;
    vec4 mv = modelViewMatrix * vec4(vec3(0.0), 1.0);
    mv.xy += (uv - 0.5) * vec2(length(modelMatrix[0].xyz), length(modelMatrix[1].xyz)) * (0.8 + uPow * 0.5);
    gl_Position = projectionMatrix * mv;
  }
`;
const THRUSTER_FRAG = /* glsl */`
  varying vec2 vUv; uniform vec3 uColor; uniform float uPow;
  void main(){
    float d = length(vUv - 0.5) * 2.0;
    float g = exp(-d * d * 5.5);
    gl_FragColor = vec4(uColor * g * (1.1 + uPow * 2.4), g * (0.7 + uPow * 0.3));
  }
`;

export function buildShip({ color = 0x2a6fe6, name = '', showTag = false } = {}) {
  const accent = new THREE.Color(color);
  const d = makeDrone('drone06', { emissiveBoost: 2.6, tint: color });
  const group = new THREE.Group();
  const body = d.group;
  group.add(body);

  // the orb IS the pilot
  const orb = new THREE.Group();
  const ball = new THREE.Mesh(
    new THREE.SphereGeometry(0.46, 24, 18),
    new THREE.MeshStandardMaterial({
      color: accent, emissive: accent, emissiveIntensity: 1.3, roughness: 0.4, metalness: 0,
    }),
  );
  orb.add(ball);
  const eyeMat = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 1.1 });
  for (const ex of [-0.14, 0.14]) {
    const eye = new THREE.Mesh(new THREE.SphereGeometry(0.075, 12, 9), eyeMat);
    eye.scale.set(0.8, 1.5, 0.5);
    eye.position.set(ex, 0.11, -0.46 * 0.82);
    orb.add(eye);
  }
  orb.position.set(0, 0.62, -0.15); // perched in the cockpit well
  body.add(orb);

  // thruster glows
  const glowGeo = new THREE.PlaneGeometry(1, 1);
  const thrusters = [];
  for (const [x, y, z, s] of [[-1.45, 0.02, 0.6, 1.15], [1.45, 0.02, 0.6, 1.15], [-0.5, -0.22, 1.42, 0.9], [0.5, -0.22, 1.42, 0.9]]) {
    const m = new THREE.Mesh(glowGeo, new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uColor: { value: accent.clone().lerp(new THREE.Color(0xbfe8ff), 0.45) }, uPow: { value: 1 } },
      vertexShader: THRUSTER_VERT, fragmentShader: THRUSTER_FRAG,
    }));
    m.position.set(x, y, z);
    m.scale.setScalar(s);
    m.frustumCulled = false;
    body.add(m);
    thrusters.push(m);
  }

  // through-fog beacon so opponents read at any range (the canyon fog eats
  // geometry past ~200 m — this additive dot is the "radar blip")
  let beacon = null;
  if (showTag) {
    const cv = document.createElement('canvas');
    cv.width = cv.height = 64;
    const c = cv.getContext('2d');
    const grad = c.createRadialGradient(32, 32, 2, 32, 32, 30);
    grad.addColorStop(0, 'rgba(255,255,255,1)');
    grad.addColorStop(0.3, `#${accent.getHexString()}`);
    grad.addColorStop(1, 'rgba(0,0,0,0)');
    c.fillStyle = grad;
    c.fillRect(0, 0, 64, 64);
    beacon = new THREE.Sprite(new THREE.SpriteMaterial({
      map: new THREE.CanvasTexture(cv),
      blending: THREE.AdditiveBlending,
      depthTest: false, depthWrite: false, transparent: true,
    }));
    beacon.renderOrder = 40;
    beacon.position.set(0, 0.4, 0);
    beacon.scale.setScalar(4.2); // reads through the fog at any range
    group.add(beacon);
  }

  let tag = null;
  if (showTag && name) {
    const cv = document.createElement('canvas');
    cv.width = 512; cv.height = 128;
    const c = cv.getContext('2d');
    c.font = '600 58px "Geist Mono", Menlo, monospace';
    c.textAlign = 'center';
    c.fillStyle = 'rgba(5,9,16,0.62)';
    const w = c.measureText(name).width + 64;
    c.beginPath(); c.roundRect((512 - w) / 2, 20, w, 88, 18); c.fill();
    c.fillStyle = '#dff2ff';
    c.fillText(name.toUpperCase(), 256, 82);
    const tex = new THREE.CanvasTexture(cv);
    tag = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthWrite: false, transparent: true }));
    tag.scale.set(3.4, 0.85, 1);
    tag.position.set(0, 2.2, 0);
    group.add(tag);
  }

  return { group, body, orb, mixer: d.mixer, thrusters, accent, tag, beacon };
}

// Pose a ship from its motion — bank/pitch/yaw + thrusters.
export function poseShip(ship, vx, vy, speed, bank, dt) {
  const g = ship.group;
  g.rotation.z = bank;
  g.rotation.x = clamp(vy * 0.02, -0.42, 0.42);
  g.rotation.y = clamp(-vx * 0.012, -0.3, 0.3);
  ship.mixer && ship.mixer.update(dt);
  const pw = clamp((speed - PLAYER.minSpeed) / (PLAYER.boostSpeed - PLAYER.minSpeed), 0, 1);
  for (const t of ship.thrusters) t.material.uniforms.uPow.value = pw;
}

// Flight physics — the rain-cab feel (mouse steer, W/S throttle, Shift
// boost + heat, Space burn), on a plain state object.
export function stepShip(P, dt, input) {
  const C = PLAYER;

  if (input.keys.has('KeyW')) P.speedHold = clamp(P.speedHold + C.throttleRate * dt, C.minSpeed, C.maxSpeed);
  if (input.keys.has('KeyS')) P.speedHold = clamp(P.speedHold - C.throttleRate * dt, C.minSpeed, C.maxSpeed);
  let target = P.speedHold;

  P.boosting = false;
  if (input.keys.has('ShiftLeft') || input.keys.has('ShiftRight')) {
    if (P.overheated <= 0 && P.heat < 100) {
      P.boosting = true;
      target = C.boostSpeed;
      P.heat += C.heatRate * dt;
      if (P.heat >= 100) { P.heat = 100; P.overheated = C.overheatLock; }
    }
  }
  if (!P.boosting) P.heat = Math.max(0, P.heat - C.coolRate * dt);
  if (P.overheated > 0) P.overheated -= dt;
  if (P.dashUntil && performance.now() < P.dashUntil) target = Math.max(target, C.boostSpeed + 12); // item dash: free surge, no heat

  P.speed = damp(P.speed, target, P.boosting ? 2.6 : 1.9, dt);

  const latT = input.mx * C.latMax;
  const vertT = -input.my * C.vertMax;
  P.vel.x = damp(P.vel.x, latT, C.steerLag, dt);
  P.vel.y = damp(P.vel.y, vertT, C.steerLag * 0.9, dt);

  if (P.burnCd > 0) P.burnCd -= dt;
  if ((input.burn || input.keys.has('Space')) && P.burnCd <= 0) {
    P.vel.y += C.burnImpulse;
    P.burnCd = C.burnCooldown;
  }

  P.vel.z = -P.speed;
  P.pos.addScaledVector(P.vel, dt);

  const XL = 38;
  if (Math.abs(P.pos.x) > XL) { P.pos.x = Math.sign(P.pos.x) * XL; P.vel.x *= -0.35; }
  if (P.pos.y > C.ceiling0) { P.pos.y = damp(P.pos.y, C.ceiling0, 8, dt); P.vel.y = Math.min(P.vel.y, 2); }
  if (P.pos.y < 1.0) P.pos.y = 1.0;

  P.bank = damp(P.bank, clamp(-P.vel.x * 0.032, -0.65, 0.65), 6, dt);
}

// Feed the wet-street hero light slots from the local ship.
export function feedHeroLights(P, accent) {
  const dl = GlobalUniforms.uDynPos.value, dc = GlobalUniforms.uDynCol.value;
  const pw = clamp((P.speed - PLAYER.minSpeed) / (PLAYER.boostSpeed - PLAYER.minSpeed), 0, 1);
  dl[0].set(P.pos.x, Math.max(P.pos.y - 1, 1), P.pos.z - 9, 1.5);
  dc[0].setRGB(0.9, 0.95, 1.0);
  dl[1].set(P.pos.x, Math.max(P.pos.y - 2, 0.5), P.pos.z, 1.1 + pw * 1.5);
  dc[1].set(accent);
}
