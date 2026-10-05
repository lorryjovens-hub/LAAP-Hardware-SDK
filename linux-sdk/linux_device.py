"""LAAP Linux Device SDK — 把树莓派/Linux 变成 LAAP 躯体"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any, Dict

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "python-sdk"))

from laap_hardware import LAAPDevice

logger = logging.getLogger("laap_linux")


class LinuxDevice(LAAPDevice):
    """Linux 设备 — 提供系统命令执行、文件操作、健康监控"""

    def __init__(self, device_id: str = "", name: str = ""):
        super().__init__(
            device_id=device_id or f"linux-{platform.node()}",
            name=name or platform.node(),
            device_type="linux",
            firmware_version="0.1.0",
        )

        # 注册能力
        self.add_capability("io.gpio")
        self.add_capability("sensor.system")
        self.add_capability("actuator.shell")

        # 注册内置工具
        self._register_builtin_tools()

    def _register_builtin_tools(self):
        self.add_tool(
            "system.run",
            self._system_run,
            "执行 shell 命令",
            {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        )
        self.add_tool(
            "file.read",
            self._file_read,
            "读取文件",
            {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )
        self.add_tool(
            "file.write",
            self._file_write,
            "写入文件",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        )
        self.add_tool(
            "device.health",
            self._device_health,
            "设备健康状态",
            {"type": "object", "properties": {}},
        )

    def _system_run(self, args: Dict) -> Dict:
        command = args.get("command", "")
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True,
                text=True, timeout=30
            )
            return {
                "stdout": result.stdout[:96000],
                "stderr": result.stderr[:2000],
                "exit_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"error": "timeout"}
        except Exception as e:
            return {"error": str(e)}

    def _file_read(self, args: Dict) -> Dict:
        path = args.get("path", "")
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return {"content": f.read(65536)}
        except Exception as e:
            return {"error": str(e)}

    def _file_write(self, args: Dict) -> Dict:
        path = args.get("path", "")
        content = args.get("content", "")
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return {"status": "ok", "bytes": len(content)}
        except Exception as e:
            return {"error": str(e)}

    def _device_health(self, args: Dict) -> Dict:
        try:
            import psutil
            return {
                "uptime": time.time() - psutil.boot_time(),
                "cpu_percent": psutil.cpu_percent(interval=0.5),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_percent": psutil.disk_usage("/").percent if os.name != "nt"
                    else psutil.disk_usage("C:\\").percent,
            }
        except ImportError:
            return {
                "uptime": time.time(),
                "platform": platform.platform(),
            }


async def main():
    """CLI 入口"""
    import argparse
    parser = argparse.ArgumentParser(description="LAAP Linux Device")
    parser.add_argument("--broker", type=str, default="ws://localhost:8765",
                        help="LAAP Broker URL")
    parser.add_argument("--device-id", type=str, default="")
    parser.add_argument("--name", type=str, default="")
    args = parser.parse_args()

    device = LinuxDevice(device_id=args.device_id, name=args.name)
    print(f"LAAP Linux Device: {device.device_id}")
    print(f"  Platform: {platform.platform()}")
    print(f"  Tools: {len(device.tools.list_tools())}")
    print(f"  Connecting to {args.broker}...")

    ok = await device.connect(args.broker)
    if ok:
        print("  Connected! Waiting for commands...")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            await device.disconnect()
    else:
        print("  Connection failed")


if __name__ == "__main__":
    asyncio.run(main())