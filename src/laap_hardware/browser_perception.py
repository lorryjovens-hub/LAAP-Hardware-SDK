"""LAAP 浏览器感知系统 — 让 Aris 真正"看见"网页

## 为什么需要这个模块

原来的 `browser_vision` 工具：
  - 截图 → base64
  - 返回 "configure a vision-capable LLM" 占位文本
  - **从不真正调用视觉模型**
  - OCR 也不一定有（tesseract 常缺）

结果：Aris 能打开网页，但"看不见"内容，也就无法决定下一步点什么。

## 本模块提供两层感知

### 第一层：结构化感知（DOM）— 始终可用，零成本
    · 所有可交互元素（按钮/链接/输入框）的精确信息
    · 文本内容（页面上写了什么）
    · 元素位置和可见性
    · 元素当前状态（禁用/选中/已填）

    这一层比视觉更强：**精确**。视觉模型只能猜坐标，DOM 直接给 selector。

### 第二层：视觉感知（截图 + 标注）— 有视觉模型时启用
    · 截图
    · 在可交互元素上画编号方框
    · 让视觉模型说"点第 5 个框"

    这一层补足 DOM 拿不到的东西：布局、图片内容、视觉状态。

## 用法

    perception = BrowserPerception(page)

    # 完整感知（结构化 + 视觉）
    seen = await perception.perceive()

    # Aris 拿到的就是这段可读文本 + 截图
    print(seen.to_prompt())

    # 决定动作后执行
    await perception.act({"action": "click", "element_id": 5})
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("laap.browser.perception")


# ══════════════════════════════════════════════════════════
#  视觉后端 — 自动探测可用的视觉模型
# ══════════════════════════════════════════════════════════

@dataclass
class VisionBackendConfig:
    """视觉后端配置"""
    provider: str = ""
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    max_tokens: int = 1500
    timeout: float = 60.0
    available: bool = False


# 已知的视觉模型提供商（按优先级）
_VISION_PROVIDERS = [
    {
        "provider": "sensenova",
        "env_key": "SENSENOVA_API_KEY",
        "model": "sensenova-6.8-flash-lite",
        "base_url": "https://token.sensenova.cn/v1",
        "note": "商汤日日新 6.8 Flash-Lite，支持图像输入，256K 上下文",
    },
    {
        "provider": "openai",
        "env_key": "OPENAI_API_KEY",
        "model": "gpt-4o",
        "base_url": "https://api.openai.com/v1",
    },
    {
        "provider": "dashscope",
        "env_key": "DASHSCOPE_API_KEY",
        "model": "qwen-vl-max",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    {
        "provider": "openrouter",
        "env_key": "OPENROUTER_API_KEY",
        "model": "anthropic/claude-sonnet-4.5",
        "base_url": "https://openrouter.ai/api/v1",
    },
    {
        "provider": "ollama",
        "env_key": "",                     # 无需 key
        "model": "llava",
        "base_url": "http://localhost:11434/v1",
    },
]


def detect_vision_backend() -> VisionBackendConfig:
    """自动探测可用的视觉后端

    优先使用环境中有 API key 的提供商。
    """
    # 显式覆盖
    explicit_model = os.environ.get("LAAP_VISION_MODEL", "")
    explicit_url = os.environ.get("LAAP_VISION_BASE_URL", "")
    explicit_key = os.environ.get("LAAP_VISION_API_KEY", "")

    if explicit_model and explicit_url:
        return VisionBackendConfig(
            provider="custom",
            model=explicit_model,
            base_url=explicit_url,
            api_key=explicit_key,
            available=True,
        )

    for p in _VISION_PROVIDERS:
        env_key = p["env_key"]
        if env_key and not os.environ.get(env_key):
            continue

        # ollama 需要额外探测服务是否在跑
        if p["provider"] == "ollama":
            if not _is_ollama_running(p["base_url"]):
                continue

        return VisionBackendConfig(
            provider=p["provider"],
            model=p["model"],
            base_url=p["base_url"],
            api_key=os.environ.get(env_key, ""),
            available=True,
        )

    return VisionBackendConfig(available=False)


def _is_ollama_running(base_url: str) -> bool:
    """探测 Ollama 是否运行"""
    try:
        import httpx
        root = base_url.rsplit("/v1", 1)[0]
        r = httpx.get(f"{root}/api/tags", timeout=1.5)
        return r.status_code == 200
    except Exception:
        return False


class VisionClient:
    """视觉模型客户端（OpenAI Vision 兼容格式）"""

    def __init__(self, config: Optional[VisionBackendConfig] = None):
        self.config = config or detect_vision_backend()

    @property
    def available(self) -> bool:
        return self.config.available

    async def describe(
        self,
        image_b64: str,
        prompt: str,
        image_format: str = "png",
    ) -> str:
        """让视觉模型看图片并回答问题"""
        if not self.available:
            return ""

        try:
            import httpx
        except ImportError:
            logger.error("需要 httpx")
            return ""

        url = f"{self.config.base_url.rstrip('/')}/chat/completions"

        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        payload = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "temperature": 0.1,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/{image_format};base64,{image_b64}"
                        },
                    },
                ],
            }],
        }

        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code != 200:
                    logger.error(
                        f"视觉模型失败 {resp.status_code}: {resp.text[:300]}"
                    )
                    return ""
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"视觉调用异常: {e}")
            return ""


# ══════════════════════════════════════════════════════════
#  页面元素
# ══════════════════════════════════════════════════════════

@dataclass
class PageElement:
    """页面上的一个可交互元素"""
    element_id: int              # 编号（用于动作引用）
    tag: str                     # button / a / input ...
    type: str = ""               # text / submit / checkbox ...
    text: str = ""               # 元素上的文字
    placeholder: str = ""        # 输入框提示
    aria_label: str = ""         # 无障碍标签
    href: str = ""               # 链接地址
    name: str = ""               # name 属性
    selector: str = ""           # CSS 选择器（精确点击用）
    x: float = 0.0               # 归一化坐标 0-1
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    visible: bool = True
    enabled: bool = True
    important: bool = False      # 是否显眼（大按钮等）

    def describe(self) -> str:
        """人类可读描述"""
        label = self.text or self.placeholder or self.aria_label or self.name
        if not label and self.href:
            label = self.href[:50]

        parts = [f"[{self.element_id}]"]

        if self.important:
            parts.append("*")

        parts.append(self.tag)

        if self.type:
            parts.append(f'type={self.type}')

        parts.append(f'"{label}"' if label else "(无文字)")

        if not self.enabled:
            parts.append("[禁用]")

        if not self.visible:
            parts.append("[不可见]")

        parts.append(f"@{self.x:.2f},{self.y:.2f}")

        return " ".join(parts)

    def to_dict(self) -> Dict:
        return {
            "id": self.element_id,
            "tag": self.tag,
            "type": self.type,
            "text": self.text,
            "placeholder": self.placeholder,
            "aria_label": self.aria_label,
            "href": self.href,
            "selector": self.selector,
            "x": round(self.x, 3),
            "y": round(self.y, 3),
            "w": round(self.width, 3),
            "h": round(self.height, 3),
            "visible": self.visible,
            "enabled": self.enabled,
        }


@dataclass
class PagePerception:
    """一次完整的页面感知结果"""
    url: str = ""
    title: str = ""
    text_content: str = ""                # 页面可见文字
    elements: List[PageElement] = field(default_factory=list)
    viewport: Tuple[int, int] = (0, 0)
    screenshot_path: str = ""
    screenshot_b64: str = ""
    annotated_path: str = ""              # 标注后的截图
    visual_description: str = ""          # 视觉模型看到的内容
    vision_available: bool = False
    perceive_time_ms: float = 0.0
    error: str = ""

    def to_prompt(self, max_text: int = 2000, max_elements: int = 60) -> str:
        """转成给 LLM 的可读提示词

        这是 Aris"看见"网页的方式。
        """
        lines = []

        lines.append("## 你正在看的网页")
        lines.append(f"URL: {self.url}")
        lines.append(f"标题: {self.title}")
        lines.append(f"视口: {self.viewport[0]}x{self.viewport[1]}")
        lines.append("")

        # 视觉描述（如果有）
        if self.visual_description:
            lines.append("## 视觉观察")
            lines.append(self.visual_description)
            lines.append("")

        # 页面文字
        if self.text_content:
            text = self.text_content[:max_text]
            if len(self.text_content) > max_text:
                text += f"\n...（还有 {len(self.text_content) - max_text} 字）"
            lines.append("## 页面文字内容")
            lines.append(text)
            lines.append("")

        # 可交互元素
        if self.elements:
            visible = [e for e in self.elements if e.visible and e.enabled]
            lines.append(f"## 可交互元素（共 {len(self.elements)} 个，"
                         f"可见可用 {len(visible)} 个）")
            lines.append("格式: [编号] 类型 \"文字\" @归一化坐标")
            lines.append("")

            for e in visible[:max_elements]:
                lines.append(e.describe())

            if len(visible) > max_elements:
                lines.append(f"...（还有 {len(visible) - max_elements} 个）")
            lines.append("")

        if self.error:
            lines.append(f"## 感知错误")
            lines.append(self.error)

        return "\n".join(lines)

    def find_element(self, element_id: int) -> Optional[PageElement]:
        for e in self.elements:
            if e.element_id == element_id:
                return e
        return None

    def find_by_text(self, query: str) -> Optional[PageElement]:
        """按文字找元素（模糊匹配）"""
        q = query.lower()
        for e in self.elements:
            haystack = f"{e.text} {e.placeholder} {e.aria_label} {e.href}".lower()
            if q in haystack:
                return e
        return None


# ══════════════════════════════════════════════════════════
#  DOM 提取脚本
# ══════════════════════════════════════════════════════════

_EXTRACT_JS = r"""
() => {
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    // 可交互元素选择器
    const SEL = 'a,button,input,textarea,select,[role="button"],[role="link"],' +
                '[role="tab"],[role="menuitem"],[onclick],[contenteditable="true"]';

    const nodes = Array.from(document.querySelectorAll(SEL));
    const out = [];
    let idx = 0;

    for (const el of nodes) {
        const rect = el.getBoundingClientRect();

        // 跳过零尺寸
        if (rect.width < 4 || rect.height < 4) continue;

        // 是否在视口附近（留些余量）
        const inView = rect.bottom > -200 && rect.top < vh + 200 &&
                       rect.right > -200 && rect.left < vw + 200;
        if (!inView) continue;

        const style = window.getComputedStyle(el);
        const visible = style.display !== 'none' &&
                        style.visibility !== 'hidden' &&
                        parseFloat(style.opacity || '1') > 0.1;

        // 文字
        let text = (el.innerText || el.value || '').trim().slice(0, 120);
        if (!text) {
            text = (el.getAttribute('aria-label') ||
                    el.title || '').trim().slice(0, 120);
        }

        // 构建唯一选择器
        let selector = '';
        if (el.id) {
            selector = '#' + CSS.escape(el.id);
        } else if (el.name) {
            selector = el.tagName.toLowerCase() + '[name="' + el.name + '"]';
        } else {
            // nth-of-type 路径
            const parts = [];
            let cur = el;
            let depth = 0;
            while (cur && cur.nodeType === 1 && depth < 5) {
                let part = cur.tagName.toLowerCase();
                const parent = cur.parentElement;
                if (parent) {
                    const siblings = Array.from(parent.children)
                        .filter(c => c.tagName === cur.tagName);
                    if (siblings.length > 1) {
                        part += ':nth-of-type(' +
                                (siblings.indexOf(cur) + 1) + ')';
                    }
                }
                parts.unshift(part);
                cur = cur.parentElement;
                depth++;
                if (cur && cur.id) {
                    parts.unshift('#' + CSS.escape(cur.id));
                    break;
                }
            }
            selector = parts.join(' > ');
        }

        // 重要判定：大按钮 / 显眼元素
        const area = rect.width * rect.height;
        const important = (area > 6000 && (el.tagName === 'BUTTON' ||
                           el.getAttribute('role') === 'button')) ||
                          el.tagName === 'INPUT' && el.type === 'submit';

        out.push({
            id: idx++,
            tag: el.tagName.toLowerCase(),
            type: el.type || '',
            text: text,
            placeholder: el.placeholder || '',
            aria_label: el.getAttribute('aria-label') || '',
            href: el.href || '',
            name: el.name || '',
            selector: selector,
            x: (rect.left + rect.width / 2) / vw,
            y: (rect.top + rect.height / 2) / vh,
            w: rect.width / vw,
            h: rect.height / vh,
            visible: visible,
            enabled: !el.disabled,
            important: important,
        });

        if (idx >= 200) break;
    }

    // 页面文字
    let textContent = '';
    if (document.body) {
        textContent = (document.body.innerText || '')
            .replace(/\n{3,}/g, '\n\n')
            .trim()
            .slice(0, 8000);
    }

    return {
        url: location.href,
        title: document.title,
        text: textContent,
        elements: out,
        viewport: [vw, vh],
        scrollY: window.scrollY,
        bodyHeight: document.body ? document.body.scrollHeight : vh,
    };
}
"""


# ══════════════════════════════════════════════════════════
#  截图标注
# ══════════════════════════════════════════════════════════

def annotate_screenshot(
    image_path: str,
    elements: List[PageElement],
    output_path: Optional[str] = None,
    max_labels: int = 40,
) -> Optional[str]:
    """在截图上画出元素编号方框

    这让视觉模型能说"点第 5 个框"，而不是猜坐标。
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.warning("需要 PIL 才能标注截图")
        return None

    try:
        img = Image.open(image_path).convert("RGB")
    except Exception as e:
        logger.error(f"打开截图失败: {e}")
        return None

    draw = ImageDraw.Draw(img)
    w, h = img.size

    # 字体
    font = None
    for fp in ("C:/Windows/Fonts/arialbd.ttf",
               "C:/Windows/Fonts/arial.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if Path(fp).exists():
            try:
                font = ImageFont.truetype(fp, 18)
                break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()

    visible = [e for e in elements if e.visible]
    for e in visible[:max_labels]:
        x1 = int((e.x - e.width / 2) * w)
        y1 = int((e.y - e.height / 2) * h)
        x2 = int((e.x + e.width / 2) * w)
        y2 = int((e.y + e.height / 2) * h)

        # 边框颜色：重要元素用红色，其他蓝色
        color = (255, 60, 60) if e.important else (60, 180, 255)
        draw.rectangle([x1, y1, x2, y2], outline=color, width=2)

        # 编号标签
        label = str(e.element_id)
        try:
            bbox = draw.textbbox((0, 0), label, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            tw, th = 10, 12

        # 标签背景
        draw.rectangle(
            [x1, y1 - th - 6, x1 + tw + 8, y1],
            fill=color,
        )
        draw.text((x1 + 4, y1 - th - 4), label,
                  fill=(255, 255, 255), font=font)

    if not output_path:
        fd, output_path = tempfile.mkstemp(prefix="laap_annotated_", suffix=".png")
        os.close(fd)

    img.save(output_path, "PNG")
    return output_path


# ══════════════════════════════════════════════════════════
#  浏览器感知主类
# ══════════════════════════════════════════════════════════

class BrowserPerception:
    """浏览器页面感知

    这是 Aris 的"眼睛"。她用它看网页。

    用法:
        perception = BrowserPerception(page)
        seen = await perception.perceive()

        # 她"看见"的内容
        print(seen.to_prompt())

        # 执行动作
        await perception.act({"action": "click", "element_id": 5})
    """

    def __init__(
        self,
        page: Any,
        vision: Optional[VisionClient] = None,
        enable_vision: bool = True,
        annotate: bool = True,
    ):
        self.page = page
        self.vision = vision or VisionClient()
        self.enable_vision = enable_vision and self.vision.available
        self.annotate = annotate

        self._last: Optional[PagePerception] = None
        self._tmp_files: List[str] = []

    async def perceive(
        self,
        question: str = "",
        full_page: bool = False,
    ) -> PagePerception:
        """完整感知一次

        Args:
            question: 你希望视觉模型注意的问题
            full_page: 是否整页截图（默认只截视口）
        """
        t0 = time.time()
        result = PagePerception()
        result.vision_available = self.enable_vision

        try:
            # ── 1. 结构化感知（DOM）──
            raw = await self.page.evaluate(_EXTRACT_JS)

            result.url = raw.get("url", "")
            result.title = raw.get("title", "")
            result.text_content = raw.get("text", "")
            vp = raw.get("viewport", [0, 0])
            result.viewport = (int(vp[0]), int(vp[1]))

            result.elements = [
                PageElement(
                    element_id=e["id"],
                    tag=e.get("tag", ""),
                    type=e.get("type", ""),
                    text=e.get("text", ""),
                    placeholder=e.get("placeholder", ""),
                    aria_label=e.get("aria_label", ""),
                    href=e.get("href", ""),
                    name=e.get("name", ""),
                    selector=e.get("selector", ""),
                    x=e.get("x", 0.0),
                    y=e.get("y", 0.0),
                    width=e.get("w", 0.0),
                    height=e.get("h", 0.0),
                    visible=e.get("visible", True),
                    enabled=e.get("enabled", True),
                    important=e.get("important", False),
                )
                for e in raw.get("elements", [])
            ]

            # ── 2. 截图 ──
            fd, shot = tempfile.mkstemp(prefix="laap_page_", suffix=".png")
            os.close(fd)
            self._tmp_files.append(shot)

            try:
                await self.page.screenshot(path=shot, full_page=full_page)
                result.screenshot_path = shot

                with open(shot, "rb") as f:
                    img_bytes = f.read()
                result.screenshot_b64 = base64.b64encode(img_bytes).decode()

            except Exception as e:
                logger.warning(f"截图失败: {e}")

            # ── 3. 标注截图 ──
            if self.annotate and result.screenshot_path and result.elements:
                annotated = annotate_screenshot(
                    result.screenshot_path, result.elements
                )
                if annotated:
                    result.annotated_path = annotated
                    self._tmp_files.append(annotated)

            # ── 4. 视觉理解 ──
            if self.enable_vision and result.screenshot_b64:
                result.visual_description = await self._visual_understand(
                    result, question
                )

        except Exception as e:
            result.error = f"{type(e).__name__}: {e}"
            logger.error(f"感知失败: {e}")

        result.perceive_time_ms = (time.time() - t0) * 1000
        self._last = result
        return result

    async def _visual_understand(
        self,
        perception: PagePerception,
        question: str,
    ) -> str:
        """让视觉模型描述页面"""
        # 优先用标注后的图
        image_b64 = perception.screenshot_b64
        if perception.annotated_path:
            try:
                with open(perception.annotated_path, "rb") as f:
                    image_b64 = base64.b64encode(f.read()).decode()
            except Exception:
                pass

        # 构建提示词
        element_hint = ""
        visible = [e for e in perception.elements if e.visible][:30]
        if visible:
            element_hint = "\n截图上已标注编号方框，对应这些元素：\n" + "\n".join(
                f"  [{e.element_id}] {e.tag} \"{(e.text or e.placeholder or e.aria_label)[:40]}\""
                for e in visible
            )

        prompt = f"""你在观察一个网页截图。

页面标题: {perception.title}
页面 URL: {perception.url}
{element_hint}

{f"特别关注: {question}" if question else ""}

请用简洁的中文回答：
1. 这个页面是什么？（导航页/表单/列表/详情/购物车…）
2. 页面上最显眼的内容是什么？
3. 如果用户想继续操作，最可能的下一步是什么？

不要罗列你看到的所有元素（上面已经列了），只说布局和意图层面的理解。
控制在 150 字内。"""

        return await self.vision.describe(image_b64, prompt)

    # ── 动作执行 ──────────────────────────────────

    async def act(self, action: Dict) -> Dict:
        """执行一个动作

        动作格式:
            {"action": "click", "element_id": 5}
            {"action": "click_text", "text": "登录"}
            {"action": "type", "element_id": 3, "text": "hello"}
            {"action": "press", "key": "Enter"}
            {"action": "scroll", "direction": "down"}
            {"action": "navigate", "url": "https://..."}
            {"action": "wait", "seconds": 2}
        """
        act_type = action.get("action", "")

        try:
            if act_type == "click":
                el = self._resolve_element(action)
                if not el:
                    return {"success": False, "error": "找不到元素"}

                if el.selector:
                    await self.page.click(el.selector, timeout=8000)
                else:
                    vp = self._last.viewport if self._last else (1280, 720)
                    await self.page.mouse.click(
                        el.x * vp[0], el.y * vp[1]
                    )
                return {"success": True, "clicked": el.describe()}

            elif act_type == "click_text":
                el = self._last.find_by_text(action["text"]) if self._last else None
                if not el:
                    return {"success": False, "error": f'找不到文字"{action["text"]}"'}
                if el.selector:
                    await self.page.click(el.selector, timeout=8000)
                return {"success": True, "clicked": el.describe()}

            elif act_type == "type":
                el = self._resolve_element(action)
                if not el:
                    return {"success": False, "error": "找不到输入框"}
                if el.selector:
                    await self.page.fill(el.selector, action.get("text", ""))
                return {"success": True, "typed": action.get("text", "")[:50]}

            elif act_type == "press":
                await self.page.keyboard.press(action.get("key", "Enter"))
                return {"success": True, "key": action.get("key")}

            elif act_type == "scroll":
                direction = action.get("direction", "down")
                amount = action.get("amount", 500)
                dy = amount if direction == "down" else -amount
                await self.page.mouse.wheel(0, dy)
                return {"success": True, "scrolled": direction}

            elif act_type == "navigate":
                await self.page.goto(action["url"], wait_until="domcontentloaded",
                                     timeout=30000)
                return {"success": True, "url": action["url"]}

            elif act_type == "wait":
                import asyncio
                await asyncio.sleep(action.get("seconds", 1))
                return {"success": True}

            else:
                return {"success": False, "error": f"未知动作: {act_type}"}

        except Exception as e:
            return {"success": False, "error": f"{type(e).__name__}: {e}"}

    def _resolve_element(self, action: Dict) -> Optional[PageElement]:
        """根据动作参数找到元素"""
        if not self._last:
            return None

        if "element_id" in action:
            el = self._last.find_element(int(action["element_id"]))
            if el:
                return el

        if "text" in action and "element_id" not in action:
            return self._last.find_by_text(action["text"])

        return None

    def cleanup(self):
        """清理临时文件"""
        for f in self._tmp_files:
            try:
                Path(f).unlink(missing_ok=True)
            except Exception:
                pass
        self._tmp_files.clear()

    # ── 便捷方法 ──────────────────────────────────

    async def see(self, question: str = "") -> str:
        """看一次，返回可读描述（最常用的接口）"""
        seen = await self.perceive(question=question)
        return seen.to_prompt()

    async def look_and_act(self, instruction: str) -> Dict:
        """看一眼，然后根据指令决定并执行一个动作

        这是自主循环的单步版本。
        """
        seen = await self.perceive(question=instruction)

        if not self.vision.available:
            return {
                "success": False,
                "error": "没有可用的视觉模型，无法自主决策。"
                         "请设置 SENSENOVA_API_KEY 或其他视觉模型 key。",
                "perception": seen.to_prompt(),
            }

        # 让视觉模型决定动作
        decision = await self._decide(seen, instruction)

        if decision.get("action") == "finish":
            return {
                "success": True,
                "finished": True,
                "message": decision.get("message", "完成"),
            }

        result = await self.act(decision)
        result["decision"] = decision
        return result

    async def _decide(
        self,
        seen: PagePerception,
        instruction: str,
    ) -> Dict:
        """让视觉模型决定下一个动作"""
        image_b64 = seen.screenshot_b64
        if seen.annotated_path:
            try:
                with open(seen.annotated_path, "rb") as f:
                    image_b64 = base64.b64encode(f.read()).decode()
            except Exception:
                pass

        prompt = f"""你是网页操作助手。

任务: {instruction}

{seen.to_prompt(max_text=1500, max_elements=40)}

截图上已标注编号方框。

请决定下一个动作，输出 JSON（只输出 JSON）：
{{"action": "click", "element_id": 5, "reason": "点击登录按钮"}}
{{"action": "type", "element_id": 3, "text": "hello", "reason": "输入搜索词"}}
{{"action": "press", "key": "Enter", "reason": "提交搜索"}}
{{"action": "scroll", "direction": "down", "reason": "查看更多"}}
{{"action": "wait", "seconds": 2, "reason": "等待加载"}}
{{"action": "finish", "message": "已完成：xxx", "reason": "任务达成"}}

优先用 element_id（比猜坐标准确）。如果任务已完成，用 finish。"""

        raw = await self.vision.describe(image_b64, prompt)

        # 解析 JSON
        try:
            text = raw.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                text = text[start:end + 1]
            return json.loads(text)
        except Exception as e:
            logger.warning(f"动作解析失败: {e}, raw={raw[:200]}")
            return {"action": "finish", "message": f"解析失败: {raw[:100]}"}


# ══════════════════════════════════════════════════════════
#  自主循环 — 看→想→做→再看
# ══════════════════════════════════════════════════════════

@dataclass
class BrowserTaskResult:
    """浏览器任务结果"""
    success: bool
    instruction: str
    message: str = ""
    steps: int = 0
    duration_s: float = 0.0
    history: List[Dict] = field(default_factory=list)
    final_page: str = ""
    error: str = ""


class BrowserAgentLoop:
    """浏览器自主循环

    看 → 决定 → 执行 → 再看 → ...直到完成或失败。

    关键设计:
    - **每步都重新感知**，不假设动作成功了
    - 连续 3 步无进展则中止（防死循环）
    - 最多 20 步
    """

    def __init__(
        self,
        perception: BrowserPerception,
        max_steps: int = 20,
        max_stall: int = 3,
    ):
        self.perception = perception
        self.max_steps = max_steps
        self.max_stall = max_stall

    async def run(self, instruction: str) -> BrowserTaskResult:
        """执行任务"""
        t0 = time.time()
        history: List[Dict] = []
        stall = 0
        last_signature = ""

        for step in range(1, self.max_steps + 1):
            logger.info(f"[浏览器任务] 步骤 {step}: {instruction}")

            # 感知
            seen = await self.perception.perceive(question=instruction)

            if seen.error:
                return BrowserTaskResult(
                    success=False,
                    instruction=instruction,
                    error=f"感知失败: {seen.error}",
                    steps=step,
                    duration_s=time.time() - t0,
                    history=history,
                )

            # 检测停滞（页面签名没变）
            signature = f"{seen.url}|{seen.title}|{len(seen.elements)}|{seen.text_content[:200]}"
            if signature == last_signature:
                stall += 1
                if stall >= self.max_stall:
                    return BrowserTaskResult(
                        success=False,
                        instruction=instruction,
                        error=f"连续 {stall} 步无进展，可能卡住了",
                        steps=step,
                        duration_s=time.time() - t0,
                        history=history,
                        final_page=seen.to_prompt(),
                    )
            else:
                stall = 0
                last_signature = signature

            # 决定
            if not self.perception.vision.available:
                return BrowserTaskResult(
                    success=False,
                    instruction=instruction,
                    error="没有可用的视觉模型",
                    steps=step,
                    duration_s=time.time() - t0,
                    history=history,
                    final_page=seen.to_prompt(),
                )

            decision = await self.perception._decide(seen, instruction)
            history.append({
                "step": step,
                "decision": decision,
                "url": seen.url,
            })

            # 完成？
            if decision.get("action") == "finish":
                return BrowserTaskResult(
                    success=True,
                    instruction=instruction,
                    message=decision.get("message", "完成"),
                    steps=step,
                    duration_s=time.time() - t0,
                    history=history,
                    final_page=seen.to_prompt(),
                )

            # 执行
            result = await self.perception.act(decision)
            logger.info(f"  动作: {decision.get('action')} -> {result}")

            if not result.get("success"):
                stall += 1
                logger.warning(f"  动作失败: {result.get('error')}")

            # 等页面稳定
            import asyncio
            await asyncio.sleep(0.8)

        return BrowserTaskResult(
            success=False,
            instruction=instruction,
            error=f"达到最大步骤 {self.max_steps}",
            steps=self.max_steps,
            duration_s=time.time() - t0,
            history=history,
        )


# ══════════════════════════════════════════════════════════
#  全局视觉后端信息
# ══════════════════════════════════════════════════════════

def get_vision_status() -> Dict:
    """当前视觉能力状态"""
    cfg = detect_vision_backend()
    return {
        "available": cfg.available,
        "provider": cfg.provider or None,
        "model": cfg.model or None,
        "base_url": cfg.base_url or None,
        "hint": (
            "视觉模型就绪"
            if cfg.available
            else "未检测到视觉模型。设置以下任一环境变量："
                 "SENSENOVA_API_KEY / OPENAI_API_KEY / DASHSCOPE_API_KEY"
        ),
    }