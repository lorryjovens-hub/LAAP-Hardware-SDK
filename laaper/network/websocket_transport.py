"""LAAPer 真实 WebSocket 传输 (Real WebSocket Transport)

跨网络的意识帧穿行：让 LAAPer 的意识可以穿越互联网。

支持：
- WebSocket 服务端（宿主）
- WebSocket 客户端（连接到其他宿主）
- 自动重连
- 心跳保活
- 消息队列
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("laaper.websocket")


@dataclass
class ConnectionInfo:
    """连接信息"""
    connection_id: str
    host_id: str
    remote_address: str
    connected_at: float = field(default_factory=time.time)
    last_ping: float = field(default_factory=time.time)
    is_alive: bool = True


class WebSocketServer:
    """WebSocket 服务端 — 接收其他宿主的意识帧"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port
        self._server = None
        self._connections: Dict[str, ConnectionInfo] = {}
        self._clients: Dict[str, Any] = {}  # connection_id -> websocket

        # 回调
        self._on_frame_received: Optional[Callable] = None
        self._on_connection_opened: Optional[Callable] = None
        self._on_connection_closed: Optional[Callable] = None

        # 消息队列
        self._inbox: List[Dict] = []

    async def start(self):
        """启动 WebSocket 服务端"""
        try:
            import websockets
            self._server = await websockets.serve(
                self._handle_client,
                self.host,
                self.port,
                ping_interval=30,
                ping_timeout=10,
            )
            logger.info(f"WebSocket server started on ws://{self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"WebSocket server start failed: {e}")
            return False

    async def _handle_client(self, websocket, path):
        """处理客户端连接"""
        connection_id = f"conn_{int(time.time() * 1000)}"
        client_info = ConnectionInfo(
            connection_id=connection_id,
            host_id="",  # 等待注册
            remote_address=str(websocket.remote_address),
        )
        self._connections[connection_id] = client_info
        self._clients[connection_id] = websocket

        logger.info(f"New connection: {connection_id} from {client_info.remote_address}")

        if self._on_connection_opened:
            self._on_connection_opened(client_info)

        try:
            async for message in websocket:
                await self._handle_message(connection_id, message)
        except Exception as e:
            logger.error(f"Connection {connection_id} error: {e}")
        finally:
            self._connections.pop(connection_id, None)
            self._clients.pop(connection_id, None)
            logger.info(f"Connection closed: {connection_id}")

            if self._on_connection_closed:
                self._on_connection_closed(client_info)

    async def _handle_message(self, connection_id: str, raw: str):
        """处理消息"""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        method = msg.get("method", "")

        if method == "register":
            # 注册宿主
            self._connections[connection_id].host_id = msg.get("host_id", "")
            logger.info(f"Host {msg.get('host_id')} registered")

        elif method == "frame":
            # 接收意识帧
            self._inbox.append(msg)
            if self._on_frame_received:
                self._on_frame_received(msg)

        elif method == "ping":
            # 心跳
            self._connections[connection_id].last_ping = time.time()

    async def send_to_host(self, host_id: str, message: Dict) -> bool:
        """发送消息到指定宿主"""
        for conn_id, conn in self._connections.items():
            if conn.host_id == host_id and conn.is_alive:
                websocket = self._clients.get(conn_id)
                if websocket:
                    await websocket.send(json.dumps(message))
                    return True
        return False

    async def broadcast(self, message: Dict):
        """广播到所有连接"""
        for conn_id, websocket in self._clients.items():
            try:
                await websocket.send(json.dumps(message))
            except Exception as e:
                logger.error(f"Broadcast to {conn_id} failed: {e}")

    async def stop(self):
        """停止服务"""
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    def get_connections(self) -> List[Dict]:
        return [
            {
                "connection_id": c.connection_id,
                "host_id": c.host_id,
                "remote": c.remote_address,
                "connected_at": c.connected_at,
                "is_alive": c.is_alive,
            }
            for c in self._connections.values()
        ]

    def on_frame_received(self, callback: Callable):
        self._on_frame_received = callback

    def on_connection_opened(self, callback: Callable):
        self._on_connection_opened = callback

    def on_connection_closed(self, callback: Callable):
        self._on_connection_closed = callback


class WebSocketClient:
    """WebSocket 客户端 — 连接到其他宿主"""

    def __init__(self, url: str, host_id: str = ""):
        self.url = url
        self.host_id = host_id
        self._ws = None
        self._connected = False
        self._reconnect_attempts = 0
        self._max_reconnect = 10

        # 回调
        self._on_message: Optional[Callable] = None
        self._on_connected: Optional[Callable] = None
        self._on_disconnected: Optional[Callable] = None

    async def connect(self) -> bool:
        """连接到 WebSocket 服务端"""
        try:
            import websockets
            self._ws = await websockets.connect(
                self.url,
                ping_interval=30,
                ping_timeout=10,
            )
            self._connected = True
            self._reconnect_attempts = 0

            # 注册宿主
            if self.host_id:
                await self._ws.send(json.dumps({
                    "method": "register",
                    "host_id": self.host_id,
                }))

            logger.info(f"Connected to {self.url}")

            if self._on_connected:
                self._on_connected()

            # 启动消息循环
            asyncio.create_task(self._message_loop())
            return True

        except Exception as e:
            logger.error(f"Connect to {self.url} failed: {e}")
            return False

    async def _message_loop(self):
        """消息循环"""
        while self._connected:
            try:
                message = await self._ws.recv()
                if self._on_message:
                    self._on_message(json.loads(message))
            except Exception as e:
                logger.error(f"Message loop error: {e}")
                self._connected = False

                if self._on_disconnected:
                    self._on_disconnected()

                # 自动重连
                if self._reconnect_attempts < self._max_reconnect:
                    self._reconnect_attempts += 1
                    await asyncio.sleep(2 ** self._reconnect_attempts)
                    await self.connect()

    async def send(self, message: Dict) -> bool:
        """发送消息"""
        if not self._connected or not self._ws:
            return False
        try:
            await self._ws.send(json.dumps(message))
            return True
        except Exception as e:
            logger.error(f"Send failed: {e}")
            return False

    async def send_frame(self, frame_dict: Dict) -> bool:
        """发送意识帧"""
        return await self.send({
            "method": "frame",
            "frame": frame_dict,
        })

    async def close(self):
        """关闭连接"""
        self._connected = False
        if self._ws:
            await self._ws.close()

    def on_message(self, callback: Callable):
        self._on_message = callback

    def on_connected(self, callback: Callable):
        self._on_connected = callback

    def on_disconnected(self, callback: Callable):
        self._on_disconnected = callback