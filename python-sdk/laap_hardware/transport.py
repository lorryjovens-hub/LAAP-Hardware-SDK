"""LHP 传输层 — WebSocket / BLE"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Dict, Optional
from abc import ABC, abstractmethod

logger = logging.getLogger("laap_hardware.transport")


class Transport(ABC):
    """传输层基类"""

    @abstractmethod
    async def connect(self) -> bool:
        pass

    @abstractmethod
    async def send(self, data: str) -> bool:
        pass

    @abstractmethod
    async def close(self):
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        pass


class WebSocketTransport(Transport):
    """WebSocket 传输层"""

    def __init__(self, url: str):
        self.url = url
        self._ws = None
        self._connected = False
        self._on_message: Optional[Callable] = None
        self._reader_task: Optional[asyncio.Task] = None

    async def connect(self) -> bool:
        try:
            import websocket
            import ssl as ssl_module

            self._ws = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: websocket.create_connection(
                    self.url,
                    sslopt={"cert_reqs": ssl_module.CERT_NONE},
                    timeout=30,
                )
            )
            self._connected = True
            logger.info(f"WebSocket connected: {self.url[:50]}...")
            self._reader_task = asyncio.create_task(self._read_loop())
            return True
        except Exception as e:
            logger.error(f"WebSocket connect failed: {e}")
            return False

    async def _read_loop(self):
        while self._connected:
            try:
                raw = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self._ws.recv()
                )
                if raw is None:
                    await asyncio.sleep(0.1)
                    continue
                if self._on_message:
                    await self._on_message(raw)
            except Exception as e:
                logger.error(f"WebSocket read error: {e}")
                break

    async def send(self, data: str) -> bool:
        if not self._connected or not self._ws:
            return False
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._ws.send(data)
            )
            return True
        except Exception as e:
            logger.error(f"WebSocket send error: {e}")
            return False

    async def close(self):
        self._connected = False
        if self._reader_task:
            self._reader_task.cancel()
        if self._ws:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, self._ws.close
                )
            except Exception:
                pass

    def is_connected(self) -> bool:
        return self._connected

    def on_message(self, callback: Callable):
        self._on_message = callback


class BLETransport(Transport):
    """BLE 传输层（模拟实现，需要平台适配）"""

    def __init__(self, device_name: str = "LAAPGadget"):
        self.device_name = device_name
        self._connected = False
        self._on_message: Optional[Callable] = None

    async def connect(self) -> bool:
        logger.warning("BLE transport: simulated mode")
        self._connected = True
        return True

    async def send(self, data: str) -> bool:
        if not self._connected:
            return False
        logger.info(f"BLE send ({len(data)} bytes)")
        return True

    async def close(self):
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def on_message(self, callback: Callable):
        self._on_message = callback