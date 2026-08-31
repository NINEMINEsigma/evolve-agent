// Global tuning constants for CYBER SPACESHIP / neon rain canyon.

export const WORLD = {
  chunkLen: 160,          // meters per city chunk
  chunkCount: 10,         // live chunks ahead/behind camera
  roadHalf: 26,           // clear canyon half-width (collision wall)
  canyonHalf: 30,         // visual building face distance
  groundY: 0,
  loopChunks: 3,          // chunk seeds repeat -> seamless 480 m arena loop
};

export const COLORS = {
  // scene accent — cyan sampled from the holo key light. HUD + key emissives share it.
  accent: 0x53d5fd,
  accent2: 0xff3d7f,      // scene-side magenta
  amber: 0xffb54d,
  fogLow: 0x0a1220,
  fogHigh: 0x05070e,
  sky: 0x05070e,
};

export const QUALITY_PRESETS = {
  影院级:   { scale: 1.45, reflScale: 0.5,  rain: 7000, bloomMips: 6, steam: 110, peds: 16, fxaa: true },
  高:     { scale: 1.2,  reflScale: 0.42, rain: 5200, bloomMips: 6, steam: 84,  peds: 13, fxaa: true },
  均衡: { scale: 1.0,  reflScale: 0.33, rain: 3600, bloomMips: 5, steam: 56,  peds: 9,  fxaa: true },
};
export const QUALITY_ORDER = ['均衡', '高', '影院级'];

export const PLAYER = {
  cruise: 40,             // m/s baseline forward speed
  minSpeed: 27,
  maxSpeed: 54,
  boostSpeed: 74,
  throttleRate: 22,       // W/S accel
  latMax: 26,             // max lateral speed
  vertMax: 18,
  steerLag: 4.8,          // 1/s responsiveness
  burnImpulse: 21,        // Space vertical burn (m/s added)
  burnCooldown: 1.9,
  heatRate: 30,           // boost heat per second (~3.4s of boost)
  coolRate: 34,
  overheatLock: 2.2,
  radius: 1.35,           // collision sphere
  startY: 46,
  ceiling0: 84,           // clearance ceiling
};

export const STORAGE = {
  quality: 'cyberspaceship.quality',
  sound: 'cyberspaceship.sound',
};
