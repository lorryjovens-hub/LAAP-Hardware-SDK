"""小智语音直连 — 说话直接控制电脑

## 完整链路

    小智硬件（麦克风）
        ↓ 音频上行
    xiaozhi.me 云端（ASR 语音转文字 + 意图理解）
        ↓ MCP tools/call
    XiaozhiVoiceLink（本模块）
        ↓
    VoiceComputerAgent / MultiStepComputerAgent
        ↓
    鼠标 · 键盘 · 滚轮
        ↓ 动作结果
    XiaozhiVoiceLink（组装成一句话）
        ↓ MCP tools/call 返回值
    xiaozhi.me 云端（TTS 语音合成）
        ↓ 音频下行
    小智硬件（扬声器）

## 关键设计

### 1. 返回值必须是"能念出来的话"

MCP 工具返回的是文本，云端会直接拿去 TTS。
所以返回值不能是 JSON 数据堆砌，要是自然语言：

    好: "翻到底了"
    坏: {"success": true, "action": "scroll_until", "iterations": 4}

带一点结构信息也可以，但主句必须是人话。

### 2. 长任务要分段报告

多步任务跑 10 秒，用户会以为她卡住了。
所以策略：先快速回一句"我开始了"，执行完再给结果。

但 MCP 是同步调用，没法中途推送。
所以：**限制单次任务时长**，超时先返回中间状态。

### 3. 危险动作要确认

语音交互里问"你确定吗"很自然。
实现方式：返回一句话问用户，用户说"确定"就再调一次带 confirm 的工具。

## 用法

    from laaper.hub.xiaozhi_voice_link import XiaozhiVoiceLink

    link = XiaozhiVoiceLink()
    await link.start()   # 连接小智 broker，注册工具

    # 工具回调自动处理
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("laaper.hub.xiaozhi_link")


# ══════════════════════════════════════════════════════════
#  工具定义（暴露给小智 broker）
# ══════════════════════════════════════════════════════════

COMPUTER_TOOLS = [
    {
        "name": "voice_command",
        "description": (
            "用自然语言控制电脑。这是最主要的方式。"
            "用户说的任何操作电脑的指令都走这里，比如："
            "往下翻、翻到底、点击登录按钮、输入你好、回车、"
            "复制、粘贴、切换到浏览器。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "用户的原话，比如「往下翻」",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "computer_task",
        "description": (
            "执行需要多步才能完成的电脑任务。"
            "比如：打开记事本输入一段话、"
            "在浏览器搜索某个内容并打开第一个结果、"
            "找到某个文件并打开。"
            "简单的单步操作用 voice_command 更快。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "要完成的任务，用自然语言描述",
                },
            },
            "required": ["instruction"],
        },
    },
    {
        "name": "pc_scroll",
        "description": "滚动屏幕。往下翻、翻到底、回到顶部。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["down", "up", "bottom", "top"],
                    "description": "滚动方向",
                },
                "pixels": {
                    "type": "integer",
                    "description": "滚动像素数，不填则默认一屏",
                },
            },
            "required": ["direction"],
        },
    },
    {
        "name": "pc_click",
        "description": (
            "点击屏幕元素。"
            "优先用 text 参数按文字找，比坐标准确。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "要点击的元素文字，如「登录」「设置」",
                },
                "x": {"type": "number", "description": "归一化横坐标 0-1"},
                "y": {"type": "number", "description": "归一化纵坐标 0-1"},
            },
        },
    },
    {
        "name": "pc_type",
        "description": "在当前焦点位置输入文字。支持中文。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要输入的文字"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "pc_key",
        "description": "按单个按键。回车、退出、上、下、左、右、删除、空格、制表。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "按键名：enter/esc/up/down/left/right/delete/space/tab",
                },
            },
            "required": ["key"],
        },
    },
    {
        "name": "pc_hotkey",
        "description": "按组合键。如 ctrl+c 复制、ctrl+v 粘贴、ctrl+z 撤销、alt+tab 切换窗口。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "按键列表，如 [\"ctrl\", \"c\"]",
                },
            },
            "required": ["keys"],
        },
    },
    {
        "name": "pc_look",
        "description": (
            "看当前屏幕。返回当前窗口是什么、有哪些可以操作的按钮。"
            "当你不确定屏幕上有什么时用这个。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "你想了解什么，比如「这个页面有什么能点的」",
                },
            },
        },
    },
    {
        "name": "pc_windows",
        "description": "列出当前打开的所有窗口，用于切换。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "pc_focus",
        "description": "切换到某个窗口。比如切换到浏览器、切换到微信。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "窗口标题的一部分",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "pc_undo",
        "description": (
            "撤销上一步操作。"
            "可以撤销：滚动、输入文字、窗口切换。"
            "不能撤销：点击、提交、发送。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "撤销几步，默认 1",
                },
            },
        },
    },
    {
        "name": "pc_history",
        "description": "查看刚才做过哪些操作，以及哪些能撤销。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "pc_status",
        "description": "电脑控制能力状态。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# ══════════════════════════════════════════════════════════
#  语音直连
# ══════════════════════════════════════════════════════════

@dataclass
class LinkStats:
    """统计"""
    calls: int = 0
    voice_commands: int = 0
    tasks: int = 0
    failures: int = 0
    total_ms: float = 0.0
    last_call_at: float = 0.0


class XiaozhiVoiceLink:
    """小智语音直连

    把 MCP 工具调用接到电脑操作上。

    用法:
        link = XiaozhiVoiceLink()
        await link.start()

        # 之后小智设备说话，云端调我们的工具，自动执行
    """

    def __init__(
        self,
        voice_agent: Any = None,
        multistep_agent: Any = None,
        journal: Any = None,
        hub: Any = None,
        max_task_seconds: float = 25.0,
    ):
        from laaper.hub.voice_computer import VoiceComputerAgent

        self.voice_agent = voice_agent or VoiceComputerAgent()
        self.multistep_agent = multistep_agent
        self.journal = journal
        self.hub = hub

        self.max_task_seconds = max_task_seconds
        self.stats = LinkStats()

        # 待确认的高危动作
        self._pending: Optional[Dict] = None

        # 桥接实例
        self._bridge = None

        # 工具处理器表
        self._handlers: Dict[str, Callable] = {
            "voice_command": self._t_voice_command,
            "computer_task": self._t_computer_task,
            "pc_scroll": self._t_scroll,
            "pc_click": self._t_click,
            "pc_type": self._t_type,
            "pc_key": self._t_key,
            "pc_hotkey": self._t_hotkey,
            "pc_look": self._t_look,
            "pc_windows": self._t_windows,
            "pc_focus": self._t_focus,
            "pc_undo": self._t_undo,
            "pc_history": self._t_history,
            "pc_status": self._t_status,
        }

    # ── 启动 ──────────────────────────────────

    async def start(self, bridge: Any = None) -> Dict[str, Any]:
        """启动语音直连

        连接小智 broker，注册工具回调。
        """
        if bridge is None:
            try:
                from laap.xiaozhi_stable import StableXiaozhiBridge
                bridge = StableXiaozhiBridge(device_tools=COMPUTER_TOOLS)
            except Exception as e:
                return {
                    "success": False,
                    "error": f"无法创建小智桥接: {e}",
                }

        self._bridge = bridge

        # 注册工具处理器
        registered = []
        for conn in getattr(bridge, "connections", {}).values():
            for tool_name, handler in self._handlers.items():
                try:
                    conn.set_tool_callback(tool_name, handler)
                    registered.append(tool_name)
                except Exception as e:
                    logger.debug(f"注册 {tool_name} 失败: {e}")

        # 启动桥接
        try:
            results = await bridge.start()
        except Exception as e:
            return {
                "success": False,
                "error": f"启动桥接失败: {e}",
                "registered": registered,
            }

        online = sum(1 for v in results.values() if v)

        logger.info(
            f"语音直连已启动: {online}/{len(results)} 设备在线, "
            f"注册 {len(registered)} 个工具"
        )

        return {
            "success": online > 0,
            "devices": results,
            "online": online,
            "tools": list(self._handlers.keys()),
            "tool_schemas": len(COMPUTER_TOOLS),
        }

    async def stop(self):
        """停止"""
        if self._bridge:
            try:
                await self._bridge.stop()
            except Exception:
                pass

    # ══════════════════════════════════════════════════════
    #  工具实现
    # ══════════════════════════════════════════════════════

    async def _t_voice_command(self, args: Dict) -> str:
        """主入口：自然语言控制"""
        t0 = time.time()
        self.stats.calls += 1
        self.stats.voice_commands += 1
        self.stats.last_call_at = time.time()

        text = str(args.get("text", "")).strip()

        if not text:
            return "你想让我做什么？"

        # 检查是否是确认回复
        if self._pending:
            confirmed = self._check_confirm(text)
            if confirmed is not None:
                pending = self._pending
                self._pending = None

                if confirmed:
                    return await self._execute_pending(pending)
                else:
                    return "好的，不执行了。"

        try:
            result = await self.voice_agent.handle(text)

            # 记录到 journal
            if self.journal and result.action_result:
                try:
                    self.journal.record(
                        action=result.action_result.get("action", ""),
                        params=(result.intent or {}).get("params", {}),
                        success=result.success,
                    )
                except Exception:
                    pass

            elapsed = (time.time() - t0) * 1000
            self.stats.total_ms += elapsed

            if not result.success:
                self.stats.failures += 1

            # 简短回复（给 TTS 念）
            return result.reply or ("好了" if result.success else "没成功")

        except Exception as e:
            self.stats.failures += 1
            logger.exception("voice_command 失败")
            return f"操作出错了：{e}"

    async def _t_computer_task(self, args: Dict) -> str:
        """多步任务"""
        t0 = time.time()
        self.stats.calls += 1
        self.stats.tasks += 1
        self.stats.last_call_at = time.time()

        instruction = str(args.get("instruction", "")).strip()

        if not instruction:
            return "你想让我做什么任务？"

        if not self.multistep_agent:
            return "多步任务能力还没启用，你可以一步一步说。"

        try:
            # 限时执行（语音交互不能等太久）
            run = await asyncio.wait_for(
                self.multistep_agent.run(instruction),
                timeout=self.max_task_seconds,
            )

            elapsed = (time.time() - t0) * 1000
            self.stats.total_ms += elapsed

            if not run.success:
                self.stats.failures += 1

            # 组装成一句能念的话
            if run.success:
                msg = run.message or "任务完成了"
                if len(run.steps) > 1:
                    msg += f"（用了 {len(run.steps)} 步）"
                return msg

            return f"没完成：{run.message or run.error}"

        except asyncio.TimeoutError:
            self.stats.failures += 1
            return (
                f"这个任务有点复杂，超过 {int(self.max_task_seconds)} 秒了。"
                f"我还在做，你可以稍后再问我进度，"
                f"或者拆成几步告诉我。"
            )
        except Exception as e:
            self.stats.failures += 1
            logger.exception("computer_task 失败")
            return f"任务出错了：{e}"

    async def _t_scroll(self, args: Dict) -> str:
        """滚动"""
        self.stats.calls += 1
        direction = str(args.get("direction", "down")).lower()
        pixels = args.get("pixels")

        try:
            if direction in ("bottom", "top"):
                r = self.voice_agent.cu.scroll_until(direction)
                self._record("scroll_until", {"direction": direction}, r.success)
                return r.message or f"滚到{'底' if direction == 'bottom' else '顶'}了"

            px = int(pixels) if pixels else 480
            if direction == "up":
                px = -abs(px)

            r = self.voice_agent.cu.scroll_pixels(px)
            self._record("scroll", {"pixels": px}, r.success)

            return f"往{'下' if px > 0 else '上'}翻了"

        except Exception as e:
            self.stats.failures += 1
            return f"滚动失败：{e}"

    async def _t_click(self, args: Dict) -> str:
        """点击"""
        self.stats.calls += 1

        try:
            if "text" in args and args["text"]:
                target = str(args["text"])
                result = await self.voice_agent.handle(f"点击{target}")
                self._record("click", {"target": target}, result.success)
                return result.reply

            if "x" in args and "y" in args:
                nx, ny = float(args["x"]), float(args["y"])
                w, h = self.voice_agent.cu.screen_size
                r = self.voice_agent.cu.click(
                    int(nx * w) if 0 <= nx <= 1 else int(nx),
                    int(ny * h) if 0 <= ny <= 1 else int(ny),
                )
                self._record("click", {"x": nx, "y": ny}, r.success)
                return "点了" if r.success else f"点击失败：{r.error}"

            r = self.voice_agent.cu.click()
            self._record("click", {}, r.success)
            return "点了" if r.success else "点击失败"

        except Exception as e:
            self.stats.failures += 1
            return f"点击失败：{e}"

    async def _t_type(self, args: Dict) -> str:
        """输入文字"""
        self.stats.calls += 1
        text = str(args.get("text", ""))

        if not text:
            return "要输入什么？"

        try:
            r = self.voice_agent.cu.type_text(text)
            self._record(
                "type", {"text": text}, r.success,
                undoable=True, undo_hint="ctrl+z",
            )
            return f"输入了「{text[:20]}」" if r.success else f"输入失败：{r.error}"
        except Exception as e:
            self.stats.failures += 1
            return f"输入失败：{e}"

    async def _t_key(self, args: Dict) -> str:
        """按键"""
        self.stats.calls += 1
        key = str(args.get("key", "enter"))

        try:
            r = self.voice_agent.cu.press(key)
            self._record("press", {"key": key}, r.success)

            key_zh = {
                "enter": "回车", "esc": "退出", "tab": "制表",
                "up": "上", "down": "下", "left": "左", "right": "右",
                "delete": "删除", "space": "空格",
            }.get(key.lower(), key)

            return f"按了{key_zh}" if r.success else f"按键失败：{r.error}"
        except Exception as e:
            self.stats.failures += 1
            return f"按键失败：{e}"

    async def _t_hotkey(self, args: Dict) -> str:
        """组合键"""
        self.stats.calls += 1
        keys = args.get("keys", [])

        if isinstance(keys, str):
            keys = keys.split("+")

        if not keys:
            return "要按什么组合键？"

        try:
            r = self.voice_agent.cu.hotkey(*keys)
            self._record("hotkey", {"keys": keys}, r.success)
            return f"按了 {'+'.join(keys)}" if r.success else f"失败：{r.error}"
        except Exception as e:
            self.stats.failures += 1
            return f"组合键失败：{e}"

    async def _t_look(self, args: Dict) -> str:
        """看屏幕"""
        self.stats.calls += 1
        question = str(args.get("question", ""))

        try:
            desc = await self.voice_agent.describe_screen()

            # 如果有视觉模型且问得具体，补充视觉理解
            if question:
                sv = self.voice_agent._get_vision() if hasattr(
                    self.voice_agent, "_get_vision"
                ) else None

                if sv and getattr(sv, "available", False):
                    import base64
                    img = self.voice_agent.cu.screenshot(max_width=1400)
                    if img:
                        b64 = base64.b64encode(img).decode()
                        visual = await sv.describe(b64, question)
                        if visual:
                            desc += f"\n视觉观察：{visual[:300]}"

            return desc

        except Exception as e:
            self.stats.failures += 1
            return f"看不了：{e}"

    async def _t_windows(self, args: Dict) -> str:
        """窗口列表"""
        self.stats.calls += 1

        try:
            windows = self.voice_agent.cu.list_windows()
            if not windows:
                return "没检测到窗口"

            titles = [
                w["title"][:30] for w in windows[:10]
                if w.get("title")
            ]
            return "打开的窗口有：" + "、".join(titles)

        except Exception as e:
            return f"列不出来：{e}"

    async def _t_focus(self, args: Dict) -> str:
        """切换窗口"""
        self.stats.calls += 1
        title = str(args.get("title", ""))

        if not title:
            return "要切到哪个窗口？"

        try:
            r = self.voice_agent.cu.focus_window(title)
            self._record("focus_window", {"title": title}, r.success)

            if r.success:
                return f"切到「{title}」了"
            return f"找不到「{title}」窗口，{r.error}"

        except Exception as e:
            self.stats.failures += 1
            return f"切换失败：{e}"

    async def _t_undo(self, args: Dict) -> str:
        """撤销"""
        self.stats.calls += 1

        if not self.journal:
            return "撤销功能没启用"

        try:
            count = int(args.get("count", 1))

            if count <= 1:
                r = self.journal.undo_last()
            else:
                r = self.journal.undo_count(count)

            if r.success:
                msg = r.message
                if r.skipped:
                    blocked = [s["action"] for s in r.skipped[:2]]
                    msg += f"。{'、'.join(blocked)}撤不回来"
                return msg

            return r.message or "没有能撤销的"

        except Exception as e:
            self.stats.failures += 1
            return f"撤销失败：{e}"

    async def _t_history(self, args: Dict) -> str:
        """操作历史"""
        self.stats.calls += 1

        if not self.journal:
            return "操作记录没启用"

        try:
            summary = self.journal.summarize()
            recent = self.journal.recent(5)

            parts = [summary]
            if recent:
                actions = [
                    f"{r['action']}" + (
                        f"({r['params'].get('text', r['params'].get('target', ''))[:10]})"
                        if r.get("params") else ""
                    )
                    for r in recent
                ]
                parts.append("最近：" + "、".join(actions))

            blocked = self.journal.get_blocked_list()
            if blocked:
                parts.append(
                    f"有 {len(blocked)} 步撤不回来"
                )

            return "。".join(parts)

        except Exception as e:
            return f"查不了：{e}"

    async def _t_status(self, args: Dict) -> str:
        """状态"""
        self.stats.calls += 1

        try:
            st = self.voice_agent.get_status()
            deps = st["computer"]["dependencies"]

            ready = all([
                deps.get("pyautogui"),
                deps.get("pyperclip"),
                deps.get("uiautomation"),
            ])

            parts = [
                f"屏幕 {st['computer']['screen_size']}",
                f"当前窗口 {st['active_window'][:25] or '未知'}",
                f"已处理 {st['handled']} 条指令",
            ]

            if ready:
                parts.append("电脑控制就绪")
            else:
                missing = [k for k, v in deps.items() if not v]
                parts.append(f"缺少 {','.join(missing)}")

            return "，".join(parts)

        except Exception as e:
            return f"查不了状态：{e}"

    # ── 确认流程 ──────────────────────────────────

    def _check_confirm(self, text: str) -> Optional[bool]:
        """检查是不是确认回复"""
        yes = ("确定", "确认", "是", "对", "好的", "执行", "要", "继续", "可以")
        no = ("不", "取消", "算了", "不要", "别", "停止")

        t = text.strip().lower()

        # 先判否（"不要" 里也有"要"）
        for w in no:
            if w in t:
                return False

        for w in yes:
            if w in t:
                return True

        return None

    async def _execute_pending(self, pending: Dict) -> str:
        """执行待确认的动作"""
        try:
            action = pending.get("action", "")
            params = pending.get("params", {})

            if action == "click_text":
                result = await self.voice_agent.handle(
                    f"点击{params.get('text', '')}"
                )
                return result.reply

            if action == "hotkey":
                keys = params.get("keys", [])
                r = self.voice_agent.cu.hotkey(*keys)
                return f"按了 {'+'.join(keys)}" if r.success else "失败了"

            return "执行了"

        except Exception as e:
            return f"执行失败：{e}"

    # ── 辅助 ──────────────────────────────────

    def _record(
        self,
        action: str,
        params: Dict,
        success: bool,
        undoable: Optional[bool] = None,
        undo_hint: str = "",
    ):
        """记录到 journal"""
        if not self.journal:
            return
        try:
            self.journal.record(
                action=action,
                params=params,
                success=success,
                undoable=undoable,
                undo_hint=undo_hint,
            )
        except Exception:
            pass

    def get_status(self) -> Dict:
        return {
            "voice_agent": self.voice_agent.get_status(),
            "multistep": bool(self.multistep_agent),
            "journal": bool(self.journal),
            "tools": len(self._handlers),
            "bridge_connected": bool(
                self._bridge and any(
                    c.state.value == "connected"
                    for c in getattr(self._bridge, "connections", {}).values()
                )
            ),
            "stats": {
                "calls": self.stats.calls,
                "voice_commands": self.stats.voice_commands,
                "tasks": self.stats.tasks,
                "failures": self.stats.failures,
                "avg_ms": round(
                    self.stats.total_ms / max(1, self.stats.calls), 1
                ),
            },
        }


# ══════════════════════════════════════════════════════════
#  一键启动
# ══════════════════════════════════════════════════════════

async def quick_start(
    connect_xiaozhi: bool = True,
    enable_multistep: bool = True,
    data_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """一键把所有东西接起来

    用法:
        result = await quick_start()
        print(result["status"])
    """
    from pathlib import Path
    from laaper.hub.computer_use import ComputerUse
    from laaper.hub.voice_computer import VoiceComputerAgent
    from laaper.hub.action_journal import ActionJournal

    # 1. 电脑操作
    cu = ComputerUse(safe_mode=True)
    voice_agent = VoiceComputerAgent(cu=cu)

    # 2. 动作日志
    journal = ActionJournal(
        cu=cu,
        persist_path=str(
            Path(data_dir or Path.home() / ".laap") / "action_journal.json"
        ),
    )

    # 3. 多步 Agent
    multistep = None
    if enable_multistep:
        try:
            from laaper.hub.multi_step import MultiStepComputerAgent
            multistep = MultiStepComputerAgent(cu=cu, locator=voice_agent.locator)
            multistep.set_journal(journal)
        except Exception as e:
            logger.warning(f"多步任务不可用: {e}")

    # 4. 语音直连
    link = XiaozhiVoiceLink(
        voice_agent=voice_agent,
        multistep_agent=multistep,
        journal=journal,
    )

    result: Dict[str, Any] = {
        "success": True,
        "components": {
            "computer_use": True,
            "voice_agent": True,
            "journal": True,
            "multistep": multistep is not None,
        },
        "tools": COMPUTER_TOOLS,
    }

    # 5. 连接小智
    if connect_xiaozhi:
        try:
            start_result = await link.start()
            result["xiaozhi"] = start_result
            result["success"] = start_result.get("success", False)
        except Exception as e:
            result["xiaozhi"] = {"success": False, "error": str(e)}
            result["success"] = False

    result["status"] = link.get_status()
    result["link"] = link

    return result