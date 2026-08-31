// AI pilots for the dogfight. Three bots fly the same airframe physics as the
// player (stepShip) on computed inputs: they run the canyon loop, dodge grid
// geometry, chase the nearest opponent with lead pursuit and fire bolts
// through the shared Combat pool — stuns, grid deaths, respawns and scoring
// all reuse the local player's code paths.
import * as THREE from 'three';
import { WORLD, PLAYER } from '../config.js';
import { clamp, damp } from '../utils.js';
import { buildShip, poseShip, stepShip, SHIP_RADIUS } from './ship.js';

const BOT_IDS = [90, 91, 92]; // the player is id 0
const MARGIN = 4.2;           // safety padding around obstacle boxes
const FIRE_RANGE = 130;       // m — max bolt engagement distance

function makeState(slot, formationPos) {
  const home = formationPos(slot);
  return {
    pos: home.clone(), vel: new THREE.Vector3(0, 0, 0),
    speed: 0, speedHold: PLAYER.cruise,
    heat: 0, overheated: 0, burnCd: 0, boosting: false, bank: 0,
    alive: true, respawnT: 0, invulnT: 0,
    stunT: 0, stunSpin: 0, stunGraceT: 0,
    itemShieldT: 0, dashUntil: 0,
  };
}

export class ArenaBots {
  // ctx: { scene, city, combat, glows, sfx, dzLoop, loop, zHome, formationPos,
  //        playerP, getMode(), board, myId(), nameOf, feed, explodeAt,
  //        showCenter, updateScore, STUN_S, STUN_GRACE_S, RESPAWN_S, INVULN_S }
  constructor(ctx, npcs) {
    this.ctx = ctx;
    this.bots = npcs.map((n, i) => {
      const id = BOT_IDS[i];
      const ship = buildShip({ color: n.color, name: n.name, showTag: true });
      ctx.scene.add(ship.group);
      const state = makeState(i + 1, ctx.formationPos); // slots 1..3 (player = 0)
      ship.group.position.copy(state.pos);
      ctx.board(id);
      return {
        id, name: n.name, color: n.color, ship, state,
        slot: i + 1, keys: new Set(),
        fireCd: 0, coolT: Math.random() * 0.6, shots: 0, inSights: false,
        skill: 0.92 + i * 0.04, // beatable: each bot a touch quicker
      };
    });
  }

  // debug/test surface for window.__arena.bots()
  list() {
    return this.bots.map(b => ({
      name: b.name,
      color: b.color.toString(16).padStart(6, '0'),
      x: +b.state.pos.x.toFixed(2), y: +b.state.pos.y.toFixed(2), z: +b.state.pos.z.toFixed(2),
      speed: +b.state.speed.toFixed(1),
      alive: b.state.alive, stunned: b.state.stunT > 0,
      hits: this.ctx.board(b.id).kills, deaths: this.ctx.board(b.id).deaths,
    }));
  }

  aliveIds() { return this.bots.filter(b => b.state.alive).map(b => b.id); }

  // Back to the start line with a clean state (between matches).
  reset() {
    for (const b of this.bots) {
      b.state = makeState(b.slot, this.ctx.formationPos);
      b.ship.group.position.copy(b.state.pos);
      b.ship.group.visible = true;
      b.keys.clear();
      b.fireCd = 0; b.coolT = Math.random() * 0.6; b.shots = 0; b.inSights = false;
    }
  }

  _dist(a, b) {
    return Math.abs(this.ctx.dzLoop(a.z, b.z)) + Math.hypot(a.x - b.x, a.y - b.y);
  }

  // ---- shared consequence paths (mirror hitMe/die/respawn in main.js) -----

  // Returns true when the stun actually landed (false = protected / not playing)
  hitBot(b, byId) {
    const s = b.state, ctx = this.ctx;
    if (!s.alive || ctx.getMode() !== 'playing') return false;
    if (s.stunT > 0 || s.stunGraceT > 0 || s.invulnT > 0) return false;
    s.stunT = ctx.STUN_S;
    s.stunSpin = (Math.random() < 0.5 ? -1 : 1) * (5 + Math.random() * 3);
    if (byId >= 0) ctx.board(byId).kills++;
    ctx.board(b.id).deaths++;
    if (byId === ctx.myId()) ctx.sfx.kill();
    ctx.feed(ctx.nameOf(byId), ctx.nameOf(b.id));
    ctx.explodeAt(s.pos, 18);
    ctx.updateScore();
    return true;
  }

  crash(b) {
    const s = b.state, ctx = this.ctx;
    if (!s.alive) return;
    s.alive = false;
    s.respawnT = ctx.RESPAWN_S;
    s.stunT = 0;
    ctx.board(b.id).deaths++;
    ctx.feed(ctx.nameOf(-1), ctx.nameOf(b.id));
    ctx.explodeAt(s.pos);
    ctx.sfx.boom();
    b.ship.group.visible = false;
    ctx.updateScore();
  }

  respawn(b) {
    const s = b.state, ctx = this.ctx;
    s.alive = true;
    s.invulnT = ctx.INVULN_S;
    s.pos.set((Math.random() - 0.5) * 24, PLAYER.startY, s.pos.z);
    s.vel.set(0, 0, -PLAYER.cruise);
    s.speed = s.speedHold = PLAYER.cruise;
    s.heat = 0; s.overheated = 0; s.bank = 0;
    b.ship.group.visible = true;
  }

  // Victim-side adjudication of the LOCAL player's item uses — the bots answer
  // shock/EMP exactly like the player would (stun, scoring, feed), and report
  // back who was hit so the HUD can announce the result in Chinese.
  onItem(msg) {
    if (msg.sub === 'shock') {
      const hitNames = [], safeNames = [];
      for (const b of this.bots) {
        const s = b.state;
        if (!s.alive) continue;
        const dz = this.ctx.dzLoop(msg.z, s.pos.z);
        const dx = msg.x - s.pos.x, dy = msg.y - s.pos.y;
        if (dx * dx + dy * dy + dz * dz < 28 * 28) {
          if (this.hitBot(b, msg.from)) hitNames.push(b.name);
          else safeNames.push(b.name);
        }
      }
      return { hitNames, safeNames };
    } else if (msg.sub === 'emp') {
      const b = this.bots.find(x => x.id === msg.targetId);
      if (!b || !b.state.alive) return { hit: false, name: b ? b.name : '?', pos: null };
      const pos = { x: b.state.pos.x, y: b.state.pos.y, z: b.state.pos.z };
      const hit = this.hitBot(b, msg.from);
      return { hit, name: b.name, pos };
    }
    return null;
  }

  // ------------------------------------------------------------------ AI ---
  _pilot(b) {
    const ctx = this.ctx, s = b.state;
    const keys = b.keys;
    keys.delete('KeyW'); keys.delete('KeyS'); keys.delete('ShiftLeft');

    // nearest opponent on the loop (the player counts like any other ship)
    let tgt = null, tgtD = Infinity;
    const pp = ctx.playerP;
    if (pp.alive) { tgt = pp; tgtD = this._dist(pp.pos, s.pos); }
    for (const o of this.bots) {
      if (o === b || !o.state.alive) continue;
      const d = this._dist(o.state.pos, s.pos);
      if (d < tgtD) { tgtD = d; tgt = o.state; }
    }

    // nearest obstacle box intersecting our safety corridor ahead
    const look = 34 + s.speed * 1.05;
    let threat = null, threatDz = Infinity;
    for (const o of ctx.city.obstaclesNear(s.pos.z - look, s.pos.z + 6)) {
      if (o.isHolo) continue;
      const dz = s.pos.z - o.max.z; // flight is -z: positive = box ahead
      if (dz < -8 || dz > look) continue;
      if (s.pos.x > o.min.x - MARGIN && s.pos.x < o.max.x + MARGIN &&
          s.pos.y > o.min.y - MARGIN && s.pos.y < o.max.y + MARGIN &&
          dz < threatDz) { threat = o; threatDz = dz; }
    }

    let wantX = 0, wantY = PLAYER.startY, wantSpd = 46, burn = false;
    if (threat) {
      wantSpd = 40;
      const fullWidth = threat.min.x < -30 && threat.max.x > 30;
      const roomL = (threat.min.x - MARGIN) + WORLD.roadHalf;
      const roomR = WORLD.roadHalf - (threat.max.x + MARGIN);
      if (fullWidth || (roomL < 7 && roomR < 7)) {
        // no way around — over or under, with a vertical burn if it's close
        const mid = (threat.min.y + threat.max.y) / 2;
        const under = threat.min.y - MARGIN - 3;
        wantY = (s.pos.y >= mid || under < 4) ? threat.max.y + MARGIN + 3 : under;
        wantX = clamp(s.pos.x, -16, 16);
        if (wantY > s.pos.y + 2 && threatDz < 30) burn = true;
      } else if (roomL > roomR) {
        wantX = clamp(threat.min.x - MARGIN - 4, -34, 34);
        wantY = clamp(s.pos.y, 4, PLAYER.ceiling0 - 6);
      } else {
        wantX = clamp(threat.max.x + MARGIN + 4, -34, 34);
        wantY = clamp(s.pos.y, 4, PLAYER.ceiling0 - 6);
      }
    } else if (tgt) {
      // lead pursuit: aim where the target will be when a bolt gets there
      const lead = clamp(tgtD / 170, 0, 0.7);
      wantX = clamp(tgt.pos.x + tgt.vel.x * lead, -30, 30);
      wantY = clamp(tgt.pos.y + tgt.vel.y * lead, 4, PLAYER.ceiling0 - 6);
      const dzT = ctx.dzLoop(tgt.pos.z, s.pos.z);
      if (dzT < -25 && s.heat < 65) keys.add('ShiftLeft'); // boost to catch up
      wantSpd = dzT < -10 ? 52 : 46;
    }
    wantSpd *= b.skill;

    // fire solution against the same target (skip while evading)
    b.inSights = false;
    if (tgt && !threat) {
      const dz = ctx.dzLoop(tgt.pos.z, s.pos.z);
      if (dz < -8 && dz > -FIRE_RANGE) {
        const dist = -dz, t = dist / 170;
        const ex = tgt.pos.x + tgt.vel.x * t - s.pos.x;
        const ey = tgt.pos.y + tgt.vel.y * t - s.pos.y;
        const tol = 3.4 + dist * 0.035;
        b.inSights = Math.abs(ex) < tol && Math.abs(ey) < tol;
      }
    }

    // throttle toward the wanted speed, steer toward the wanted point
    if (s.speedHold < wantSpd - 1) keys.add('KeyW');
    else if (s.speedHold > wantSpd + 1) keys.add('KeyS');
    const mx = clamp((wantX - s.pos.x) * 1.4 / PLAYER.latMax, -1, 1);
    const my = clamp(-(wantY - s.pos.y) * 1.1 / PLAYER.vertMax, -1, 1);
    return { keys, mx, my, burn };
  }

  _trigger(b, dt) {
    const s = b.state;
    b.fireCd -= dt;
    b.coolT -= dt;
    if (b.fireCd > 0 || b.coolT > 0 || !b.inSights) return;
    this.ctx.combat.fireFrom(s, b.id); // victim-adjudicated, same as player shots
    b.fireCd = 0.22;                   // the regulation fire interval
    if (++b.shots % 7 === 0) b.coolT = 0.5 + Math.random() * 0.7; // burst pauses
  }

  // ------------------------------------------------------------- per frame -
  update(dt, time) {
    const ctx = this.ctx;
    const mode = ctx.getMode();
    const playing = mode === 'playing';
    const parked = mode === 'menu' || mode === 'countdown';
    for (const b of this.bots) {
      const s = b.state;
      if (!s.alive) {
        s.respawnT -= dt;
        if (s.respawnT <= 0 && mode !== 'over') this.respawn(b);
        continue;
      }
      if (parked) {
      // hover on the start line, same as the local ship
        const home = ctx.formationPos(b.slot);
        s.pos.x = damp(s.pos.x, home.x, 4, dt);
        s.pos.z = damp(s.pos.z, home.z, 4, dt);
        s.pos.y = home.y + Math.sin(time * 1.7 + b.slot) * 0.5;
        s.vel.set(0, 0, 0);
        s.speed = damp(s.speed, 0, 3, dt);
        s.bank = damp(s.bank, 0, 4, dt);
        b.ship.group.position.copy(s.pos);
        poseShip(b.ship, 0, 0, PLAYER.minSpeed, s.bank, dt);
        continue;
      }
      if (mode === 'over') {
        // results are up: cruise straight, same as the local ship
        stepShip(s, dt, { keys: b.keys, mx: 0, my: 0, burn: false });
        if (s.pos.z < ctx.zHome - ctx.loop) s.pos.z += ctx.loop;
        b.ship.group.position.copy(s.pos);
        poseShip(b.ship, s.vel.x, s.vel.y, s.speed, s.bank, dt);
        continue;
      }
      if (s.stunT > 0) {
        // systems offline: coast + tumble (mirrors the local stun branch)
        s.stunT -= dt;
        s.vel.x = damp(s.vel.x, 0, 1.2, dt);
        s.vel.y = damp(s.vel.y, -6, 1.5, dt);
        s.speed = damp(s.speed, PLAYER.minSpeed * 0.5, 1.4, dt);
        s.vel.z = -s.speed;
        s.pos.addScaledVector(s.vel, dt);
        if (s.pos.y < 2.0) { s.pos.y = 2.0; s.vel.y = 0; }
        s.bank += s.stunSpin * dt;
        for (let i = 0; i < 2; i++) {
          ctx.glows.push(s.pos.x + (Math.random() - 0.5), s.pos.y + 0.3, s.pos.z + Math.random(), 2.6, 1.0, 0.3, 0.7, 0);
        }
        if (s.stunT <= 0) { s.stunGraceT = ctx.STUN_GRACE_S; s.bank = s.bank % (Math.PI * 2); }
      } else {
        if (s.stunGraceT > 0) s.stunGraceT -= dt;
        const input = this._pilot(b);
        if (s.speed < PLAYER.minSpeed) s.speed = Math.max(s.speed, PLAYER.minSpeed * 0.6);
        stepShip(s, dt, input);
      }
      // seamless loop wrap (same boundary as the local ship)
      if (s.pos.z < ctx.zHome - ctx.loop) s.pos.z += ctx.loop;

      // grid crash → explode + respawn (same box-sphere test as the player)
      if (playing && s.invulnT <= 0) {
        for (const o of ctx.city.obstaclesNear(s.pos.z - 60, s.pos.z + 30)) {
          if (o.isHolo) continue;
          const dx = Math.max(o.min.x - s.pos.x, 0, s.pos.x - o.max.x);
          const dy = Math.max(o.min.y - s.pos.y, 0, s.pos.y - o.max.y);
          const dz = Math.max(o.min.z - s.pos.z, 0, s.pos.z - o.max.z);
          if (Math.hypot(dx, dy, dz) - PLAYER.radius <= 0) { this.crash(b); break; }
        }
        if (!s.alive) continue;
      }

      if (s.pos.y < 2.0) { s.pos.y = 2.0; s.vel.y = Math.max(s.vel.y, 0); }
      b.ship.group.position.copy(s.pos);
      poseShip(b.ship, s.vel.x, s.vel.y, s.speed, s.bank, dt);
      if (s.invulnT > 0) {
        s.invulnT -= dt;
        b.ship.group.visible = Math.sin(time * 30) > -0.6;
        if (s.invulnT <= 0) b.ship.group.visible = true;
      }
      // nametag fade with loop distance to the player
      if (b.ship.tag) {
        b.ship.tag.material.opacity = clamp(2.0 - Math.abs(ctx.dzLoop(s.pos.z, ctx.playerP.pos.z)) / 260, 0, 1);
      }
      if (playing && s.stunT <= 0) this._trigger(b, dt);
    }

    // bolts vs bots — victim adjudication (my bolts + other bots' bolts)
    for (const bolt of ctx.combat.bolts) {
      if (!bolt.active) continue;
      for (const b of this.bots) {
        const s = b.state;
        if (!s.alive || bolt.from === b.id) continue;
        const dz = ctx.dzLoop(bolt.p.z, s.pos.z);
        const dx = bolt.p.x - s.pos.x, dy = bolt.p.y - s.pos.y;
        if (dx * dx + dy * dy + dz * dz < SHIP_RADIUS * SHIP_RADIUS) {
          ctx.combat.killBolt(bolt);
          this.hitBot(b, bolt.from);
          break;
        }
      }
    }
  }
}
