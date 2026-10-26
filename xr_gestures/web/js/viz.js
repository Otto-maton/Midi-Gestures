// 3D feedback: tracked hand joints, the two control zones with their XY/depth
// cursors, and floating text labels.
import * as THREE from 'three';
import { JOINTS, SIDES, zoneCenter } from './gestures.js';

export const COLORS = {
  right: new THREE.Color(0x35d0ff),
  left: new THREE.Color(0xff7ab8),
  shift: new THREE.Color(0xffb340),
  idle: new THREE.Color(0x6b7785),
  white: new THREE.Color(0xffffff),
};

const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
export const noteName = (n) => `${NOTE_NAMES[n % 12]}${Math.floor(n / 12) - 1}`;

const TAP_FLASH_S = 0.18;

// Billboard text drawn to a canvas; redraws only when the text changes.
export class TextSprite {
  constructor(heightM = 0.03, { px = 64, widthPx = 512, color = '#e6edf3' } = {}) {
    this.canvas = document.createElement('canvas');
    this.canvas.width = widthPx;
    this.canvas.height = px * 1.5;
    this.ctx = this.canvas.getContext('2d');
    this.px = px;
    this.color = color;
    this.texture = new THREE.CanvasTexture(this.canvas);
    this.texture.colorSpace = THREE.SRGBColorSpace;
    this.sprite = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: this.texture, transparent: true, depthWrite: false }),
    );
    this.sprite.scale.set((heightM * this.canvas.width) / this.canvas.height, heightM, 1);
    this.sprite.renderOrder = 10;
    this.text = null;
  }

  set(text, color = this.color) {
    if (text === this.text && color === this.drawnColor) return;
    this.text = text;
    this.drawnColor = color;
    const { ctx, canvas, px } = this;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.font = `600 ${px}px system-ui, -apple-system, Segoe UI, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.lineWidth = px / 6;
    ctx.strokeStyle = 'rgba(5, 8, 14, 0.85)';
    ctx.strokeText(text, canvas.width / 2, canvas.height / 2);
    ctx.fillStyle = color;
    ctx.fillText(text, canvas.width / 2, canvas.height / 2);
    this.texture.needsUpdate = true;
  }
}

export class HandViz {
  constructor(scene) {
    this.mesh = new THREE.InstancedMesh(
      new THREE.SphereGeometry(1, 12, 8),
      new THREE.MeshBasicMaterial({ color: 0xffffff }),
      JOINTS.length * 2,
    );
    this.mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.mesh.frustumCulled = false;
    for (let i = 0; i < this.mesh.count; i++) this.mesh.setColorAt(i, COLORS.white);
    scene.add(this.mesh);

    this.pinchLines = {};
    for (const side of SIDES) {
      const geo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]);
      const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ transparent: true }));
      line.frustumCulled = false;
      line.visible = false;
      scene.add(line);
      this.pinchLines[side] = line;
    }
    this.flashes = {};
    this._m = new THREE.Matrix4();
    this._p = new THREE.Vector3();
    this._q = new THREE.Quaternion();
    this._s = new THREE.Vector3();
    this._c = new THREE.Color();
  }

  flash(side, finger, t) {
    this.flashes[`${side}-${finger}`] = t;
  }

  // world: { left, right } joints in world metres (or null); engine: GestureEngine.
  update(world, engine, t) {
    SIDES.forEach((side, h) => {
      const j = world[side];
      const s = engine.sides[side];
      const base = side === 'left' && engine.shift ? COLORS.shift : COLORS[side];
      JOINTS.forEach((name, k) => {
        const i = h * JOINTS.length + k;
        if (!j) {
          this._m.makeScale(0, 0, 0);
          this.mesh.setMatrixAt(i, this._m);
          return;
        }
        const p = j[name];
        let r = Math.max(0.004, (p.r || 0.008) * 0.8);
        this._c.copy(s.present ? base : COLORS.idle);
        if (name.endsWith('-tip')) {
          const f = this.flashes[`${side}-${name.split('-')[0]}`];
          if (f !== undefined && t - f < TAP_FLASH_S) {
            const k2 = 1 - (t - f) / TAP_FLASH_S;
            r *= 1 + 1.2 * k2;
            this._c.lerp(COLORS.white, k2);
          }
        }
        this._p.set(p.x, p.y, p.z);
        this._s.setScalar(r);
        this._m.compose(this._p, this._q, this._s);
        this.mesh.setMatrixAt(i, this._m);
        this.mesh.setColorAt(i, this._c);
      });

      const line = this.pinchLines[side];
      line.visible = !!j && s.present;
      if (line.visible) {
        const a = j['thumb-tip'];
        const b = j['index-finger-tip'];
        const pos = line.geometry.attributes.position;
        pos.setXYZ(0, a.x, a.y, a.z);
        pos.setXYZ(1, b.x, b.y, b.z);
        pos.needsUpdate = true;
        line.material.color.copy(s.pinchActive ? COLORS.white : base);
        line.material.opacity = 0.15 + 0.85 * s.pinch;
      }
    });
    this.mesh.instanceMatrix.needsUpdate = true;
    this.mesh.instanceColor.needsUpdate = true;
  }
}

// One translucent box per hand. The cursor shows where the palm sits in the
// box: x/y are the XY pad, front/back is depth.
export class ZoneViz {
  constructor(root, xr) {
    this.zones = {};
    const [hx, hy, hz] = xr.zone_half_size_m;
    this.half = [hx, hy, hz];
    for (const side of SIDES) {
      const c = zoneCenter(side, xr);
      const group = new THREE.Group();
      group.position.set(c.x, c.y, c.z);
      root.add(group);

      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(new THREE.BoxGeometry(hx * 2, hy * 2, hz * 2)),
        new THREE.LineBasicMaterial({ color: COLORS[side], transparent: true }),
      );
      group.add(edges);

      const back = new THREE.Mesh(
        new THREE.PlaneGeometry(hx * 2, hy * 2),
        new THREE.MeshBasicMaterial({ color: COLORS[side], transparent: true, opacity: 0.06, depthWrite: false }),
      );
      back.position.z = -hz;
      group.add(back);

      const cursor = new THREE.Mesh(
        new THREE.SphereGeometry(0.011, 16, 12),
        new THREE.MeshBasicMaterial({ color: COLORS[side], transparent: true }),
      );
      group.add(cursor);

      const crossGeo = new THREE.BufferGeometry().setFromPoints(
        [0, 1, 2, 3].map(() => new THREE.Vector3()),
      );
      const cross = new THREE.LineSegments(
        crossGeo,
        new THREE.LineBasicMaterial({ color: COLORS[side], transparent: true }),
      );
      cross.frustumCulled = false;
      group.add(cross);

      const label = new TextSprite(0.022, { px: 48, widthPx: 768 });
      label.sprite.position.set(0, hy + 0.025, 0);
      group.add(label.sprite);

      this.zones[side] = { group, edges, back, cursor, cross, label };
    }
  }

  // labels: { right: string, left: string } text above each zone.
  update(engine, labels) {
    const [hx, hy, hz] = this.half;
    for (const side of SIDES) {
      const z = this.zones[side];
      const s = engine.sides[side];
      const color = side === 'right' && engine.shift ? COLORS.shift : COLORS[side];
      const strength = s.present ? 1 : s.tracked ? 0.45 : 0.25;
      z.edges.material.color.copy(color);
      z.edges.material.opacity = 0.25 + 0.65 * strength;
      z.back.material.color.copy(color);
      z.back.material.opacity = s.present ? 0.1 : 0.04;

      const x = (s.outX - 0.5) * 2 * hx;
      const y = (s.outY - 0.5) * 2 * hy;
      const d = -(s.depth - 0.5) * 2 * hz;
      z.cursor.position.set(x, y, d);
      z.cursor.material.color.copy(color);
      z.cursor.material.opacity = 0.3 + 0.7 * strength;
      const pos = z.cross.geometry.attributes.position;
      pos.setXYZ(0, -hx, y, d);
      pos.setXYZ(1, hx, y, d);
      pos.setXYZ(2, x, -hy, d);
      pos.setXYZ(3, x, hy, d);
      pos.needsUpdate = true;
      z.cross.material.color.copy(color);
      z.cross.material.opacity = 0.15 + 0.35 * strength;

      z.label.set(labels[side], `#${color.getHexString()}`);
    }
  }
}
