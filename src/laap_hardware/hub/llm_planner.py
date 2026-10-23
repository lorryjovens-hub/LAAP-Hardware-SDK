"""LLM 任务规划器 — 用 DeepSeek 听懂人话并拆成跨端步骤

## 为什么规则 planner 不够

原来的规则 planner：

    输入: "帮我打开 laap.cn 截图发手机"
    → 正则匹配 "打开" + "http" → browse
    → 匹配 "截图" → screenshot
    → 匹配 "手机" → display

能处理这个句式。但：

    输入: "把刚才那张图发给我妈"
    输入: "电脑上那个页面，手机上接着看"
    输入: "看看现在几点，如果超过十点就提醒我睡觉"
    → 正则全瞎

## DeepSeek 怎么适配

关键洞察：**DeepSeek 没有视觉，但不需要视觉也能操作电脑。**

人的两种视觉通路：
  · 腹侧（what）：这是什么 → 需要图像
  · 背侧（where/how）：在哪、怎么够 → 只需要空间关系

我们的结构化感知层（DOM）给的是**背侧通路信息**：
  · 每个元素是什么（tag/text/type）
  · 在哪（归一化坐标）
  · 能不能点（enabled/clickable）
  · 唯一标识（selector）

**这已经足够精准操作了。** 而且比视觉更强：
  · 不需要猜坐标
  · 没有识别错误
  · token 消耗低 10 倍
  · 速度快得多

所以本模块的策略：

    默认：DeepSeek + DOM 文本（快、准、便宜）
    兜底：SenseNova 视觉（DOM 不够时，比如看图片内容、判断视觉状态）

## 用法

    planner = LLMPlanner()
    steps = await planner.plan(
        instruction="把刚才那张图发给我妈",
        context="用户刚才让我截了 LAAP 官网的图",
        available_nodes=[...],
    )
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laaper.hub.planner")


# ══════════════════════════════════════════════════════════
#  LLM 配置
# ══════════════════════════════════════════════════════════

@dataclass
class LLMConfig:
    """LLM 配置"""
    provider: str = "deepseek"
    model: str = "deepseek-flash"
    base_url: str = "https://api.deepseek.com/v1"
    api_key: str = ""
    temperature: float = 0.1
    max_tokens: int = 2000
    timeout: float = 60.0


def detect_llm_config() -> LLMConfig:
    """自动探测主 LLM"""
    # 显式覆盖
    if os.environ.get("LAAP_PLANNER_MODEL"):
        return LLMConfig(
            provider="custom",
            model=os.environ["LAAP_PLANNER_MODEL"],
            base_url=os.environ.get("LAAP_PLANNER_BASE_URL", ""),
            api_key=os.environ.get("LAAP_PLANNER_API_KEY", ""),
        )

    # DeepSeek（LAAP 主力模型）
    if os.environ.get("DEEPSEEK_API_KEY"):
        return LLMConfig(
            provider="deepseek",
            model=os.environ.get("LAAP_MODEL", "deepseek-flash"),
            base_url="https://api.deepseek.com/v1",
            api_key=os.environ["DEEPSEEK_API_KEY"],
        )

    # SenseNova（也可当文本模型）
    if os.environ.get("SENSENOVA_API_KEY"):
        return LLMConfig(
            provider="sensenova",
            model="deepseek-v4-flash",
            base_url="https://token.sensenova.cn/v1",
            api_key=os.environ["SENSENOVA_API_KEY"],
        )

    # OpenAI
    if os.environ.get("OPENAI_API_KEY"):
        return LLMConfig(
            provider="openai",
            model="gpt-4o-mini",
            base_url="https://api.openai.com/v1",
            api_key=os.environ["OPENAI_API_KEY"],
        )

    return LLMConfig(provider="none", api_key="")


# ══════════════════════════════════════════════════════════
#  LLM 客户端
# ══════════════════════════════════════════════════════════

class LLMClient:
    """轻量 LLM 客户端（OpenAI 兼容）"""

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or detect_llm_config()

    @property
    def available(self) -> bool:
        return self.config.provider != "none" and bool(self.config.base_url)

    async def chat(
        self,
        messages: List[Dict[str, str]],
        json_mode: bool = False,
    ) -> str:
        """发一次对话"""
        if not self.available:
            return ""

        try:
            import httpx
        except ImportError:
            logger.error("需要 httpx")
            return ""

        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }
        payload: Dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code != 200:
                    logger.error(
                        f"LLM 失败 {resp.status_code}: {resp.text[:300]}"
                    )
                    # json_mode 不被支持时降级重试
                    if json_mode and resp.status_code == 400:
                        payload.pop("response_format", None)
                        resp = await client.post(url, headers=headers, json=payload)
                        if resp.status_code == 200:
                            return resp.json()["choices"][0]["message"]["content"]
                    return ""
                return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"LLM 调用异常: {e}")
            return ""


# ══════════════════════════════════════════════════════════
#  规划器
# ══════════════════════════════════════════════════════════

_PLAN_SYSTEM = """你是 LAAP 三端系统的任务规划器。

系统有三个节点，能力如下：
- 电脑(pc)：高算力、浏览器、文件系统、Shell 命令、键鼠控制、截屏
- 手机(phone)：摄像头、GPS、触摸、随身显示、震动
- 小智硬件(hardware)：语音输入输出、温度/湿度/压力传感器、继电器

感知能力(sensors)可选值：
  screen, camera, microphone, speaker, touch, keyboard, mouse, gps, motion, temperature, humidity, pressure, light, proximity

行动能力(actuators)可选值：
  click, type, shell, file, browse, speak, display, vibrate, relay

你需要把用户的一句话拆成有序的执行步骤。

输出 JSON：
{
  "understanding": "你理解用户想要什么（一句话）",
  "steps": [
    {
      "description": "这一步做什么（给人看的中文描述）",
      "needs_sensors": ["screen"],
      "needs_actuators": ["browse"],
      "min_compute": 0.5,
      "action": "browse",
      "params": {"url": "https://example.com"}
    }
  ],
  "reply_template": "完成后要回给用户的话"
}

可用 action 取值：
  browse(url)          在电脑上打开网页
  screenshot(full_page) 截屏
  display(payload)     把内容显示到某端
  shell(command)       执行命令
  file_read(path)      读文件
  camera_capture()     手机拍照
  speak(text)          语音播报
  vibrate()            手机震动

规则：
1. 只用真实存在的 action
2. 步骤要按依赖顺序
3. 如果一句话只需要一步，就只给一步
4. 无法完成时 steps 返回空数组，understanding 说明原因
5. 只输出 JSON，不要其他内容"""


@dataclass
class PlanStep:
    """规划出的一个步骤"""
    description: str = ""
    needs_sensors: List[str] = field(default_factory=list)
    needs_actuators: List[str] = field(default_factory=list)
    min_compute: float = 0.0
    action: str = ""
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Plan:
    """完整计划"""
    understanding: str = ""
    steps: List[PlanStep] = field(default_factory=list)
    reply_template: str = ""
    raw: str = ""
    parse_error: str = ""

    @property
    def empty(self) -> bool:
        return not self.steps


class LLMPlanner:
    """LLM 任务规划器

    把自然语言拆成跨端步骤。用 DeepSeek（或任何 OpenAI 兼容模型）。
    """

    def __init__(self, client: Optional[LLMClient] = None):
        self.client = client or LLMClient()

    async def plan(
        self,
        instruction: str,
        context: str = "",
        available_nodes: Optional[List[str]] = None,
    ) -> Plan:
        """规划任务"""
        if not self.client.available:
            return Plan(
                parse_error="没有可用的 LLM，请设置 DEEPSEEK_API_KEY",
            )

        user_parts = [f"用户说：{instruction}"]

        if context:
            user_parts.append(f"\n最近的对话上下文：\n{context}")

        if available_nodes:
            user_parts.append(f"\n当前在线节点：{', '.join(available_nodes)}")

        messages = [
            {"role": "system", "content": _PLAN_SYSTEM},
            {"role": "user", "content": "\n".join(user_parts)},
        ]

        raw = await self.client.chat(messages, json_mode=True)

        return self._parse(raw)

    def _parse(self, raw: str) -> Plan:
        """解析 LLM 输出"""
        plan = Plan(raw=raw)

        if not raw:
            plan.parse_error = "LLM 无响应"
            return plan

        # 提取 JSON
        text = raw.strip()
        if "```" in text:
            parts = text.split("```")
            for p in parts:
                if "{" in p:
                    text = p
                    break
            if text.startswith("json"):
                text = text[4:]

        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]

        try:
            data = json.loads(text)
        except Exception as e:
            plan.parse_error = f"JSON 解析失败: {e}"
            logger.warning(f"规划解析失败: {raw[:300]}")
            return plan

        plan.understanding = data.get("understanding", "")
        plan.reply_template = data.get("reply_template", "")

        for s in data.get("steps", []):
            plan.steps.append(PlanStep(
                description=s.get("description", ""),
                needs_sensors=s.get("needs_sensors", []) or [],
                needs_actuators=s.get("needs_actuators", []) or [],
                min_compute=float(s.get("min_compute", 0.0) or 0.0),
                action=s.get("action", ""),
                params=s.get("params", {}) or {},
            ))

        return plan

    def as_hub_planner(self):
        """转成 TriNodeHub.set_planner 接受的格式"""
        async def planner(text: str, context: str):
            plan = await self.plan(text, context)
            if plan.empty:
                return None
            return [
                {
                    "description": s.description,
                    "needs_sensors": s.needs_sensors,
                    "needs_actuators": s.needs_actuators,
                    "min_compute": s.min_compute,
                    "action": s.action,
                    "params": s.params,
                }
                for s in plan.steps
            ]

        return planner


# ══════════════════════════════════════════════════════════
#  DeepSeek Computer Use — 用 DOM 文本操作网页/桌面
# ══════════════════════════════════════════════════════════

_CU_SYSTEM = """你是网页操作智能体。你能"看见"网页，方式是通过结构化描述。

页面描述长这样：
## 你正在看的网页
URL: https://example.com
标题: 示例网站
视口: 1280x800

## 页面文字内容
（页面上的所有文字）

## 可交互元素
[0] a "首页" @0.26,0.05
[5] button "登录" @0.50,0.10
[12] input "请输入用户名" @0.50,0.30

格式说明：
  [编号] 标签 "文字" @归一化坐标(x,y)
  * 开头表示显眼的大按钮
  [禁用] 表示不可点
  [不可见] 表示当前看不到

你的任务：根据当前页面状态，决定下一个动作。

输出 JSON（只输出 JSON）：
{"action": "click", "element_id": 5, "reason": "点击登录按钮"}
{"action": "type", "element_id": 12, "text": "用户名", "reason": "填写用户名"}
{"action": "press", "key": "Enter", "reason": "提交表单"}
{"action": "scroll", "direction": "down", "reason": "查看下方内容"}
{"action": "wait", "seconds": 2, "reason": "等待加载"}
{"action": "navigate", "url": "https://...", "reason": "打开新页面"}
{"action": "finish", "message": "任务完成说明", "reason": "目标已达成"}

关键规则：
1. **优先用 element_id**，不要猜坐标
2. 如果需要视觉信息（比如看图片内容、判断颜色/布局），
   返回 {"action": "need_vision", "question": "你想看什么"}
3. 任务已完成时用 finish
4. 如果卡住了，用 finish 说明卡在哪"""


@dataclass
class CUResult:
    """Computer Use 结果"""
    success: bool
    instruction: str
    message: str = ""
    steps: int = 0
    history: List[Dict] = field(default_factory=list)
    used_vision: int = 0
    error: str = ""


class DeepSeekComputerUse:
    """DeepSeek 驱动的 Computer Use

    核心设计：**默认不用视觉**
      · DOM 文本给 DeepSeek → 它决定动作
      · 只在它主动要求时（need_vision）才调视觉模型

    这样比纯视觉方案：
      · 快 3-5 倍（一次 LLM 调用 vs 一次视觉调用）
      · 便宜 10 倍（文本 token vs 图像 token）
      · 更准（不需要猜坐标）
    """

    def __init__(
        self,
        page: Any,
        client: Optional[LLMClient] = None,
        max_steps: int = 15,
        max_stall: int = 3,
        enable_vision_fallback: bool = True,
    ):
        self.page = page
        self.client = client or LLMClient()
        self.max_steps = max_steps
        self.max_stall = max_stall
        self.enable_vision_fallback = enable_vision_fallback

        # 视觉兜底
        self._vision = None
        self._perception = None

    def _get_perception(self):
        if self._perception is None:
            from laap.tools.browser_perception import BrowserPerception
            self._perception = BrowserPerception(
                self.page, annotate=False, enable_vision=False
            )
        return self._perception

    def _get_vision(self):
        if self._vision is None:
            from laap.tools.browser_perception import VisionClient
            self._vision = VisionClient()
        return self._vision

    async def run(self, instruction: str) -> CUResult:
        """执行任务"""
        t0 = __import__("time").time()
        history: List[Dict] = []
        stall = 0
        last_sig = ""
        vision_calls = 0

        perception = self._get_perception()

        for step in range(1, self.max_steps + 1):
            # 1. 感知（DOM，无视觉）
            seen = await perception.perceive()

            if seen.error:
                return CUResult(
                    success=False,
                    instruction=instruction,
                    error=f"感知失败: {seen.error}",
                    steps=step,
                    history=history,
                )

            # 2. 停滞检测
            sig = f"{seen.url}|{len(seen.elements)}|{seen.text_content[:300]}"
            if sig == last_sig:
                stall += 1
                if stall >= self.max_stall:
                    return CUResult(
                        success=False,
                        instruction=instruction,
                        error=f"连续 {stall} 步无进展",
                        steps=step,
                        history=history,
                        used_vision=vision_calls,
                    )
            else:
                stall = 0
                last_sig = sig

            # 3. 让 LLM 决定
            decision = await self._decide(seen, instruction, history)

            history.append({
                "step": step,
                "url": seen.url,
                "decision": decision,
            })

            action = decision.get("action", "")

            # 4. 完成
            if action == "finish":
                return CUResult(
                    success=True,
                    instruction=instruction,
                    message=decision.get("message", "完成"),
                    steps=step,
                    history=history,
                    used_vision=vision_calls,
                )

            # 5. LLM 要求视觉
            if action == "need_vision":
                if not self.enable_vision_fallback:
                    return CUResult(
                        success=False,
                        instruction=instruction,
                        error="LLM 要求视觉但已禁用视觉兜底",
                        steps=step,
                        history=history,
                    )

                vision_answer = await self._ask_vision(
                    seen, decision.get("question", "")
                )
                vision_calls += 1

                # 把视觉答案加入历史，让 LLM 下轮参考
                history[-1]["vision_answer"] = vision_answer
                logger.info(f"[步骤{step}] 视觉兜底: {vision_answer[:100]}")
                continue

            # 6. 执行动作
            result = await perception.act(decision)
            history[-1]["result"] = result

            if not result.get("success"):
                stall += 1
                logger.warning(f"[步骤{step}] 动作失败: {result.get('error')}")

            # 7. 等页面稳定
            import asyncio
            await asyncio.sleep(0.6)

        return CUResult(
            success=False,
            instruction=instruction,
            error=f"达到最大步数 {self.max_steps}",
            steps=self.max_steps,
            history=history,
            used_vision=vision_calls,
        )

    async def _decide(
        self,
        seen: Any,
        instruction: str,
        history: List[Dict],
    ) -> Dict:
        """让 LLM 决定动作"""
        # 历史压缩
        history_text = ""
        if history:
            lines = []
            for h in history[-5:]:
                d = h.get("decision", {})
                lines.append(
                    f"  步骤{h['step']}: {d.get('action')} "
                    f"- {d.get('reason', '')}"
                )
                if h.get("vision_answer"):
                    lines.append(f"    视觉看到: {h['vision_answer'][:200]}")
                if h.get("result") and not h["result"].get("success"):
                    lines.append(f"    失败: {h['result'].get('error')}")
            history_text = "已执行的步骤:\n" + "\n".join(lines)

        user_content = f"""任务: {instruction}

{history_text}

{seen.to_prompt(max_text=3000, max_elements=50)}

请决定下一个动作。只输出 JSON。"""

        messages = [
            {"role": "system", "content": _CU_SYSTEM},
            {"role": "user", "content": user_content},
        ]

        raw = await self.client.chat(messages, json_mode=True)
        return self._parse_decision(raw)

    def _parse_decision(self, raw: str) -> Dict:
        """解析动作"""
        if not raw:
            return {"action": "finish", "message": "LLM 无响应"}

        text = raw.strip()
        if "```" in text:
            parts = text.split("```")
            for p in parts:
                if "{" in p:
                    text = p
                    break
            if text.startswith("json"):
                text = text[4:]

        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]

        try:
            return json.loads(text)
        except Exception as e:
            logger.warning(f"动作解析失败: {e}, raw={raw[:200]}")
            return {"action": "finish", "message": f"解析失败: {raw[:80]}"}

    async def _ask_vision(self, seen: Any, question: str) -> str:
        """视觉兜底：问视觉模型"""
        vision = self._get_vision()

        if not vision.available:
            return "（没有可用的视觉模型）"

        if not seen.screenshot_b64:
            return "（没有截图）"

        return await vision.describe(
            seen.screenshot_b64,
            question or "请描述这个页面的视觉布局和关键视觉元素",
        )


# ══════════════════════════════════════════════════════════
#  混合视觉决策 — DOM 优先，视觉兜底
# ══════════════════════════════════════════════════════════

class HybridVisionStrategy:
    """混合视觉策略

    决定什么时候用视觉、什么时候只用 DOM。

    原则：
      1. 能用 DOM 解决就用 DOM（快、准、便宜）
      2. 需要判断视觉状态时才用视觉：
         · 验证码
         · 图片内容
         · 颜色/布局判断
         · 元素不可见/hidden 想确认是否真的看不到
         · 页面结构复杂，DOM 元素太多
    """

    VISION_TRIGGERS = (
        "验证码", "图片", "颜色", "长什么样", "看起来",
        "布局", "图标", "logo", "照片", "截图", "画面",
        "是否显示", "有没有显示", "看起来对不对",
    )

    @classmethod
    def needs_vision(cls, instruction: str, element_count: int) -> bool:
        """判断任务是否需要视觉"""
        # 明确提到视觉相关词汇
        if any(t in instruction for t in cls.VISION_TRIGGERS):
            return True

        # 元素太多，DOM 可能不够用
        if element_count > 120:
            return True

        return False

    @classmethod
    def describe_strategy(cls, instruction: str, element_count: int) -> str:
        """说明当前策略（给人看）"""
        if cls.needs_vision(instruction, element_count):
            return "视觉优先（任务涉及视觉判断）"
        return "DOM 优先（纯结构化操作，更快更准）"


# ══════════════════════════════════════════════════════════
#  状态
# ══════════════════════════════════════════════════════════

def get_llm_status() -> Dict:
    """LLM 能力状态"""
    cfg = detect_llm_config()
    return {
        "available": cfg.provider != "none",
        "provider": cfg.provider,
        "model": cfg.model,
        "base_url": cfg.base_url,
        "hint": (
            "LLM 规划器就绪"
            if cfg.provider != "none"
            else "未配置 LLM。设置 DEEPSEEK_API_KEY 或 LAAP_PLANNER_MODEL"
        ),
    }