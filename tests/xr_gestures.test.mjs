// Unit tests for the headset gesture engine. Run: node --test tests/xr_gestures.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  GestureEngine,
  classifyGesture,
  measureHand,
  zoneCenter,
  XR_DEFAULTS,
} from '../xr_gestures/web/js/gestures.js';

const DEG = Math.PI / 180;
const FINGER_X = { index: -0.025, middle: -0.008, ring: 0.01, pinky: 0.026 };
const BONES = [0.045, 0.027, 0.023];
const BENDS = [80 * DEG, 100 * DEG, 60 * DEG];

// Right hand, palm down, fingers pointing forward (-z), wrist at the origin.
// curls: 0 = straight, 1 = fist. thumb: 'out' | 'tucked' | 'pinch'.
function rightHand({ curls = {}, thumb = 'out' } = {}) {
  const j = { wrist: { x: 0, y: 0, z: 0 } };
  for (const [f, x] of Object.entries(FINGER_X)) {
    const c = curls[f] ?? 0;
    let p = { x, y: 0, z: f === 'middle' ? -0.095 : -0.09 };
    j[`${f}-finger-metacarpal`] = { x: x * 0.4, y: 0, z: -0.01 };
    j[`${f}-finger-phalanx-proximal`] = p;
    const names = ['phalanx-intermediate', 'phalanx-distal', 'tip'];
    let theta = 0;
    BONES.forEach((len, i) => {
      theta += c * BENDS[i];
      p = { x, y: p.y - Math.sin(theta) * len, z: p.z - Math.cos(theta) * len };
      j[`${f}-finger-${names[i]}`] = p;
    });
  }
  j['thumb-metacarpal'] = { x: -0.025, y: -0.01, z: -0.02 };
  j['thumb-phalanx-proximal'] = { x: -0.05, y: -0.01, z: -0.045 };
  if (thumb === 'out') {
    j['thumb-phalanx-distal'] = { x: -0.07, y: -0.01, z: -0.07 };
    j['thumb-tip'] = { x: -0.085, y: -0.01, z: -0.09 };
  } else if (thumb === 'tucked') {
    j['thumb-phalanx-distal'] = { x: -0.04, y: -0.035, z: -0.075 };
    const mid = j['index-finger-phalanx-intermediate'];
    j['thumb-tip'] = { x: mid.x + 0.008, y: mid.y - 0.012, z: mid.z };
  } else if (thumb === 'pinch') {
    const tip = j['index-finger-tip'];
    j['thumb-phalanx-distal'] = { x: -0.045, y: -0.03, z: -0.08 };
    j['thumb-tip'] = { x: tip.x, y: tip.y - 0.006, z: tip.z };
  }
  return j;
}

const mirror = (j) =>
  Object.fromEntries(Object.entries(j).map(([k, p]) => [k, { x: -p.x, y: p.y, z: p.z }]));

// Rotate about the wrist: axis 'x' or 'z', angle in degrees.
function rotate(j, axis, deg) {
  const c = Math.cos(deg * DEG);
  const s = Math.sin(deg * DEG);
  return Object.fromEntries(
    Object.entries(j).map(([k, p]) => {
      if (axis === 'z') return [k, { x: p.x * c - p.y * s, y: p.x * s + p.y * c, z: p.z }];
      return [k, { x: p.x, y: p.y * c - p.z * s, z: p.y * s + p.z * c }];
    }),
  );
}

// Translate so the palm centre sits at `to` (control space).
function placePalm(j, to) {
  const palm = measureHand(j, 'right').palm;
  return Object.fromEntries(
    Object.entries(j).map(([k, p]) => [k, { x: p.x - palm.x + to.x, y: p.y - palm.y + to.y, z: p.z - palm.z + to.z }]),
  );
}

const FIST = { index: 1, middle: 1, ring: 1, pinky: 1 };
const classify = (j, side = 'right') => classifyGesture(measureHand(j, side));
const RIGHT_ZONE = zoneCenter('right', XR_DEFAULTS);
const LEFT_ZONE = zoneCenter('left', XR_DEFAULTS);

// Run `frames` frames at `hz`, collecting every message.
function run(engine, handsAt, frames, { hz = 90, t0 = 0 } = {}) {
  const out = [];
  const dt = 1 / hz;
  for (let i = 0; i < frames; i++) {
    const t = t0 + i * dt;
    out.push(...engine.update(handsAt(i, t), t, dt));
  }
  return out;
}
const paths = (msgs, prefix) => msgs.filter(([p]) => p.startsWith(prefix));

test('palm normal points out of the palm for both hands', () => {
  for (const [side, j] of [['right', rightHand()], ['left', mirror(rightHand())]]) {
    const f = measureHand(j, side);
    assert.ok(f.normal.y < -0.9, `${side} palm faces down, normal ${JSON.stringify(f.normal)}`);
  }
});

test('finger curl spans 0 (straight) to 1 (fist)', () => {
  assert.ok(measureHand(rightHand(), 'right').curls.index < 0.05);
  assert.ok(measureHand(rightHand({ curls: FIST }), 'right').curls.index > 0.95);
});

test('static gestures match the MediaPipe label set', () => {
  assert.equal(classify(rightHand()), 'Open_Palm');
  assert.equal(classify(rightHand({ curls: FIST, thumb: 'tucked' })), 'Closed_Fist');
  assert.equal(classify(rotate(rightHand({ curls: FIST }), 'z', -90)), 'Thumb_Up');
  assert.equal(classify(rotate(rightHand({ curls: FIST }), 'z', 90)), 'Thumb_Down');
  assert.equal(classify(rightHand({ curls: { ring: 1, pinky: 1 }, thumb: 'tucked' })), 'Victory');
  assert.equal(classify(rotate(rightHand({ curls: { middle: 1, ring: 1, pinky: 1 } }), 'x', 90)), 'Pointing_Up');
  assert.equal(classify(rightHand({ curls: { middle: 1, ring: 1, pinky: 1 } })), 'None', 'pointing forward');
  assert.equal(classify(rightHand({ curls: { middle: 1, ring: 1 } })), 'ILoveYou');
  assert.equal(classify(mirror(rightHand({ curls: { ring: 1, pinky: 1 }, thumb: 'tucked' })), 'left'), 'Victory');
});

test('a hand only plays inside its zone', () => {
  const e = new GestureEngine();
  const outside = placePalm(rightHand(), { x: 0.6, y: 0, z: 0 });
  assert.equal(paths(run(e, () => ({ right: outside }), 10), '/hand/right/').length, 0);
  assert.equal(e.sides.right.tracked, true);
  const inside = placePalm(rightHand(), RIGHT_ZONE);
  const msgs = run(e, () => ({ right: inside }), 5);
  assert.deepEqual(msgs[0], ['/hand/right/present', [1]]);
  assert.ok(paths(msgs, '/hand/right/xy').length > 0);
});

test('xy follows the palm across the zone', () => {
  const e = new GestureEngine();
  const [hx, hy] = XR_DEFAULTS.zone_half_size_m;
  const at = (dx, dy) => placePalm(rightHand(), { x: RIGHT_ZONE.x + dx, y: dy, z: 0 });
  let msgs = run(e, () => ({ right: at(0, 0) }), 60);
  assert.deepEqual(paths(msgs, '/hand/right/xy').at(-1)[1], [0.5, 0.5]);
  msgs = run(e, () => ({ right: at(hx * 0.98, hy * 0.98) }), 90);
  const [x, y] = paths(msgs, '/hand/right/xy').at(-1)[1];
  assert.ok(x > 0.95 && y > 0.95, `top right corner gave ${x}, ${y}`);
});

test('smoothing is frame-rate independent', () => {
  const settle = (hz) => {
    const e = new GestureEngine();
    const msgs = run(e, () => ({ right: placePalm(rightHand(), { x: RIGHT_ZONE.x + 0.1, y: 0, z: 0 }) }), hz / 5, { hz });
    return paths(msgs, '/hand/right/xy').at(-1)[1][0];
  };
  assert.ok(Math.abs(settle(30) - settle(90)) < 0.05);
});

test('left fist toggles shift with hysteresis', () => {
  const e = new GestureEngine();
  const fist = mirror(placePalm(rightHand({ curls: FIST, thumb: 'tucked' }), { x: -LEFT_ZONE.x, y: 0, z: 0 }));
  let msgs = run(e, () => ({ left: fist }), 30);
  assert.deepEqual(paths(msgs, '/shift'), [['/shift', [1]]]);
  const open = mirror(placePalm(rightHand(), { x: -LEFT_ZONE.x, y: 0, z: 0 }));
  msgs = run(e, () => ({ left: open }), 30);
  assert.deepEqual(paths(msgs, '/shift'), [['/shift', [0]]]);
});

test('pinch fires pinch_on, and pitch pinch sends note edges only', () => {
  const e = new GestureEngine({ pitch_pinch: { note_min: 48, note_max: 84 } });
  const open = placePalm(rightHand(), RIGHT_ZONE);
  const pinch = placePalm(rightHand({ curls: { index: 0.45 }, thumb: 'pinch' }), RIGHT_ZONE);
  run(e, () => ({ right: open }), 10);
  let msgs = run(e, () => ({ right: pinch }), 20);
  assert.equal(paths(msgs, '/event/hand/right/pinch_on').length, 1);
  const pitch = paths(msgs, '/hand/right/pinch_pitch');
  assert.equal(pitch.length, 1, 'one note-on, not one per frame');
  const note = pitch[0][1][0];
  assert.equal(pitch[0][1][1], 1);

  // Raise the hand: old note off, new note on.
  const higher = placePalm(rightHand({ curls: { index: 0.45 }, thumb: 'pinch' }), { ...RIGHT_ZONE, y: 0.12 });
  msgs = run(e, () => ({ right: higher }), 60);
  const moves = paths(msgs, '/hand/right/pinch_pitch');
  assert.deepEqual(moves[0], ['/hand/right/pinch_pitch', [note, 0]]);
  assert.ok(moves.at(-1)[1][0] > note && moves.at(-1)[1][1] === 1);
  for (let i = 0; i < moves.length; i += 2) assert.equal(moves[i][1][1], 0);

  msgs = run(e, () => ({ right: placePalm(rightHand(), { ...RIGHT_ZONE, y: 0.12 }) }), 20);
  const last = moves.at(-1)[1][0];
  assert.deepEqual(paths(msgs, '/hand/right/pinch_pitch'), [['/hand/right/pinch_pitch', [last, 0]]]);
  assert.equal(paths(msgs, '/event/hand/right/pinch_off').length, 1);
});

test('a quick finger flick taps once; moving the whole hand does not', () => {
  const e = new GestureEngine();
  const pose = (c) => placePalm(rightHand({ curls: { index: c } }), RIGHT_ZONE);
  run(e, () => ({ right: pose(0) }), 10);
  // Flex 0 -> 0.35 in 3 frames (~33 ms), then hold still.
  const msgs = run(e, (i) => ({ right: pose(Math.min(i, 3) * 0.12) }), 20, { t0: 1 });
  assert.deepEqual(paths(msgs, '/event/hand/right/tap_'), [['/event/hand/right/tap_index', [1]]]);

  const e2 = new GestureEngine();
  const msgs2 = run(e2, (i) => ({ right: placePalm(rightHand(), { ...RIGHT_ZONE, y: 0.1 - i * 0.012 }) }), 15);
  assert.equal(paths(msgs2, '/event/hand/right/tap_').length, 0);
});

test('losing a hand releases everything it held', () => {
  const e = new GestureEngine();
  const fist = mirror(placePalm(rightHand({ curls: FIST, thumb: 'tucked' }), { x: -LEFT_ZONE.x, y: 0, z: 0 }));
  run(e, () => ({ left: fist }), 30);
  assert.equal(e.shift, true);
  assert.equal(e.sides.left.gesture, 'Closed_Fist');
  const msgs = e.releaseAll(1);
  assert.ok(msgs.some(([p, a]) => p === '/hand/left/present' && a[0] === 0));
  assert.ok(msgs.some(([p, a]) => p === '/shift' && a[0] === 0));
  assert.ok(msgs.some(([p, a]) => p === '/hand/left/gesture/closed_fist' && a[0] === 0));
  assert.ok(msgs.some(([p, a]) => p === '/hand/left/pinch' && a[0] === 0));
});

test('mode cycles through num_modes', () => {
  const e = new GestureEngine({ mode_manager: { num_modes: 3 } });
  assert.deepEqual(e.nextMode(), [['/mode/index', [1]]]);
  e.nextMode();
  assert.deepEqual(e.nextMode(), [['/mode/index', [0]]]);
});
