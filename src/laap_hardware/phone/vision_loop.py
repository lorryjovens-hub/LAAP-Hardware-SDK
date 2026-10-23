"""Vision-Action Loop — 视觉动作闭环

LAAPer 看着手机屏幕，理解界面，决定动作，执行，再验证。

这就是"AI 操作手机"的核心循环：
    截图 → 理解界面元素 → 规划动作 → 执行 → 等待界面稳定 → 验证 → 循环
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from phone.controller import PhoneController
from phone.types import ActionResult, ActionType, ScreenFrame, TouchAction

logger = logging.getLogger("laap.phone.loop")


@dataclass
class UIAction:
    """一个 UI 动作"""
    action: str                  # tap / drag / type / key / home / wait / finish
    x: float = 0.0
    y: float = 0.0
    to_x: float = 0.0
    to_y: float = 0.0
    text: str = ""
    key: str = ""
    duration_ms: int = 300
    reason: str = ""             # 为什么做这个动作

    def to_dict(self) -> Dict:
        return {
            "action": self.action,
            "x": self.x,
            "y": self.y,
            "to_x": self.to_x,
            "to_y": self.to_y,
            "text": self.text,
            "key": self.key,
            "reason": self.reason,
        }


@dataclass
class TaskStep:
    """任务步骤记录"""
    step: int
    action: UIAction
    result: ActionResult
    frame_before: Optional[str] = None
    frame_after: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class TaskResult:
    """任务执行结果"""
    task_id: str
    instruction: str
    success: bool
    steps: List[TaskStep] = field(default_factory=list)
    final_message: str = ""
    error: str = ""
    total_steps: int = 0
    duration_seconds: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "instruction": self.instruction,
            "success": self.success,
            "total_steps": self.total_steps,
            "duration": round(self.duration_seconds, 1),
            "final_message": self.final_message,
            "error": self.error,
            "steps": [
                {
                    "step": s.step,
                    "action": s.action.to_dict(),
                    "success": s.result.success,
                    "changed": s.result.changed,
                }
                for s in self.steps
            ],
        }


# ── 视觉理解接口 ──────────────────────────────────

class VisionAnalyzer:
    """视觉分析器 — 把截图变成可理解的结构

    可以用两种方式：
    1. LLM 视觉模型（GPT-4V / Claude / Qwen-VL）
    2. 本地启发式（找按钮、文本区域）
    """

    def __init__(self, llm_client: Optional[Any] = None):
        self.llm_client = llm_client

    async def analyze(
        self,
        frame: ScreenFrame,
        instruction: str,
        history: List[TaskStep],
    ) -> Optional[UIAction]:
        """分析屏幕，决定下一个动作

        Args:
            frame: 当前屏幕帧
            instruction: 用户任务指令
            history: 已执行的步骤

        Returns:
            下一个动作，或 None（表示完成）
        """
        if self.llm_client:
            return await self._analyze_with_llm(frame, instruction, history)
        else:
            return await self._analyze_heuristic(frame, instruction, history)

    async def _analyze_with_llm(
        self,
        frame: ScreenFrame,
        instruction: str,
        history: List[TaskStep],
    ) -> Optional[UIAction]:
        """用 LLM 视觉模型分析"""
        prompt = self._build_prompt(frame, instruction, history)

        try:
            # 调用 LLM（实际使用时注入客户端）
            response = await self.llm_client.chat_with_image(
                prompt=prompt,
                image_data=frame.data,
                image_format=frame.format,
            )
            return self._parse_response(response)
        except Exception as e:
            logger.error(f"LLM 视觉分析失败: {e}")
            return None

    def _build_prompt(
        self,
        frame: ScreenFrame,
        instruction: str,
        history: List[TaskStep],
    ) -> str:
        """构建视觉理解 prompt"""
        history_text = ""
        if history:
            recent = history[-5:]
            history_text = "已执行的动作:\n" + "\n".join(
                f"  {s.step}. {s.action.action} "
                f"{'(成功)' if s.result.success else '(失败)'} "
                f"— {s.action.reason}"
                for s in recent
            )

        return f"""你是一个手机操作助手。看着这张手机截图，完成用户的任务。

用户任务: {instruction}

{history_text}

请分析当前屏幕，决定下一个动作。可选动作：

1. tap(x, y) — 点击某个位置（x, y 是 0-1 的归一化坐标）
2. drag(x, y, to_x, to_y, duration_ms) — 拖拽
3. type(text) — 输入文字
4. key(key_name) — 按键（enter/escape/backspace/home）
5. home() — 回到主屏幕
6. wait(seconds) — 等待界面加载
7. finish(message) — 任务完成

只输出 JSON，格式：
{{
  "action": "tap",
  "x": 0.5,
  "y": 0.8,
  "reason": "点击'设置'图标"
}}

或者任务完成时：
{{
  "action": "finish",
  "reason": "已成功设置闹钟",
  "message": "闹钟已设置：明早 8:00，每周一和周二重复"
}}

注意：
- 坐标必须是 0-1 的归一化值，不是像素
- 如果界面还在加载，用 wait
- 如果上一步失败了，换个方法
- 不要重复已经成功过的动作"""

    def _parse_response(self, response: str) -> Optional[UIAction]:
        """解析 LLM 响应"""
        try:
            # 提取 JSON
            text = response.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            data = json.loads(text.strip())

            return UIAction(
                action=data.get("action", "wait"),
                x=float(data.get("x", 0)),
                y=float(data.get("y", 0)),
                to_x=float(data.get("to_x", 0)),
                to_y=float(data.get("to_y", 0)),
                text=data.get("text", ""),
                key=data.get("key", ""),
                duration_ms=int(data.get("duration_ms", 300)),
                reason=data.get("reason", ""),
            )
        except Exception as e:
            logger.error(f"解析 LLM 响应失败: {e}")
            return None

    async def _analyze_heuristic(
        self,
        frame: ScreenFrame,
        instruction: str,
        history: List[TaskStep],
    ) -> Optional[UIAction]:
        """启发式分析（无 LLM 时的降级方案）

        仅做简单的屏幕变化检测，不能真正理解界面。
        """
        if not history:
            # 第一步：点屏幕中心试试
            return UIAction(
                action="tap",
                x=0.5,
                y=0.5,
                reason="启发式：点击屏幕中心",
            )

        # 如果连续几步都没变化，放弃
        if len(history) >= 3:
            no_change = all(not s.result.changed for s in history[-3:])
            if no_change:
                return UIAction(
                    action="finish",
                    reason="启发式：界面无响应，停止",
                )

        return UIAction(
            action="wait",
            reason="启发式：等待界面稳定",
        )


# ── 视觉动作闭环 ──────────────────────────────────

class VisionActionLoop:
    """视觉-动作闭环

    用法:
        loop = VisionActionLoop(phone_controller, vision_analyzer)
        result = await loop.run("帮我设置明早 8 点的闹钟")
    """

    def __init__(
        self,
        controller: PhoneController,
        analyzer: Optional[VisionAnalyzer] = None,
        max_steps: int = 20,
        settle_time: float = 0.8,
    ):
        self.controller = controller
        self.analyzer = analyzer or VisionAnalyzer()
        self.max_steps = max_steps
        self.settle_time = settle_time

        # 回调
        self._on_step: Optional[Callable] = None
        self._on_frame: Optional[Callable] = None

    async def run(self, instruction: str) -> TaskResult:
        """执行任务

        Args:
            instruction: 自然语言任务指令

        Returns:
            任务结果
        """
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        start_time = time.time()

        logger.info(f"[{task_id}] 开始任务: {instruction}")

        result = TaskResult(
            task_id=task_id,
            instruction=instruction,
            success=False,
        )

        if not self.controller.connected:
            result.error = "手机未连接"
            return result

        steps: List[TaskStep] = []

        try:
            for step_num in range(1, self.max_steps + 1):
                # 1. 感知：截屏
                frame = await self.controller.screenshot()
                if not frame:
                    result.error = "无法获取屏幕截图"
                    break

                if self._on_frame:
                    self._on_frame(frame)

                # 2. 理解 + 决策
                action = await self.analyzer.analyze(
                    frame, instruction, steps
                )

                if not action:
                    result.error = "视觉分析失败"
                    break

                # 3. 判断是否完成
                if action.action == "finish":
                    result.success = True
                    result.final_message = action.reason
                    logger.info(f"[{task_id}] 任务完成: {action.reason}")
                    break

                # 4. 执行动作
                action_result = await self._execute(action)

                # 5. 等待界面稳定
                if action.action != "wait":
                    await asyncio.sleep(self.settle_time)

                # 6. 记录步骤
                step = TaskStep(
                    step=step_num,
                    action=action,
                    result=action_result,
                )
                steps.append(step)

                if self._on_step:
                    self._on_step(step)

                logger.info(
                    f"[{task_id}] 步骤 {step_num}: {action.action} "
                    f"— {action.reason} ({'成功' if action_result.success else '失败'})"
                )

                # 连续失败保护
                if len(steps) >= 3 and all(not s.result.success for s in steps[-3:]):
                    result.error = "连续 3 步失败，中止任务"
                    break

            else:
                result.error = f"达到最大步数限制 ({self.max_steps})"

        except Exception as e:
            logger.error(f"[{task_id}] 任务异常: {e}")
            result.error = str(e)

        finally:
            # 安全释放
            try:
                await self.controller.emergency_stop()
            except Exception:
                pass

        result.steps = steps
        result.total_steps = len(steps)
        result.duration_seconds = time.time() - start_time

        logger.info(
            f"[{task_id}] 任务结束: "
            f"{'成功' if result.success else '失败'} "
            f"({result.total_steps} 步, {result.duration_seconds:.1f}s)"
        )

        return result

    async def _execute(self, action: UIAction) -> ActionResult:
        """执行单个动作"""
        try:
            if action.action == "tap":
                return await self.controller.tap(action.x, action.y)

            elif action.action == "drag":
                return await self.controller.drag(
                    action.x, action.y,
                    action.to_x, action.to_y,
                    action.duration_ms,
                )

            elif action.action == "type":
                return await self.controller.type_text(action.text)

            elif action.action == "key":
                return await self.controller.press_key(action.key)

            elif action.action == "home":
                return await self.controller.go_home()

            elif action.action == "wait":
                return await self.controller.wait(1.0)

            else:
                return ActionResult(
                    success=False,
                    action_type=ActionType.WAIT,
                    error=f"未知动作: {action.action}",
                )

        except Exception as e:
            logger.error(f"执行动作失败: {e}")
            return ActionResult(
                success=False,
                action_type=ActionType.WAIT,
                error=str(e),
            )

    def on_step(self, callback: Callable):
        """注册步骤回调"""
        self._on_step = callback

    def on_frame(self, callback: Callable):
        """注册帧回调"""
        self._on_frame = callback