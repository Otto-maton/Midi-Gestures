// WebSocket link to the PC bridge. Sends one batch of [path, args] bus
// messages per XR frame and receives bridge/MIDI status.

const PING_INTERVAL_MS = 2000;
const RECONNECT_MS = 1500;
const BACKLOG_BYTES = 64 * 1024;

// Edges (note on/off, shift, gestures...) must never be dropped. Continuous
// values are, when the network backs up, since newer ones follow next frame.
export function isEdge(path) {
  return (
    path.startsWith('/event/') ||
    path === '/shift' ||
    path === '/mode/index' ||
    path.includes('/gesture/') ||
    path.endsWith('/present') ||
    path.endsWith('/pinch_pitch')
  );
}

const round = (v) => Math.round(v * 1e4) / 1e4;

export class Link {
  constructor(url) {
    this.url = url;
    this.ws = null;
    this.open = false;
    this.rtt = null;
    this.status = null;
    this.sent = 0;
    this._pingTimer = setInterval(() => this._ping(), PING_INTERVAL_MS);
    this._connect();
  }

  _connect() {
    let ws;
    try {
      ws = new WebSocket(this.url);
    } catch (e) {
      setTimeout(() => this._connect(), RECONNECT_MS);
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      this.open = true;
      this._ping();
    };
    ws.onmessage = (e) => {
      let d;
      try {
        d = JSON.parse(e.data);
      } catch {
        return;
      }
      if (d.type === 'status') this.status = d;
      else if (d.type === 'pong') this.rtt = performance.now() - d.t;
    };
    ws.onclose = () => {
      this.open = false;
      this.ws = null;
      this.status = null;
      this.rtt = null;
      setTimeout(() => this._connect(), RECONNECT_MS);
    };
  }

  _ping() {
    if (this.open) this.ws.send(JSON.stringify({ ping: performance.now() }));
  }

  send(messages) {
    if (!this.open || messages.length === 0) return;
    let batch = messages;
    if (this.ws.bufferedAmount > BACKLOG_BYTES) batch = messages.filter(([p]) => isEdge(p));
    if (batch.length === 0) return;
    this.ws.send(JSON.stringify({ m: batch.map(([p, a]) => [p, a.map(round)]) }));
    this.sent += batch.length;
  }
}
