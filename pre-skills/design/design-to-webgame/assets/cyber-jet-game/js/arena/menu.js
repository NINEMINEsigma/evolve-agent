// Terminal-style menu system: right-aligned column over the live scene.
// Keyboard and mouse share one selection state; screens replay their staggered
// entrance every time they open. Blips are synthesized on the spot (lazy
// AudioContext on the first user gesture). Settings persist to localStorage.
import { QUALITY_PRESETS, QUALITY_ORDER, STORAGE } from '../config.js';

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

// ------------------------------------------------------------------ blips --
const blip = (() => {
  let ctx = null;
  let enabled = true;
  const ac = () => (ctx = ctx || new (window.AudioContext || window.webkitAudioContext)());
  const tone = (freq, dur, gain, delay = 0) => {
    if (!enabled) return;
    try {
      const t0 = ac().currentTime + delay;
      const o = ac().createOscillator();
      const g = ac().createGain();
      o.type = 'sine'; o.frequency.value = freq;
      g.gain.setValueAtTime(gain, t0);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
      o.connect(g); g.connect(ac().destination);
      o.start(t0); o.stop(t0 + dur + 0.02);
    } catch { /* audio unavailable */ }
  };
  return {
    nav: () => tone(2100, 0.05, 0.035),
    confirm: () => { tone(1320, 0.06, 0.04); tone(1980, 0.09, 0.04, 0.07); },
    back: () => tone(880, 0.05, 0.03),
    set enabled(v) { enabled = v; },
    get enabled() { return enabled; },
  };
})();

export class Menu {
  // hooks: { onStart(), onResume(), onRestart(), onQuit(), onQuality(name), onSound(on) }
  constructor(hooks) {
    this.hooks = hooks;
    this.screens = {};
    for (const el of $$('.screen')) this.screens[el.dataset.screen] = el;
    this.stack = [];
    this.active = null;
    this.sel = 0;
    this.items = [];

    this.quality = localStorage.getItem(STORAGE.quality) || '均衡';
    if (!QUALITY_PRESETS[this.quality]) this.quality = '均衡';
    this.sound = (localStorage.getItem(STORAGE.sound) ?? 'ON') === 'ON';
    blip.enabled = this.sound;

    // menu keyboard (captures while a screen is active)
    window.addEventListener('keydown', (e) => {
      if (!this.active) return;
      const k = e.code;
      if (k === 'ArrowUp' || k === 'KeyW') this._move(-1);
      else if (k === 'ArrowDown' || k === 'KeyS') this._move(1);
      else if (k === 'Enter' || k === 'Space') this._confirm();
      else if (k === 'ArrowLeft' || k === 'KeyA') this._cycle(-1);
      else if (k === 'ArrowRight' || k === 'KeyD') this._cycle(1);
      else if (k === 'Escape') this._back();
      else return;
      e.preventDefault();
      e.stopImmediatePropagation(); // menu owns the key — don't leak to flight controls
    }, true);

    // item hover + click share the keyboard selection state
    for (const name in this.screens) {
      [...this.screens[name].querySelectorAll('.item')].forEach((el, i) => {
        el.addEventListener('mouseenter', () => {
          if (this.active !== name || this.sel === i) return;
          this.sel = i; this._paintSel(); blip.nav();
        });
        el.addEventListener('click', () => {
          if (this.active !== name) return;
          this.sel = i; this._paintSel();
          this._confirm();
        });
      });
    }
  }

  // ------------------------------------------------------------ screens --
  showScreen(name, push = true) {
    if (this.active === name) return;
    if (this.active && push) this.stack.push(this.active);
    for (const n in this.screens) this.screens[n].classList.remove('active');
    const el = this.screens[name];
    // stagger index + reflow so the entrance replays on every open
    el.querySelectorAll('.anim').forEach((n, i) => n.style.setProperty('--i', i));
    void el.offsetWidth;
    el.classList.add('active');
    document.body.classList.add('menu-open');
    this.active = name;
    this.items = [...el.querySelectorAll('.item')];
    this.sel = 0;
    this._paintSel();
    this._syncVals();
  }

  hideAll() {
    for (const n in this.screens) this.screens[n].classList.remove('active');
    document.body.classList.remove('menu-open');
    this.active = null;
    this.stack.length = 0;
  }

  isOpen() { return !!this.active; }

  _move(d) {
    if (!this.items.length) return;
    this.sel = (this.sel + d + this.items.length) % this.items.length;
    this._paintSel();
    blip.nav();
  }

  _paintSel() {
    this.items.forEach((el, i) => {
      const on = i === this.sel;
      el.classList.toggle('sel', on);
      if (on) { // one-shot lateral nudge on every selection change
        el.classList.remove('nudge');
        void el.offsetWidth;
        el.classList.add('nudge');
      }
    });
  }

  _confirm() {
    const el = this.items[this.sel];
    if (!el) return;
    if (el.dataset.val) { this._cycle(1); return; }
    blip.confirm();
    switch (el.dataset.act) {
      case 'start': this.hideAll(); this.hooks.onStart(); break;
      case 'controls': this.showScreen('controls'); break;
      case 'items': this.showScreen('items'); break;
      case 'settings': this.showScreen('settings'); break;
      case 'back': this._back(); break;
      case 'resume': this.hideAll(); this.hooks.onResume(); break;
      case 'restart': this.hideAll(); this.hooks.onRestart(); break;
      case 'rematch': this.hideAll(); this.hooks.onRestart(); break;
      case 'quit': this.hooks.onQuit(); break; // game switches mode, then calls toMain()
    }
  }

  _cycle(d) {
    const el = this.items[this.sel];
    if (!el || !el.dataset.val) return;
    blip.nav();
    if (el.dataset.val === 'quality') {
      const i = QUALITY_ORDER.indexOf(this.quality);
      this.quality = QUALITY_ORDER[(i + d + QUALITY_ORDER.length) % QUALITY_ORDER.length];
      localStorage.setItem(STORAGE.quality, this.quality);
      this.hooks.onQuality(this.quality);
    } else if (el.dataset.val === 'sound') {
      this.sound = !this.sound;
      localStorage.setItem(STORAGE.sound, this.sound ? 'ON' : 'OFF');
      blip.enabled = this.sound;
      this.hooks.onSound(this.sound);
    }
    this._syncVals();
  }

  _syncVals() {
    const q = $('.item[data-val="quality"] .vtext');
    if (q) q.textContent = this.quality;
    const s = $('.item[data-val="sound"] .vtext');
    if (s) s.textContent = this.sound ? 'ON' : 'OFF';
  }

  _back() {
    blip.back();
    if (this.active === 'pause') { this.hideAll(); this.hooks.onResume(); return; }
    if (this.active === 'results') { this.hooks.onQuit(); return; }
    const prev = this.stack.pop();
    if (prev) this.showScreen(prev, false);
    else this.showScreen('main', false);
  }

  // ------------------------------------------------------- game events ---
  toMain() {
    this.hideAll();
    this.showScreen('main');
  }

  openPause() {
    this.stack.length = 0;
    this.showScreen('pause', false);
  }

  // rows: [{name, kills, deaths, me}] sorted by standing; title: result headline
  showResults(title, rows) {
    $('#r-title').innerHTML = title;
    $('#r-rows').innerHTML = rows.map((r, i) =>
      `<div class="row anim${r.me ? ' me' : ''}" style="--i:${i + 2}">` +
      `<span class="k">${String(i + 1).padStart(2, '0')} — ${r.name}</span>` +
      `<span class="v">命中 ${r.kills} · 被击落 ${r.deaths}</span></div>`,
    ).join('');
    this.stack.length = 0;
    this.showScreen('results', false);
  }
}
