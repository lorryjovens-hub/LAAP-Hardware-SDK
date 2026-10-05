"""LAAP Hardware Broker — 设备与 Agent 的桥梁

管理设备注册、工具路由、消息转发。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger("laap_hardware.broker")


class DeviceSession:
    """设备会话"""

    def __init__(self, device_id: str, name: str, send_func: Callable):
        self.device_id = device_id
        self.name = name
        self.send = send_func
        self.capabilities: Dict = {}
        self.tools: List[Dict] = []
        self.connected_at = time.time()
        self.last_heartbeat = time.time()
        self.is_online = True


class LAAPBroker:
    """LAAP Hardware Broker

    连接设备与 LAAP Agent 的桥梁。

    用法：
        broker = LAAPBroker()
        await broker.start(port=8765)
    """

    def __init__(self):
        self._devices: Dict[str, DeviceSession] = {}
        self._agents: Dict[str, Callable] = {}  # agent_id -> send_func
        self._server = None
        self._tool_handlers: Dict[str, Callable] = {}

    async def start(self, host: str = "0.0.0.0", port: int = 8765):
        """启动 Broker"""
        try:
            import websockets
            self._server = await websockets.serve(
                self._handle_connection, host, port
            )
            logger.info(f"LAAP Broker started on ws://{host}:{port}")
            await self._server.wait_closed()
        except ImportError:
            logger.error("websockets library not installed")
        except Exception as e:
            logger.error(f"Broker start failed: {e}")

    async def _handle_connection(self, websocket, path):
        """处理 WebSocket 连接"""
        logger.info(f"New connection: {path}")
        device_id = None

        try:
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                method = msg.get("method", "")
                params = msg.get("params", {})
                msg_id = msg.get("id")

                if method == "device.register":
                    device_id = params.get("device_id", "unknown")
                    session = DeviceSession(
                        device_id=device_id,
                        name=params.get("name", device_id),
                        send_func=websocket.send,
                    )
                    session.capabilities = params.get("capabilities", {})
                    session.tools = params.get("tools", [])
                    self._devices[device_id] = session

                    # 响应
                    resp = {"jsonrpc": "2.0", "id": msg_id,
                            "result": {"status": "registered"}}
                    await websocket.send(json.dumps(resp))
                    logger.info(f"Device registered: {device_id}")

                elif method == "device.heartbeat":
                    if device_id in self._devices:
                        self._devices[device_id].last_heartbeat = time.time()
                    resp = {"jsonrpc": "2.0", "id": msg_id, "result": {"status": "ok"}}
                    await websocket.send(json.dumps(resp))

                elif method == "tools.call":
                    # 路由到设备
                    target = params.get("device_id", device_id)
                    if target in self._devices:
                        session = self._devices[target]
                        await session.send(raw)

                else:
                    # 默认转发
                    if device_id in self._devices:
                        session = self._devices[device_id]
                        await session.send(raw)

        except Exception as e:
            logger.error(f"Connection error: {e}")
        finally:
            if device_id and device_id in self._devices:
                self._devices[device_id].is_online = False
                logger.info(f"Device disconnected: {device_id}")

    def list_devices(self) -> List[Dict]:
        """列出所有设备"""
        return [
            {
                "device_id": d.device_id,
                "name": d.name,
                "online": d.is_online,
                "capabilities": d.capabilities,
                "tools": len(d.tools),
                "connected_at": d.connected_at,
            }
            for d in self._devices.values()
        ]

    async def call_device_tool(self, device_id: str, tool_name: str,
                                args: Dict) -> Any:
        """调用设备工具"""
        session = self._devices.get(device_id)
        if not session or not session.is_online:
            return {"error": f"Device {device_id} not available"}

        msg = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000),
            "method": "tools.call",
            "params": {"tool_name": tool_name, "args": args},
        }
        await session.send(json.dumps(msg))
        # TODO: 等待响应
        return {"status": "sent"}

    async def broadcast(self, content: str):
        """向所有设备广播消息"""
        msg = {
            "jsonrpc": "2.0",
            "method": "message.receive",
            "params": {"content": content},
        }
        for session in self._devices.values():
            if session.is_online:
                await session.send(json.dumps(msg))