// Pickup items for the dogfight. Neon crates float in the canyon; E to use.
// Everything is adjudicated locally: offensive uses are handed to the bots
// (the potential victims) through ctx.broadcast, defensive ones just apply.
// Every pickup and use reports back in Chinese, with hit/range feedback.
import * as THREE from 'three';

const RESPAWN = 8;
const PICKUP_R2 = 6 * 6;
export const SHOCK_R = 28; // shockwave radius — the hit check is spherical

export const ITEM_DEFS = {
  shock:  { label: '冲击波', w: 0.30, color: '#72adf7' },
  emp:    { label: '电磁脉冲', w: 0.22, color: '#c27bff' },
  shield: { label: '护盾', w: 0.24, color: '#7dffc7' },
  dash:   { label: '疾冲', w: 0.24, color: '#35e0ff' },
};

const ICONS = {
  shock: '<circle cx="16" cy="16" r="4" fill="none" stroke="currentColor" stroke-width="2.4"/><circle cx="16" cy="16" r="9" fill="none" stroke="currentColor" stroke-width="2" opacity=".65"/><circle cx="16" cy="16" r="14" fill="none" stroke="currentColor" stroke-width="1.6" opacity=".35"/>',
  emp: '<path d="M17 3L7 18h7l-2 11 11-16h-7z" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round"/>',
  shield: '<path d="M16 4l10 4v8c0 7-4 11-10 13-6-2-10-6-10-13V8z" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round"/>',
  dash: '<path d="M5 8h12M3 16h16M5 24h12" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/><path d="M20 8l7 8-7 8" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>',
};

function rollItem() {
  let total = 0;
  for (const k in ITEM_DEFS) total += ITEM_DEFS[k].w;
  let r = Math.random() * total;
  for (const k in ITEM_DEFS) { r -= ITEM_DEFS[k].w; if (r <= 0) return k; }
  return 'shock';
}

const lerp = (a, b, k) => a + (b - a) * k;

// ctx: { scene, glows, dzLoop, zHome, loop, P, leaderId(), applyHit(byId),
//        broadcast(payload) -> hit report, showMsg(text, ms, color), sfx, isOn() }
export class ArenaItems {
  constructor(ctx) {
    this.ctx = ctx;
    this.held = null;
    this._buildSlot();
    this._buildCrates();
    this._buildFx();
  }

  _buildSlot() {
    const slot = document.createElement('div');
    slot.id = 'item-slot';
    slot.innerHTML = '<span id="item-icon"></span>' +
      '<span class="ibadge">E</span>' +
      '<span id="item-label"></span>';
    document.body.appendChild(slot);
    this.slotEl = slot;
    this.iconEl = slot.querySelector('#item-icon');
    this.labelEl = slot.querySelector('#item-label');
  }

  _setHeld(kind) {
    this.held = kind;
    if (!kind) { this.slotEl.style.display = 'none'; return; }
    const def = ITEM_DEFS[kind];
    this.slotEl.style.display = 'flex';
    this.slotEl.style.borderColor = def.color;
    this.slotEl.style.boxShadow = `0 0 22px ${def.color}55`;
    this.iconEl.innerHTML =
      `<svg viewBox="0 0 32 32" style="width:36px;height:36px;display:block;color:${def.color};filter:drop-shadow(0 0 7px currentColor)">${ICONS[kind]}</svg>`;
    this.labelEl.textContent = `${def.label} · 按 E 使用`;
    this.labelEl.style.color = def.color;
    // pop-in animation
    this.slotEl.classList.remove('pop');
    void this.slotEl.offsetWidth;
    this.slotEl.classList.add('pop');
  }

  _buildCrates() {
    const group = new THREE.Group();
    this.ctx.scene.add(group);
    const shellGeo = new THREE.IcosahedronGeometry(1.6, 0);
    const shellMat = new THREE.MeshBasicMaterial({
      color: new THREE.Color('#72adf7').multiplyScalar(2.0),
      wireframe: true, transparent: true, opacity: 0.9,
    });
    const coreGeo = new THREE.OctahedronGeometry(0.65, 0);
    const coreMat = new THREE.MeshBasicMaterial({
      color: new THREE.Color('#ffffff').multiplyScalar(2.2),
      transparent: true, opacity: 0.95, blending: THREE.AdditiveBlending, depthWrite: false,
    });
    this.boxes = [];
    // 4 rows down the loop × 3 crates (lateral + altitude spread)
    const rows = [40, 160, 280, 400];
    const spots = [[-14, 26], [0, 48], [14, 68]];
    for (let ri = 0; ri < rows.length; ri++) {
      const z = this.ctx.zHome - rows[ri];
      for (let k = 0; k < spots.length; k++) {
        const x = spots[k][0];
        const y = spots[(k + ri) % spots.length][1]; // stagger altitudes per row
        const grp = new THREE.Group();
        grp.position.set(x, y, z);
        grp.add(new THREE.Mesh(shellGeo, shellMat));
        grp.add(new THREE.Mesh(coreGeo, coreMat.clone()));
        group.add(grp);
        this.boxes.push({ grp, x, y, z, active: true, respawn: 0, phase: Math.random() * 6.28 });
      }
    }
  }

  // In-world feedback meshes: shield bubble, shock range hint, shock wave shell
  _buildFx() {
    // shield bubble around the player while the item shield is up
    this.shieldFx = new THREE.Mesh(
      new THREE.SphereGeometry(3.1, 28, 20),
      new THREE.MeshBasicMaterial({
        color: new THREE.Color('#7dffc7').multiplyScalar(1.6),
        transparent: true, opacity: 0.16, blending: THREE.AdditiveBlending,
        depthWrite: false, side: THREE.DoubleSide,
      }),
    );
    const shieldWire = new THREE.Mesh(
      new THREE.SphereGeometry(3.25, 12, 8),
      new THREE.MeshBasicMaterial({
        color: new THREE.Color('#7dffc7').multiplyScalar(1.8),
        wireframe: true, transparent: true, opacity: 0.28,
        blending: THREE.AdditiveBlending, depthWrite: false,
      }),
    );
    this.shieldFx.add(shieldWire);
    this.shieldFx.visible = false;
    this.ctx.scene.add(this.shieldFx);

    // faint sphere showing the shockwave's 28 m reach while one is held
    this.rangeFx = new THREE.Mesh(
      new THREE.SphereGeometry(SHOCK_R, 36, 24),
      new THREE.MeshBasicMaterial({
        color: new THREE.Color('#72adf7'),
        transparent: true, opacity: 0.05, blending: THREE.AdditiveBlending,
        depthWrite: false, side: THREE.BackSide,
      }),
    );
    const rangeRim = new THREE.Mesh(
      new THREE.SphereGeometry(SHOCK_R, 18, 12),
      new THREE.MeshBasicMaterial({
        color: new THREE.Color('#72adf7'),
        wireframe: true, transparent: true, opacity: 0.045,
        blending: THREE.AdditiveBlending, depthWrite: false,
      }),
    );
    this.rangeFx.add(rangeRim);
    this.rangeFx.visible = false;
    this.ctx.scene.add(this.rangeFx);

    // expanding shell when the shockwave fires
    this.waveFx = new THREE.Mesh(
      new THREE.SphereGeometry(1, 36, 24),
      new THREE.MeshBasicMaterial({
        color: new THREE.Color('#9cc6ff').multiplyScalar(1.3),
        transparent: true, opacity: 0, blending: THREE.AdditiveBlending,
        depthWrite: false, side: THREE.DoubleSide,
      }),
    );
    this.waveFx.visible = false;
    this.waveT = 1e9;
    this.ctx.scene.add(this.waveFx);
  }

  // Back to a fresh board (between matches): no held item, every crate live.
  reset() {
    this._setHeld(null);
    this.waveFx.visible = false;
    this.rangeFx.visible = false;
    this.shieldFx.visible = false;
    for (const b of this.boxes) {
      b.active = true; b.respawn = 0;
      b.grp.visible = true;
      b.grp.scale.setScalar(1);
    }
  }

  use() {
    if (!this.held || !this.ctx.isOn()) return;
    const kind = this.held;
    this._setHeld(null);
    const P = this.ctx.P;
    const r = (v) => Math.round(v * 100) / 100;
    if (kind === 'shock') {
      this._fireWave(P.pos);
      this._burst(P.pos, 26, [1.4, 2.4, 3.6]);
      this.ctx.sfx.boom?.();
      // the bots adjudicate — and report who was actually inside the radius
      const rep = this.ctx.broadcast({ sub: 'shock', x: r(P.pos.x), y: r(P.pos.y), z: r(P.pos.z) });
      if (rep && rep.hitNames.length) {
        this.ctx.showMsg(`冲击波 · 命中 ${rep.hitNames.join('、')}`, 1600, '#9cc6ff');
      } else if (rep && rep.safeNames.length) {
        this.ctx.showMsg(`冲击波 · ${rep.safeNames.join('、')} 处于保护状态`, 1600, '#9cc6ff');
      } else {
        this.ctx.showMsg(`冲击波 · ${SHOCK_R} 米内无目标`, 1400, '#9cc6ff');
      }
    } else if (kind === 'emp') {
      const target = this.ctx.leaderId();
      if (target == null) {
        this.ctx.showMsg('电磁脉冲 · 无可锁定目标', 1400, '#c27bff');
        this._setHeld(kind); // no one to lock — hand the item back
        return;
      }
      this.ctx.sfx.zapOut?.();
      const rep = this.ctx.broadcast({ sub: 'emp', targetId: target });
      if (rep && rep.pos) this._empBeam(P.pos, rep.pos);
      if (rep && rep.hit) {
        this.ctx.showMsg(`电磁脉冲 · 命中 ${rep.name}`, 1600, '#c27bff');
      } else if (rep) {
        this.ctx.showMsg(`电磁脉冲 · ${rep.name} 处于保护状态`, 1600, '#c27bff');
      }
    } else if (kind === 'shield') {
      P.itemShieldT = 8;
      this.ctx.showMsg('护盾启动 · 8 秒内抵挡一次命中', 1600, '#7dffc7');
      this.ctx.sfx.shieldUp?.();
    } else if (kind === 'dash') {
      P.dashUntil = performance.now() + 2500;
      this.ctx.showMsg('疾冲 · 极速推进 2.5 秒', 1400, '#35e0ff');
      this.ctx.sfx.go?.();
    }
  }

  // my shield eats one incoming hit (bolt or item)
  tryBlock() {
    const P = this.ctx.P;
    if (P.itemShieldT > 0) {
      P.itemShieldT = 0;
      this.ctx.showMsg('护盾格挡！', 1200, '#7dffc7');
      this._burst(P.pos, 8, [1.2, 3.4, 2.2]);
      this.ctx.sfx.shieldUp?.();
      return true;
    }
    return false;
  }

  _fireWave(p) {
    this.waveFx.position.copy(p);
    this.waveFx.visible = true;
    this.waveT = 0;
  }

  // purple arc from my ship to the EMP victim (loop-adjusted)
  _empBeam(from, toRaw) {
    const to = {
      x: toRaw.x, y: toRaw.y,
      z: from.z + this.ctx.dzLoop(toRaw.z, from.z),
    };
    const n = 26;
    for (let i = 0; i <= n; i++) {
      const k = i / n;
      this.ctx.glows.push(
        lerp(from.x, to.x, k) + (Math.random() - 0.5) * 1.2,
        lerp(from.y, to.y, k) + (Math.random() - 0.5) * 1.2,
        lerp(from.z, to.z, k) + (Math.random() - 0.5) * 1.2,
        2.0, 0.9, 3.6, 0.9, 0,
      );
    }
    this._burst(to, 4, [2.4, 1.0, 4.0]);
  }

  _burst(p, radius, col = [1.4, 2.4, 3.6]) {
    for (let i = 0; i < 24; i++) {
      const a = Math.random() * Math.PI * 2, b = (Math.random() - 0.5) * Math.PI;
      const rr = radius * (0.3 + Math.random() * 0.7);
      this.ctx.glows.push(
        p.x + Math.cos(a) * Math.cos(b) * rr * 0.4,
        p.y + Math.sin(b) * rr * 0.3,
        p.z + Math.sin(a) * Math.cos(b) * rr * 0.4,
        col[0], col[1], col[2], 1.1, 0,
      );
    }
  }

  update(dt) {
    const P = this.ctx.P;
    const t = performance.now() / 1000;
    for (const b of this.boxes) {
      if (!b.active) {
        b.respawn -= dt;
        if (b.respawn <= 0) { b.active = true; b.grp.visible = true; b.grp.scale.setScalar(0.01); }
        continue;
      }
      const pop = Math.min(1, b.grp.scale.x + dt * 3);
      if (pop < 1) b.grp.scale.setScalar(pop);
      b.grp.rotation.y += dt * 1.4;
      b.grp.position.y = b.y + Math.sin(t * 1.8 + b.phase) * 0.6;
      if (this.ctx.isOn() && !this.held) {
        const dz = this.ctx.dzLoop(b.z, P.pos.z);
        const dx = P.pos.x - b.x, dy = P.pos.y - b.grp.position.y;
        if (dx * dx + dy * dy + dz * dz < PICKUP_R2) {
          const kind = rollItem();
          this._setHeld(kind);
          b.active = false; b.respawn = RESPAWN; b.grp.visible = false;
          const def = ITEM_DEFS[kind];
          const c = new THREE.Color(def.color);
          this._burst(b.grp.position, 5, [c.r * 3, c.g * 3, c.b * 3]); // crate pop flash
          this.ctx.showMsg(`已拾取 · ${def.label}`, 1400, def.color);
          this.ctx.sfx.pickup?.();
        }
      }
    }
    if (P.itemShieldT > 0) P.itemShieldT -= dt;

    // ---- feedback meshes follow the player
    if (this.shieldFx) {
      this.shieldFx.visible = P.itemShieldT > 0 && this.ctx.P.alive !== false;
      if (this.shieldFx.visible) {
        this.shieldFx.position.copy(P.pos);
        const k = Math.min(1, P.itemShieldT / 8);
        this.shieldFx.material.opacity = 0.10 + 0.08 * k + Math.sin(t * 6) * 0.03;
        this.shieldFx.rotation.y += dt * 0.8;
      }
      // shock range hint while a shockwave is in hand
      this.rangeFx.visible = this.held === 'shock' && this.ctx.isOn();
      if (this.rangeFx.visible) {
        this.rangeFx.position.copy(P.pos);
        this.rangeFx.material.opacity = 0.04 + Math.sin(t * 3.2) * 0.015;
      }
      // expanding shockwave shell
      if (this.waveFx.visible) {
        this.waveT += dt;
        const k = this.waveT / 0.55;
        if (k >= 1) this.waveFx.visible = false;
        else {
          const e = 1 - (1 - k) * (1 - k); // ease-out
          this.waveFx.scale.setScalar(2 + (SHOCK_R - 2) * e);
          this.waveFx.material.opacity = 0.15 * (1 - k);
        }
      }
    }
  }
}
