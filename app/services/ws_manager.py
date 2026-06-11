import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        # Prune any stale connections before adding the new one
        live = []
        for ws in self._connections:
            try:
                await ws.send_json({"type": "ping"})
                live.append(ws)
            except Exception:
                pass
        self._connections = live
        self._connections.append(websocket)
        logger.info("WebSocket client connected", extra={"total": len(self._connections)})

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)
        logger.info("WebSocket client disconnected", extra={"total": len(self._connections)})

    async def broadcast(self, data: dict) -> None:
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.remove(ws)


# Module-level singleton shared across all routers
manager = ConnectionManager()
