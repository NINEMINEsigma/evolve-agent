// CYBER SPACESHIP — single-player dogfight over the neon rain canyon.
// The scene modules (engine/city/sky/life) render the canyon as a seamless
// 480 m loop (periodic chunk seeds). Three local AI pilots fly the same
// physics, combat and scoring paths as the player; every hit is adjudicated
// locally on the victim's side. No network, no server — open and play.
import * as THREE from 'three';
import { Engine } from '../engine.js';
import { loadAssets } from '../assets.js';
import { makeSky, makeEnvironment } from '../sky.js';
import { City } from '../city.js';
import { Life, GlowPool } from '../life.js';
import { WORLD, PLAYER, QUALITY_PRESETS } from '../config.js';
import { clamp, damp, GlobalUniforms, FogUniforms } from '../utils.js';
import { buildShip, poseShip, stepShip, feedHeroLights } from './ship.js';
import { Combat } from './combat.js';
import { ArenaItems } from './items.js';
import { ArenaBots } from './bots.js';
import { Menu } from './menu.js';

const LOOP = WORLD.chunkLen * WORLD.loopChunks; // 480 m
const Z_HOME = -160;                            // loop window: (Z_HOME - LOOP, Z_HOME]
const MATCH_MS = 180000;                        // 3-minute dogfight
const COUNTDOWN_MS = 4200;                      // ENGAGE IN 3… countdown
const STUN_S = 2.0;                             // one hit = 2 s of dead controls
const STUN_GRACE_S = 1.2;                       // can't be re-hit right after recovering
const RESPAWN_S = 2.6;
const INVULN_S = 2.0;

const MY_ID = 0;
const MY_NAME = '你';
const MY_COLOR = 0x2a6fe6;
const RIVALS = [ // the three AI pilots sharing the start line
  { name: 'VEX', color: 0xff3d7f },
  { name: 'JOLT', color: 0xffb54d },
  { name: 'NOVA', color: 0x7dffc7 },
];

const dzLoop = (z, ref) => {
  let d = (z - ref) % LOOP;
  if (d > LOOP / 2) d -= LOOP;
  if (d < -LOOP / 2) d += LOOP;
  return d;
};

// ------------------------------------------------------------------ sfx ----
const sfx = (() => {
  let ctx = null;
  let enabled = true;
  const ac = () => (ctx = ctx || new (window.AudioContext || window.webkitAudioContext)());
  const env = (dur, gain = 0.05) => {
    const g = ac().createGain();
    g.gain.setValueAtTime(gain, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + dur);
    g.connect(ctx.destination);
    return g;
  };
  const tone = (freq, type, dur, gain, slide = 0) => {
    if (!enabled) return;
    try {
      const o = ac().createOscillator();
      o.type = type; o.frequency.value = freq;
      if (slide) o.frequency.exponentialRampToValueAtTime(Math.max(30, freq + slide), ctx.currentTime + dur);
      o.connect(env(dur, gain));
      o.start(); o.stop(ctx.currentTime + dur + 0.02);
    } catch { /* audio unavailable */ }
  };
  return {
    shot: () => { tone(920, 'sawtooth', 0.09, 0.028, -600); tone(1840, 'square', 0.05, 0.012, -900); },
    clang: () => tone(2600, 'triangle', 0.07, 0.03, -1400),
    hurt: () => { tone(160, 'sawtooth', 0.22, 0.06, -70); tone(70, 'sine', 0.3, 0.07); },
    boom: () => { tone(90, 'sawtooth', 0.65, 0.09, -55); tone(46, 'sine', 0.8, 0.1, -18); },
    kill: () => { tone(660, 'square', 0.09, 0.04); setTimeout(() => tone(990, 'square', 0.12, 0.04), 90); },
    tick: () => tone(1320, 'sine', 0.07, 0.045),
    go: () => { tone(880, 'square', 0.1, 0.05); setTimeout(() => tone(1320, 'square', 0.16, 0.05), 100); },
    pickup: () => { tone(1040, 'sine', 0.07, 0.05); setTimeout(() => tone(1560, 'sine', 0.1, 0.045), 70); },
    zapOut: () => { tone(1800, 'sawtooth', 0.16, 0.04, -1500); tone(300, 'square', 0.12, 0.03, -180); },
    shieldUp: () => tone(520, 'sine', 0.2, 0.05, 260),
    set enabled(v) { enabled = v; },
  };
})();

// ------------------------------------------------------------------ boot ---
export async function boot(rootEl) {
  const $ = id => document.getElementById(id);
  const hud = $('hud'), fade = $('fade');
  const canvas = document.createElement('canvas');
  canvas.id = 'gl';
  rootEl.appendChild(canvas);

  const menu = new Menu({
    onStart: () => startMatch(),
    onResume: () => resumeGame(),
    onRestart: () => startMatch(),
    onQuit: () => quitToMenu(),
    onQuality: (name) => applyQuality(name),
    onSound: (on) => { sfx.enabled = on; },
  });

  const engine = new Engine(canvas);
  engine.applyQuality(QUALITY_PRESETS[menu.quality]);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(62, innerWidth / innerHeight, 0.35, 3600);
  camera.position.set(0, 30, Z_HOME + 30);
  scene.add(camera);

  scene.add(new THREE.HemisphereLight(0x1d2a40, 0x100c14, 1.1));
  const key = new THREE.DirectionalLight(0x8fb4d8, 0.5);
  key.position.set(-40, 90, 30);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xff3d7f, 0.22);
  fill.position.set(50, 30, -60);
  scene.add(fill);
  scene.add(makeSky());
  scene.environment = makeEnvironment(engine.renderer);

  const onResize = () => { camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); };
  window.addEventListener('resize', onResize);
  onResize();

  fade.textContent = '赛 博 战 机';
  await loadAssets((p) => { fade.textContent = `加载中 ${Math.round(p * 100)}%`; });
  fade.textContent = '赛 博 战 机';

  const city = new City(scene);
  const life = new Life(scene, city);
  life.applyQuality(QUALITY_PRESETS[menu.quality]);
  const glows = new GlowPool(scene, 200);
  city.groundMat.uniforms.tRefl.value = engine.reflRT.texture;

  function applyQuality(name) {
    const q = QUALITY_PRESETS[name];
    engine.applyQuality(q);
    life.applyQuality(q);
  }

  // ---------------------------------------------------------- local state --
  const P = {
    pos: new THREE.Vector3(0, PLAYER.startY, Z_HOME),
    vel: new THREE.Vector3(0, 0, -PLAYER.cruise),
    speed: PLAYER.cruise,
    speedHold: PLAYER.cruise,
    heat: 0, overheated: 0, burnCd: 0, boosting: false, bank: 0,
    alive: true, respawnT: 0, invulnT: 0,
    stunT: 0, stunSpin: 0, stunGraceT: 0,
    itemShieldT: 0, dashUntil: 0,
  };
  let mode = 'menu'; // menu | countdown | playing | paused | over
  const MY_SLOT = 0;

  // Everyone launches from the same start line: a grid formation keyed by slot.
  function formationPos(slot) {
    const col = slot % 5, row = Math.floor(slot / 5);
    return new THREE.Vector3((col - 2) * 8, PLAYER.startY, Z_HOME - row * 14);
  }
  function parkAtFormation() {
    P.pos.copy(formationPos(MY_SLOT));
    P.vel.set(0, 0, 0);
    P.speed = 0;
    P.speedHold = PLAYER.cruise;
    P.bank = 0;
    P.heat = 0; P.overheated = 0;
    P.stunT = 0; P.stunGraceT = 0;
    P.alive = true; P.invulnT = 0;
    myShip.group.visible = true;
  }
  let matchStartAt = 0, matchEndAt = 0, pauseStart = 0;
  let shake = 0;
  const sparks = [];
  const scoreboard = new Map(); // id -> {kills, deaths}
  const names = new Map();      // id -> {name, color}
  const board = id => { if (!scoreboard.has(id)) scoreboard.set(id, { kills: 0, deaths: 0 }); return scoreboard.get(id); };
  names.set(MY_ID, { name: MY_NAME, color: MY_COLOR.toString(16) });
  board(MY_ID);

  const myShip = buildShip({ color: MY_COLOR, name: MY_NAME, showTag: false });
  myShip.group.position.copy(P.pos);
  scene.add(myShip.group);

  // One hit = systems offline for STUN_S — the ship tumbles uncontrolled,
  // then control returns (no HP, no death from bolts). Shared by bolts and
  // offensive items; the item shield eats one incoming hit first.
  function hitMe(fromId) {
    if (!P.alive || mode !== 'playing') return;
    if (P.stunT > 0 || P.stunGraceT > 0 || P.invulnT > 0) return;
    if (items && items.tryBlock()) return;
    P.stunT = STUN_S;
    P.stunSpin = (Math.random() < 0.5 ? -1 : 1) * (5 + Math.random() * 3);
    shake = Math.min(1.2, shake + 0.7);
    engine.params.flash = Math.max(engine.params.flash, 0.35);
    sfx.hurt();
    board(fromId).kills++;
    board(MY_ID).deaths++;
    feed(nameOf(fromId), nameOf(MY_ID));
    explodeAt(P.pos, 18);
    showCenter('系统离线', false, STUN_S * 1000);
    updateScore();
  }

  const combat = new Combat({
    scene, glows, dzLoop,
    getMyPos: () => (P.alive ? P.pos : null),
    sfx,
    onSelfHit: (fromId) => hitMe(fromId),
  });

  let bots = null; // ArenaBots, created below (items.broadcast closes over it)
  const items = new ArenaItems({
    scene, glows, dzLoop,
    zHome: Z_HOME, loop: LOOP, P,
    leaderId: () => {
      // EMP seeks the HITS leader among the rival pilots
      let best = null, bestK = -1;
      for (const id of bots.aliveIds()) {
        const k = board(id).kills;
        if (k > bestK) { bestK = k; best = id; }
      }
      return best;
    },
    applyHit: (byId) => hitMe(byId),
    broadcast: (payload) => bots.onItem({ from: MY_ID, ...payload }), // bots adjudicate my shock/EMP on themselves
    showMsg: (text, ms = 1200, color = '') => showCenter(text, false, ms, color),
    sfx,
    isOn: () => mode === 'playing' && P.alive,
  });

  bots = new ArenaBots({
    scene, city, combat, glows, sfx, dzLoop, loop: LOOP, zHome: Z_HOME,
    formationPos, playerP: P, getMode: () => mode,
    board, myId: () => MY_ID, nameOf, feed, explodeAt, showCenter, updateScore,
    STUN_S, STUN_GRACE_S, RESPAWN_S, INVULN_S,
  }, RIVALS);
  for (const b of bots.bots) names.set(b.id, { name: b.name, color: b.color.toString(16) });

  // ------------------------------------------------------ rival markers ---
  // One HUD marker per rival: a colored diamond + name + distance that tracks
  // the ship on screen, and turns into an edge arrow when it's off screen.
  const markersEl = $('markers');
  const markerEls = bots.bots.map((b) => {
    const el = document.createElement('div');
    el.className = 'marker';
    el.style.setProperty('--mc', `#${b.color.toString(16).padStart(6, '0')}`);
    el.innerHTML = '<i class="dot"></i><span class="mlab"></span>';
    el.style.display = 'none';
    markersEl.appendChild(el);
    return { el, lab: el.querySelector('.mlab') };
  });
  const _mv = new THREE.Vector3();
  function updateMarkers() {
    const show = mode === 'playing' || mode === 'countdown';
    camera.updateMatrixWorld();
    bots.bots.forEach((b, i) => {
      const m = markerEls[i];
      if (!show || !b.state.alive) { m.el.style.display = 'none'; return; }
      const s = b.state;
      const dz = dzLoop(s.pos.z, P.pos.z); // nearest copy on the loop
      const dist = Math.hypot(s.pos.x - P.pos.x, s.pos.y - P.pos.y, dz);
      _mv.set(s.pos.x, s.pos.y + 2.6, P.pos.z + dz).project(camera);
      const behind = _mv.z > 1;
      const cx = innerWidth / 2, cy = innerHeight / 2, margin = 48;
      let dx = _mv.x * 0.5 * innerWidth, dy = -_mv.y * 0.5 * innerHeight;
      if (behind) { dx = -dx; dy = -dy; }
      const tX = dx ? (cx - margin) / Math.abs(dx) : Infinity;
      const tY = dy ? (cy - margin) / Math.abs(dy) : Infinity;
      const t = Math.min(tX, tY, 1);
      const edge = t < 1;
      m.el.style.display = 'flex';
      m.el.style.left = `${cx + dx * t}px`;
      m.el.style.top = `${cy + dy * t}px`;
      m.el.classList.toggle('edge', edge);
      if (edge) m.el.style.setProperty('--ang', `${Math.atan2(dy, dx) + Math.PI / 2}rad`);
      m.lab.textContent = `${b.name} · ${Math.round(dist)} 米`;
    });
  }

  // --------------------------------------------------------------- input ---
  const keys = new Set();
  const mouse = { x: 0, y: 0 };
  let firing = false, burnQueued = false;
  window.addEventListener('keydown', (e) => {
    if (e.repeat) return;
    keys.add(e.code);
    if (e.code === 'Space') { burnQueued = true; e.preventDefault(); }
    if (e.code === 'KeyJ') firing = true;
    if (e.code === 'KeyE') items.use();
    if (e.code === 'Escape' && mode === 'playing') pauseGame();
  });
  window.addEventListener('keyup', (e) => { keys.delete(e.code); if (e.code === 'KeyJ') firing = false; });
  window.addEventListener('mousemove', (e) => {
    mouse.x = clamp((e.clientX / innerWidth) * 2 - 1, -1, 1);
    mouse.y = clamp((e.clientY / innerHeight) * 2 - 1, -1, 1);
  });
  window.addEventListener('mousedown', () => { firing = true; });
  window.addEventListener('mouseup', () => { firing = false; });
  window.addEventListener('blur', () => { keys.clear(); firing = false; });

  // ----------------------------------------------------------------- hud ---
  const centerEl = $('center-msg'), timerEl = $('timer'), killsEl = $('kills'),
    hpFill = $('hp-fill'), heatFill = $('heat-fill'), speedEl = $('speed'),
    feedEl = $('feed'), whoEl = $('who');
  whoEl.textContent = MY_NAME;
  let centerTimer = 0;
  function showCenter(text, sticky = false, ms = 1400, color = '') {
    centerEl.textContent = text;
    centerEl.style.color = color || '';
    centerEl.style.opacity = '1';
    clearTimeout(centerTimer);
    if (!sticky) centerTimer = setTimeout(() => { centerEl.style.opacity = '0'; }, ms);
  }
  function nameOf(id) { return id === -1 ? '格栅' : (names.get(id)?.name || `P${id}`).toUpperCase(); }
  function feed(killer, victim) {
    const row = document.createElement('div');
    row.textContent = `${killer} ▸ ${victim}`;
    feedEl.prepend(row);
    while (feedEl.children.length > 4) feedEl.lastChild.remove();
    setTimeout(() => { row.style.opacity = '0'; setTimeout(() => row.remove(), 600); }, 4200);
  }
  // top bar doubles as the stun-recovery meter: full cyan when in control,
  // draining red while systems are offline
  function updateStunBar() {
    if (P.stunT > 0) {
      hpFill.style.width = `${(P.stunT / STUN_S) * 100}%`;
      hpFill.style.background = '#ff5470';
    } else {
      hpFill.style.width = '100%';
      hpFill.style.background = '#53d5fd';
    }
  }
  function updateScore() { killsEl.textContent = `命中 ${board(MY_ID).kills}`; }
  updateStunBar(); updateScore();

  function updateChrome() {
    hud.style.opacity = mode === 'menu' ? '0' : '1';
    document.body.classList.toggle('playing', mode === 'countdown' || mode === 'playing');
  }

  // ------------------------------------------------------------ lifecycle --
  function startMatch() {
    scoreboard.clear();
    board(MY_ID);
    for (const b of bots.bots) board(b.id);
    combat.reset();
    items.reset();
    bots.reset();
    resultsShown = false;
    parkAtFormation();
    matchStartAt = Date.now() + COUNTDOWN_MS;
    matchEndAt = matchStartAt + MATCH_MS;
    lastTickShown = -1;
    timerEl.textContent = '3:00';
    mode = 'countdown';
    updateChrome();
    updateScore(); updateStunBar();
  }

  function pauseGame() {
    if (mode !== 'playing') return;
    mode = 'paused';
    pauseStart = Date.now();
    updateChrome();
    menu.openPause();
  }

  function resumeGame() {
    if (mode !== 'paused') return;
    const held = Date.now() - pauseStart;
    matchStartAt += held; // the clock ignores the pause
    matchEndAt += held;
    mode = 'playing';
    updateChrome();
  }

  function quitToMenu() {
    mode = 'menu';
    firing = false;
    centerEl.style.opacity = '0';
    updateChrome();
    menu.toMain();
  }

  // crashing into the grid is the only way to blow up — bolts just stun
  function die() {
    if (!P.alive) return;
    P.alive = false;
    P.respawnT = RESPAWN_S;
    P.stunT = 0;
    board(MY_ID).deaths++;
    feed(nameOf(-1), nameOf(MY_ID));
    explodeAt(P.pos);
    engine.params.flash = 0.6;
    shake = 1.6;
    sfx.boom();
    myShip.group.visible = false;
    showCenter('撞上格栅', false, 1800);
    updateScore();
  }

  function respawn() {
    P.alive = true;
    P.invulnT = INVULN_S;
    P.pos.set((Math.random() - 0.5) * 24, PLAYER.startY, P.pos.z);
    P.vel.set(0, 0, -PLAYER.cruise);
    P.speed = P.speedHold = PLAYER.cruise;
    P.heat = 0; P.overheated = 0; P.bank = 0;
    myShip.group.visible = true;
  }

  function explodeAt(p, n = 60) {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2, b = (Math.random() - 0.5) * Math.PI;
      const sp = 5 + Math.random() * 24;
      sparks.push({
        p: p.clone(),
        v: new THREE.Vector3(Math.cos(a) * Math.cos(b) * sp, Math.sin(b) * sp + 5, Math.sin(a) * Math.cos(b) * sp),
        life: 0.5 + Math.random() * 1.0, t: 0, hot: Math.random(),
      });
    }
  }

  let resultsShown = false;
  function showResults() {
    resultsShown = true;
    const rows = [...scoreboard.entries()]
      .map(([id, s]) => ({ id, name: nameOf(id), me: id === MY_ID, ...s }))
      .sort((a, b) => b.kills - a.kills || a.deaths - b.deaths);
    const tied = rows.length > 1 && rows[0].kills === rows[1].kills && rows[0].deaths === rows[1].deaths;
    const title = tied ? '<b>平局</b>'
      : rows[0].me ? '你 <b>获胜</b>'
      : `${rows[0].name} <b>获胜</b>`;
    menu.showResults(title, rows);
  }

  // ------------------------------------------------------------ main loop --
  let last = performance.now();
  let lastTickShown = -1;
  let menuT = 0, menuZ = Z_HOME + 30; // attract-flight camera state
  const _lastCamPos = new THREE.Vector3().copy(camera.position);
  const camVel = new THREE.Vector3();

  updateChrome();
  menu.toMain();
  fade.style.opacity = '0';
  setTimeout(() => { fade.style.display = 'none'; }, 2700);

  function frame(now) {
    const dt = Math.min((now - last) / 1000, 0.05);
    last = now;
    const time = engine.time;
    GlobalUniforms.uTime.value = time;
    const nowMs = Date.now();

    if (mode === 'paused') {
      // frozen sim, live render — the pause menu floats over the held frame
      engine.renderReflection(scene, camera);
      city.groundMat.uniforms.uMirrorVP.value.copy(engine.mirrorVP);
      engine.render(scene, camera, dt);
      return;
    }

    // ---- mode transitions
    if (mode === 'countdown') {
      const remain = matchStartAt - nowMs;
      const c = Math.ceil(remain / 1000);
      if (remain <= 0) { mode = 'playing'; updateChrome(); showCenter('开战！', false, 1000); sfx.go(); }
      else if (c !== lastTickShown) { lastTickShown = c; showCenter(`开战倒计时 ${c}`, true); sfx.tick(); }
    }
    if (mode === 'playing' && nowMs >= matchEndAt && !resultsShown) {
      mode = 'over';
      updateChrome();
      showCenter('时间到', false, 1600);
      sfx.boom();
      setTimeout(showResults, 1200);
    }

    // ---- local ship
    const playing = mode === 'playing';
    const parked = mode === 'menu' || mode === 'countdown';
    if (P.alive && !playing && !parked) {
      // match over: cruise straight while the results are up
      stepShip(P, dt, { keys: new Set(), mx: 0, my: 0, burn: false });
      if (P.pos.z < Z_HOME - LOOP) { P.pos.z += LOOP; camera.position.z += LOOP; _lastCamPos.z += LOOP; }
      myShip.group.position.copy(P.pos);
      poseShip(myShip, P.vel.x, P.vel.y, P.speed, P.bank, dt);
      feedHeroLights(P, myShip.accent);
    } else if (P.alive && parked) {
      // parked on the start line: hover in formation, no forward motion —
      // everyone leaves the same line when ENGAGE hits
      burnQueued = false;
      const home = formationPos(MY_SLOT);
      P.pos.x = damp(P.pos.x, home.x, 4, dt);
      P.pos.z = damp(P.pos.z, home.z, 4, dt);
      P.pos.y = home.y + Math.sin(time * 1.7 + MY_SLOT) * 0.5;
      P.vel.set(0, 0, 0);
      P.speed = damp(P.speed, 0, 3, dt);
      P.bank = damp(P.bank, 0, 4, dt);
      myShip.group.position.copy(P.pos);
      poseShip(myShip, 0, 0, PLAYER.minSpeed, P.bank, dt); // idle thruster shimmer
      feedHeroLights(P, myShip.accent);
    } else if (P.alive) {
      const stunned = P.stunT > 0;
      if (stunned) {
        // systems offline: controls dead, the ship coasts and tumbles
        P.stunT -= dt;
        P.vel.x = damp(P.vel.x, 0, 1.2, dt);
        P.vel.y = damp(P.vel.y, -6, 1.5, dt); // sags out of the sky
        P.speed = damp(P.speed, PLAYER.minSpeed * 0.5, 1.4, dt);
        P.vel.z = -P.speed;
        P.pos.addScaledVector(P.vel, dt);
        if (P.pos.y < 2.0) { P.pos.y = 2.0; P.vel.y = 0; }
        P.bank += P.stunSpin * dt; // uncontrolled roll
        for (let i = 0; i < 2; i++) {
          glows.push(P.pos.x + (Math.random() - 0.5), P.pos.y + 0.3, P.pos.z + Math.random(), 2.6, 1.0, 0.3, 0.7, 0);
        }
        if (P.stunT <= 0) {
          P.stunGraceT = STUN_GRACE_S;
          P.bank = P.bank % (Math.PI * 2);
          showCenter('系统恢复上线', false, 800);
        }
        updateStunBar();
      }
      if (P.stunGraceT > 0) P.stunGraceT -= dt;
      const input = stunned
        ? { keys: new Set(), mx: 0, my: 0, burn: false }
        : { keys, mx: mouse.x, my: mouse.y, burn: burnQueued };
      burnQueued = false;
      if (!stunned) {
        if (P.speed < PLAYER.minSpeed) P.speed = Math.max(P.speed, PLAYER.minSpeed * 0.6); // spool up off the line
        stepShip(P, dt, input);
        if (hpFill.style.width !== '100%') updateStunBar();
      }

      // seamless loop wrap (the city repeats every LOOP meters)
      if (P.pos.z < Z_HOME - LOOP) {
        P.pos.z += LOOP;
        camera.position.z += LOOP;
        _lastCamPos.z += LOOP;
        for (const s of sparks) s.p.z += LOOP;
      }

      // obstacle crash → explode + respawn (deathmatch, not run-over)
      if (playing && P.invulnT <= 0) {
        for (const o of city.obstaclesNear(P.pos.z - 60, P.pos.z + 30)) {
          if (o.isHolo) continue;
          const dx = Math.max(o.min.x - P.pos.x, 0, P.pos.x - o.max.x);
          const dy = Math.max(o.min.y - P.pos.y, 0, P.pos.y - o.max.y);
          const dz = Math.max(o.min.z - P.pos.z, 0, P.pos.z - o.max.z);
          if (Math.hypot(dx, dy, dz) - PLAYER.radius <= 0) { die(); break; }
        }
      }

      if (P.alive) {
        // street skim: sparks + shake, not death
        if (P.pos.y < 2.0) {
          P.pos.y = 2.0;
          P.vel.y = Math.max(P.vel.y, 0);
          shake = Math.max(shake, 0.25);
        }
        myShip.group.position.copy(P.pos);
        poseShip(myShip, P.vel.x, P.vel.y, P.speed, P.bank, dt);
        // invulnerability shimmer after respawn
        if (P.invulnT > 0) {
          P.invulnT -= dt;
          myShip.group.visible = Math.sin(time * 30) > -0.6;
          if (P.invulnT <= 0) myShip.group.visible = true;
        }
        if (playing && firing) combat.tryFire(P, dt);
        else combat.fireCd = Math.min(combat.fireCd, 0.05);
        feedHeroLights(P, myShip.accent);
      }
    } else {
      P.respawnT -= dt;
      if (P.respawnT <= 0 && mode !== 'over') respawn();
    }

    // ---- bots: AI pilots on the same physics/combat paths
    bots.update(dt, time);

    // ---- combat + sparks
    glows.begin();
    items.update(dt);
    combat.update(dt, P.invulnT > 0 || P.stunT > 0 || P.stunGraceT > 0 || !P.alive || !playing);
    for (let i = sparks.length - 1; i >= 0; i--) {
      const s = sparks[i];
      s.t += dt;
      if (s.t > s.life) { sparks.splice(i, 1); continue; }
      s.v.y -= 22 * dt;
      s.p.addScaledVector(s.v, dt);
      const k = 1 - s.t / s.life;
      const col = s.hot > 0.6 ? [3.4, 2.2, 0.6] : [3.0, 0.8, 0.3];
      glows.push(s.p.x, s.p.y, s.p.z, col[0] * k, col[1] * k, col[2] * k, 0.5 + k * 0.5, 0);
    }
    glows.end();

    // ---- camera: attract flight (menu) / chase (alive) / wreck orbit (dead)
    if (mode === 'menu') {
      menuT += dt;
      menuZ -= 22 * dt;
      if (menuZ < Z_HOME - LOOP) menuZ += LOOP;
      camera.position.set(
        Math.sin(menuT * 0.12) * 14,
        36 + Math.sin(menuT * 0.23) * 6,
        menuZ,
      );
      camera.lookAt(Math.sin(menuT * 0.12 + 0.5) * 8, 30 + Math.sin(menuT * 0.17) * 4, menuZ - 46);
      camera.fov = damp(camera.fov, 62, 4, dt);
    } else if (P.alive) {
      const back = 8.6 + P.speed * 0.022;
      const tp = new THREE.Vector3(
        P.pos.x * 0.92 - P.vel.x * 0.055,
        Math.max(P.pos.y + 2.9 - P.vel.y * 0.03, 2.2),
        P.pos.z + back,
      );
      const look = new THREE.Vector3(P.pos.x + P.vel.x * 0.22, P.pos.y + P.vel.y * 0.16 - 0.4, P.pos.z - 17);
      if (camera.position.distanceTo(tp) > 100) camera.position.copy(tp);
      else {
        camera.position.x = damp(camera.position.x, tp.x, 7.5, dt);
        camera.position.y = damp(camera.position.y, tp.y, 7.5, dt);
        camera.position.z = damp(camera.position.z, tp.z, 14, dt);
      }
      const m = new THREE.Matrix4().lookAt(camera.position, look, new THREE.Vector3(0, 1, 0));
      const q = new THREE.Quaternion().setFromRotationMatrix(m);
      q.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), P.bank * 0.5));
      camera.quaternion.slerp(q, 1 - Math.exp(-9 * dt));
      const speedN = clamp((P.speed - PLAYER.minSpeed) / (PLAYER.boostSpeed - PLAYER.minSpeed), 0, 1);
      camera.fov = damp(camera.fov, 62 + speedN * 12 + (P.boosting ? 5 : 0), 4, dt);
    } else {
      const t = time * 0.4 + 2.2;
      const c = P.pos;
      const pos = new THREE.Vector3(c.x + Math.cos(t) * 12, Math.max(c.y + 4, 6), c.z + 10 + Math.sin(t) * 5);
      camera.position.lerp(pos, 1 - Math.exp(-2.2 * dt));
      camera.lookAt(c.x, c.y, c.z);
    }
    if (shake > 0.003) {
      camera.rotation.x += (Math.random() - 0.5) * shake * 0.012;
      camera.rotation.y += (Math.random() - 0.5) * shake * 0.012;
      camera.rotation.z += (Math.random() - 0.5) * shake * 0.017;
    }
    shake = Math.max(0, shake - dt * 3.2);
    camera.updateProjectionMatrix();
    updateMarkers();

    // ---- world systems
    const camZ = camera.position.z;
    city.update(camZ, time);
    camVel.copy(camera.position).sub(_lastCamPos).divideScalar(Math.max(dt, 1e-4));
    if (camVel.length() > 400) camVel.set(0, 0, -P.speed); // wrap frame
    _lastCamPos.copy(camera.position);
    life.update(dt, time, camZ, camera.position, camVel, playing);

    engine.params.warp = damp(engine.params.warp, (P.boosting || performance.now() < P.dashUntil) && playing ? 1 : 0, 4, dt);
    engine.params.flash = Math.max(0, engine.params.flash - dt * 2.6);
    engine.params.rain = damp(engine.params.rain, 0.55, 1.2, dt);
    FogUniforms.uFogDensity.value = 0.0027;

    // ---- HUD
    if (playing || mode === 'over') {
      const remain = Math.max(0, matchEndAt - nowMs);
      const mm = Math.floor(remain / 60000), ss = Math.floor((remain % 60000) / 1000);
      timerEl.textContent = `${mm}:${String(ss).padStart(2, '0')}`;
    }
    speedEl.textContent = `${Math.round(P.speed * 3.6)} 公里/时`;
    heatFill.style.width = `${P.heat}%`;
    heatFill.style.background = P.overheated > 0 ? '#ff5470' : '#53d5fd';

    // ---- render
    engine.renderReflection(scene, camera);
    city.groundMat.uniforms.uMirrorVP.value.copy(engine.mirrorVP);
    engine.render(scene, camera, dt);
  }
  function loop(now) {
    requestAnimationFrame(loop);
    frame(now);
  }
  requestAnimationFrame(loop);

  // debug surface
  window.__arena = {
    get P() { return P; }, get mode() { return mode; },
    combat, scoreboard, items,
    get myShip() { return myShip; },
    LOOP, dzLoop,
    bots: () => bots.list(),
    startMatch, quitToMenu,
    endNow: () => { matchEndAt = Math.min(matchEndAt, Date.now()); }, // tests: close out the match
    step: (now) => frame(now), // headless tests: drive frames manually if rAF stalls
  };
}
