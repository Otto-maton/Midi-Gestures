// Floating canvas-textured panels: the info HUD and the pokeable button strip.
import * as THREE from 'three';

const C = {
  bg: 'rgba(10, 14, 22, 0.86)',
  border: 'rgba(255, 255, 255, 0.10)',
  text: '#e6edf3',
  dim: '#6b7785',
  faint: 'rgba(255, 255, 255, 0.07)',
  right: '#35d0ff',
  left: '#ff7ab8',
  shift: '#ffb340',
  ok: '#3ddc84',
  bad: '#ff4d5e',
};
const FONT = 'system-ui, -apple-system, Segoe UI, sans-serif';
const HUD_REDRAW_S = 1 / 15;

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}

class CanvasPanel {
  constructor(widthM, heightM, widthPx) {
    this.widthM = widthM;
    this.heightM = heightM;
    this.canvas = document.createElement('canvas');
    this.canvas.width = widthPx;
    this.canvas.height = Math.round((widthPx * heightM) / widthM);
    this.ctx = this.canvas.getContext('2d');
    this.texture = new THREE.CanvasTexture(this.canvas);
    this.texture.colorSpace = THREE.SRGBColorSpace;
    this.texture.anisotropy = 4;
    this.mesh = new THREE.Mesh(
      new THREE.PlaneGeometry(widthM, heightM),
      new THREE.MeshBasicMaterial({ map: this.texture, transparent: true, depthWrite: false }),
    );
    this.mesh.renderOrder = 5;
  }

  commit() {
    this.texture.needsUpdate = true;
  }
}

const ROWS = [
  { key: 'x', label: 'X', path: 'xy', out: 0, value: (s) => s.outX },
  { key: 'y', label: 'Y', path: 'xy', out: 1, value: (s) => s.outY },
  { key: 'pinch', label: 'Pinch', path: 'pinch', out: 0, value: (s) => s.pinch },
  { key: 'roll', label: 'Roll', path: 'roll', out: 0, value: (s) => s.roll },
  { key: 'depth', label: 'Depth', path: 'depth', out: 0, value: (s) => s.depth },
  { key: 'speed', label: 'Speed', path: 'speed', out: 0, value: (s) => s.speed },
];

export class Hud extends CanvasPanel {
  constructor() {
    super(0.56, 0.24, 1024);
    this.lastDraw = -Infinity;
  }

  // info: { engine, lookup, link, muted, lastEvent, taps, notice }
  update(t, info) {
    if (t - this.lastDraw < HUD_REDRAW_S) return;
    this.lastDraw = t;
    const { ctx, canvas } = this;
    const W = canvas.width;
    const H = canvas.height;
    const { engine, lookup, link, muted } = info;
    ctx.clearRect(0, 0, W, H);
    roundRect(ctx, 2, 2, W - 4, H - 4, 28);
    ctx.fillStyle = C.bg;
    ctx.fill();
    ctx.strokeStyle = C.border;
    ctx.lineWidth = 2;
    ctx.stroke();

    // Header: title and connection status.
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    ctx.fillStyle = C.text;
    ctx.font = `700 28px ${FONT}`;
    ctx.fillText('MIDI GESTURES XR', 28, 44);

    const st = link.status;
    const midiOk = !!(st && st.midi && st.midi.connected);
    let x = W - 28;
    ctx.textAlign = 'right';
    ctx.font = `500 21px ${FONT}`;
    const midiText = st ? `MIDI  ${st.midi.port || '?'}` : 'MIDI  --';
    x = this._status(x, 44, midiText, link.open ? (midiOk ? C.ok : C.bad) : C.dim);
    const rtt = link.rtt == null ? '' : `  ${Math.round(link.rtt)} ms`;
    this._status(x - 28, 44, `PC bridge${rtt}`, link.open ? C.ok : C.bad);

    // Mode / shift / mute chips and the last event.
    ctx.textAlign = 'left';
    let cx = 28;
    ctx.font = `600 18px ${FONT}`;
    ctx.fillStyle = C.dim;
    ctx.fillText('MODE', cx, 98);
    cx += 62;
    for (let m = 0; m < engine.cfg.numModes; m++) {
      cx = this._chip(cx, 98, String(m + 1), m === engine.mode ? C.text : null) + 6;
    }
    cx = this._chip(cx + 14, 98, 'SHIFT', engine.shift ? C.shift : null) + 8;
    if (muted) cx = this._chip(cx, 98, 'MUTED', C.bad) + 8;
    if (info.notice) {
      ctx.fillStyle = C.shift;
      ctx.font = `500 19px ${FONT}`;
      ctx.fillText(info.notice, cx + 12, 98);
    } else if (info.lastEvent) {
      ctx.fillStyle = C.dim;
      ctx.font = `500 19px ${FONT}`;
      ctx.fillText(info.lastEvent, cx + 12, 98);
    }

    // One column per hand.
    for (const side of ['left', 'right']) {
      const x0 = side === 'left' ? 28 : W / 2 + 12;
      const s = engine.sides[side];
      const accent = side === 'right' && engine.shift ? C.shift : C[side];
      ctx.textAlign = 'left';
      ctx.font = `700 20px ${FONT}`;
      ctx.fillStyle = accent;
      ctx.fillText(side === 'left' ? 'LEFT' : 'RIGHT', x0, 140);
      ctx.font = `500 18px ${FONT}`;
      ctx.fillStyle = C.dim;
      const where = s.present ? 'in zone' : s.tracked ? 'outside zone' : 'not tracked';
      ctx.fillText(where, x0 + 80, 140);

      ROWS.forEach((row, i) => {
        const y = 176 + i * 33;
        const map = lookup(`/hand/${side}/${row.path}`, engine.shift, row.out);
        const live = !!(map && map.enabled);
        const v = row.value(s);
        ctx.font = `500 19px ${FONT}`;
        ctx.textAlign = 'left';
        ctx.fillStyle = live ? C.text : C.dim;
        ctx.fillText(row.label, x0, y);
        ctx.fillStyle = C.dim;
        ctx.fillText(map ? `${map.label}${map.enabled ? '' : ' off'}` : 'unmapped', x0 + 72, y);
        const bx = x0 + 182;
        const bw = 220;
        roundRect(ctx, bx, y - 8, bw, 16, 8);
        ctx.fillStyle = C.faint;
        ctx.fill();
        roundRect(ctx, bx, y - 8, Math.max(16, bw * v), 16, 8);
        ctx.fillStyle = live && s.present ? accent : C.dim;
        ctx.globalAlpha = live && s.present ? 0.9 : 0.35;
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.textAlign = 'right';
        ctx.fillStyle = C.text;
        ctx.fillText(String(Math.round(v * 127)), x0 + 466, y);
      });

      // Gesture and taps.
      const gy = 176 + ROWS.length * 33 + 4;
      ctx.textAlign = 'left';
      ctx.font = `500 19px ${FONT}`;
      if (s.gesture !== 'None') {
        const map = lookup(`/hand/${side}/gesture/${s.gesture.toLowerCase()}`, engine.shift, 0);
        ctx.fillStyle = map && map.enabled ? accent : C.dim;
        ctx.fillText(`${s.gesture.replace('_', ' ')}${map ? `  ${map.label}` : ''}`, x0, gy);
      } else {
        ctx.fillStyle = C.dim;
        ctx.fillText('no gesture', x0, gy);
      }
      if (engine.cfg.xr.tap_sides.includes(side)) {
        let tx = x0 + 466;
        for (const f of [...engine.cfg.tap.fingers].reverse()) {
          const ago = t - (s.lastTap[f] ?? -Infinity);
          tx = this._chip(tx, gy, f[0].toUpperCase(), ago < 0.2 ? accent : null, 'right') - 6;
        }
        ctx.textAlign = 'right';
        ctx.fillStyle = C.dim;
        ctx.fillText('taps', tx - 4, gy);
      }
    }
    this.commit();
  }

  _status(xRight, y, text, color) {
    const { ctx } = this;
    ctx.textAlign = 'right';
    ctx.fillStyle = C.text;
    ctx.fillText(text, xRight, y);
    const w = ctx.measureText(text).width;
    ctx.beginPath();
    ctx.arc(xRight - w - 14, y, 6, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    return xRight - w - 28;
  }

  _chip(x, y, text, color, align = 'left') {
    const { ctx } = this;
    ctx.font = `600 18px ${FONT}`;
    const w = ctx.measureText(text).width + 20;
    const left = align === 'left' ? x : x - w;
    roundRect(ctx, left, y - 15, w, 30, 8);
    ctx.fillStyle = color || C.faint;
    ctx.globalAlpha = color ? 0.9 : 1;
    ctx.fill();
    ctx.globalAlpha = 1;
    ctx.fillStyle = color ? '#0a0e16' : C.dim;
    ctx.textAlign = 'center';
    ctx.fillText(text, left + w / 2, y + 1);
    ctx.textAlign = 'left';
    return align === 'left' ? left + w : left;
  }
}

// Vertical strip of buttons you press with a fingertip.
export class ButtonPanel extends CanvasPanel {
  // buttons: [{ id, label: () => string, color }]
  constructor(buttons) {
    super(0.12, 0.3, 256);
    this.buttons = buttons.map((b, i) => {
      const gap = 16;
      const h = (this.canvas.height - gap * (buttons.length + 1)) / buttons.length;
      const rect = { x: gap, y: gap + i * (h + gap), w: this.canvas.width - 2 * gap, h };
      return { ...b, rect, hover: false, pressed: false, armed: true };
    });
    this._v = new THREE.Vector3();
    this.dirty = true;
  }

  _local(rect) {
    const W = this.canvas.width;
    const H = this.canvas.height;
    return {
      x0: (rect.x / W - 0.5) * this.widthM,
      x1: ((rect.x + rect.w) / W - 0.5) * this.widthM,
      y0: (0.5 - (rect.y + rect.h) / H) * this.heightM,
      y1: (0.5 - rect.y / H) * this.heightM,
    };
  }

  // tips: world-space fingertip positions. Calls onPress(id) once per poke.
  poke(tips, onPress) {
    for (const b of this.buttons) {
      const r = this._local(b.rect);
      let hover = false;
      let near = false;
      let touch = false;
      for (const tip of tips) {
        const p = this.mesh.worldToLocal(this._v.copy(tip));
        const inside = p.x > r.x0 && p.x < r.x1 && p.y > r.y0 && p.y < r.y1 && p.z > -0.05;
        if (inside && p.z < 0.07) hover = true;
        if (inside && p.z < 0.03) near = true;
        if (inside && p.z < 0.012) touch = true;
      }
      if (touch && b.armed) {
        b.armed = false;
        onPress(b.id);
      }
      // Re-arm once the finger backs off the surface (hysteresis vs. touch).
      if (!near) b.armed = true;
      if (hover !== b.hover || touch !== b.pressed) {
        b.hover = hover;
        b.pressed = touch;
        this.dirty = true;
      }
    }
  }

  draw(force = false) {
    if (!this.dirty && !force) return;
    this.dirty = false;
    const { ctx, canvas } = this;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    roundRect(ctx, 2, 2, canvas.width - 4, canvas.height - 4, 24);
    ctx.fillStyle = C.bg;
    ctx.fill();
    for (const b of this.buttons) {
      const { x, y, w, h } = b.rect;
      roundRect(ctx, x, y, w, h, 18);
      ctx.fillStyle = b.pressed ? b.color : b.hover ? 'rgba(255,255,255,0.16)' : C.faint;
      ctx.fill();
      ctx.lineWidth = 3;
      ctx.strokeStyle = b.color;
      ctx.stroke();
      ctx.fillStyle = b.pressed ? '#0a0e16' : C.text;
      ctx.font = `700 30px ${FONT}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(b.label(), x + w / 2, y + h / 2);
    }
    this.commit();
  }
}

export const BUTTON_COLORS = C;
