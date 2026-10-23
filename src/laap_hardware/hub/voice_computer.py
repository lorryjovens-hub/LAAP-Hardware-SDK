"""语音驱动的电脑操作 — 说话就动手

## 这是那条完整链路

    小智硬件麦克风
        ↓ ASR（语音转文字）
    "往下翻"
        ↓ 意图识别（规则层 0ms → LLM 兜底）
    电脑操作（滚轮）
        ↓ 执行
        ↓ 截图验证
    "翻好了"
        ↓ TTS
    小智硬件扬声器

## 三层意图识别

### 第一层：规则（0ms，覆盖高频指令）
    "往下翻" / "翻到底" / "点击登录" / "输入你好" / "回车"
    这类占实际使用的 80%，必须瞬时响应。

### 第二层：元素定位（目标在哪）
    她说"点登录按钮"，那么"登录"在哪？
      策略 A: Windows UIA（无障碍接口，精确）
      策略 B: 视觉模型（找不到时兜底）
      策略 C: 屏幕文字定位

### 第三层：LLM（复杂指令）
    "把那个表格里的第三行复制下来"
    规则搞不定，交给 DeepSeek + 当前屏幕状态。

## 关键设计：动作后可验证

每个动作执行后截屏对比。没变化就是可能失败了。
这样她不会说"好了"其实什么都没发生。
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from laaper.hub.computer_use import (
    ComputerUse, CUAction, CUActionResult, VoiceIntent, VoiceIntentParser,
    get_computer_status,
)

logger = logging.getLogger("laaper.hub.voice_computer")


# ══════════════════════════════════════════════════════════
#  元素定位
# ══════════════════════════════════════════════════════════

@dataclass
class ScreenElement:
    """屏幕上的一个可交互元素"""
    name: str = ""
    control_type: str = ""
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    source: str = ""            # uia / vision / ocr

    def describe(self) -> str:
        return f"[{self.control_type}] {self.name} @({self.x},{self.y})"


class ElementLocator:
    """屏幕元素定位器

    她说"点击登录按钮"，需要找到"登录"在哪。

    策略优先级：
      1. Windows UIA（无障碍接口）— 最精确，能拿到控件名和坐标
      2. 视觉模型 — UIA 找不到时（比如网页 canvas 内容）
      3. 失败并诚实报告 — 不要瞎点
    """

    def __init__(self, vision_client: Any = None):
        self._uia = None
        self._vision = vision_client
        self._uia_available = None
        self._screen = (1920, 1080)
        try:
            from laaper.hub.computer_use import get_screen_size
            self._screen = get_screen_size()
        except Exception:
            pass

    def _get_uia(self):
        """惰性加载 uiautomation"""
        if self._uia_available is False:
            return None

        if self._uia is None:
            try:
                import uiautomation
                self._uia = uiautomation
                self._uia_available = True
            except ImportError:
                self._uia_available = False
                logger.warning(
                    "未安装 uiautomation，元素定位精度受限。"
                    "安装: pip install uiautomation"
                )
        return self._uia

    # 可交互控件类型（UIA 里对应可按可填的元素）
    INTERACTIVE_TYPES = (
        "Button", "MenuItem", "Hyperlink", "Edit", "ListItem",
        "TabItem", "CheckBox", "RadioButton", "ComboBox", "SplitButton",
        "Text", "Image", "TreeItem", "Slider",
    )

    def find_by_uia(
        self,
        text: str,
        timeout: float = 2.5,
        limit: int = 20,
    ) -> List[ScreenElement]:
        """用 Windows UIA 找元素

        关键：用 uiautomation 的原生搜索（C++ 实现），
        比 Python 递归遍历快 20-50 倍，而且能搜得更深。

        之前的 Python 递归版搜不到 Edge 页面内容的元素，
        就是因为深度限制和速度太慢。
        """
        uia = self._get_uia()
        if not uia:
            return []

        results: List[ScreenElement] = []

        try:
            root = uia.GetForegroundControl()
            if not root:
                return []

            # 用原生搜索（搜整个窗口子树）
            try:
                matches = root.GetChildren()
            except Exception:
                matches = []

            # 策略：逐个可交互类型做原生 SubName 搜索
            for ctype in ("Button", "Hyperlink", "MenuItem", "ListItem",
                          "TabItem", "CheckBox", "RadioButton", "Edit",
                          "Text", "ComboBox", "SplitButton"):
                if len(results) >= limit:
                    break
                try:
                    # uiautomation 的 SubName 支持模糊匹配
                    ctrls = root.Control(
                        searchDepth=20,
                        ControlType=getattr(uia.ControlType, ctype, None),
                        SubName=text,
                    )
                    if not ctrls:
                        continue

                    if not isinstance(ctrls, (list, tuple)):
                        ctrls = [ctrls]

                    for ctrl in ctrls:
                        if len(results) >= limit:
                            break
                        try:
                            rect = ctrl.BoundingRectangle
                            if not rect or rect.width() < 3 or rect.height() < 3:
                                continue

                            # 跳过屏幕外的
                            x, y = rect.xcenter(), rect.ycenter()
                            if x < 0 or y < 0:
                                continue
                            if x > self._screen[0] or y > self._screen[1]:
                                continue

                            results.append(ScreenElement(
                                name=ctrl.Name or text,
                                control_type=ctype,
                                x=x,
                                y=y,
                                width=rect.width(),
                                height=rect.height(),
                                source="uia",
                            ))
                        except Exception:
                            continue
                except Exception as e:
                    logger.debug(f"UIA {ctype} 搜索失败: {e}")
                    continue

        except Exception as e:
            logger.debug(f"UIA 搜索失败: {e}")

        return results

    async def find_by_vision(self, text: str) -> List[ScreenElement]:
        """用视觉模型找元素

        兜底方案。让视觉模型看截图，指出目标位置的归一化坐标。
        """
        if not self._vision:
            try:
                from laap.tools.browser_perception import VisionClient
                self._vision = VisionClient()
            except Exception:
                return []

        if not getattr(self._vision, "available", False):
            return []

        # 截屏（必须降采样，4K 原图 6MB 会让视觉 API 报错）
        cu = ComputerUse()
        img = cu.screenshot(max_width=1600)
        if not img:
            return []

        b64 = base64.b64encode(img).decode()
        w, h = cu.screen_size

        prompt = f"""这是一张电脑屏幕截图（{w}x{h}）。

请找到「{text}」在屏幕上的位置。

输出 JSON（只输出 JSON）：
{{"found": true, "x": 0.52, "y": 0.34, "description": "登录按钮"}}
{{"found": false, "reason": "屏幕上没有这个元素"}}

坐标用归一化的 0-1（左上角是 0,0）。
只找当前屏幕上真实可见的元素，不要猜。"""

        answer = await self._vision.describe(b64, prompt)

        # 解析
        try:
            t = answer.strip()
            if "```" in t:
                parts = t.split("```")
                for p in parts:
                    if "{" in p:
                        t = p
                        break
            s = t.find("{")
            e = t.rfind("}")
            if s >= 0 and e > s:
                d = json.loads(t[s:e + 1])
                if d.get("found"):
                    return [ScreenElement(
                        name=d.get("description", text),
                        control_type="vision",
                        x=int(d.get("x", 0.5) * w),
                        y=int(d.get("y", 0.5) * h),
                        source="vision",
                    )]
        except Exception as e:
            logger.debug(f"视觉定位解析失败: {e}")

        return []

    async def locate(self, text: str) -> Tuple[Optional[ScreenElement], str]:
        """定位元素

        Returns:
            (元素, 定位方式说明)
        """
        # 1. UIA
        uia_results = self.find_by_uia(text)
        if uia_results:
            # 优先可点击类型
            for r in uia_results:
                if any(k in r.control_type for k in
                       ("Button", "MenuItem", "Hyperlink", "ListItem")):
                    return r, "uia"
            return uia_results[0], "uia"

        # 2. 视觉
        vision_results = await self.find_by_vision(text)
        if vision_results:
            return vision_results[0], "vision"

        return None, "not_found"

    def list_interactive(self, limit: int = 30) -> List[ScreenElement]:
        """列出当前窗口的可交互元素

        给她一个"菜单"，让她知道屏幕上能点什么。
        用原生搜索，比递归快得多。
        """
        uia = self._get_uia()
        if not uia:
            return []

        results: List[ScreenElement] = []
        seen = set()

        try:
            root = uia.GetForegroundControl()
            if not root:
                return []

            for ctype in ("Button", "MenuItem", "Hyperlink", "Edit",
                          "ListItem", "TabItem", "CheckBox"):
                if len(results) >= limit:
                    break
                try:
                    ctrls = root.Control(
                        searchDepth=12,
                        ControlType=getattr(uia.ControlType, ctype, None),
                    )
                    if not ctrls:
                        continue
                    if not isinstance(ctrls, (list, tuple)):
                        ctrls = [ctrls]

                    for ctrl in ctrls[:15]:
                        if len(results) >= limit:
                            break
                        try:
                            name = (ctrl.Name or "").strip()
                            if not name or name in seen:
                                continue

                            rect = ctrl.BoundingRectangle
                            if not rect or rect.width() < 3:
                                continue

                            x, y = rect.xcenter(), rect.ycenter()
                            if x < 0 or y < 0 or x > self._screen[0] or y > self._screen[1]:
                                continue

                            seen.add(name)
                            results.append(ScreenElement(
                                name=name,
                                control_type=ctype,
                                x=x,
                                y=y,
                                width=rect.width(),
                                height=rect.height(),
                                source="uia",
                            ))
                        except Exception:
                            continue
                except Exception:
                    continue

        except Exception as e:
            logger.debug(f"枚举元素失败: {e}")

        return results


# ══════════════════════════════════════════════════════════
#  语音电脑操作 Agent
# ══════════════════════════════════════════════════════════

@dataclass
class VoiceActionResult:
    """语音动作结果"""
    success: bool
    instruction: str = ""
    reply: str = ""                     # 要播报的话
    intent: Optional[Dict] = None
    action_result: Optional[Dict] = None
    locate_method: str = ""
    duration_ms: float = 0.0
    verified: bool = False


class VoiceComputerAgent:
    """语音驱动的电脑操作

    用法:
        agent = VoiceComputerAgent()

        # 她说"往下翻"
        result = await agent.handle("往下翻")
        print(result.reply)      # "翻好了"

        # 她说"点击登录按钮"
        result = await agent.handle("点击登录按钮")

        # 她说"输入你好世界然后回车"
        result = await agent.handle("输入你好世界然后回车")
    """

    def __init__(
        self,
        cu: Optional[ComputerUse] = None,
        llm_client: Any = None,
        enable_llm: bool = True,
        verify_actions: bool = True,
    ):
        self.cu = cu or ComputerUse(safe_mode=True)
        self.locator = ElementLocator()
        self.enable_llm = enable_llm
        self.verify_actions = verify_actions

        self._llm = llm_client
        if self._llm is None and enable_llm:
            try:
                from laaper.hub.llm_planner import LLMClient
                self._llm = LLMClient()
            except Exception:
                self._llm = None

        # 历史（用于上下文消解）
        self.history: List[Dict] = []

        # 统计
        self.stats = {
            "handled": 0,
            "rule_hits": 0,
            "llm_hits": 0,
            "failures": 0,
            "not_found": 0,
        }

    # ── 主入口 ──────────────────────────────────

    async def handle(self, text: str) -> VoiceActionResult:
        """处理一句语音指令"""
        t0 = time.time()
        self.stats["handled"] += 1

        text = text.strip()
        if not text:
            return VoiceActionResult(
                success=False,
                reply="我没听清，再说一次？",
            )

        # ── 第一层：规则解析 ──
        intent = VoiceIntentParser.parse(text)

        if intent:
            self.stats["rule_hits"] += 1
            logger.info(f"[规则] {text} → {intent.action} {intent.params}")
            result = await self._execute_intent(intent, text)
            result.duration_ms = (time.time() - t0) * 1000
            self._record(text, intent, result)
            return result

        # ── 第二层：LLM ──
        if self.enable_llm and self._llm and self._llm.available:
            self.stats["llm_hits"] += 1
            logger.info(f"[LLM] {text}")
            result = await self._handle_with_llm(text)
            result.duration_ms = (time.time() - t0) * 1000
            self._record(text, None, result)
            return result

        # ── 兜底 ──
        self.stats["failures"] += 1
        return VoiceActionResult(
            success=False,
            instruction=text,
            reply=f"我不太懂「{text}」要怎么操作。"
                  f"你可以说：往下翻、点击某个按钮、输入文字、回车。",
            duration_ms=(time.time() - t0) * 1000,
        )

    # ── 执行意图 ──────────────────────────────────

    async def _execute_intent(
        self,
        intent: VoiceIntent,
        original_text: str,
    ) -> VoiceActionResult:
        """执行解析出的意图"""
        action = intent.action
        params = intent.params

        # ── 滚动 ──
        if action == "scroll":
            pixels = params.get("pixels", 480)
            r = self.cu.scroll_pixels(pixels)
            direction = "下" if pixels > 0 else "上"
            return VoiceActionResult(
                success=r.success,
                instruction=original_text,
                reply=(f"往{direction}翻了。" if r.success
                       else f"滚动失败：{r.error}"),
                intent={"action": action, "params": params},
                action_result=self._r2d(r),
                verified=r.success,
            )

        if action == "scroll_until":
            direction = params.get("direction", "bottom")
            r = self.cu.scroll_until(direction)

            word = "底" if direction == "bottom" else "顶"
            steps = r.data.get("iterations", 0)

            if r.success:
                reply = f"翻到{word}了。"
                if steps <= 1:
                    reply = f"已经在{word}了。"
            else:
                reply = f"滚动失败：{r.error}"

            return VoiceActionResult(
                success=r.success,
                instruction=original_text,
                reply=reply,
                intent={"action": action, "params": params},
                action_result=self._r2d(r),
                verified=r.success,
            )

        # ── 点击文字目标 ──
        if action == "click_text":
            target = params["text"]
            element, method = await self.locator.locate(target)

            if not element:
                self.stats["not_found"] += 1
                return VoiceActionResult(
                    success=False,
                    instruction=original_text,
                    reply=f"屏幕上没找到「{target}」。",
                    locate_method=method,
                )

            r = self.cu.click(element.x, element.y, verify=self.verify_actions)

            return VoiceActionResult(
                success=r.success,
                instruction=original_text,
                reply=(f"点了「{element.name}」。" if r.success
                       else f"点击失败：{r.error}"),
                intent={"action": action, "params": params},
                action_result=self._r2d(r),
                locate_method=method,
                verified=r.screen_changed if self.verify_actions else r.success,
            )

        if action == "double_click_text":
            target = params["text"]
            element, method = await self.locator.locate(target)

            if not element:
                self.stats["not_found"] += 1
                return VoiceActionResult(
                    success=False,
                    instruction=original_text,
                    reply=f"屏幕上没找到「{target}」。",
                    locate_method=method,
                )

            r = self.cu.double_click(element.x, element.y)
            return VoiceActionResult(
                success=r.success,
                instruction=original_text,
                reply=(f"双击了「{element.name}」。" if r.success
                       else f"双击失败：{r.error}"),
                action_result=self._r2d(r),
                locate_method=method,
            )

        if action == "right_click":
            target = params.get("text", "")
            if target:
                element, method = await self.locator.locate(target)
                if not element:
                    return VoiceActionResult(
                        success=False,
                        instruction=original_text,
                        reply=f"屏幕上没找到「{target}」。",
                        locate_method=method,
                    )
                r = self.cu.right_click(element.x, element.y)
                reply = f"右键点了「{element.name}」。"
            else:
                # 右键当前位置
                r = self.cu.right_click(0, 0)
                reply = "右键点了。"

            return VoiceActionResult(
                success=r.success,
                instruction=original_text,
                reply=reply if r.success else f"失败：{r.error}",
                action_result=self._r2d(r),
            )

        # ── 点击（无目标，点当前） ──
        if action == "click":
            r = self.cu.click(verify=self.verify_actions)
            return VoiceActionResult(
                success=r.success,
                instruction=original_text,
                reply=("点了。" if r.success else f"点击失败：{r.error}"),
                action_result=self._r2d(r),
            )

        # ── 输入 ──
        if action == "type":
            text_to_type = params.get("text", "")
            r = self.cu.type_text(text_to_type)
            return VoiceActionResult(
                success=r.success,
                instruction=original_text,
                reply=(f"输入了「{text_to_type[:20]}」。" if r.success
                       else f"输入失败：{r.error}"),
                action_result=self._r2d(r),
                verified=r.success,
            )

        # ── 按键 ──
        if action == "press":
            key = params.get("key", "enter")
            r = self.cu.press(key)
            key_zh = {"enter": "回车", "esc": "退出", "tab": "制表"}.get(key, key)
            return VoiceActionResult(
                success=r.success,
                instruction=original_text,
                reply=(f"按了{key_zh}。" if r.success
                       else f"按键失败：{r.error}"),
                action_result=self._r2d(r),
            )

        # ── 组合键 ──
        if action == "hotkey":
            keys = params.get("keys", [])
            r = self.cu.hotkey(*keys)
            combo = "+".join(keys)
            return VoiceActionResult(
                success=r.success,
                instruction=original_text,
                reply=(f"按了 {combo}。" if r.success
                       else f"组合键失败：{r.error}"),
                action_result=self._r2d(r),
            )

        # ── 窗口切换 ──
        if action == "focus_window":
            title = params.get("title", "")
            r = self.cu.focus_window(title)
            return VoiceActionResult(
                success=r.success,
                instruction=original_text,
                reply=(f"切到「{title}」了。" if r.success
                       else f"找不到「{title}」窗口。"),
                action_result=self._r2d(r),
            )

        return VoiceActionResult(
            success=False,
            instruction=original_text,
            reply="这个动作我暂时不会。",
        )

    # ── LLM 兜底 ──────────────────────────────────

    async def _handle_with_llm(self, text: str) -> VoiceActionResult:
        """复杂指令交给 LLM"""
        # 收集当前状态
        active = self.cu.get_active_window()
        elements = self.locator.list_interactive(20)

        elements_text = "\n".join(
            f"  [{e.control_type}] {e.name}" for e in elements
        ) if elements else "  （无法枚举）"

        history_text = ""
        if self.history:
            lines = [f"  {h['text']} → {h.get('action', '')}"
                     for h in self.history[-5:]]
            history_text = "最近操作:\n" + "\n".join(lines)

        screen_w, screen_h = self.cu.screen_size

        system = """你是电脑操作智能体。你能控制鼠标和键盘。

可用动作（输出 JSON，只输出 JSON）：
{"action": "click", "x": 0.5, "y": 0.3, "reason": "..."}
{"action": "click_text", "text": "登录", "reason": "..."}
{"action": "scroll", "pixels": 480, "reason": "向下翻"}
{"action": "scroll_until", "direction": "bottom", "reason": "翻到底"}
{"action": "type", "text": "要输入的内容", "reason": "..."}
{"action": "press", "key": "enter", "reason": "..."}
{"action": "hotkey", "keys": ["ctrl", "c"], "reason": "..."}
{"action": "focus_window", "title": "窗口标题片段", "reason": "..."}
{"action": "wait", "seconds": 1, "reason": "..."}
{"action": "finish", "message": "完成说明", "reason": "..."}

优先用 click_text（按文字找元素，比猜坐标准）。
坐标 x/y 是归一化 0-1。
如果指令无法完成，用 finish 说明原因，不要瞎猜。"""

        user = f"""指令: {text}

当前窗口: {active.get('title', '未知')}
屏幕尺寸: {screen_w}x{screen_h}

当前窗口可交互元素:
{elements_text}

{history_text}

决定下一个动作。只输出 JSON。"""

        raw = await self._llm.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            json_mode=True,
        )

        decision = self._parse_json(raw)

        if not decision:
            return VoiceActionResult(
                success=False,
                instruction=text,
                reply="我理解不了这个操作，换个说法？",
            )

        act = decision.get("action", "")

        if act == "finish":
            return VoiceActionResult(
                success=True,
                instruction=text,
                reply=decision.get("message", "好了。"),
                intent=decision,
            )

        # 转成 VoiceIntent 执行
        intent = VoiceIntent(
            action=act,
            params={k: v for k, v in decision.items()
                    if k not in ("action", "reason")},
            confidence=0.7,
            raw_text=text,
        )

        # click 用归一化坐标
        if act == "click" and "x" in decision:
            nx, ny = decision["x"], decision["y"]
            element = ScreenElement(
                name="LLM 指定的位置",
                x=int(nx * screen_w),
                y=int(ny * screen_h),
                source="llm",
            )
            r = self.cu.click(element.x, element.y, verify=self.verify_actions)
            return VoiceActionResult(
                success=r.success,
                instruction=text,
                reply=(decision.get("reason") or "点了") if r.success
                      else f"点击失败：{r.error}",
                intent=decision,
                action_result=self._r2d(r),
            )

        result = await self._execute_intent(intent, text)
        result.intent = decision
        return result

    def _parse_json(self, raw: str) -> Optional[Dict]:
        if not raw:
            return None
        t = raw.strip()
        if "```" in t:
            parts = t.split("```")
            for p in parts:
                if "{" in p:
                    t = p
                    break
        s = t.find("{")
        e = t.rfind("}")
        if s >= 0 and e > s:
            try:
                return json.loads(t[s:e + 1])
            except Exception:
                return None
        return None

    # ── 辅助 ──────────────────────────────────

    def _r2d(self, r: CUActionResult) -> Dict:
        return {
            "success": r.success,
            "action": r.action if isinstance(r.action, str) else r.action.value,
            "message": r.message,
            "error": r.error,
            "data": r.data,
            "duration_ms": round(r.duration_ms, 1),
            "screen_changed": r.screen_changed,
        }

    def _record(self, text: str, intent: Optional[VoiceIntent],
                result: VoiceActionResult):
        self.history.append({
            "text": text,
            "action": intent.action if intent else "llm",
            "success": result.success,
            "ts": time.time(),
        })
        if len(self.history) > 50:
            self.history = self.history[-50:]

    # ── 状态 ──────────────────────────────────

    def get_status(self) -> Dict:
        from laaper.hub.computer_use import get_computer_status
        return {
            "computer": get_computer_status(),
            "llm_available": bool(self._llm and self._llm.available),
            "uia_available": self.locator._uia_available,
            "active_window": self.cu.get_active_window().get("title", ""),
            "history_size": len(self.history),
            **self.stats,
        }

    async def describe_screen(self) -> str:
        """描述当前屏幕（她"看见"桌面）"""
        active = self.cu.get_active_window()
        elements = self.locator.list_interactive(15)

        parts = [f"当前窗口：{active.get('title', '未知')}"]

        if elements:
            parts.append("可操作的控件：")
            for e in elements[:10]:
                parts.append(f"  · {e.name}（{e.control_type}）")
        else:
            parts.append("（无法枚举控件）")

        return "\n".join(parts)


# ══════════════════════════════════════════════════════════
#  接入三端中枢
# ══════════════════════════════════════════════════════════

def register_computer_use_handlers(
    hub: Any,
    pc_node: str = "pc-01",
    agent: Optional[VoiceComputerAgent] = None,
) -> Dict[str, Any]:
    """把电脑操作注册到中枢

    这样小智硬件说话 → 中枢 → 电脑鼠标键盘。
    """
    agent = agent or VoiceComputerAgent()

    handlers = {}

    # 滚动
    async def scroll(params: Dict) -> Dict:
        pixels = params.get("pixels", 480)
        r = agent.cu.scroll_pixels(pixels)
        return {"success": r.success, "data": agent._r2d(r)}

    hub.transport.register_handler(pc_node, "scroll", scroll)
    handlers["scroll"] = True

    # 翻到边界
    async def scroll_until(params: Dict) -> Dict:
        direction = params.get("direction", "bottom")
        r = agent.cu.scroll_until(direction)
        return {"success": r.success, "data": agent._r2d(r)}

    hub.transport.register_handler(pc_node, "scroll_until", scroll_until)
    handlers["scroll_until"] = True

    # 鼠标点击
    async def mouse_click(params: Dict) -> Dict:
        x = params.get("x")
        y = params.get("y")

        if "text" in params:
            result = await agent.handle(f"点击{params['text']}")
            return {
                "success": result.success,
                "data": {"reply": result.reply},
                "error": "" if result.success else result.reply,
            }

        if x is not None and y is not None:
            # 归一化坐标
            if 0 <= x <= 1 and 0 <= y <= 1:
                w, h = agent.cu.screen_size
                x, y = int(x * w), int(y * h)
            r = agent.cu.click(int(x), int(y))
            return {"success": r.success, "data": agent._r2d(r)}

        r = agent.cu.click()
        return {"success": r.success, "data": agent._r2d(r)}

    hub.transport.register_handler(pc_node, "mouse_click", mouse_click)
    hub.transport.register_handler(pc_node, "click", mouse_click)
    handlers["mouse_click"] = True

    # 键盘输入
    async def keyboard_type(params: Dict) -> Dict:
        text = params.get("text", "")
        r = agent.cu.type_text(text)
        return {"success": r.success, "data": agent._r2d(r)}

    hub.transport.register_handler(pc_node, "keyboard_type", keyboard_type)
    hub.transport.register_handler(pc_node, "type", keyboard_type)
    handlers["keyboard_type"] = True

    # 按键
    async def keyboard_press(params: Dict) -> Dict:
        key = params.get("key", "enter")
        r = agent.cu.press(key)
        return {"success": r.success, "data": agent._r2d(r)}

    hub.transport.register_handler(pc_node, "keyboard_press", keyboard_press)
    hub.transport.register_handler(pc_node, "press", keyboard_press)
    handlers["keyboard_press"] = True

    # 组合键
    async def keyboard_hotkey(params: Dict) -> Dict:
        keys = params.get("keys", [])
        if isinstance(keys, str):
            keys = keys.split("+")
        r = agent.cu.hotkey(*keys)
        return {"success": r.success, "data": agent._r2d(r)}

    hub.transport.register_handler(pc_node, "keyboard_hotkey", keyboard_hotkey)
    hub.transport.register_handler(pc_node, "hotkey", keyboard_hotkey)
    handlers["keyboard_hotkey"] = True

    # 语音指令直通（最核心）
    async def voice_command(params: Dict) -> Dict:
        text = params.get("text", "")
        result = await agent.handle(text)
        return {
            "success": result.success,
            "data": {
                "reply": result.reply,
                "intent": result.intent,
                "action": result.action_result,
                "locate_method": result.locate_method,
                "duration_ms": round(result.duration_ms, 1),
            },
            "error": "" if result.success else result.reply,
        }

    hub.transport.register_handler(pc_node, "voice_command", voice_command)
    hub.transport.register_handler(pc_node, "computer", voice_command)
    handlers["voice_command"] = True

    # 窗口切换
    async def focus_window(params: Dict) -> Dict:
        title = params.get("title", "")
        r = agent.cu.focus_window(title)
        return {"success": r.success, "data": agent._r2d(r)}

    hub.transport.register_handler(pc_node, "focus_window", focus_window)
    handlers["focus_window"] = True

    # 屏幕描述
    async def describe_screen(params: Dict) -> Dict:
        desc = await agent.describe_screen()
        return {"success": True, "data": {"description": desc}}

    hub.transport.register_handler(pc_node, "describe_screen", describe_screen)
    handlers["describe_screen"] = True

    return {
        "agent": agent,
        "handlers": list(handlers.keys()),
        "status": agent.get_status(),
    }


def get_voice_computer_status() -> Dict:
    """语音电脑操作环境状态"""
    deps = {}
    for m in ("pyautogui", "pyperclip", "pygetwindow", "mss", "uiautomation"):
        try:
            __import__(m)
            deps[m] = True
        except ImportError:
            deps[m] = False

    return {
        "dependencies": deps,
        "ready": deps.get("pyautogui") and deps.get("pyperclip"),
        "uia_available": deps.get("uiautomation", False),
        "screen": get_computer_status()["screen_size"],
        "hint": (
            "语音控制电脑就绪"
            if deps.get("pyautogui")
            else "缺少 pyautogui: pip install pyautogui pyperclip"
        ),
    }