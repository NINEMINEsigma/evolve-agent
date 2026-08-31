import * as THREE from 'three';
import { FogUniforms, GlobalUniforms } from './utils.js';

// Sky dome: ink-blue night, low storm cloud deck lit from below by the city,
// horizon light pollution, faint stars above. Follows the camera.
export function makeSky() {
  const geo = new THREE.SphereGeometry(3200, 40, 24);
  const mat = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, fog: false,
    uniforms: {
      uTime: GlobalUniforms.uTime,
      uHorizonA: { value: new THREE.Color(0x39638a) },  // cyan-ish glow
      uHorizonB: { value: new THREE.Color(0x6a2c55) },  // magenta pollution
      uZenith: { value: new THREE.Color(0x070c16) },
      uCloud: { value: new THREE.Color(0x18263c) },
    },
    vertexShader: /* glsl */`
      varying vec3 vDir;
      void main(){
        vDir = normalize(position);
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_Position = projectionMatrix * mv;
        gl_Position.z = gl_Position.w * 0.99999; // pin to far plane
      }
    `,
    fragmentShader: /* glsl */`
      varying vec3 vDir;
      uniform float uTime;
      uniform vec3 uHorizonA, uHorizonB, uZenith, uCloud;
      float h21(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7)))*43758.5453); }
      float noise(vec2 p){
        vec2 i = floor(p), f = fract(p);
        f = f*f*(3.0-2.0*f);
        return mix(mix(h21(i), h21(i+vec2(1,0)), f.x), mix(h21(i+vec2(0,1)), h21(i+vec2(1,1)), f.x), f.y);
      }
      float fbm(vec2 p){
        float a = 0.5, s = 0.0;
        for (int i=0;i<5;i++){ s += a*noise(p); p = p*2.03 + 11.7; a *= 0.5; }
        return s;
      }
      void main(){
        vec3 d = normalize(vDir);
        float h = clamp(d.y, 0.0, 1.0);
        // horizon hue varies around the compass so the two sides of the city read differently
        float side = 0.5 + 0.5 * sin(atan(d.x, d.z) * 1.0 + 0.7);
        vec3 hor = mix(uHorizonA, uHorizonB, side);
        vec3 col = mix(hor * 1.15, uZenith, pow(h, 0.42));
        // low rolling cloud deck, lit from below
        vec2 cuv = d.xz / max(d.y, 0.06) * 0.55;
        cuv += uTime * vec2(0.008, 0.013);
        float cl = fbm(cuv * 2.2);
        float deck = smoothstep(0.38, 0.78, cl) * smoothstep(0.0, 0.14, d.y) * exp(-d.y * 1.9);
        vec3 cloudCol = mix(uCloud * 1.3, hor * 1.05, exp(-d.y * 3.2) * 0.85);
        col = mix(col, cloudCol, deck * 0.95);
        // faint stars through gaps
        float st = step(0.9985, h21(floor(d.xz / max(d.y,0.05) * 220.0)));
        col += st * (1.0 - deck) * smoothstep(0.25, 0.6, d.y) * 0.25;
        // slow distant lightning shimmer
        float storm = pow(max(0.0, sin(uTime * 0.31 + 2.0)) , 24.0) * pow(max(0.0, sin(uTime * 3.7)), 8.0);
        col += hor * storm * 0.6 * exp(-d.y * 3.0);
        gl_FragColor = vec4(col, 1.0);
      }
    `,
  });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = -10;
  // NOTE: deliberately NOT on layer 1 — the wet street should mirror city
  // lights against the dark clear color, not the bright horizon glow.
  return mesh;
}

// Small procedural environment for PBR (drones / robots pick up city color).
export function makeEnvironment(renderer) {
  const scene = new THREE.Scene();
  const geo = new THREE.SphereGeometry(10, 16, 12);
  const mat = new THREE.ShaderMaterial({
    side: THREE.BackSide,
    vertexShader: `varying vec3 vP; void main(){ vP = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
    fragmentShader: /* glsl */`
      varying vec3 vP;
      void main(){
        vec3 d = normalize(vP);
        float h = clamp(d.y * 0.5 + 0.5, 0.0, 1.0);
        vec3 col = mix(vec3(0.10, 0.16, 0.24), vec3(0.008, 0.012, 0.03), pow(h, 0.6));
        float side = 0.5 + 0.5 * sin(atan(d.x, d.z) + 0.6);
        col += mix(vec3(0.06, 0.35, 0.55), vec3(0.5, 0.08, 0.28), side) * exp(-abs(d.y + 0.05) * 5.5) * 0.85;
        col += vec3(0.9, 0.6, 0.3) * exp(-abs(d.y + 0.55) * 9.0) * 0.12; // sodium under-glow
        gl_FragColor = vec4(col, 1.0);
      }
    `,
  });
  scene.add(new THREE.Mesh(geo, mat));
  const pmrem = new THREE.PMREMGenerator(renderer);
  const env = pmrem.fromScene(scene, 0.04);
  pmrem.dispose();
  return env.texture;
}
