from __future__ import annotations
import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Callable

from aiohttp import web, WSMsgType

from midi_gestures.bus import AsyncBus, BusMessage

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent / "web"
STATUS_INTERVAL_S = 1.0
_MAX_BATCH = 256
_MAX_ARGS = 4
_MAX_PATH = 128


def _route(path: str) -> tuple[str, str]:
    """Bus msg_type and priority for a path coming from the headset.

    State changes go in the high-priority lane so they are never dropped or
    queued behind the continuous CC stream.
    """
    if (
        path.startswith("/event/")
        or path in ("/shift", "/mode/index")
        or "/gesture/" in path
        or path.endswith(("/present", "/pinch_pitch"))
    ):
        return "event", "hi"
    return "signal", "lo"


def to_bus_message(item, t_s: float) -> BusMessage | None:
    """Validate one [path, args] pair from the headset."""
    if not isinstance(item, (list, tuple)) or len(item) != 2:
        return None
    path, args = item
    if not isinstance(path, str) or not path.startswith("/") or len(path) > _MAX_PATH:
        return None
    if not isinstance(args, list) or len(args) > _MAX_ARGS:
        return None
    if not all(isinstance(a, (int, float)) and not isinstance(a, bool) for a in args):
        return None
    msg_type, priority = _route(path)
    return BusMessage(path=path, t_s=t_s, args=list(args), msg_type=msg_type, priority=priority)


@web.middleware
async def _no_cache(request, handler):
    # The Quest Browser caches hard; always serve the current app files.
    resp = await handler(request)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


class XRServer:
    """Serves the WebXR app and feeds headset gesture messages into the bus."""

    def __init__(
        self,
        bus: AsyncBus,
        client_config: dict,
        status_fn: Callable[[], dict],
        on_all_disconnected: Callable[[], None],
    ):
        self._bus = bus
        self._client_config = client_config
        self._status_fn = status_fn
        self._on_all_disconnected = on_all_disconnected
        self._clients: set[web.WebSocketResponse] = set()
        self._status_task: asyncio.Task | None = None

    def build_app(self) -> web.Application:
        app = web.Application(middlewares=[_no_cache])
        app.router.add_get("/", self._index)
        app.router.add_get("/api/config", self._config)
        app.router.add_get("/ws", self._ws)
        app.router.add_static("/", WEB_DIR, show_index=False)
        app.on_startup.append(self._start_status_task)
        app.on_shutdown.append(self._shutdown)
        return app

    async def _index(self, _request):
        return web.FileResponse(WEB_DIR / "index.html")

    async def _config(self, _request):
        return web.json_response(self._client_config)

    async def _ws(self, request):
        ws = web.WebSocketResponse(heartbeat=10.0, max_msg_size=1 << 16)
        await ws.prepare(request)
        self._clients.add(ws)
        logger.info("Headset connected from %s (%d client(s))", request.remote, len(self._clients))
        try:
            await ws.send_json(self._status())
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._handle_text(ws, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    break
        finally:
            self._clients.discard(ws)
            logger.info("Headset disconnected from %s (%d client(s))", request.remote, len(self._clients))
            if not self._clients:
                self._on_all_disconnected()
        return ws

    async def _handle_text(self, ws: web.WebSocketResponse, text: str):
        try:
            data = json.loads(text)
        except ValueError:
            return
        if not isinstance(data, dict):
            return
        if "ping" in data:
            await ws.send_json({"type": "pong", "t": data["ping"]})
        batch = data.get("m")
        if not isinstance(batch, list):
            return
        now = time.monotonic()
        for item in batch[:_MAX_BATCH]:
            msg = to_bus_message(item, now)
            if msg is not None:
                self._bus.publish(msg)

    def _status(self) -> dict:
        return {"type": "status", "clients": len(self._clients), **self._status_fn()}

    async def _start_status_task(self, _app):
        self._status_task = asyncio.create_task(self._status_loop())

    async def _status_loop(self):
        while True:
            await asyncio.sleep(STATUS_INTERVAL_S)
            status = self._status()
            for ws in list(self._clients):
                try:
                    await ws.send_json(status)
                except (ConnectionError, RuntimeError):
                    pass

    async def _shutdown(self, _app):
        if self._status_task:
            self._status_task.cancel()
        for ws in list(self._clients):
            await ws.close()
