"""Phone MCP Tools — 把手机控制暴露为 MCP 工具

LAAPer 通过这些工具调用手机。

与 actell 的差异：
- actell: 模型直接调用 tap/screenshot 工具
- LAAPer: 语音 → 认知引擎 → 高层任务工具（phone_do_task）或原子工具
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from phone.bridge import BridgeConfig
from phone.controller import PhoneController
from phone.types import TransportRoute
from phone.vision_loop import VisionActionLoop, VisionAnalyzer

logger = logging.getLogger("laap.phone.tools")


# ── MCP 工具定义 ──────────────────────────────────

PHONE_TOOLS = [
    # 高层：一句话完成复杂任务
    {
        "name": "phone_do_task",
        "description": (
            "控制手机完成一个任务。用自然语言描述你要做的事，"
            "LAAPer 会自动截图、理解界面、点击输入，直到完成。"
            "例：'帮我设置明早8点的闹钟'、'打开微信发消息给张三'、"
            "'在设置里把亮度调到最高'"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "任务的自然语言描述",
                },
                "max_steps": {
                    "type": "integer",
                    "description": "最大执行步数，默认 20",
                    "default": 20,
                },
            },
            "required": ["instruction"],
        },
    },
    # 原子工具
    {
        "name": "phone_screenshot",
        "description": "截取手机屏幕，返回当前界面画面",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "phone_tap",
        "description": "点击手机屏幕指定位置（归一化坐标 0-1）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "横坐标 0-1"},
                "y": {"type": "number", "description": "纵坐标 0-1"},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "phone_swipe",
        "description": "在手机屏幕上滑动",
        "inputSchema": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["up", "down", "left", "right"],
                    "description": "滑动方向",
                },
                "distance": {
                    "type": "number",
                    "description": "滑动距离 0-1，默认 0.5",
                    "default": 0.5,
                },
            },
            "required": ["direction"],
        },
    },
    {
        "name": "phone_type",
        "description": "在手机当前的输入框中输入文字",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要输入的文字"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "phone_key",
        "description": "按下手机上的按键",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "enum": ["enter", "escape", "backspace", "home", "delete"],
                    "description": "按键名称",
                },
            },
            "required": ["key"],
        },
    },
    {
        "name": "phone_home",
        "description": "回到手机主屏幕",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "phone_status",
        "description": "查询手机连接状态和统计信息",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "phone_stop",
        "description": "紧急停止手机控制，释放所有输入设备",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# ── 工具执行器 ──────────────────────────────────

class PhoneToolHandler:
    """手机工具执行器

    用法:
        handler = PhoneToolHandler()
        await handler.connect()

        result = await handler.execute("phone_do_task", {
            "instruction": "设置明早8点的闹钟"
        })
    """

    def __init__(
        self,
        config: Optional[BridgeConfig] = None,
        llm_client: Optional[Any] = None,
    ):
        self.config = config or BridgeConfig()
        self.controller = PhoneController(self.config)
        self.analyzer = VisionAnalyzer(llm_client)
        self.loop = VisionActionLoop(self.controller, self.analyzer)

        # 任务历史
        self._task_history: List[Dict] = []

    async def connect(self) -> bool:
        """连接手机"""
        return await self.controller.connect()

    async def disconnect(self):
        await self.controller.disconnect()

    async def execute(self, tool_name: str, args: Dict) -> str:
        """执行工具调用，返回 JSON 字符串"""
        try:
            if tool_name == "phone_do_task":
                return await self._do_task(args)
            elif tool_name == "phone_screenshot":
                return await self._screenshot()
            elif tool_name == "phone_tap":
                return await self._tap(args)
            elif tool_name == "phone_swipe":
                return await self._swipe(args)
            elif tool_name == "phone_type":
                return await self._type(args)
            elif tool_name == "phone_key":
                return await self._key(args)
            elif tool_name == "phone_home":
                return await self._home()
            elif tool_name == "phone_status":
                return await self._status()
            elif tool_name == "phone_stop":
                return await self._stop()
            else:
                return json.dumps({
                    "status": "error",
                    "error": f"未知工具: {tool_name}",
                }, ensure_ascii=False)

        except Exception as e:
            logger.error(f"工具执行失败 {tool_name}: {e}")
            return json.dumps({
                "status": "error",
                "error": str(e),
            }, ensure_ascii=False)

    # ── 工具实现 ──────────────────────────────────

    async def _do_task(self, args: Dict) -> str:
        """执行完整任务"""
        instruction = args.get("instruction", "")
        max_steps = args.get("max_steps", 20)

        if not instruction:
            return json.dumps({
                "status": "error",
                "error": "缺少任务说明",
            }, ensure_ascii=False)

        self.loop.max_steps = max_steps
        result = await self.loop.run(instruction)

        # 记录历史
        self._task_history.append(result.to_dict())

        return json.dumps({
            "status": "ok" if result.success else "failed",
            "task_id": result.task_id,
            "success": result.success,
            "steps": result.total_steps,
            "duration": round(result.duration_seconds, 1),
            "message": result.final_message,
            "error": result.error,
            "detail": result.to_dict(),
        }, ensure_ascii=False)

    async def _screenshot(self) -> str:
        """截屏"""
        frame = await self.controller.screenshot()
        if not frame:
            return json.dumps({
                "status": "error",
                "error": "无法截屏（可能未连接）",
            }, ensure_ascii=False)

        return json.dumps({
            "status": "ok",
            "frame": frame.to_dict(),
            "size_kb": frame.size_kb(),
        }, ensure_ascii=False)

    async def _tap(self, args: Dict) -> str:
        """点击"""
        x = float(args.get("x", 0))
        y = float(args.get("y", 0))
        result = await self.controller.tap(x, y)
        return json.dumps({
            "status": "ok" if result.success else "failed",
            "message": result.message,
        }, ensure_ascii=False)

    async def _swipe(self, args: Dict) -> str:
        """滑动"""
        direction = args.get("direction", "up")
        distance = float(args.get("distance", 0.5))
        result = await self.controller.swipe(direction, distance)
        return json.dumps({
            "status": "ok" if result.success else "failed",
            "message": result.message,
        }, ensure_ascii=False)

    async def _type(self, args: Dict) -> str:
        """输入文字"""
        text = args.get("text", "")
        result = await self.controller.type_text(text)
        return json.dumps({
            "status": "ok" if result.success else "failed",
            "message": result.message,
        }, ensure_ascii=False)

    async def _key(self, args: Dict) -> str:
        """按键"""
        key = args.get("key", "enter")
        result = await self.controller.press_key(key)
        return json.dumps({
            "status": "ok" if result.success else "failed",
            "message": result.message,
        }, ensure_ascii=False)

    async def _home(self) -> str:
        """回主页"""
        result = await self.controller.go_home()
        return json.dumps({
            "status": "ok" if result.success else "failed",
            "message": result.message,
        }, ensure_ascii=False)

    async def _status(self) -> str:
        """状态查询"""
        stats = self.controller.get_stats()
        info = await self.controller.get_info()
        return json.dumps({
            "status": "ok",
            "connected": stats["connected"],
            "hid_available": stats["hid_available"],
            "route": stats["route"],
            "actions_total": stats["actions_total"],
            "success_rate": stats["success_rate"],
            "uptime_seconds": stats["uptime_seconds"],
            "tasks_completed": len([
                t for t in self._task_history if t.get("success")
            ]),
            "phone": {
                "os": info.os_type.value,
                "version": info.os_version,
                "screen": f"{info.screen_width}x{info.screen_height}",
            },
        }, ensure_ascii=False)

    async def _stop(self) -> str:
        """紧急停止"""
        result = await self.controller.emergency_stop()
        return json.dumps({
            "status": "ok" if result.success else "failed",
            "message": "已释放所有输入",
        }, ensure_ascii=False)

    def get_tools(self) -> List[Dict]:
        """返回 MCP 工具列表"""
        return PHONE_TOOLS

    def get_task_history(self) -> List[Dict]:
        """获取任务历史"""
        return list(self._task_history)