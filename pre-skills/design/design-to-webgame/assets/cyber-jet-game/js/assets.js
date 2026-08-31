import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js';
import { patchStdMaterial } from './utils.js';

// All models are original work, built from primitives for this project:
//  - protagonist taxi body : drone-cab.glb (hover + rotor-spin clips)
//  - pursuer interceptor   : drone-interceptor.glb
//  - ambient patrol        : drone-patrol.glb
//  - passenger + pedestrians: android.glb (17-bone skinned mannequin)
//  - their animation clips  : android-clips.glb (hand-keyed NLA bank:
//    Standing_Phone_01_FemaleA, Standing_Idle_01, Walking_Chat_01, Walking_Phone_01)
const FILES = {
  drone06: 'assets/models/drone-cab.glb',
  drone08: 'assets/models/drone-interceptor.glb',
  drone10: 'assets/models/drone-patrol.glb',
  robot: 'assets/models/android.glb',
  clips: 'assets/models/android-clips.glb',
};

export const Assets = {
  gltf: {},           // raw gltf scenes
  clips: [],          // all 49 humanoid clips
  clipByName: new Map(),
  ready: false,
};

export async function loadAssets(onProgress) {
  const loader = new GLTFLoader();
  const keys = Object.keys(FILES);
  let done = 0;
  await Promise.all(keys.map(async (k) => {
    const g = await loader.loadAsync(FILES[k]);
    Assets.gltf[k] = g;
    done++; onProgress && onProgress(done / keys.length, k);
  }));

  // animation bank
  const bank = Assets.gltf.clips;
  for (const clip of bank.animations) {
    prepClip(clip);
    Assets.clips.push(clip);
    Assets.clipByName.set(clip.name, clip);
  }
  Assets.ready = true;
}

// Strip horizontal root motion from walking clips so we can drive position
// ourselves; keep vertical bob. The travel lives on the track with the
// largest XZ range (the Bip01 root).
function prepClip(clip) {
  if (!/^Walking/.test(clip.name)) return;
  let rootTrack = null, best = 0;
  for (const track of clip.tracks) {
    if (!track.name.endsWith('.position')) continue;
    const v = track.values; let minX = 1e9, maxX = -1e9, minZ = 1e9, maxZ = -1e9;
    for (let i = 0; i < v.length; i += 3) {
      minX = Math.min(minX, v[i]); maxX = Math.max(maxX, v[i]);
      minZ = Math.min(minZ, v[i + 2]); maxZ = Math.max(maxZ, v[i + 2]);
    }
    const range = (maxX - minX) + (maxZ - minZ);
    if (range > best) { best = range; rootTrack = track; }
  }
  if (rootTrack && best > 0.4) {
    const v = rootTrack.values, n = v.length / 3;
    const x0 = v[0], z0 = v[2];
    for (let i = 0; i < n; i++) { v[i * 3] = x0; v[i * 3 + 2] = z0; }
  }
}

// ---- drone prep -------------------------------------------------------------
// Wraps a drone gltf scene in a normalizing group: recenters, re-orients so the
// nose faces -Z and up is +Y, and scales to a target length.
// The drones are modeled nose-forward (+Y => glTF -Z), so no rotation.
const DRONE_ORIENT = {
  drone06: { rotY: 0, rotX: 0, length: 3.4 },
  drone08: { rotY: 0, rotX: 0, length: 3.0 },
  drone10: { rotY: 0, rotX: 0, length: 2.6 },
};

export function makeDrone(key, { emissiveBoost = 2.2, tint = null } = {}) {
  const src = Assets.gltf[key];
  const inst = SkeletonUtils.clone(src.scene);
  const orient = DRONE_ORIENT[key];

  const pivot = new THREE.Group();
  const shell = new THREE.Group();
  pivot.add(shell);
  shell.add(inst);

  inst.rotation.set(orient.rotX, orient.rotY, 0);
  inst.updateMatrixWorld(true);

  // measure and normalize
  const box = new THREE.Box3().setFromObject(inst);
  const size = box.getSize(new THREE.Vector3());
  const scale = orient.length / Math.max(size.z, 1e-3);
  shell.scale.setScalar(scale);
  const center = box.getCenter(new THREE.Vector3()).multiplyScalar(scale);
  shell.position.set(-center.x, -center.y, -center.z);

  const mats = [];
  inst.traverse((o) => {
    if (o.isMesh || o.isSkinnedMesh) {
      o.frustumCulled = false;
      o.castShadow = false; o.receiveShadow = false;
      if (o.material) {
        const m = o.material = o.material.clone();
        m.emissiveIntensity = emissiveBoost;
        // tint only materials that actually emit — hulls stay dark
        if (tint && m.emissive && (m.emissive.r + m.emissive.g + m.emissive.b) > 0.02) {
          m.emissive = new THREE.Color(tint);
        }
        m.metalness = Math.min(0.9, (m.metalness ?? 0.5) + 0.15);
        m.envMapIntensity = 1.35;
        patchStdMaterial(m);
        mats.push(m);
      }
    }
  });

  // animation: every embedded clip plays on loop (per-object hover/spin actions)
  let mixer = null;
  if (src.animations && src.animations.length) {
    mixer = new THREE.AnimationMixer(inst);
    for (const clip of src.animations) {
      const act = mixer.clipAction(clip);
      act.setLoop(THREE.LoopRepeat);
      act.play();
    }
  }
  const half = new THREE.Vector3(size.x, size.y, size.z).multiplyScalar(scale * 0.5);
  return { group: pivot, mixer, mats, half };
}

// ---- humanoid robot ---------------------------------------------------------
// The raw GLB stands ~4.55m tall (double unit-scale bake); normalize to 1.8m
// with a wrapper so callers can attach props in meters.
let robotMatShared = null;
let robotScale = 0;
export function makeRobot({ clipName, timeScale = 1, dark = false } = {}) {
  const src = Assets.gltf.robot;
  const inst = SkeletonUtils.clone(src.scene);
  if (!robotScale) {
    const box = new THREE.Box3().setFromObject(inst);
    robotScale = 1.8 / Math.max(box.max.y - box.min.y, 0.01);
  }
  const wrapper = new THREE.Group();
  inst.scale.setScalar(robotScale);
  wrapper.add(inst);
  if (!robotMatShared) {
    robotMatShared = new THREE.MeshStandardMaterial({
      color: 0xd9e2ee, metalness: 0.6, roughness: 0.3, envMapIntensity: 2.1,
      emissive: 0x0e1a28, emissiveIntensity: 0.55, // cool self-fill so figures read against black streets
    });
    patchStdMaterial(robotMatShared);
  }
  let darkMat = null;
  inst.traverse((o) => {
    if (o.isSkinnedMesh || o.isMesh) {
      o.frustumCulled = false;
      if (dark) {
        if (!darkMat) {
          darkMat = new THREE.MeshStandardMaterial({
            color: 0x39434f, metalness: 0.65, roughness: 0.42, envMapIntensity: 1.7,
          });
          patchStdMaterial(darkMat);
        }
        o.material = darkMat;
      } else o.material = robotMatShared;
    }
  });
  const mixer = new THREE.AnimationMixer(inst);
  let action = null;
  if (clipName && Assets.clipByName.has(clipName)) {
    action = mixer.clipAction(Assets.clipByName.get(clipName));
    action.timeScale = timeScale;
    action.play();
  }
  return { group: wrapper, inner: inst, mixer, action };
}

export function robotClipNames(prefix) {
  return Assets.clips.map(c => c.name).filter(n => n.startsWith(prefix));
}
