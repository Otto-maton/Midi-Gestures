// XR-native port of the midi_gestures plugins (pinch, pitch pinch, shift, xy,
// roll, depth, speed, tap, static gestures).
//
// Input is the 25 WebXR hand joints per hand, expressed in control-space
// metres: +x right, +y up, +z toward the user (the frame of the control zones
// floating in front of you). Output is a list of [path, args] bus messages
// with the same paths and 0..1 value ranges the Python plugins publish, so the
// existing MappingEngine on the PC turns them into the same MIDI/OSC.
//
// This module has no three.js dependency so it can be unit-tested in Node.

export const JOINTS = [
  'wrist',
  'thumb-metacarpal', 'thumb-phalanx-proximal', 'thumb-phalanx-distal', 'thumb-tip',
  'index-finger-metacarpal', 'index-finger-phalanx-proximal',
  'index-finger-phalanx-intermediate', 'index-finger-phalanx-distal', 'index-finger-tip',
  'middle-finger-metacarpal', 'middle-finger-phalanx-proximal',
  'middle-finger-phalanx-intermediate', 'middle-finger-phalanx-distal', 'middle-finger-tip',
  'ring-finger-metacarpal', 'ring-finger-phalanx-proximal',
  'ring-finger-phalanx-intermediate', 'ring-finger-phalanx-distal', 'ring-finger-tip',
  'pinky-finger-metacarpal', 'pinky-finger-phalanx-proximal',
  'pinky-finger-phalanx-intermediate', 'pinky-finger-phalanx-distal', 'pinky-finger-tip',
];

export const FINGERS = ['index', 'middle', 'ring', 'pinky'];
export const SIDES = ['right', 'left'];

// Defaults for the optional "xr" block in config.json. Keep in sync with
// xr_gestures/settings.py.
export const XR_DEFAULTS = {
  zone_distance_m: 0.40,
  zone_drop_m: 0.30,
  zone_offset_x_m: 0.20,
  zone_half_size_m: [0.15, 0.15, 0.15],
  zone_gating: true,
  pinch_closed_m: 0.015,
  pinch_open_m: 0.10,
  pinch_on_m: 0.025,
  pinch_off_m: 0.040,
  pinch_suppress_m: 0.035,
  roll_range_deg: 90,
  speed_cap_mps: 1.0,
  tap_velocity_mps: 0.35,
  tap_sides: ['right'],
  pitch_span_m: 0.6,
  passthrough: true,
};

// config.json "tap.fingers" uses MediaPipe landmark names.
const TAP_FINGER = {
  INDEX_FINGER_TIP: 'index',
  MIDDLE_FINGER_TIP: 'middle',
  RING_FINGER_TIP: 'ring',
  PINKY_TIP: 'pinky',
};

// The smoothing values in config.json were tuned for ~30 Hz webcam inference.
// XR runs at 72-120 Hz, so alpha and slew are rescaled per frame by dt.
const REF_DT = 1 / 30;
// Frames to keep sending zeroed continuous values after a hand leaves, so the
// MappingEngine's per-CC rate limiter cannot swallow the final value.
const LINGER_FRAMES = 12;
const CURL_MIN = (25 * Math.PI) / 180;
const CURL_MAX = (200 * Math.PI) / 180;
const EXTENDED = 0.35;
const CURLED = 0.55;

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const clamp01 = (v) => clamp(v, 0, 1);
const sub = (a, b) => ({ x: a.x - b.x, y: a.y - b.y, z: a.z - b.z });
const dot = (a, b) => a.x * b.x + a.y * b.y + a.z * b.z;
const cross = (a, b) => ({
  x: a.y * b.z - a.z * b.y,
  y: a.z * b.x - a.x * b.z,
  z: a.x * b.y - a.y * b.x,
});
const len = (a) => Math.hypot(a.x, a.y, a.z);
const dist = (a, b) => len(sub(a, b));
const norm = (a) => {
  const l = len(a) || 1;
  return { x: a.x / l, y: a.y / l, z: a.z / l };
};
const angle = (a, b) => Math.acos(clamp(dot(a, b) / (len(a) * len(b) || 1), -1, 1));

function average(points) {
  const s = { x: 0, y: 0, z: 0 };
  for (const p of points) {
    s.x += p.x;
    s.y += p.y;
    s.z += p.z;
  }
  return { x: s.x / points.length, y: s.y / points.length, z: s.z / points.length };
}

function emaAlpha(alpha, dt) {
  return 1 - Math.pow(1 - alpha, clamp(dt / REF_DT, 0, 3));
}

// The Python plugins' per-frame chain (clamp the error to slew_limit, then
// EMA) moves at most alpha * slew_limit per 30 Hz frame. Expressed as a rate
// so it behaves the same at any frame rate; identical to it at 30 Hz.
function smooth(prev, target, alpha, slewLimit, dt) {
  const maxStep = alpha * slewLimit * clamp(dt / REF_DT, 0, 3);
  return prev + clamp(emaAlpha(alpha, dt) * (target - prev), -maxStep, maxStep);
}

export function resolveConfig(cfg = {}) {
  const get = (section, key, fallback) => {
    const s = cfg[section];
    return s && s[key] !== undefined ? s[key] : fallback;
  };
  const xr = { ...XR_DEFAULTS, ...(cfg.xr || {}) };
  return {
    xr,
    pinch: {
      alpha: get('pinch', 'alpha', 0.35),
      deadZone: get('pinch', 'dead_zone', 0.05),
      slew: get('pinch', 'slew_limit', 0.15),
    },
    shift: {
      alpha: get('shift', 'alpha', 0.3),
      on: get('shift', 'on_thresh', 0.7),
      off: get('shift', 'off_thresh', 0.45),
    },
    xy: {
      alpha: get('xy', 'alpha', 0.5),
      deadZone: get('xy', 'dead_zone', 0.04),
      slew: get('xy', 'slew_limit', 0.12),
      relative: get('xy', 'relative_mode', false),
    },
    roll: { alpha: get('roll', 'alpha', 0.1), slew: get('roll', 'slew_limit', 0.05) },
    depth: { alpha: get('depth', 'alpha', 0.1), slew: get('depth', 'slew_limit', 0.05) },
    speed: { alpha: get('speed', 'alpha', 0.25) },
    tap: {
      cooldown: get('tap', 'cooldown_s', 0.25),
      fingers: get('tap', 'fingers', ['INDEX_FINGER_TIP', 'MIDDLE_FINGER_TIP', 'RING_FINGER_TIP'])
        .map((n) => TAP_FINGER[n])
        .filter(Boolean),
    },
    gesture: { holdS: get('gesture', 'hold_frames', 2) * REF_DT },
    pitch: {
      noteMin: get('pitch_pinch', 'note_min', 48),
      noteMax: get('pitch_pinch', 'note_max', 84),
      alpha: get('pitch_pinch', 'pitch_alpha', 0.25),
    },
    numModes: get('mode_manager', 'num_modes', 4),
  };
}

export function zoneCenter(side, xr) {
  const off = xr.zone_offset_x_m;
  return { x: side === 'right' ? off : -off, y: 0, z: 0 };
}

function inZone(p, c, half, margin) {
  return (
    Math.abs(p.x - c.x) < half[0] + margin &&
    Math.abs(p.y - c.y) < half[1] + margin &&
    Math.abs(p.z - c.z) < half[2] + margin
  );
}

// 0 = straight finger, 1 = fully curled (sum of MCP, PIP and DIP bend angles).
export function fingerCurl(j, f) {
  const meta = j[`${f}-finger-metacarpal`];
  const prox = j[`${f}-finger-phalanx-proximal`];
  const inter = j[`${f}-finger-phalanx-intermediate`];
  const dist_ = j[`${f}-finger-phalanx-distal`];
  const tip = j[`${f}-finger-tip`];
  const b0 = sub(prox, meta);
  const b1 = sub(inter, prox);
  const b2 = sub(dist_, inter);
  const b3 = sub(tip, dist_);
  const bend = angle(b0, b1) + angle(b1, b2) + angle(b2, b3);
  return clamp01((bend - CURL_MIN) / (CURL_MAX - CURL_MIN));
}

export function measureHand(j, side) {
  const wrist = j.wrist;
  const indexMcp = j['index-finger-phalanx-proximal'];
  const pinkyMcp = j['pinky-finger-phalanx-proximal'];
  const palm = average([
    wrist,
    indexMcp,
    j['middle-finger-phalanx-proximal'],
    j['ring-finger-phalanx-proximal'],
    pinkyMcp,
  ]);
  const handSize = dist(wrist, j['middle-finger-phalanx-proximal']) || 0.09;
  // Points out of the palm (the side fingers curl toward).
  let normal = norm(cross(sub(indexMcp, wrist), sub(pinkyMcp, wrist)));
  if (side === 'left') normal = { x: -normal.x, y: -normal.y, z: -normal.z };

  const curls = {};
  for (const f of FINGERS) curls[f] = fingerCurl(j, f);

  const tMeta = j['thumb-metacarpal'];
  const tProx = j['thumb-phalanx-proximal'];
  const tDist = j['thumb-phalanx-distal'];
  const tTip = j['thumb-tip'];
  const thumbBend = angle(sub(tProx, tMeta), sub(tDist, tProx)) + angle(sub(tDist, tProx), sub(tTip, tDist));
  // A thumb wrapped over a fist rests on the index/middle middle phalanges.
  const thumbTuck =
    Math.min(
      dist(tTip, j['index-finger-phalanx-intermediate']),
      dist(tTip, j['index-finger-phalanx-distal']),
      dist(tTip, j['middle-finger-phalanx-intermediate']),
      dist(tTip, j['middle-finger-phalanx-distal']),
    ) / handSize;

  return {
    wrist,
    palm,
    handSize,
    normal,
    curls,
    thumbBend,
    thumbTuck,
    thumbReach: dist(tTip, indexMcp) / handSize,
    thumbDir: norm(sub(tTip, tProx)),
    indexDir: norm(sub(j['index-finger-tip'], indexMcp)),
    pinchDist: dist(tTip, j['index-finger-tip']),
    knuckles: sub(pinkyMcp, indexMcp),
  };
}

// Rule-based stand-in for the MediaPipe gesture classifier, same label set.
export function classifyGesture(f) {
  const ext = (n) => f.curls[n] < EXTENDED;
  const cur = (n) => f.curls[n] > CURLED;
  const thumbOut = f.thumbReach > 0.55 && f.thumbBend < 0.9 && f.thumbTuck > 0.4;

  if (FINGERS.every(cur)) {
    if (thumbOut && f.thumbDir.y > 0.6) return 'Thumb_Up';
    if (thumbOut && f.thumbDir.y < -0.6) return 'Thumb_Down';
    return 'Closed_Fist';
  }
  if (FINGERS.every(ext) && thumbOut) return 'Open_Palm';
  if (ext('index') && ext('middle') && cur('ring') && cur('pinky')) return 'Victory';
  if (ext('index') && cur('middle') && cur('ring') && cur('pinky')) {
    return f.indexDir.y > 0.6 ? 'Pointing_Up' : 'None';
  }
  if (thumbOut && ext('index') && ext('pinky') && cur('middle') && cur('ring')) return 'ILoveYou';
  return 'None';
}

function newSide() {
  return {
    tracked: false,
    present: false,
    engaged: false,
    lostFrames: LINGER_FRAMES + 1,
    joints: null,
    features: null,
    pinch: 0,
    pinchHist: [],
    pinchActive: false,
    pitch: 0.5,
    pitchNote: null,
    note: null,
    noteOn: false,
    x: 0.5,
    y: 0.5,
    outX: 0.5,
    outY: 0.5,
    lastPalm: null,
    relPalm: null,
    depth: 0.5,
    roll: 0.5,
    speed: 0,
    tap: {},
    lastTap: {},
    gesture: 'None',
    candidate: 'None',
    candidateSince: 0,
  };
}

export class GestureEngine {
  constructor(cfg = {}) {
    this.setConfig(cfg);
    this.reset();
  }

  setConfig(cfg) {
    this.cfg = resolveConfig(cfg);
  }

  reset() {
    this.sides = { right: newSide(), left: newSide() };
    this.shift = false;
    this.fist = 0;
    this.mode = 0;
  }

  // hands: { left: joints | null, right: joints | null }, joints keyed by
  // WebXR joint name with {x, y, z} in control-space metres.
  update(hands, t, dt) {
    const out = [];
    const xr = this.cfg.xr;
    for (const side of SIDES) {
      const s = this.sides[side];
      const j = hands[side] || null;
      s.tracked = !!j;
      s.joints = j;
      s.features = j ? measureHand(j, side) : null;
      if (j && xr.zone_gating) {
        s.engaged = inZone(s.features.palm, zoneCenter(side, xr), xr.zone_half_size_m, s.engaged ? 0.06 : 0.02);
      } else {
        s.engaged = !!j;
      }
      if (s.engaged !== s.present) {
        s.present = s.engaged;
        out.push([`/hand/${side}/present`, [s.present ? 1 : 0]]);
      }
      s.lostFrames = s.present ? 0 : s.lostFrames + 1;
    }
    for (const side of SIDES) {
      const s = this.sides[side];
      const other = this.sides[side === 'right' ? 'left' : 'right'];
      this._pinch(side, s, dt, out);
      this._pitchPinch(side, s, other, dt, out);
      this._xy(side, s, dt, out);
      this._depth(side, s, dt, out);
      this._roll(side, s, dt, out);
      this._speed(side, s, dt, out);
      if (xr.tap_sides.includes(side)) this._tap(side, s, t, dt, out);
      this._gesture(side, s, t, out);
    }
    this._shift(dt, out);
    return out;
  }

  // Everything off, as if both hands left. Used for mute and session end.
  releaseAll(t) {
    return this.update({ left: null, right: null }, t, 0);
  }

  setMode(index) {
    this.mode = ((index % this.cfg.numModes) + this.cfg.numModes) % this.cfg.numModes;
    return [['/mode/index', [this.mode]]];
  }

  nextMode() {
    return this.setMode(this.mode + 1);
  }

  _pinchAmount(d) {
    const { pinch_closed_m: closed, pinch_open_m: open } = this.cfg.xr;
    return clamp01(1 - (d - closed) / (open - closed));
  }

  _pinch(side, s, dt, out) {
    const P = this.cfg.pinch;
    if (!s.present) {
      if (s.pinchActive) {
        s.pinchActive = false;
        out.push([`/event/hand/${side}/pinch_off`, [0]]);
      }
      s.pinch = 0;
      s.pinchHist.length = 0;
      if (s.lostFrames <= LINGER_FRAMES) {
        out.push([`/hand/${side}/pinch`, [0]], [`/hand/${side}/pinch_held`, [0]]);
      }
      return;
    }
    let d = s.features.pinchDist;
    s.pinchHist.push(d);
    if (s.pinchHist.length > 3) s.pinchHist.shift();
    if (s.pinchHist.length === 3) d = [...s.pinchHist].sort((a, b) => a - b)[1];
    const raw = this._pinchAmount(d);
    s.pinch = smooth(s.pinch, raw, P.alpha, P.slew, dt);
    out.push([`/hand/${side}/pinch`, [s.pinch < P.deadZone ? 0 : s.pinch]]);

    // The gate reads the fingertip distance directly: the smoothed CC ramps
    // too slowly to trigger notes. Hysteresis is in metres.
    const xr = this.cfg.xr;
    if (!s.pinchActive && d <= xr.pinch_on_m) {
      s.pinchActive = true;
      out.push([`/event/hand/${side}/pinch_on`, [raw]]);
    } else if (s.pinchActive && d >= xr.pinch_off_m) {
      s.pinchActive = false;
      out.push([`/event/hand/${side}/pinch_off`, [raw]]);
    }
    out.push([`/hand/${side}/pinch_held`, [s.pinchActive ? 1 : 0]]);
  }

  // Held note whose pitch follows hand height (or the height difference
  // between both hands). Only note edges are sent: the MappingEngine turns
  // every gate-on message into a note-on, so streaming would retrigger.
  _pitchPinch(side, s, other, dt, out) {
    const path = `/hand/${side}/pinch_pitch`;
    if (!s.present) {
      if (s.noteOn) {
        out.push([path, [s.note, 0]]);
        s.noteOn = false;
      }
      return;
    }
    const xr = this.cfg.xr;
    const { noteMin, noteMax, alpha } = this.cfg.pitch;
    let raw;
    if (other.present && other.features) {
      raw = (s.features.wrist.y - other.features.wrist.y) / xr.pitch_span_m + 0.5;
    } else {
      const c = zoneCenter(side, xr);
      raw = (s.features.wrist.y - c.y) / (2 * xr.zone_half_size_m[1]) + 0.5;
    }
    s.pitch += emaAlpha(alpha, dt) * (clamp01(raw) - s.pitch);
    const cont = noteMin + s.pitch * (noteMax - noteMin);
    let note = clamp(Math.round(cont), 0, 127);
    // Stick to the sounding note until the hand clearly moves off it.
    if (s.noteOn && Math.abs(cont - s.note) < 0.7) note = s.note;
    s.pitchNote = note;

    if (s.pinchActive) {
      if (!s.noteOn) {
        out.push([path, [note, 1]]);
        s.noteOn = true;
        s.note = note;
      } else if (note !== s.note) {
        out.push([path, [s.note, 0]], [path, [note, 1]]);
        s.note = note;
      }
    } else if (s.noteOn) {
      out.push([path, [s.note, 0]]);
      s.noteOn = false;
    }
  }

  _xy(side, s, dt, out) {
    if (!s.present) {
      s.relPalm = null;
      return;
    }
    const xr = this.cfg.xr;
    const XY = this.cfg.xy;
    const half = xr.zone_half_size_m;
    const p = s.features.palm;
    let nx;
    let ny;
    if (XY.relative) {
      if (!s.relPalm) s.relPalm = p;
      nx = clamp01(s.x + (p.x - s.relPalm.x) / (half[0] * 2));
      ny = clamp01(s.y + (p.y - s.relPalm.y) / (half[1] * 2));
      s.relPalm = p;
    } else {
      const c = zoneCenter(side, xr);
      nx = clamp01(((p.x - c.x) / half[0]) * 0.5 + 0.5);
      ny = clamp01(((p.y - c.y) / half[1]) * 0.5 + 0.5);
    }
    s.x = smooth(s.x, nx, XY.alpha, XY.slew, dt);
    s.y = smooth(s.y, ny, XY.alpha, XY.slew, dt);
    s.outX = Math.abs(s.x - 0.5) < XY.deadZone ? 0.5 : s.x;
    s.outY = Math.abs(s.y - 0.5) < XY.deadZone ? 0.5 : s.y;
    out.push([`/hand/${side}/xy`, [s.outX, s.outY]]);
  }

  // Push the hand forward (away from you) for higher values.
  _depth(side, s, dt, out) {
    if (!s.present) return;
    const xr = this.cfg.xr;
    const c = zoneCenter(side, xr);
    const raw = clamp01(0.5 + (c.z - s.features.palm.z) / (2 * xr.zone_half_size_m[2]));
    s.depth = smooth(s.depth, raw, this.cfg.depth.alpha, this.cfg.depth.slew, dt);
    out.push([`/hand/${side}/depth`, [s.depth]]);
  }

  // Tilt of the knuckle line (index MCP -> pinky MCP) in the frontal plane,
  // like turning a dial. Level = 0.5, +/- roll_range_deg spans 0..1. The
  // left hand is mirrored so both hands read the same way.
  _roll(side, s, dt, out) {
    if (!s.present) return;
    const k = s.features.knuckles;
    const kx = side === 'left' ? -k.x : k.x;
    const range = (this.cfg.xr.roll_range_deg * Math.PI) / 180;
    const raw = clamp01(0.5 + Math.atan2(k.y, kx) / (2 * range));
    s.roll = smooth(s.roll, raw, this.cfg.roll.alpha, this.cfg.roll.slew, dt);
    out.push([`/hand/${side}/roll`, [s.roll]]);
  }

  _speed(side, s, dt, out) {
    if (!s.present) {
      s.lastPalm = null;
      s.speed = 0;
      if (s.lostFrames <= LINGER_FRAMES) out.push([`/hand/${side}/speed`, [0]]);
      return;
    }
    const p = s.features.palm;
    if (s.lastPalm && dt > 0) {
      // Small floor so tracking jitter at rest reads as zero.
      const v = Math.max(0, dist(p, s.lastPalm) / dt - 0.03);
      const raw = clamp01(v / this.cfg.xr.speed_cap_mps);
      s.speed += emaAlpha(this.cfg.speed.alpha, dt) * (raw - s.speed);
      out.push([`/hand/${side}/speed`, [s.speed]]);
    }
    s.lastPalm = p;
  }

  // A tap is a quick flex of one finger toward the palm, measured relative to
  // its own knuckle so moving or flicking the whole hand does not trigger it.
  // It fires when the flick stops (the "impact").
  _tap(side, s, t, dt, out) {
    const xr = this.cfg.xr;
    for (const f of this.cfg.tap.fingers) {
      const st = s.tap[f] || (s.tap[f] = { h: null, armed: false, armedAt: 0 });
      if (!s.present) {
        st.h = null;
        st.armed = false;
        continue;
      }
      const tip = s.joints[`${f}-finger-tip`];
      const mcp = s.joints[`${f}-finger-phalanx-proximal`];
      const h = dot(sub(tip, mcp), s.features.normal);
      if (st.h === null || dt <= 0) {
        st.h = h;
        continue;
      }
      const v = (h - st.h) / dt;
      st.h = h;
      if (v > xr.tap_velocity_mps) {
        if (!st.armed) {
          st.armed = true;
          st.armedAt = t;
        }
      } else if (st.armed && v < xr.tap_velocity_mps * 0.25) {
        st.armed = false;
        if (t - st.armedAt > 0.3) continue; // slow curl, not a flick
        if (s.features.pinchDist < xr.pinch_suppress_m) continue;
        if (s.features.curls[f] > 0.8) continue; // closing into a fist
        if (t - (s.lastTap[f] ?? -Infinity) < this.cfg.tap.cooldown) continue;
        s.lastTap[f] = t;
        out.push([`/event/hand/${side}/tap_${f}`, [1]]);
      }
    }
  }

  _gesture(side, s, t, out) {
    const send = (g, v) => out.push([`/hand/${side}/gesture/${g.toLowerCase()}`, [v]]);
    if (!s.present) {
      s.candidate = 'None';
      if (s.gesture !== 'None') {
        send(s.gesture, 0);
        s.gesture = 'None';
      }
      return;
    }
    const raw = classifyGesture(s.features);
    if (raw !== s.candidate) {
      s.candidate = raw;
      s.candidateSince = t;
    }
    if (s.candidate !== s.gesture && t - s.candidateSince >= this.cfg.gesture.holdS) {
      if (s.gesture !== 'None') send(s.gesture, 0);
      s.gesture = s.candidate;
      if (s.gesture !== 'None') send(s.gesture, 1);
    }
  }

  // Left fist = shift layer.
  _shift(dt, out) {
    const S = this.cfg.shift;
    const s = this.sides.left;
    if (!s.present) {
      this.fist = 0;
      if (this.shift) {
        this.shift = false;
        out.push(['/shift', [0]]);
      }
      return;
    }
    const c = s.features.curls;
    const fist = (c.index + c.middle + c.ring + c.pinky) / 4;
    this.fist += emaAlpha(S.alpha, dt) * (fist - this.fist);
    if (!this.shift && this.fist >= S.on) {
      this.shift = true;
      out.push(['/shift', [1]]);
    } else if (this.shift && this.fist <= S.off) {
      this.shift = false;
      out.push(['/shift', [0]]);
    }
  }
}
