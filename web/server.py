"""FastAPI Web Server with WebSocket for real-time communication."""
import asyncio
import json
import logging
from typing import List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from core.config import Config
from modules.orchestrator import Orchestrator

logger = logging.getLogger(__name__)


class WebServer:
    """Web server with WebSocket for real-time orchestrator communication."""

    def __init__(self, config: Config, orchestrator: Orchestrator):
        self.config = config
        self.orchestrator = orchestrator
        self.app = FastAPI(title="Agent Orchestrator", version="1.0.0")
        self.active_connections: List[WebSocket] = []
        self._setup_routes()

    def _setup_routes(self):
        """Setup all routes."""
        self.app.mount("/static", StaticFiles(directory="web/static"), name="static")
        templates = Jinja2Templates(directory="web/templates")

        @self.app.get("/", response_class=HTMLResponse)
        async def index(request: Request):
            return templates.TemplateResponse("index.html", {"request": request})

        @self.app.get("/api/status")
        async def get_status():
            return self.orchestrator.state.get_status_dict()

        @self.app.get("/api/files")
        async def get_files():
            files = []
            for path, info in self.orchestrator.state.repo.files.items():
                files.append({
                    "path": info.relative_path,
                    "priority": info.priority_tag,
                    "indexed": info.indexed,
                    "extension": info.extension,
                    "size": info.size_bytes,
                    "insight": info.insight,
                })
            return {"files": files}

        @self.app.get("/api/insights/{file_path:path}")
        async def get_insight(file_path: str):
            info = self.orchestrator.state.repo.files.get(file_path)
            if info:
                return {"path": file_path, "insight": info.insight}
            return {"error": "File not found"}

        @self.app.get("/api/cr")
        async def get_cr():
            return self.orchestrator.state.repo.cr_results or {}

        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            self.active_connections.append(websocket)
            logger.info(f"WebSocket connected. Active: {len(self.active_connections)}")

            # Set message handler for orchestrator
            async def send_to_ws(content: str, msg_type: str = "info"):
                await self._broadcast({
                    "type": "message",
                    "content": content,
                    "msg_type": msg_type,
                })
                # Also send state update
                await self._broadcast({
                    "type": "state_update",
                    "data": self.orchestrator.state.get_status_dict(),
                })

            self.orchestrator.set_message_handler(send_to_ws)

            # Send welcome message
            await websocket.send_json({
                "type": "message",
                "content": "⚡ Chào mừng đến với **Agent Orchestrator**.\nGõ `/help` để xem danh sách lệnh.",
                "msg_type": "welcome",
            })

            try:
                while True:
                    data = await websocket.receive_text()
                    try:
                        msg = json.loads(data)
                        command = msg.get("command", "")
                    except json.JSONDecodeError:
                        command = data

                    if command:
                        # Run command in background task
                        asyncio.create_task(
                            self.orchestrator.handle_command(command)
                        )
            except WebSocketDisconnect:
                self.active_connections.remove(websocket)
                logger.info(f"WebSocket disconnected. Active: {len(self.active_connections)}")

    async def _broadcast(self, message: dict):
        """Broadcast message to all connected WebSocket clients."""
        disconnected = []
        for ws in self.active_connections:
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(ws)

        for ws in disconnected:
            self.active_connections.remove(ws)
