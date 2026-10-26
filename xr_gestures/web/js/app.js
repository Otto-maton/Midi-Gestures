// Midi Gestures XR: WebXR hand tracking on Meta Quest 3 -> gesture engine ->
// PC bridge (MIDI/OSC), with in-headset feedback.
import * as THREE from 'three';
import { GestureEngine, JOINTS, SIDES } from './gestures.js';
import { Link } from './link.js';
import { Hud, ButtonPanel, BUTTON_COLORS } from './panel.js';
import { HandViz, ZoneViz, TextSprite, noteName } from './viz.js';

const params = new URLSearchParams(location.search);
const ui = {
  enter: document.getElementById('enter'),
  note: document.getElementById('xr-note'),
  bridge: document.getElementById('bridge'),
  midi: document.getElementById('midi'),
  urls: document.getElementById('urls'),
};

if (params.has('emulate')) {
  const { installEmulator } = await import('./emulate.js');
  await installEmulator({ devUI: params.get('emulate') !== 'bare' });
}

const boot = await loadBootstrap();
const engine = new GestureEngine(boot.config);
const xrCfg = engine.cfg.xr;
const lookup = makeLookup(boot.rules);
const link = new Link(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
window.midiGestures = { engine, link };

const NO_HANDS = { left: null, right: null };
let muted = false;
let pendingRecenter = false;
let lastT = null;
let linkWasOpen = false;
let lastHandSeen = 0;
let lastEvent = '';
let lastEventT = -Infinity;

// ── Scene ──────────────────────────────────────────────────────────────────
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.xr.enabled = true;
renderer.xr.setReferenceSpaceType('local-floor');
document.getElementById('stage').appendChild(renderer.domElement);
window.midiGestures.renderer = renderer;

const scene = new THREE.Scene();
const BACKGROUND = new THREE.Color(0x0b0f17);
scene.background = BACKGROUND;
const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.01, 50);
camera.position.set(0, 1.62, 0.35);
camera.lookAt(0, 1.4, -0.45);

const grid = new THREE.GridHelper(8, 32, 0x1d2735, 0x141b26);
scene.add(grid);

// Everything you play with lives in zoneRoot, placed in front of you and
// turned to face you (see placeZones). Its local frame is the control space
// the gesture engine works in.
const zoneRoot = new THREE.Group();
scene.add(zoneRoot);
const zones = new ZoneViz(zoneRoot, xrCfg);
const [hx, hy, hz] = xrCfg.zone_half_size_m;

const hud = new Hud();
hud.mesh.position.set(0, hy + 0.13, -hz - 0.12);
zoneRoot.add(hud.mesh);

const buttons = new ButtonPanel([
  { id: 'panic', label: () => 'PANIC', color: BUTTON_COLORS.bad },
  { id: 'mode', label: () => `MODE ${engine.mode + 1}`, color: BUTTON_COLORS.text },
  { id: 'recenter', label: () => 'RECENTER', color: BUTTON_COLORS.right },
  { id: 'mute', label: () => (muted ? 'UNMUTE' : 'MUTE'), color: BUTTON_COLORS.shift },
  { id: 'hud', label: () => (hud.mesh.visible ? 'HIDE HUD' : 'SHOW HUD'), color: BUTTON_COLORS.dim },
]);
// Left of the left zone, angled toward you, so pressing it never puts a palm
// inside a zone.
buttons.mesh.position.set(-(xrCfg.zone_offset_x_m + hx + 0.11), 0.02, 0.06);
buttons.mesh.rotation.set(-0.2, 0.7, 0, 'YXZ');
zoneRoot.add(buttons.mesh);
buttons.draw(true);

const handViz = new HandViz(scene);
const noteLabels = {};
for (const side of SIDES) {
  noteLabels[side] = new TextSprite(0.035, { px: 72 });
  noteLabels[side].sprite.visible = false;
  scene.add(noteLabels[side].sprite);
}

placeZones(new THREE.Vector3(0, 1.6, 0), new THREE.Quaternion());

// ── Frame loop ─────────────────────────────────────────────────────────────
renderer.setAnimationLoop((time, frame) => {
  // A stray window frame while presenting has no hand data; ignore it rather
  // than reading it as both hands lost.
  if (renderer.xr.isPresenting && !frame) return;
  const t = time / 1000;
  const dt = lastT === null ? 0 : Math.min(0.1, t - lastT);
  lastT = t;

  // After the bridge (re)connects it has released everything; start clean so
  // the next frame re-sends presence, shift and gesture state.
  if (link.open && !linkWasOpen) engine.releaseAll(t);
  linkWasOpen = link.open;

  let world = NO_HANDS;
  let notice = null;
  if (frame) {
    const ref = renderer.xr.getReferenceSpace();
    if (pendingRecenter) {
      const viewer = frame.getViewerPose(ref);
      if (viewer) {
        placeZones(viewer.transform.position, viewer.transform.orientation);
        pendingRecenter = false;
      }
    }
    // Hands are not reported while the system menu is up; treat as gone.
    if (frame.session.visibilityState === 'visible') world = readHands(frame, ref);
    if (world.left || world.right) lastHandSeen = t;
    else if (t - lastHandSeen > 3) notice = handNotice(frame.session);
  }

  // Muted plays as if no hands were there, so the release messages (note
  // offs, zeroed CCs) still go out and then nothing more.
  const msgs = engine.update(muted ? NO_HANDS : toLocal(world), t, dt);
  link.send(msgs);
  noteEvents(msgs, t);

  const tips = SIDES.filter((s) => world[s]).map((s) => world[s]['index-finger-tip']);
  buttons.poke(tips, press);
  buttons.draw();
  handViz.update(world, engine, t);
  zones.update(engine, zoneLabels());
  updateNoteLabels(world);
  hud.update(t, {
    engine,
    lookup,
    link,
    muted,
    notice,
    lastEvent: t - lastEventT < 2.5 ? lastEvent : '',
  });
  renderer.render(scene, camera);
});

// ── Hands ──────────────────────────────────────────────────────────────────
function readHands(frame, ref) {
  const out = { left: null, right: null };
  for (const src of frame.session.inputSources) {
    if (!src.hand || !(src.handedness in out)) continue;
    const joints = {};
    let ok = true;
    for (const name of JOINTS) {
      const space = src.hand.get(name);
      const pose = space && frame.getJointPose(space, ref);
      if (!pose) {
        ok = false;
        break;
      }
      const p = pose.transform.position;
      joints[name] = { x: p.x, y: p.y, z: p.z, r: pose.radius };
    }
    if (ok) out[src.handedness] = joints;
  }
  return out;
}

const _inv = new THREE.Matrix4();
const _v = new THREE.Vector3();
function toLocal(world) {
  _inv.copy(zoneRoot.matrixWorld).invert();
  const out = { left: null, right: null };
  for (const side of SIDES) {
    const j = world[side];
    if (!j) continue;
    const local = {};
    for (const name of JOINTS) {
      _v.set(j[name].x, j[name].y, j[name].z).applyMatrix4(_inv);
      local[name] = { x: _v.x, y: _v.y, z: _v.z };
    }
    out[side] = local;
  }
  return out;
}

function handNotice(session) {
  const controllers = [...session.inputSources].some((s) => !s.hand && s.gamepad);
  return controllers
    ? 'Put the controllers down: this app is played with your hands'
    : 'Show your hands (hand tracking must be on in Quest settings)';
}

// Zones sit in front of and below your eyes, turned to face you.
function placeZones(position, orientation) {
  const fwd = new THREE.Vector3(0, 0, -1).applyQuaternion(orientation);
  fwd.y = 0;
  if (fwd.lengthSq() < 1e-6) fwd.set(0, 0, -1);
  fwd.normalize();
  zoneRoot.position.copy(position).addScaledVector(fwd, xrCfg.zone_distance_m);
  zoneRoot.position.y -= xrCfg.zone_drop_m;
  zoneRoot.rotation.set(0, Math.atan2(-fwd.x, -fwd.z), 0);
  zoneRoot.updateMatrixWorld(true);
}

// ── Controls ───────────────────────────────────────────────────────────────
function press(id) {
  const t = lastT ?? 0;
  if (id === 'panic') {
    link.send([['/event/panic', [1]]]);
    showEvent('PANIC: all notes off', t);
  } else if (id === 'mode') {
    link.send(engine.nextMode());
    showEvent(`mode ${engine.mode + 1}`, t);
  } else if (id === 'recenter') {
    if (renderer.xr.isPresenting) pendingRecenter = true;
    else placeZones(new THREE.Vector3(0, 1.6, 0), new THREE.Quaternion());
  } else if (id === 'mute') {
    muted = !muted;
    if (muted) link.send([['/event/panic', [1]]]);
    showEvent(muted ? 'muted: no MIDI from gestures' : 'unmuted', t);
  } else if (id === 'hud') {
    hud.mesh.visible = !hud.mesh.visible;
  }
  buttons.dirty = true;
}

window.addEventListener('keydown', (e) => {
  if (e.target instanceof HTMLInputElement || e.repeat) return;
  const id = { p: 'panic', m: 'mode', r: 'recenter', ' ': 'mute', h: 'hud' }[e.key.toLowerCase()];
  if (id) {
    e.preventDefault();
    press(id);
  }
});

// ── Labels and events ──────────────────────────────────────────────────────
function makeLookup(rules) {
  const cache = new Map();
  return (path, shift, out = 0) => {
    const key = `${path}|${shift}|${out}`;
    if (!cache.has(key)) {
      const r = rules.find((x) => x.path === path && (x.shift === null || x.shift === shift));
      let res = null;
      if (r) {
        const cc = r.cc[out];
        const note = r.notes[out];
        const label = cc ? `CC${cc.cc}` : note && note.kind !== 'midi_note_gate_pitched' ? `note ${note.note}` : '';
        res = { enabled: r.enabled, label };
      }
      cache.set(key, res);
    }
    return cache.get(key);
  };
}

function zoneLabels() {
  const label = (side, title) => {
    const x = lookup(`/hand/${side}/xy`, engine.shift, 0);
    const y = lookup(`/hand/${side}/xy`, engine.shift, 1);
    if (!x || !x.enabled) return `${title}  (XY off)`;
    return `${title}  X ${x.label}  Y ${y.label}`;
  };
  return {
    right: label('right', engine.shift ? 'SHIFT' : 'RIGHT'),
    left: label('left', 'LEFT'),
  };
}

function showEvent(text, t) {
  lastEvent = text;
  lastEventT = t;
}

function noteEvents(msgs, t) {
  for (const [path, args] of msgs) {
    const parts = path.split('/');
    let text = null;
    if (path.startsWith('/event/hand/') && parts[4].startsWith('tap_')) {
      const finger = parts[4].slice(4);
      handViz.flash(parts[3], finger, t);
      text = `tap ${finger}`;
    } else if (parts[3] === 'gesture' && args[0] >= 0.5) {
      text = `${parts[2]} ${parts[4].replace('_', ' ')}`;
    } else if (path === '/shift') {
      text = args[0] ? 'shift on' : 'shift off';
    }
    if (text) {
      const map = lookup(path, engine.shift, 0);
      showEvent(map && map.enabled && map.label ? `${text} > ${map.label}` : text, t);
    }
  }
}

function updateNoteLabels(world) {
  for (const side of SIDES) {
    const s = engine.sides[side];
    const label = noteLabels[side];
    const map = lookup(`/hand/${side}/pinch_pitch`, engine.shift);
    const j = world[side];
    label.sprite.visible = !!(j && s.noteOn && map && map.enabled);
    if (label.sprite.visible) {
      const a = j['thumb-tip'];
      const b = j['index-finger-tip'];
      label.sprite.position.set((a.x + b.x) / 2, (a.y + b.y) / 2 + 0.05, (a.z + b.z) / 2);
      label.set(`${noteName(s.note)}  ${s.note}`);
    }
  }
}

// ── Page (outside the headset) ─────────────────────────────────────────────
async function loadBootstrap() {
  try {
    const r = await fetch('api/config', { cache: 'no-store' });
    if (r.ok) return await r.json();
  } catch {
    // Served without the bridge; fall through to defaults.
  }
  return { config: {}, rules: [], urls: [] };
}

function refreshPage() {
  const st = link.status;
  ui.bridge.textContent = link.open ? 'PC bridge: connected' : 'PC bridge: not connected';
  ui.bridge.dataset.state = link.open ? 'ok' : 'bad';
  if (st) {
    ui.midi.textContent = `MIDI: ${st.midi.port}${st.midi.connected ? '' : ' (port not found)'}`;
    ui.midi.dataset.state = st.midi.connected ? 'ok' : 'bad';
  } else {
    ui.midi.textContent = 'MIDI: --';
    ui.midi.dataset.state = '';
  }
}
setInterval(refreshPage, 500);
refreshPage();

if (boot.urls.length) {
  ui.urls.textContent = `On the Quest 3, open ${boot.urls[0]} in the Meta Quest Browser.`;
}

async function setupEnterButton() {
  if (!navigator.xr) {
    ui.enter.textContent = 'WebXR not available';
    ui.note.textContent = window.isSecureContext
      ? 'Open this page in the Meta Quest Browser on your Quest 3 (or add ?emulate to try it here).'
      : 'WebXR needs a secure page. Use the https:// address the bridge printed.';
    return;
  }
  const ar = await navigator.xr.isSessionSupported('immersive-ar').catch(() => false);
  const vr = await navigator.xr.isSessionSupported('immersive-vr').catch(() => false);
  const mode = ar && xrCfg.passthrough ? 'immersive-ar' : vr ? 'immersive-vr' : ar ? 'immersive-ar' : null;
  if (!mode) {
    ui.enter.textContent = 'No headset found';
    ui.note.textContent = 'Open this page in the Meta Quest Browser on your Quest 3 (or add ?emulate to try it here).';
    return;
  }
  ui.enter.textContent = mode === 'immersive-ar' ? 'Enter mixed reality' : 'Enter VR';
  ui.enter.disabled = false;
  ui.enter.onclick = () => startSession(mode).catch((e) => {
    ui.note.textContent = `Could not start XR: ${e.message || e}`;
  });
}

async function startSession(mode) {
  const session = await navigator.xr.requestSession(mode, {
    requiredFeatures: ['local-floor'],
    optionalFeatures: ['hand-tracking'],
  });
  await renderer.xr.setSession(session);
  const passthrough = session.environmentBlendMode && session.environmentBlendMode !== 'opaque';
  scene.background = passthrough ? null : BACKGROUND;
  grid.visible = !passthrough;
  if (session.supportedFrameRates && [...session.supportedFrameRates].includes(90)) {
    session.updateTargetFrameRate(90).catch(() => {});
  }
  pendingRecenter = true;
  lastHandSeen = lastT ?? 0;
  document.body.classList.add('in-xr');
  session.addEventListener('end', () => {
    link.send(engine.releaseAll(lastT ?? 0));
    scene.background = BACKGROUND;
    grid.visible = true;
    document.body.classList.remove('in-xr');
    placeZones(new THREE.Vector3(0, 1.6, 0), new THREE.Quaternion());
  });
}

window.addEventListener('resize', () => {
  if (renderer.xr.isPresenting) return;
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

setupEnterButton();
