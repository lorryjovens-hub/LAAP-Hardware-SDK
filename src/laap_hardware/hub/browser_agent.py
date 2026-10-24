"""浏览器语音代理 — 让小智硬件能"看"网页、"点"网页

## 为什么需要它

VoiceComputerAgent 只操作桌面 GUI（pyautogui + UIA）：
  · 网页里的按钮 UIA 拿不到（浏览器内容不走无障碍树）
  · 它没有 playwright 页面概念，根本无法"看"网页内容

BrowserVoiceAgent 复用 VoiceIntentParser 的意图解析，但把执行
切到浏览器层（DOM 精确 selector + 截图 + 视觉确认）：

  小智说「打开 www.laap.cn 看看有什么」
    → navigate → perceive（DOM+截图+视觉）→ 返回可读描述

  小智说「点击页面上的 进入 Studio」
    → DOM 找文字 → 点击 → 重截图确认变了

## 用法

    from laaper.hub.browser_agent import BrowserVoiceAgent

    agent = BrowserVoiceAgent()
    r = await agent.handle("打开 www.laap.cn 看看有什么")
    print(r.reply)   # 描述网页内容

    r2 = await agent.handle("点击进入 Studio")
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laaper.hub.browser_agent")


@dataclass
class BrowserActionResult:
    """浏览器语音动作结果"""
    success: bool
    instruction: str = ""
    reply: str = ""                     # 要播报/显示的话
    intent: Optional[Dict] = None
    action_detail: Optional[Dict] = None
    duration_ms: float = 0.0
    page_changed: bool = False


class BrowserVoiceAgent:
    """浏览器语音代理 — 语音指令 → 浏览器操作

    维护一个常驻浏览器（延迟启动），处理：
      navigate / see / click_text / scroll / type / press / finish
    """

    def __init__(self, headless: bool = True, viewport: tuple = (1280, 800)):
        self.headless = headless
        self.viewport = viewport

        self._pw = None
        self._browser = None
        self._page = None
        self._perception = None

        self.stats = {
            "handled": 0,
            "navigates": 0,
            "clicks": 0,
            "sees": 0,
            "failures": 0,
        }

    # ── 浏览器生命周期 ──────────────────────────────────

    async def ensure_browser(self) -> bool:
        """启动常驻浏览器（幂等）"""
        if self._page is not None:
            return True
        try:
            from playwright.async_api import async_playwright
            from laap.tools.browser_perception import BrowserPerception

            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=self.headless,
            )
            self._page = await self._browser.new_page(
                viewport={"width": self.viewport[0], "height": self.viewport[1]},
            )
            self._perception = BrowserPerception(self._page, annotate=True)
            logger.info(f"浏览器就绪 ({self.viewport[0]}x{self.viewport[1]})")
            return True
        except Exception as e:
            logger.error(f"浏览器启动失败: {e}")
            self.stats["failures"] += 1
            return False

    async def close(self):
        """关闭浏览器"""
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._browser = None
        self._page = None
        self._perception = None
        self._pw = None

    @property
    def ready(self) -> bool:
        return self._page is not None

    @property
    def current_url(self) -> str:
        try:
            return self._page.url if self._page else ""
        except Exception:
            return ""

    # ── 主入口：语音指令 ──────────────────────────────────

    async def handle(self, text: str) -> BrowserActionResult:
        """处理一句语音指令（网页上下文）"""
        t0 = time.time()
        self.stats["handled"] += 1
        text = text.strip()

        if not await self.ensure_browser():
            return BrowserActionResult(
                success=False,
                instruction=text,
                reply="浏览器启动失败了，我先看不了网页。",
                duration_ms=(time.time() - t0) * 1000,
            )

        # ── 意图解析（复用 voice_computer 的规则层）──
        from laaper.hub.computer_use import VoiceIntentParser

        intent = VoiceIntentParser.parse(text)

        # 搜索（优先于导航：搜得越多越要精确进入搜索框）
        if self._is_search_request(text):
            result = await self._do_search(text)
            result.duration_ms = (time.time() - t0) * 1000
            return result

        # 打开网页
        if self._is_navigate_request(text):
            result = await self._do_navigate(text)
            result.duration_ms = (time.time() - t0) * 1000
            return result

        # 看/描述
        if self._is_see_request(text):
            result = await self._do_see(text)
            result.duration_ms = (time.time() - t0) * 1000
            return result

        # 规则化动作（点/滚/输/按/搜）
        if intent:
            result = await self._run_intent(intent, text)
            result.duration_ms = (time.time() - t0) * 1000
            return result

        # 兜底：把整句当自然语言，走一次多步（LLM）——留给上层
        return BrowserActionResult(
            success=False,
            instruction=text,
            reply="这句我没能拆成网页动作（可以用：打开xx、看看页面、点击xx、往下翻、搜索xx）。",
            duration_ms=(time.time() - t0) * 1000,
        )

    # ── 意图判定 ──────────────────────────────────

    def _is_search_request(self, text: str) -> bool:
        """搜索意图：搜 X / 查一下 X / 找找 X / 搜一下开源的 X"""
        # 必须是"动词 + 查询词"的结构，不能是"搜索框"这种名词
        leads = ("搜索", "搜一下", "搜一搜", "帮我搜", "查一下", "查一查",
                 "帮我查", "找一下", "找一找", "帮我找", "找找")
        for lead in leads:
            if lead in text:
                # 去掉引导词后还有实质内容（至少 2 个字符且不是"下/看"等）
                rest = text.split(lead, 1)[1].strip(" ，。！？吧的")
                if len(rest) >= 2:
                    return True
        return False

    def _is_navigate_request(self, text: str) -> bool:
        t = text.lower()
        # 含 http / www
        if ("http" in t or "www." in t) and any(
            k in text for k in ("打开", "访问", "去", "上", "进")
        ):
            return True
        if any(k in text for k in ("打开网页", "打开网站")):
            return True
        # "打开 bilibili"、"上一下知乎" 这类（有名站点关键词 + 打开/上）
        if any(k in text for k in ("打开", "访问", "去", "上一下", "上")) and (
            "网" in text or "站" in text or "页" in text
        ):
            return True
        # 能提取出网址且开头是"打开/去/进" → 导航
        url = self._extract_url(text)
        if url and any(text.startswith(k) for k in ("打开", "去", "进", "访问")):
            return True
        return False

    def _is_see_request(self, text: str) -> bool:
        return any(k in text for k in (
            "看看有什么", "看看", "看下", "看一", "描述一下", "有什么",
            "这个页面", "网页上", "页面上", "看到什么",
        ))

    def _extract_url(self, text: str) -> str:
        import re
        m = re.search(r"https?://[^\s，,。]+", text)
        if m:
            return m.group()
        # "打开 xxx.com" / "打开 bilibili"
        known = {
            "bilibili": "https://www.bilibili.com",
            "哔哩哔哩": "https://www.bilibili.com",
            "知乎": "https://www.zhihu.com",
            "百度": "https://www.baidu.com",
            "淘宝": "https://www.taobao.com",
            "京东": "https://www.jd.com",
            "抖音": "https://www.douyin.com",
            "微博": "https://weibo.com",
            "github": "https://github.com",
            "laap": "https://www.laap.cn",
            "小红书": "https://www.xiaohongshu.com",
        }
        for kw, url in known.items():
            if kw in text:
                return url
        # 提取裸域名 xxx.com / xxx.cn
        m = re.search(r"([a-zA-Z0-9-]+\.(?:com|cn|net|org|io|me|cc)[a-zA-Z0-9/._-]*)", text)
        if m:
            return "https://" + m.group(1)
        return ""

    # ── 动作实现 ──────────────────────────────────

    async def _do_search(self, text: str) -> BrowserActionResult:
        """搜索：选引擎 → 打开结果页 → 感知并摘录结果"""
        self.stats["navigates"] += 1
        query = self._extract_query(text)
        if not query:
            return BrowserActionResult(
                success=False, instruction=text,
                reply="想搜什么？可以说：搜索 LAAP 开源 / 查一下天气。",
            )

        # 按内容选引擎
        tl = query.lower()
        if any(k in tl for k in ("github", "开源", "代码", "库", "repo", "仓库")):
            url = "https://github.com/search?q=" + self._enc(query)
            engine = "GitHub"
        elif any(k in tl for k in ("论文", "paper", "arxiv", "文献")):
            url = "https://arxiv.org/search/?query=" + self._enc(query)
            engine = "arXiv"
        else:
            url = "https://www.bing.com/search?q=" + self._enc(query)
            engine = "Bing"

        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(2.0)   # 给结果渲染时间

            # 感知（视觉 + DOM）
            seen = await self._perception.perceive(
                question="这是搜索结果页，主要结果是什么？"
            )
            self.stats["sees"] += 1

            # 摘录结果标题（通用：取正文链接文字中的短文本）
            titles = await self._extract_result_titles(limit=5)

            reply = f"在{engine}搜「{query}」"
            if seen.visual_description:
                desc = seen.visual_description.strip().replace("\n", " ")
                reply += "，我看到：" + desc[:120]

            if titles:
                reply += "。结果："
                reply += "；".join(titles)

            return BrowserActionResult(
                success=True,
                instruction=text,
                reply=reply,
                intent={"action": "search", "query": query, "engine": engine},
                action_detail={
                    "query": query, "engine": engine,
                    "url": self._page.url, "titles": titles,
                },
            )
        except Exception as e:
            self.stats["failures"] += 1
            return BrowserActionResult(
                success=False, instruction=text,
                reply=f"搜索失败了：{e}",
            )

    async def _extract_result_titles(self, limit: int = 5) -> list:
        """从结果页 DOM 提取结果标题（通用的短链接文字）"""
        try:
            js = """() => {
                const out = [];
                const seen = new Set();
                for (const a of document.querySelectorAll('a')) {
                    const t = (a.innerText || '').trim();
                    if (t.length >= 6 && t.length <= 80 && !seen.has(t)) {
                        // 过滤导航/按钮类
                        if (/^(首页|登录|注册|搜索|设置|更多|Sign|Log|Home|Menu)/i.test(t)) continue;
                        seen.add(t);
                        out.push(t);
                        if (out.length >= 8) break;
                    }
                }
                return out;
            }"""
            items = await self._page.evaluate(js)
            return items[:limit]
        except Exception:
            return []

    def _extract_query(self, text: str) -> str:
        """从「搜索 XX / 查一下 YY」里提取查询词"""
        leads = ("搜索", "搜一下", "搜一搜", "帮我搜", "查一下", "查一查",
                 "帮我查", "找一下", "找一找", "帮我找", "找找")
        q = text
        for lead in leads:
            if lead in q:
                q = q.split(lead, 1)[1]
                break
        q = q.strip(" ，。！？吧的嗯好")
        # 留 1-3 个词（中文搜索词常常整句，但去掉多余语气）
        return q[:60]

    @staticmethod
    def _enc(query: str) -> str:
        from urllib.parse import quote
        return quote(query)

    async def _do_navigate(self, text: str) -> BrowserActionResult:
        url = self._extract_url(text)
        if not url:
            # 有页面则回退描述当前页面，而不是报错
            if self._page:
                return await self._do_see(text)
            return BrowserActionResult(
                success=False, instruction=text,
                reply="没听出要打开哪个网址（可以说：打开 bilibili / 打开 www.xxx.com）。",
            )
        self.stats["navigates"] += 1
        try:
            before = self._page.url
            await self._page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(1.5)

            title = await self._page.title()

            # 感知（DOM + 截图 + 视觉）→ 能"看到"网页
            seen = await self._perception.perceive(question="这个页面是干什么的？")
            self.stats["sees"] += 1

            reply = f"打开了「{title}」。"
            if seen.visual_description:
                # 视觉描述精炼
                desc = seen.visual_description.strip().replace("\n", " ")
                reply += " 我看到：" + desc[:150]

            return BrowserActionResult(
                success=True,
                instruction=text,
                reply=reply,
                intent={"action": "navigate", "url": url},
                action_detail={
                    "url": url,
                    "title": title,
                    "elements": len(seen.elements),
                    "visual": seen.visual_description[:200],
                },
                page_changed=before != self._page.url,
            )
        except Exception as e:
            logger.error(f"打开网页失败 {url}: {e}")
            self.stats["failures"] += 1
            return BrowserActionResult(
                success=False, instruction=text,
                reply=f"打开网页失败了：{e}",
            )

    async def _do_see(self, text: str) -> BrowserActionResult:
        if not self._page:
            return BrowserActionResult(
                success=False, instruction=text, reply="还没有打开网页。",
            )
        self.stats["sees"] += 1
        try:
            seen = await self._perception.perceive(
                question="这个页面主要是什么？有什么可以点的？"
            )
            title = await self._page.title()

            parts = [f"页面「{title}」，地址 {self._page.url}"]

            if seen.visual_description:
                parts.append(seen.visual_description.strip().replace("\n", " ")[:200])

            # 可交互元素摘要
            clickables = [
                e for e in seen.elements if e.visible and e.enabled and (
                    e.tag in ("a", "button") or (e.text and len(e.text) < 25)
                )
            ][:12]
            if clickables:
                labels = [c.text or c.aria_label or c.tag for c in clickables]
                parts.append("可以点：")
                parts.append("、".join(labels[:10]))
            else:
                parts.append("页面暂时没有明显的可点按钮。")

            return BrowserActionResult(
                success=True,
                instruction=text,
                reply="。".join(parts),
                intent={"action": "see"},
                action_detail={
                    "url": self._page.url, "title": title,
                    "elements": len(seen.elements),
                },
            )
        except Exception as e:
            self.stats["failures"] += 1
            return BrowserActionResult(
                success=False, instruction=text, reply=f"看网页失败了：{e}",
            )

    async def _run_intent(
        self, intent: Any, text: str,
    ) -> BrowserActionResult:
        """执行一个已解析的意图（浏览器版）"""
        action = intent.action
        params = intent.params

        try:
            if action == "click_text":
                return await self._do_click_text(params.get("text", ""), text)

            if action == "scroll":
                pixels = params.get("pixels", 480)
                await self._page.mouse.wheel(0, pixels)
                await asyncio.sleep(0.3)
                return BrowserActionResult(
                    success=True, instruction=text,
                    reply=f"往下滚了。",
                    intent={"action": "scroll"},
                )

            if action == "type":
                await self._page.keyboard.type(params.get("text", ""), delay=20)
                return BrowserActionResult(
                    success=True, instruction=text,
                    reply=f"输入了「{params.get('text', '')[:20]}」。",
                    intent={"action": "type"},
                )

            if action == "press":
                key = params.get("key", "enter")
                await self._page.keyboard.press(key)
                await asyncio.sleep(0.8)
                return BrowserActionResult(
                    success=True, instruction=text,
                    reply="按了回车。",
                    intent={"action": "press", "key": key},
                )

            if action == "hotkey":
                keys = params.get("keys", [])
                await self._page.keyboard.press("+".join(keys))
                return BrowserActionResult(
                    success=True, instruction=text,
                    reply=f"按了 {'+'.join(keys)}。",
                    intent={"action": "hotkey"},
                )

            return BrowserActionResult(
                success=False, instruction=text,
                reply=f"网页上做不了「{action}」。",
            )

        except Exception as e:
            self.stats["failures"] += 1
            return BrowserActionResult(
                success=False, instruction=text, reply=f"操作失败：{e}",
            )

    async def _do_click_text(self, target: str, original: str) -> BrowserActionResult:
        """DOM 精确点击 + 截图确认"""
        if not target:
            return BrowserActionResult(
                success=False, instruction=original, reply="点哪个？",
            )
        self.stats["clicks"] += 1
        try:
            # 先感知（DOM 拿元素）
            seen = await self._perception.perceive()
            el = seen.find_by_text(target)

            if not el:
                # 试试视觉定位兜底
                hint = f"截图中找到「{target}」的位置并告诉我归一化坐标"
                visual = await self._perception._visual_understand(seen, hint)
                logger.info(f"视觉定位兜底: {visual}")

                return BrowserActionResult(
                    success=False, instruction=original,
                    reply=f"页面上没找到「{target}」。{visual[:100] if visual else ''}",
                )

            # 点击前截图签名
            before = await self._page.screenshot()

            r = await self._perception.act(
                {"action": "click", "element_id": el.element_id}
            )
            await asyncio.sleep(1.0)

            # 点击后确认
            after = await self._page.screenshot()
            changed = before != after
            if not changed:
                # 再等一下（动态页面）
                await asyncio.sleep(1.0)
                after2 = await self._page.screenshot()
                changed = before != after2

            label = (el.text or el.aria_label or el.tag)
            reply = f"点了「{label}」。"
            if changed:
                reply += " 页面动了一下。"
            else:
                reply += " 页面好像没变化（可能已经在这页或按钮没响应）。"

            return BrowserActionResult(
                success=True,
                instruction=original,
                reply=reply,
                intent={"action": "click_text", "text": target},
                action_detail={
                    "element": el.to_dict(),
                    "page_changed": changed,
                },
                page_changed=changed,
            )

        except Exception as e:
            self.stats["failures"] += 1
            return BrowserActionResult(
                success=False, instruction=original, reply=f"点击失败：{e}",
            )

    # ── 状态 ──────────────────────────────────

    def get_status(self) -> Dict:
        return {
            "ready": self.ready,
            "url": self.current_url,
            "headless": self.headless,
            **self.stats,
        }

    async def describe_current(self) -> str:
        """当前页面一句话描述（给上层/日志）"""
        if not self._page:
            return "（浏览器未启动）"
        try:
            seen = await self._perception.perceive()
            return (
                f"{self._page.url} | {await self._page.title()} | "
                f"{len(seen.elements)} 元素 | {seen.visual_description[:80] if seen.visual_description else ''}"
            )
        except Exception as e:
            return f"（描述失败: {e}）"


# ══════════════════════════════════════════════════════════
#  注册到守护节点
# ══════════════════════════════════════════════════════════

def register_browser_handlers(hub: Any, pc_node: str = "pc-hub",
                              agent: Optional[BrowserVoiceAgent] = None):
    """把浏览器能力挂到守护节点（hub.transport）"""
    agent = agent or BrowserVoiceAgent()

    async def browser_command(params: Dict) -> Dict:
        text = params.get("text") or params.get("instruction", "")
        r = await agent.handle(text)
        return {
            "success": r.success,
            "data": {
                "reply": r.reply,
                "url": agent.current_url,
                "intent": r.intent,
                "action": r.action_detail,
            },
            "error": "" if r.success else r.reply,
        }

    hub.transport.register_handler(pc_node, "browser_command", browser_command)
    hub.transport.register_handler(pc_node, "browser", browser_command)

    async def browser_see(params: Dict) -> Dict:
        r = await agent._do_see(params.get("question", "看看页面"))
        return {"success": r.success, "data": {"reply": r.reply}}

    hub.transport.register_handler(pc_node, "browser_see", browser_see)

    async def browser_open(params: Dict) -> Dict:
        r = await agent._do_navigate(params.get("url", ""))
        return {"success": r.success, "data": {"reply": r.reply}}

    hub.transport.register_handler(pc_node, "browser_open", browser_open)

    async def browser_click(params: Dict) -> Dict:
        r = await agent._do_click_text(params.get("text", ""), "点击")
        return {"success": r.success, "data": {"reply": r.reply}}

    hub.transport.register_handler(pc_node, "browser_click", browser_click)

    return {
        "agent": agent,
        "handlers": ["browser_command", "browser", "browser_see",
                     "browser_open", "browser_click"],
    }