"""多步电脑任务 — 看 → 想 → 做 → 验 → 循环

## 为什么需要这个

单个动作只能干一件事。真实任务是多步的：

    "帮我在浏览器里搜一下 LAAP 的官网，然后打开第一个结果"
    ↓
    步骤 1: 找到地址栏
    步骤 2: 点击地址栏
    步骤 3: 输入搜索词
    步骤 4: 回车
    步骤 5: 看搜索结果
    步骤 6: 点击第一个链接
    步骤 7: 确认页面变了

每一步都要：看当前屏幕 → 决定动作 → 执行 → 验证生效。

## 三层验证（成本递增）

动作后不能盲目继续。但每步都调视觉模型太贵太慢（一轮任务十几秒）。

所以分三层，只在必要时升级：

    第一层：像素变化检测（20ms，免费）
      动作后屏幕变了吗？变了 → 大概率成功
      没变 → 升级到第二层

    第二层：结构化校验（200ms，免费）
      目标元素还在吗？页面结构变了吗？URL 变了吗？
      仍然不确定 → 升级到第三层

    第三层：视觉确认（1-3s，有 API 成本）
      让视觉模型看截图回答"登录成功了吗"
      只在关键节点用（任务开始、关键动作后、失败前）

## 停滞与失败处理

    连续 3 步屏幕无变化 → 判定卡住，中止并报告
    单步动作失败 → 重试 2 次（换个方式），仍失败则中止
    达到最大步数 → 中止并报告已完成的部分
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laaper.hub.multistep")


class VerifyLevel(str, Enum):
    """验证层级"""
    NONE = "none"              # 不验证
    PIXEL = "pixel"            # 像素变化（最快）
    STRUCTURE = "structure"    # 结构化校验
    VISION = "vision"          # 视觉模型确认（最贵）


@dataclass
class StepResult:
    """单步结果"""
    step: int = 0
    action: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    success: bool = False
    error: str = ""
    verify_level: str = ""
    verified: bool = False
    screen_changed: bool = False
    duration_ms: float = 0.0
    reason: str = ""                    # LLM 给的理由


@dataclass
class TaskRun:
    """任务执行记录"""
    task_id: str = ""
    instruction: str = ""
    success: bool = False
    message: str = ""
    steps: List[StepResult] = field(default_factory=list)
    total_ms: float = 0.0
    error: str = ""
    vision_calls: int = 0

    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "instruction": self.instruction,
            "success": self.success,
            "message": self.message,
            "step_count": len(self.steps),
            "total_ms": round(self.total_ms, 1),
            "vision_calls": self.vision_calls,
            "error": self.error,
            "steps": [
                {
                    "step": s.step,
                    "action": s.action,
                    "success": s.success,
                    "verified": s.verified,
                    "verify_level": s.verify_level,
                    "duration_ms": round(s.duration_ms, 1),
                    "reason": s.reason,
                    "error": s.error,
                }
                for s in self.steps
            ],
        }


# ══════════════════════════════════════════════════════════
#  系统提示
# ══════════════════════════════════════════════════════════

_SYSTEM = """你是电脑操作智能体。你能控制鼠标和键盘来完成用户的任务。

## 你能看到什么

每次交互你会收到：

1. **当前窗口**：标题、位置
2. **可交互控件列表**：从 Windows 无障碍接口（UIA）读到的真实控件
   格式：`[类型] 名称`
   这些是**精确的**，能直接点
3. **屏幕像素摘要**：屏幕是否在变化
4. **已执行的步骤**：你之前做了什么、成功没有

## 你可以做什么

输出 JSON（只输出一个 JSON 对象，不要其他文字）：

{"action": "click_text", "text": "登录", "reason": "点击登录按钮"}
{"action": "click", "x": 0.5, "y": 0.3, "reason": "点击屏幕中间的位置"}
{"action": "type", "text": "要输入的文字", "reason": "在地址栏输入"}
{"action": "press", "key": "enter", "reason": "提交搜索"}
{"action": "hotkey", "keys": ["ctrl", "c"], "reason": "复制"}
{"action": "scroll", "pixels": 480, "reason": "向下滚动"}
{"action": "scroll_until", "direction": "bottom", "reason": "翻到底"}
{"action": "focus_window", "title": "Chrome", "reason": "切换到浏览器"}
{"action": "launch_app", "name": "notepad", "reason": "打开记事本"}
{"action": "wait", "seconds": 2, "reason": "等待页面加载"}
{"action": "verify", "question": "登录成功了吗", "reason": "需要视觉确认"}
{"action": "finish", "message": "任务完成说明", "reason": "目标达成"}
{"action": "abort", "message": "无法完成的原因", "reason": "卡住了"}

## 关键规则

1. **优先用 click_text**：按文字找控件，比猜坐标准确得多
2. **一次只做一步**：不要试图一步完成整个任务
3. **坐标是归一化 0-1**：x=0.5 表示屏幕水平中点
4. **需要视觉时主动要**：如果你不确定屏幕上是什么状态，用 verify
5. **卡住就 abort**：连续两次同样的动作没效果，说明方法错了
6. **诚实**：做不到就说做不到，不要假装完成

## 常见任务模式

搜索：
  click_text 地址栏 → type 关键词 → press enter → wait

表单：
  click_text 输入框 → type 内容 → click_text 提交按钮

导航：
  click_text 菜单名 → wait → click_text 子菜单

阅读长文：
  scroll_until bottom 或 scroll pixels
"""


# ══════════════════════════════════════════════════════════
#  多步 Agent
# ══════════════════════════════════════════════════════════

class MultiStepComputerAgent:
    """多步电脑任务 Agent

    用法:
        agent = MultiStepComputerAgent()

        result = await agent.run("打开记事本，输入你好世界，保存")
        print(result.message)
        print(f"用了 {len(result.steps)} 步")
    """

    def __init__(
        self,
        cu: Any = None,
        llm_client: Any = None,
        locator: Any = None,
        max_steps: int = 20,
        max_stall: int = 3,
        vision_budget: int = 3,
        enable_vision: bool = True,
    ):
        from laaper.hub.computer_use import ComputerUse
        from laaper.hub.voice_computer import ElementLocator

        self.cu = cu or ComputerUse(safe_mode=True)
        self.locator = locator or ElementLocator()
        self.max_steps = max_steps
        self.max_stall = max_stall
        self.vision_budget = vision_budget
        self.enable_vision = enable_vision

        # LLM
        self._llm = llm_client
        if self._llm is None:
            try:
                from laaper.hub.llm_planner import LLMClient
                self._llm = LLMClient()
            except Exception:
                self._llm = None

        # 视觉
        self._vision = None

        # 动作日志（撤销用）
        self._journal = None

        # 统计
        self.stats = {
            "tasks": 0,
            "tasks_success": 0,
            "tasks_failed": 0,
            "steps_total": 0,
            "vision_calls": 0,
        }

    def _get_vision(self):
        if self._vision is None:
            try:
                from laap.tools.browser_perception import VisionClient
                self._vision = VisionClient()
            except Exception:
                pass
        return self._vision

    def set_journal(self, journal):
        """挂载动作日志（支持撤销）"""
        self._journal = journal

    # ── 主入口 ──────────────────────────────────

    async def run(
        self,
        instruction: str,
        session_context: str = "",
    ) -> TaskRun:
        """执行多步任务"""
        import uuid

        t0 = time.time()

        run = TaskRun(
            task_id=f"t_{uuid.uuid4().hex[:8]}",
            instruction=instruction,
        )

        self.stats["tasks"] += 1

        if not self._llm or not self._llm.available:
            run.error = "没有可用的 LLM，无法规划多步任务"
            run.total_ms = (time.time() - t0) * 1000
            self.stats["tasks_failed"] += 1
            return run

        history: List[Dict] = []
        stall = 0
        last_sig = ""
        vision_used = 0
        repeated_action = 0
        last_action_sig = ""

        for step in range(1, self.max_steps + 1):
            # ── 1. 感知当前状态 ──
            state = await self._observe()

            # ── 2. 停滞检测 ──
            sig = state["signature"]
            if sig == last_sig:
                stall += 1
                if stall >= self.max_stall:
                    run.error = f"连续 {stall} 步屏幕无变化，卡住了"
                    run.message = run.error
                    break
            else:
                stall = 0
                last_sig = sig

            # ── 3. 让 LLM 决定下一步 ──
            decision = await self._decide(
                instruction, state, history, session_context,
            )

            action = decision.get("action", "")
            reason = decision.get("reason", "")

            # ── 4. 特殊动作 ──
            if action == "finish":
                run.success = True
                run.message = decision.get("message", "完成")
                break

            if action == "abort":
                run.error = decision.get("message", "无法完成")
                run.message = run.error
                break

            if action == "verify":
                if vision_used >= self.vision_budget:
                    history.append({
                        "step": step,
                        "action": "verify",
                        "result": "视觉预算已用完",
                        "success": False,
                    })
                    continue

                answer = await self._ask_vision(
                    decision.get("question", "")
                )
                vision_used += 1
                self.stats["vision_calls"] += 1

                history.append({
                    "step": step,
                    "action": "verify",
                    "question": decision.get("question", ""),
                    "answer": answer,
                    "success": True,
                })
                continue

            # ── 5. 检测重复动作 ──
            action_sig = f"{action}|{json.dumps({k: v for k, v in decision.items() if k not in ('reason',)}, sort_keys=True, default=str)}"
            if action_sig == last_action_sig:
                repeated_action += 1
                if repeated_action >= 2:
                    run.error = (
                        f"重复执行同一动作 {repeated_action + 1} 次无效，"
                        f"判定方法错误"
                    )
                    run.message = run.error
                    break
            else:
                repeated_action = 0
                last_action_sig = action_sig

            # ── 6. 执行 ──
            step_t0 = time.time()
            result = await self._execute(decision)

            sr = StepResult(
                step=step,
                action=action,
                params={k: v for k, v in decision.items()
                        if k not in ("action", "reason")},
                success=result.get("success", False),
                error=result.get("error", ""),
                reason=reason,
                duration_ms=(time.time() - step_t0) * 1000,
            )

            # ── 7. 验证 ──
            verified, level = await self._verify(
                action, decision, result, vision_used,
            )
            sr.verified = verified
            sr.verify_level = level
            sr.screen_changed = result.get("screen_changed", False)

            if level == "vision":
                vision_used += 1
                self.stats["vision_calls"] += 1

            run.steps.append(sr)
            self.stats["steps_total"] += 1

            history.append({
                "step": step,
                "action": action,
                "params": sr.params,
                "success": sr.success,
                "verified": verified,
                "error": sr.error,
                "reason": reason,
            })

            # ── 8. 等界面稳定 ──
            await asyncio.sleep(0.5)

        else:
            run.error = f"达到最大步数 {self.max_steps}"
            run.message = f"做了 {len(run.steps)} 步还没完成：{run.error}"

        run.vision_calls = vision_used
        run.total_ms = (time.time() - t0) * 1000

        if run.success:
            self.stats["tasks_success"] += 1
            if not run.message:
                run.message = "完成"
        else:
            self.stats["tasks_failed"] += 1
            if not run.message:
                run.message = run.error or "未完成"

        return run

    # ── 感知 ──────────────────────────────────

    async def _observe(self) -> Dict:
        """感知当前状态"""
        active = self.cu.get_active_window()
        elements = self.locator.list_interactive(20)

        elements_text = "\n".join(
            f"  [{e.control_type}] {e.name}" for e in elements
        ) if elements else "  （无法枚举控件）"

        # 屏幕签名（判断是否变化）
        h = self.cu._screen_hash()

        return {
            "window_title": active.get("title", "未知"),
            "window_rect": {
                "left": active.get("left", 0),
                "top": active.get("top", 0),
                "width": active.get("width", 0),
                "height": active.get("height", 0),
            },
            "elements": elements,
            "elements_text": elements_text,
            "screen_size": self.cu.screen_size,
            "signature": h,
        }

    # ── 决策 ──────────────────────────────────

    async def _decide(
        self,
        instruction: str,
        state: Dict,
        history: List[Dict],
        session_context: str = "",
    ) -> Dict:
        """让 LLM 决定下一步"""
        # 历史压缩
        history_text = ""
        if history:
            lines = []
            for h in history[-6:]:
                mark = "OK" if h.get("success") else "FAIL"
                lines.append(
                    f"  步骤{h['step']} [{mark}] {h['action']} "
                    f"({h.get('reason', '')})"
                )
                if h.get("answer"):
                    lines.append(f"    视觉答: {h['answer'][:150]}")
                if h.get("error"):
                    lines.append(f"    错误: {h['error']}")
            history_text = "## 已执行\n" + "\n".join(lines)

        sw, sh = state["screen_size"]
        rect = state["window_rect"]

        user = f"""## 任务
{instruction}

{f"## 会话上下文{chr(10)}{session_context}" if session_context else ""}

## 当前状态
窗口: {state['window_title']}
窗口位置: ({rect['left']},{rect['top']}) 尺寸 {rect['width']}x{rect['height']}
屏幕: {sw}x{sh}

## 可交互控件（精确，优先用 click_text）
{state['elements_text']}

{history_text}

决定下一个动作。只输出一个 JSON 对象。"""

        raw = await self._llm.chat(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user},
            ],
            json_mode=True,
        )

        return self._parse(raw)

    def _parse(self, raw: str) -> Dict:
        """解析 LLM 输出

        ## 为什么不能简单 json.loads

        实测发现：即使设了 json_mode，模型也常常输出：
          {"action": "click", ...}
          Wait, let me reconsider. ...

        即 JSON 后面跟着一段推理文字。直接 json.loads 会报
        "Extra data: line 3 column 1"。

        解决：用 raw_decode 只解析第一个完整 JSON 对象，
        后面的内容全部忽略。
        """
        if not raw:
            return {"action": "abort", "message": "LLM 无响应"}

        text = raw.strip()

        # 去掉 markdown 代码块标记
        if "```" in text:
            parts = text.split("```")
            for p in parts:
                if "{" in p:
                    text = p
                    break

        # 从第一个 { 开始，用 raw_decode 只取第一个完整对象
        start = text.find("{")
        if start < 0:
            logger.warning(f"输出里没有 JSON: {raw[:150]}")
            return {
                "action": "abort",
                "message": f"模型没给出有效动作: {raw[:80]}",
            }

        candidate = text[start:]

        try:
            obj, end_idx = json.JSONDecoder().raw_decode(candidate)
            if isinstance(obj, dict) and "action" in obj:
                return obj
            logger.warning(f"JSON 但无 action 字段: {str(obj)[:120]}")
        except json.JSONDecodeError as e:
            logger.debug(f"raw_decode 失败: {e}")

        # 退回老的括号匹配法
        lt = candidate.rfind("}")
        if lt > 0:
            try:
                obj = json.loads(candidate[:lt + 1])
                if isinstance(obj, dict) and "action" in obj:
                    return obj
            except Exception:
                pass

        logger.warning(f"无法解析决策: {raw[:200]}")
        return {
            "action": "abort",
            "message": f"决策解析失败: {raw[:80]}",
        }

    # ── 执行 ──────────────────────────────────

    async def _execute(self, decision: Dict) -> Dict:
        """执行一个动作"""
        action = decision.get("action", "")

        try:
            # 文本目标点击
            if action == "click_text":
                target = decision.get("text", "")
                if not target:
                    return {"success": False, "error": "缺少 text"}

                el, method = await self.locator.locate(target)
                if not el:
                    return {
                        "success": False,
                        "error": f"找不到「{target}」",
                    }

                before = self.cu._screen_hash()
                r = self.cu.click(el.x, el.y)
                await asyncio.sleep(0.3)
                changed = self.cu._screen_hash() != before

                if self._journal:
                    self._journal.record(
                        action="click",
                        params={"x": el.x, "y": el.y, "target": el.name},
                        screen_before=before,
                    )

                return {
                    "success": r.success,
                    "error": r.error,
                    "screen_changed": changed,
                    "located": method,
                }

            # 坐标点击
            if action == "click":
                x, y = decision.get("x"), decision.get("y")
                sw, sh = self.cu.screen_size

                if x is None or y is None:
                    return {"success": False, "error": "缺少坐标"}

                # 归一化
                if 0 <= x <= 1 and 0 <= y <= 1:
                    x, y = int(x * sw), int(y * sh)

                before = self.cu._screen_hash()
                r = self.cu.click(int(x), int(y))
                await asyncio.sleep(0.3)
                changed = self.cu._screen_hash() != before

                if self._journal:
                    self._journal.record(
                        action="click",
                        params={"x": int(x), "y": int(y)},
                        screen_before=before,
                    )

                return {
                    "success": r.success,
                    "error": r.error,
                    "screen_changed": changed,
                }

            # 输入
            if action == "type":
                text = decision.get("text", "")
                if not text:
                    return {"success": False, "error": "缺少 text"}

                before = self.cu._screen_hash()
                r = self.cu.type_text(text)
                await asyncio.sleep(0.3)

                if self._journal:
                    self._journal.record(
                        action="type",
                        params={"text": text},
                        undoable=True,
                        undo_hint="ctrl+z",
                    )

                return {
                    "success": r.success,
                    "error": r.error,
                    "screen_changed": self.cu._screen_hash() != before,
                }

            # 按键
            if action == "press":
                key = decision.get("key", "enter")
                before = self.cu._screen_hash()
                r = self.cu.press(key)
                await asyncio.sleep(0.3)

                if self._journal:
                    self._journal.record(
                        action="press",
                        params={"key": key},
                        undoable=key.lower() not in ("enter", "return"),
                    )

                return {
                    "success": r.success,
                    "error": r.error,
                    "screen_changed": self.cu._screen_hash() != before,
                }

            # 组合键
            if action == "hotkey":
                keys = decision.get("keys", [])
                if isinstance(keys, str):
                    keys = keys.split("+")
                before = self.cu._screen_hash()
                r = self.cu.hotkey(*keys)
                await asyncio.sleep(0.3)

                if self._journal:
                    self._journal.record(
                        action="hotkey",
                        params={"keys": list(keys)},
                        undoable=False,
                    )

                return {
                    "success": r.success,
                    "error": r.error,
                    "screen_changed": self.cu._screen_hash() != before,
                }

            # 滚动
            if action == "scroll":
                pixels = decision.get("pixels", 480)
                before = self.cu._screen_hash()
                r = self.cu.scroll_pixels(pixels)
                await asyncio.sleep(0.3)

                if self._journal:
                    self._journal.record(
                        action="scroll",
                        params={"pixels": pixels},
                        undoable=True,
                        undo_hint=f"scroll {-pixels}",
                    )

                return {
                    "success": r.success,
                    "error": r.error,
                    "screen_changed": self.cu._screen_hash() != before,
                }

            if action == "scroll_until":
                direction = decision.get("direction", "bottom")
                before = self.cu._screen_hash()
                r = self.cu.scroll_until(direction)

                return {
                    "success": r.success,
                    "error": r.error,
                    "screen_changed": r.data.get("reached_boundary", False),
                    "data": r.data,
                }

            # 窗口切换
            if action == "focus_window":
                title = decision.get("title", "")
                before = self.cu._screen_hash()
                r = self.cu.focus_window(title)

                if self._journal:
                    self._journal.record(
                        action="focus_window",
                        params={"title": title},
                        undoable=True,
                        undo_hint="restore_previous_window",
                    )

                return {
                    "success": r.success,
                    "error": r.error,
                    "screen_changed": self.cu._screen_hash() != before,
                }

            # 启动应用
            if action == "launch_app":
                name = decision.get("name", "")
                r = self.cu.launch_app(name)

                if self._journal:
                    self._journal.record(
                        action="launch_app",
                        params={"name": name},
                        undoable=False,
                    )

                return {
                    "success": r.success,
                    "error": r.error,
                    "screen_changed": True,
                }

            # 等待
            if action == "wait":
                secs = min(float(decision.get("seconds", 1)), 10.0)
                await asyncio.sleep(secs)
                return {"success": True, "screen_changed": False}

            return {
                "success": False,
                "error": f"未知动作: {action}",
            }

        except Exception as e:
            logger.exception(f"执行 {action} 异常")
            return {"success": False, "error": f"{type(e).__name__}: {e}"}

    # ── 验证 ──────────────────────────────────

    async def _verify(
        self,
        action: str,
        decision: Dict,
        result: Dict,
        vision_used: int,
    ) -> tuple:
        """三层验证

        Returns:
            (是否验证通过, 实际用的验证层级)
        """
        # 等待类动作不需要验证
        if action in ("wait",):
            return True, VerifyLevel.NONE

        # 第一层：像素变化
        if result.get("screen_changed"):
            return True, VerifyLevel.PIXEL

        # 动作本身失败
        if not result.get("success"):
            return False, VerifyLevel.PIXEL

        # 第二层：结构化校验
        # 动作成功但屏幕没变，可能是：
        #   a) 真的生效了但变化不明显
        #   b) 什么都没发生
        await asyncio.sleep(0.4)

        if action in ("type", "press", "hotkey"):
            # 键盘动作屏幕不一定变（比如在输入框里打字看不到变化）
            # 保守认为成功
            return True, VerifyLevel.STRUCTURE

        # 第三层：视觉确认（只在还有预算且动作应该改变界面时）
        if (self.enable_vision
                and vision_used < self.vision_budget
                and action in ("click", "click_text", "focus_window",
                               "launch_app")):
            answer = await self._ask_vision(
                f"执行了「{decision.get('reason', action)}」，"
                f"这个操作成功了吗？屏幕现在是什么状态？"
                f"请简短回答：成功/失败 + 原因"
            )
            success = "成功" in answer or "success" in answer.lower()
            return success, VerifyLevel.VISION

        # 没预算了，保守认为成功
        return True, VerifyLevel.STRUCTURE

    async def _ask_vision(self, question: str) -> str:
        """问视觉模型（降采样后）"""
        vision = self._get_vision()

        if not vision or not getattr(vision, "available", False):
            return "（无可用视觉模型）"

        img = self.cu.screenshot(max_width=1400)
        if not img:
            return "（截图失败）"

        b64 = base64.b64encode(img).decode()

        return await vision.describe(b64, question)

    # ── 状态 ──────────────────────────────────

    def get_status(self) -> Dict:
        from laaper.hub.computer_use import get_computer_status

        return {
            "llm": bool(self._llm and self._llm.available),
            "vision": bool(
                self._get_vision()
                and getattr(self._get_vision(), "available", False)
            ),
            "max_steps": self.max_steps,
            "vision_budget": self.vision_budget,
            "computer": get_computer_status(),
            **self.stats,
        }


# ══════════════════════════════════════════════════════════
#  接入三端中枢
# ══════════════════════════════════════════════════════════

def register_multistep_handlers(
    hub: Any,
    pc_node: str = "pc-01",
    agent: Optional[MultiStepComputerAgent] = None,
) -> Dict[str, Any]:
    """把多步任务注册到中枢"""
    import concurrent.futures

    agent = agent or MultiStepComputerAgent()

    def _run_sync(coro, timeout: float = 300.0):
        """同步环境跑异步"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, coro).result(timeout=timeout)
        except RuntimeError:
            pass
        return asyncio.run(coro)

    async def computer_task(params: Dict) -> Dict:
        instruction = params.get("instruction", "")
        if not instruction:
            return {"success": False, "error": "未提供 instruction"}

        run = await agent.run(instruction)

        return {
            "success": run.success,
            "data": {
                "message": run.message,
                "steps": len(run.steps),
                "duration_ms": round(run.total_ms, 1),
                "vision_calls": run.vision_calls,
                "detail": run.to_dict(),
            },
            "error": "" if run.success else run.message,
        }

    hub.transport.register_handler(pc_node, "computer_task", computer_task)
    hub.transport.register_handler(pc_node, "do_task", computer_task)

    return {
        "agent": agent,
        "handlers": ["computer_task", "do_task"],
        "status": agent.get_status(),
    }