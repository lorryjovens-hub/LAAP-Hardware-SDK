"""Computer Use — 让 Aris 真正能操作电脑

## 为什么不能直接用 pyautogui 了事

原生 pyautogui 有四个硬伤，在"语音控制电脑"场景下全部会暴露：

### 硬伤 1：中文输入不工作
    pyautogui.typewrite("你好")   → 什么都不发生
    因为 typewrite 只发 ASCII 键码，中文没有对应键码。

### 硬伤 2：滚轮是离散的
    pyautogui.scroll(1)  是一格（Windows 约 3 行）
    用户说"往下翻一点"和"翻到底"，这是连续量，需要换算 + 闭环。

### 硬伤 3：没有窗口概念
    用户说"往下翻"，翻哪个窗口？当前焦点窗口。
    但执行前得确认焦点在哪，否则可能翻错地方。

### 硬伤 4：没有验证
    点完不知道成功没有。猜错了也不知道。

## 本模块怎么解决

| 硬伤 | 方案 |
|------|------|
| 中文输入 | 剪贴板 + Ctrl+V（pyperclip），或 SendInput Unicode |
| 滚轮连续量 | 像素为单位 + **截图对比闭环**（翻到底真的翻到底） |
| 窗口概念 | pygetwindow 管理焦点，动作前报告当前窗口 |
| 没有验证 | 每个动作后截图，比较前后差异 |

## 核心设计：滚轮是闭环控制

"翻到底"不是发一个 scroll 命令就完了，是：

    截图 → 滚动 → 截图 → 比较
                ↑              ↓
                └── 没到底，继续 ──┘

直到：内容不再变化 / 到达边界 / 超过最大次数

这样用户说"翻到底"，它就真的到底了。
"""
from __future__ import annotations

import ctypes
import hashlib
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("laaper.hub.computer")


# ══════════════════════════════════════════════════════════
#  动作类型
# ══════════════════════════════════════════════════════════

class CUAction(str, Enum):
    """电脑动作"""
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    MOVE = "move"
    DRAG = "drag"
    SCROLL = "scroll"
    SCROLL_UNTIL = "scroll_until"
    TYPE = "type"
    PRESS = "press"
    HOTKEY = "hotkey"
    FOCUS_WINDOW = "focus_window"
    LAUNCH_APP = "launch_app"
    SCREENSHOT = "screenshot"
    WAIT = "wait"
    FINISH = "finish"


@dataclass
class CUActionResult:
    """动作结果"""
    success: bool
    action: str
    message: str = ""
    error: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    screen_changed: bool = False


# ══════════════════════════════════════════════════════════
#  DPI 处理
# ══════════════════════════════════════════════════════════

def enable_dpi_awareness():
    """开启 DPI 感知

    不加这个，高分屏上鼠标坐标会偏。
    """
    try:
        # Windows 8.1+
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


enable_dpi_awareness()


def get_screen_size() -> Tuple[int, int]:
    """获取真实屏幕尺寸（物理像素）"""
    try:
        user32 = ctypes.windll.user32
        return (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    except Exception:
        try:
            import pyautogui
            return pyautogui.size()
        except Exception:
            return (1920, 1080)


# ══════════════════════════════════════════════════════════
#  Computer Use 主体
# ══════════════════════════════════════════════════════════

class ComputerUse:
    """电脑操作器

    用法:
        cu = ComputerUse()

        cu.click(960, 540)
        cu.scroll_pixels(-600)               # 向下滚 600 像素
        cu.scroll_until("bottom")            # 翻到底（闭环）
        cu.type_text("你好世界")              # 中文也没问题
        cu.hotkey("ctrl", "c")

        shot = cu.screenshot()               # bytes
    """

    # 一次滚轮格数对应的像素（Windows 默认 3 行 ≈ 60px，按需调）
    PIXELS_PER_NOTCH = 60

    def __init__(
        self,
        safe_mode: bool = True,
        move_duration: float = 0.15,
    ):
        self.safe_mode = safe_mode
        self.move_duration = move_duration

        self._pyautogui = None
        self._screen_size = get_screen_size()

        # 统计
        self.stats = {
            "clicks": 0,
            "scrolls": 0,
            "keystrokes": 0,
            "types": 0,
            "failures": 0,
        }

        # 危险区域（屏幕四角，防误触）
        self._forbidden_zones: List[Tuple[int, int, int, int]] = []

        # 当前操作目标窗口（hwnd）
        self._target_window: Optional[int] = None

        # ScrollPattern 是否可信（探测后缓存）
        self._pattern_valid: Optional[bool] = None

    # ── 惰性初始化 pyautogui ──────────────────────────────────

    @property
    def pag(self):
        if self._pyautogui is None:
            try:
                import pyautogui
                pyautogui.FAILSAFE = True       # 鼠标到角落可紧急中断
                pyautogui.PAUSE = 0.06
                self._pyautogui = pyautogui
            except ImportError:
                logger.error(
                    "缺少 pyautogui。安装: pip install pyautogui"
                )
                raise
        return self._pyautogui

    @property
    def screen_size(self) -> Tuple[int, int]:
        return self._screen_size

    # ── 鼠标 ──────────────────────────────────

    def move(self, x: int, y: int) -> CUActionResult:
        """移动鼠标"""
        t0 = time.time()
        try:
            self.pag.moveTo(x, y, duration=self.move_duration)
            return CUActionResult(
                success=True,
                action=CUAction.MOVE,
                message=f"移动到 ({x}, {y})",
                duration_ms=(time.time() - t0) * 1000,
            )
        except Exception as e:
            self.stats["failures"] += 1
            return CUActionResult(
                success=False, action=CUAction.MOVE, error=str(e)
            )

    def click(
        self,
        x: Optional[int] = None,
        y: Optional[int] = None,
        button: str = "left",
        clicks: int = 1,
        verify: bool = False,
    ) -> CUActionResult:
        """点击"""
        t0 = time.time()
        before = self._screen_hash() if verify else ""

        try:
            if x is not None and y is not None:
                if self.safe_mode and self._in_forbidden(x, y):
                    return CUActionResult(
                        success=False,
                        action=CUAction.CLICK,
                        error=f"({x},{y}) 在保护区，拒绝点击",
                    )
                self.pag.click(x, y, button=button, clicks=clicks)
            else:
                # 点当前位置
                self.pag.click(button=button, clicks=clicks)

            self.stats["clicks"] += 1

            changed = False
            if verify:
                time.sleep(0.4)
                changed = self._screen_hash() != before

            return CUActionResult(
                success=True,
                action=CUAction.CLICK,
                message=f"点击 ({x}, {y}) {button} x{clicks}",
                data={"x": x, "y": y, "button": button},
                duration_ms=(time.time() - t0) * 1000,
                screen_changed=changed,
            )
        except Exception as e:
            self.stats["failures"] += 1
            return CUActionResult(
                success=False, action=CUAction.CLICK, error=str(e)
            )

    def click_normalized(self, nx: float, ny: float, **kw) -> CUActionResult:
        """按归一化坐标点击"""
        w, h = self._screen_size
        return self.click(int(nx * w), int(ny * h), **kw)

    def double_click(self, x: int, y: int) -> CUActionResult:
        return self.click(x, y, clicks=2)

    def right_click(self, x: int, y: int) -> CUActionResult:
        return self.click(x, y, button="right")

    def drag(
        self,
        x1: int, y1: int,
        x2: int, y2: int,
        duration: float = 0.5,
    ) -> CUActionResult:
        """拖拽"""
        t0 = time.time()
        try:
            self.pag.moveTo(x1, y1, duration=0.1)
            self.pag.dragTo(x2, y2, duration=duration)
            return CUActionResult(
                success=True,
                action=CUAction.DRAG,
                message=f"从 ({x1},{y1}) 拖到 ({x2},{y2})",
                duration_ms=(time.time() - t0) * 1000,
            )
        except Exception as e:
            self.stats["failures"] += 1
            return CUActionResult(
                success=False, action=CUAction.DRAG, error=str(e)
            )

    # ── 滚轮（核心） ──────────────────────────────────

    def scroll_notches(self, notches: int, ensure_focus: bool = True) -> CUActionResult:
        """滚轮滚动（正数向上，负数向下）

        ## 关键坑

        pyautogui.scroll() 把滚轮事件发给**鼠标当前位置**。
        鼠标停在屏幕角落、标题栏、或侧边栏上，页面根本不会滚。

        所以滚动前必须把鼠标移到可滚动区域的中央。
        这是个大坑：不移动鼠标的话，你以为滚了，其实什么都没动。
        """
        t0 = time.time()
        try:
            if ensure_focus:
                self._ensure_scroll_target()

            self.pag.scroll(notches)
            self.stats["scrolls"] += 1
            return CUActionResult(
                success=True,
                action=CUAction.SCROLL,
                message=f"滚动 {notches} 格",
                data={"notches": notches},
                duration_ms=(time.time() - t0) * 1000,
            )
        except Exception as e:
            self.stats["failures"] += 1
            return CUActionResult(
                success=False, action=CUAction.SCROLL, error=str(e)
            )

    def _ensure_scroll_target(self):
        """把鼠标移到可滚动区域的中央

        ## 为什么这步少不了

        Windows 把滚轮事件发给**鼠标下面的窗口**。
        鼠标停在别处，滚动就无效。

        ## 顺序

        1. 如果有指定目标窗口（focus_window 设过），用它的矩形
        2. 否则用前台窗口
        3. 都拿不到用屏幕中心
        """
        w, h = self._screen_size
        target = None

        # 1. 优先用显式指定的目标窗口
        target_rect = None
        if self._target_window:
            target_rect = self._get_window_rect(self._target_window)

        # 2. 退到前台窗口
        if not target_rect:
            try:
                import uiautomation as uia
                root = uia.GetForegroundControl()
                if root:
                    rect = root.BoundingRectangle
                    if rect and rect.width() > 200 and rect.height() > 200:
                        target_rect = (
                            rect.left, rect.top,
                            rect.width(), rect.height(),
                        )
            except Exception:
                pass

        if target_rect:
            left, top, ww, wh = target_rect
            # 取窗口内容区中心偏上（避开底部状态栏和标题栏）
            target = (left + ww // 2, top + int(wh * 0.45))

        if not target:
            target = (w // 2, int(h * 0.45))

        # 3. 移动鼠标
        try:
            cx, cy = self.pag.position()
            if abs(cx - target[0]) > 15 or abs(cy - target[1]) > 15:
                self.pag.moveTo(target[0], target[1], duration=0.04)
        except Exception:
            pass

        time.sleep(0.04)

    def _get_window_rect(self, hwnd: int) -> Optional[Tuple[int, int, int, int]]:
        """拿窗口矩形 (left, top, width, height)"""
        try:
            import ctypes
            from ctypes import wintypes

            rect = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(
                wintypes.HWND(hwnd), ctypes.byref(rect)
            )
            ww = rect.right - rect.left
            hh = rect.bottom - rect.top
            if ww > 100 and hh > 100:
                return (rect.left, rect.top, ww, hh)
        except Exception:
            pass
        return None

    def _is_window_visible_at(self, hwnd: int, x: int, y: int) -> bool:
        """检查某个坐标上真的是目标窗口

        ## 为什么必须查这个

        SetForegroundWindow 会报成功，但它只管"逻辑前台"，
        不代表窗口真的画在上面。

        Windows 前台锁、全屏应用、被别的窗口遮住都会导致：
          API 说成功 → 实际你看不到 → 截图截到别的窗口

        用 WindowFromPoint 查那个坐标上到底是哪个窗口，才是真相。
        """
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32

            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

            pt = POINT(int(x), int(y))
            hwnd_at_point = user32.WindowFromPoint(pt)

            if not hwnd_at_point:
                return False

            # 可能是子窗口，往上找根窗口
            root = user32.GetAncestor(wintypes.HWND(hwnd_at_point), 2)  # GA_ROOT
            if root:
                hwnd_at_point = root

            return hwnd_at_point == hwnd

        except Exception as e:
            logger.debug(f"可见性检查失败: {e}")
            return True     # 查不了就不阻挠

    def _ensure_visible(self, hwnd: int) -> bool:
        """确保窗口真的可见

        Returns:
            True = 确认可见；False = 看不到（可能被遮住）
        """
        rect = self._get_window_rect(hwnd)
        if not rect:
            return False

        left, top, ww, wh = rect

        # 多个检查点：中心 + 偏上 + 偏下
        # 单点可能落在子控件上，多点更可靠
        points = [
            (left + ww // 2, top + int(wh * 0.45)),
            (left + ww // 2, top + int(wh * 0.25)),
            (left + int(ww * 0.3), top + int(wh * 0.6)),
        ]

        for cx, cy in points:
            if self._is_window_visible_at(hwnd, cx, cy):
                return True

        return False

    def _get_window_rect(self, hwnd: int) -> Optional[Tuple[int, int, int, int]]:
        """拿窗口矩形 (left, top, width, height)"""
        try:
            import ctypes
            from ctypes import wintypes

            rect = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(
                wintypes.HWND(hwnd), ctypes.byref(rect)
            )
            ww = rect.right - rect.left
            hh = rect.bottom - rect.top
            if ww > 100 and hh > 100:
                return (rect.left, rect.top, ww, hh)
        except Exception:
            pass
        return None

    def _force_focus(self, hwnd: int) -> bool:
        """强制把窗口拿到前台

        ## 为什么 pygetwindow.activate() 不够

        Windows 有前台锁（foreground lock）：不允许后台程序
        随意抢焦点，防止弹窗骚扰。pygetwindow 的 activate()
        会失败但不报错，你以为成功了，其实窗口还在后面。

        ## 破解方式

        1. 先模拟一下 ALT 键（解除前台锁限制，经典技巧）
        2. SetForegroundWindow
        3. 配合 BringWindowToTop 和 SetWindowPos 置顶
        4. 如果还不行，用 AttachThreadInput 把线程输入队列挂到前台
        """
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            # 最小化的先还原
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)      # SW_RESTORE

            # 已经在前台就不折腾
            fg = user32.GetForegroundWindow()
            if fg == hwnd:
                return True

            # 技巧 1：模拟 ALT 键，解除前台锁
            VK_MENU = 0x12
            KEYEVENTF_KEYUP = 0x0002
            user32.keybd_event(VK_MENU, 0, 0, 0)
            user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)

            # 尝试直接设置
            user32.BringWindowToTop(hwnd)
            ok = user32.SetForegroundWindow(hwnd)

            # 验证
            if user32.GetForegroundWindow() == hwnd:
                return True

            # 技巧 2：AttachThreadInput
            try:
                fg_thread = user32.GetWindowThreadProcessId(fg, None)
                target_thread = user32.GetWindowThreadProcessId(hwnd, None)
                cur_thread = kernel32.GetCurrentThreadId()

                if fg_thread != target_thread:
                    user32.AttachThreadInput(cur_thread, fg_thread, True)
                    user32.AttachThreadInput(cur_thread, target_thread, True)

                    user32.BringWindowToTop(hwnd)
                    user32.SetForegroundWindow(hwnd)
                    user32.SetFocus(hwnd)

                    user32.AttachThreadInput(cur_thread, fg_thread, False)
                    user32.AttachThreadInput(cur_thread, target_thread, False)
            except Exception:
                pass

            time.sleep(0.15)
            return user32.GetForegroundWindow() == hwnd

        except Exception as e:
            logger.debug(f"强制前台失败: {e}")
            return False

    def _find_hwnd(self, title_contains: str) -> Optional[Tuple[int, str]]:
        """用 Win32 枚举窗口，按标题模糊匹配

        比 pygetwindow 可靠，而且能拿到 hwnd。
        """
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            matches: List[Tuple[int, str]] = []

            EnumWindowsProc = ctypes.WINFUNCTYPE(
                ctypes.c_bool, wintypes.HWND, wintypes.LPARAM
            )

            def callback(hwnd, lparam):
                try:
                    if not user32.IsWindowVisible(hwnd):
                        return True

                    length = user32.GetWindowTextLengthW(hwnd)
                    if length == 0:
                        return True

                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value

                    if title_contains.lower() in title.lower():
                        # 过滤掉工具窗口（没标题按钮的）
                        matches.append((hwnd, title))
                except Exception:
                    pass
                return True

            user32.EnumWindows(EnumWindowsProc(callback), 0)

            if matches:
                # 优先选大的窗口（真正的应用窗口）
                best = None
                best_area = 0
                for hwnd, title in matches:
                    rect = self._get_window_rect(hwnd)
                    if rect:
                        area = rect[2] * rect[3]
                        if area > best_area:
                            best_area = area
                            best = (hwnd, title)
                    elif best is None:
                        best = (hwnd, title)
                return best
        except Exception as e:
            logger.debug(f"枚举窗口失败: {e}")
        return None

    # ── UIA 滚动位置（精确，不靠像素猜） ─────────────────

    def scroll_pixels(
        self,
        pixels: int,
        ensure_focus: bool = True,
    ) -> CUActionResult:
        """按像素滚动（正数向下，负数向上）

        语音说"往下翻一点"，换算成像素更直观。
        Windows 一格滚轮 ≈ 3 行 ≈ 60px。
        """
        notches = int(abs(pixels) / self.PIXELS_PER_NOTCH)
        if notches == 0:
            notches = 1

        # pyautogui 正数是向上，我们约定正数是向下
        notches = -notches if pixels > 0 else notches

        return self.scroll_notches(notches, ensure_focus=ensure_focus)

    def get_scroll_percent(self) -> Optional[float]:
        """用 UIA ScrollPattern 获取垂直滚动位置（0-100）

        只在**真的可用**时返回数值：
          · 控件必须 VerticallyScrollable == True
          · 控件必须有实际尺寸
          · 百分比必须在 0-100

        否则返回 None。

        实证：记事本、很多原生应用不暴露 ScrollPattern，
        强行读会拿到垃圾值（比如永远 100）。宁可不返回。
        """
        try:
            import uiautomation as uia
            root = uia.GetForegroundControl()
            if not root:
                return None

            return self._find_scroll_percent(root, depth=0)
        except Exception as e:
            logger.debug(f"ScrollPattern 读取失败: {e}")
            return None

    def _find_scroll_percent(self, ctrl, depth: int = 0) -> Optional[float]:
        """在控件树里找真正可滚动的节点"""
        if depth > 6:
            return None

        try:
            sp = ctrl.GetScrollPattern()
            if sp:
                try:
                    # 必须真的可滚动
                    scrollable = sp.VerticallyScrollable
                    if not scrollable:
                        raise ValueError("not scrollable")

                    pct = sp.VerticalScrollPercent
                    if pct is None or not (0 <= pct <= 100):
                        raise ValueError(f"bad pct {pct}")

                    # 控件必须有尺寸（过滤掉隐藏的壳）
                    rect = ctrl.BoundingRectangle
                    if not rect or rect.width() < 100 or rect.height() < 100:
                        raise ValueError("too small")

                    return float(pct)
                except Exception:
                    pass
        except Exception:
            pass

        try:
            for child in ctrl.GetChildren():
                pct = self._find_scroll_percent(child, depth + 1)
                if pct is not None:
                    return pct
        except Exception:
            pass

        return None

    def scroll_until(
        self,
        direction: str = "bottom",
        max_iterations: int = 15,
        pixels_per_step: int = 1200,
        settle_time: float = 0.25,
        change_threshold: float = 0.004,
    ) -> CUActionResult:
        """闭环滚动到边界

        ## 自动降级策略

        实证结果：滚轮（WM_MOUSEWHEEL / SendInput）在部分应用里完全无效：
          · Windows 11 新版记事本（WinUI 应用）
          · 部分 Electron 应用
          · 某些全屏应用

        但键盘按键在这些应用里总是有效的：
          · Ctrl+End / Ctrl+Home  直接跳转
          · PageDown / PageUp     逐页翻

        所以本方法做两阶段：
          1. 先用滚轮，检测是否有变化
          2. 滚轮无效则自动降级到键盘

        这样不管什么应用都能真的翻动。
        """
        t0 = time.time()
        down = direction.lower() in ("bottom", "down", "end", "底部", "下面")

        # ── 阶段 1：试滚轮 ──
        wheel_result = self._scroll_until_wheel(
            down, max_iterations, pixels_per_step, settle_time, change_threshold,
        )

        if wheel_result.data.get("reached_boundary") and \
           not wheel_result.data.get("already_at_boundary"):
            # 滚轮真的翻动了
            wheel_result.duration_ms = (time.time() - t0) * 1000
            return wheel_result

        # ── 阶段 2：滚轮无效，用键盘 ──
        if wheel_result.data.get("already_at_boundary"):
            # 先确认是真的已在边界，而不是滚轮失效
            kb_result = self._scroll_until_keyboard(down, max_iterations)

            if kb_result.data.get("changed"):
                # 键盘能翻 → 滚轮刚才失效了
                logger.info("滚轮无效，已降级到键盘滚动")
                kb_result.data["fallback_from_wheel"] = True
                kb_result.duration_ms = (time.time() - t0) * 1000
                return kb_result

            # 键盘也翻不动 → 真的在边界
            wheel_result.duration_ms = (time.time() - t0) * 1000
            return wheel_result

        wheel_result.duration_ms = (time.time() - t0) * 1000
        return wheel_result

    def _scroll_until_wheel(
        self,
        down: bool,
        max_iterations: int,
        pixels_per_step: int,
        settle_time: float,
        change_threshold: float,
    ) -> CUActionResult:
        """用滚轮闭环滚动"""
        t0 = time.time()

        prev = self._gray_small()
        if prev is None:
            return CUActionResult(
                success=False,
                action=CUAction.SCROLL_UNTIL,
                error="无法抓取屏幕",
            )

        iterations = 0
        stagnant = 0
        history: List[Dict] = []
        total_change = 0.0

        for i in range(max_iterations):
            iterations = i + 1

            self.scroll_pixels(
                pixels_per_step if down else -pixels_per_step,
                ensure_focus=(i == 0),
            )
            time.sleep(settle_time)

            cur = self._gray_small()
            if cur is None:
                break

            max_band, _ = self._diff_bands(prev, cur, bands=8)
            max_band = float(max_band)
            total_change += max_band

            history.append({
                "step": iterations,
                "max_band": round(max_band, 4),
            })

            if max_band < change_threshold:
                stagnant += 1
                if stagnant >= 2:
                    break
            else:
                stagnant = 0

            prev = cur

        self.stats["scrolls"] += iterations
        reached = stagnant >= 2
        already = iterations <= 2 and total_change < change_threshold

        direction_name = "底" if down else "顶"

        if already:
            msg = f"已经在{direction_name}了"
        elif reached:
            msg = f"滚到{direction_name}了"
        else:
            msg = f"滚了 {iterations} 步，可能还没到{direction_name}"

        return CUActionResult(
            success=True,
            action=CUAction.SCROLL_UNTIL,
            message=msg,
            data={
                "mode": "wheel",
                "direction": "bottom" if down else "top",
                "iterations": iterations,
                "reached_boundary": reached,
                "already_at_boundary": already,
                "history": history,
            },
            duration_ms=(time.time() - t0) * 1000,
            screen_changed=total_change > change_threshold,
        )

    def _scroll_until_keyboard(
        self,
        down: bool,
        max_iterations: int = 15,
    ) -> CUActionResult:
        """用键盘翻页（滚轮失效时的降级方案）

        Ctrl+End / Ctrl+Home 直接跳到文档两端，一步到位。
        比逐页翻快得多。
        """
        t0 = time.time()

        before = self._gray_small()

        # 直接跳到边界
        if down:
            self.hotkey("ctrl", "end")
        else:
            self.hotkey("ctrl", "home")

        time.sleep(0.6)

        after = self._gray_small()

        if before is None or after is None:
            return CUActionResult(
                success=False,
                action=CUAction.SCROLL_UNTIL,
                error="无法抓取屏幕",
            )

        max_band, _ = self._diff_bands(before, after, bands=8)
        changed = float(max_band) > 0.004

        direction_name = "底" if down else "顶"

        return CUActionResult(
            success=True,
            action=CUAction.SCROLL_UNTIL,
            message=(
                f"用键盘跳到{direction_name}了"
                if changed else
                f"已经在{direction_name}了"
            ),
            data={
                "mode": "keyboard",
                "changed": changed,
                "reached_boundary": True,
                "already_at_boundary": not changed,
                "max_band": round(float(max_band), 4),
            },
            duration_ms=(time.time() - t0) * 1000,
            screen_changed=changed,
        )

    def _gray_small(self, crop_to_target: bool = True):
        """抓一张小尺寸灰度图（用于比对）

        Args:
            crop_to_target: 只抓目标窗口区域

        只抓窗口区域能让信号强很多，但**前提是窗口真的可见**。
        被别的窗口盖住时必须退回全屏，否则截到的是别人的画面。
        """
        try:
            import mss
            from PIL import Image

            monitor = None

            if crop_to_target and self._target_window:
                rect = self._get_window_rect(self._target_window)

                # 关键：先确认窗口真的可见
                if rect and self._ensure_visible(self._target_window):
                    left, top, ww, wh = rect
                    monitor = {
                        "left": left + 8,
                        "top": top + 40,
                        "width": max(50, ww - 16),
                        "height": max(50, wh - 60),
                    }
                elif rect:
                    logger.debug(
                        "目标窗口被遮挡，退回全屏抓图"
                    )

            with mss.mss() as sct:
                if monitor is None:
                    monitor = sct.monitors[0]

                img = sct.grab(monitor)
                pil = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
                small = pil.resize((320, max(1, int(320 * pil.height / pil.width))))
                return small.convert("L")
        except Exception as e:
            logger.debug(f"抓图失败: {e}")
            return None

    @staticmethod
    def _diff_ratio(a, b) -> float:
        """两张灰度图的差异率（0-1，全图平均）"""
        try:
            import numpy as np

            arr_a = np.asarray(a, dtype=np.int16)
            arr_b = np.asarray(b, dtype=np.int16)

            if arr_a.shape != arr_b.shape:
                return 1.0

            diff = np.abs(arr_a - arr_b)
            changed = np.count_nonzero(diff > 12)
            return changed / arr_a.size

        except ImportError:
            ba, bb = a.tobytes(), b.tobytes()
            if len(ba) != len(bb):
                return 1.0
            diff = sum(1 for x, y in zip(ba, bb) if abs(x - y) > 12)
            return diff / len(ba)
        except Exception:
            return 1.0

    @staticmethod
    def _diff_bands(a, b, bands: int = 8) -> Tuple[float, List[float]]:
        """分带差异检测

        ## 为什么需要分带

        整屏平均差异会被“静态区域”稀释。

        比如 YouTube：中间 60% 是视频播放器，滚动时它不动。
        整屏平均差异可能只有 1%，但下方列表其实已经滚了好几屏。

        分带后看每个横带的差异，只要有任何一带变化大，
        就说明内容在动。

        Returns:
            (最大带差异, 各带差异列表)
        """
        try:
            import numpy as np

            arr_a = np.asarray(a, dtype=np.int16)
            arr_b = np.asarray(b, dtype=np.int16)

            if arr_a.shape != arr_b.shape or arr_a.shape[0] < bands:
                return 1.0, []

            h = arr_a.shape[0]
            band_h = h // bands
            ratios: List[float] = []

            for i in range(bands):
                y1 = i * band_h
                y2 = h if i == bands - 1 else (i + 1) * band_h

                sa = arr_a[y1:y2, :]
                sb = arr_b[y1:y2, :]

                diff = np.abs(sa - sb)
                changed = np.count_nonzero(diff > 12)
                ratios.append(round(float(changed / sa.size), 4))

            return max(ratios) if ratios else 0.0, ratios

        except ImportError:
            # 无 numpy：退回字节比较
            ba, bb = a.tobytes(), b.tobytes()
            if len(ba) != len(bb):
                return 1.0, []
            r = sum(1 for x, y in zip(ba, bb) if abs(x - y) > 12) / len(ba)
            return r, [r]
        except Exception:
            return 1.0, []

    # ── 键盘 ──────────────────────────────────

    def type_text(self, text: str, method: str = "auto") -> CUActionResult:
        """输入文字（支持中文）

        Args:
            text: 要输入的文字
            method: auto / paste / typewrite
                auto      纯 ASCII 用 typewrite（更稳），含中文用粘贴
                paste     总是用剪贴板粘贴
                typewrite 强制用按键模拟（只能 ASCII）
        """
        t0 = time.time()

        if not text:
            return CUActionResult(
                success=False, action=CUAction.TYPE, error="文本为空"
            )

        has_non_ascii = any(ord(c) > 127 for c in text)

        if method == "auto":
            method = "paste" if has_non_ascii else "typewrite"

        try:
            if method == "paste":
                ok = self._paste_text(text)
                if not ok:
                    # 剪贴板失败，退回 typewrite
                    method = "typewrite"
                else:
                    self.stats["types"] += 1
                    return CUActionResult(
                        success=True,
                        action=CUAction.TYPE,
                        message=f"粘贴输入 {len(text)} 字",
                        data={"text": text[:50], "method": "paste"},
                        duration_ms=(time.time() - t0) * 1000,
                    )

            if method == "typewrite":
                if has_non_ascii:
                    # 逐字符尝试（可能丢失非 ASCII）
                    logger.warning(
                        "typewrite 不支持非 ASCII，可能丢字"
                    )

                # typewrite 不支持中文，分段处理
                self.pag.typewrite(text, interval=0.01)
                self.stats["types"] += 1
                return CUActionResult(
                    success=True,
                    action=CUAction.TYPE,
                    message=f"键入输入 {len(text)} 字",
                    data={"text": text[:50], "method": "typewrite"},
                    duration_ms=(time.time() - t0) * 1000,
                )

        except Exception as e:
            self.stats["failures"] += 1
            return CUActionResult(
                success=False, action=CUAction.TYPE, error=str(e)
            )

    def _paste_text(self, text: str) -> bool:
        """通过剪贴板粘贴文字（支持中文）"""
        try:
            import pyperclip
        except ImportError:
            logger.error("缺少 pyperclip。安装: pip install pyperclip")
            return False

        try:
            # 保存原剪贴板
            try:
                original = pyperclip.paste()
            except Exception:
                original = ""

            pyperclip.copy(text)
            time.sleep(0.06)

            # Ctrl+V
            self.pag.hotkey("ctrl", "v")
            time.sleep(0.15)

            # 恢复剪贴板（可选，避免污染用户剪贴板）
            # 注意：如果用户马上要用，恢复太快可能导致粘贴失败
            # 所以延迟恢复
            if original:
                def restore():
                    time.sleep(0.5)
                    try:
                        pyperclip.copy(original)
                    except Exception:
                        pass

                import threading
                threading.Thread(target=restore, daemon=True).start()

            return True

        except Exception as e:
            logger.error(f"粘贴失败: {e}")
            return False

    def press(self, key: str) -> CUActionResult:
        """按键"""
        t0 = time.time()
        try:
            # 别名映射
            aliases = {
                "回车": "enter",
                "确定": "enter",
                "空格": "space",
                "退格": "backspace",
                "删除": "delete",
                "制表": "tab",
                "上": "up",
                "下": "down",
                "左": "left",
                "右": "right",
                "逃逸": "esc",
                "退出": "esc",
                "escape": "esc",
                "return": "enter",
            }
            k = aliases.get(key.lower(), key.lower())

            self.pag.press(k)
            self.stats["keystrokes"] += 1

            return CUActionResult(
                success=True,
                action=CUAction.PRESS,
                message=f"按键 {k}",
                duration_ms=(time.time() - t0) * 1000,
            )
        except Exception as e:
            self.stats["failures"] += 1
            return CUActionResult(
                success=False, action=CUAction.PRESS, error=str(e)
            )

    def hotkey(self, *keys: str) -> CUActionResult:
        """组合键"""
        t0 = time.time()
        try:
            # 中文别名
            mapping = {
                "控制": "ctrl", "命令": "win", "窗口": "win",
                "换挡": "shift", "其他": "alt",
            }
            normalized = [mapping.get(k.lower(), k.lower()) for k in keys]

            self.pag.hotkey(*normalized)
            self.stats["keystrokes"] += 1

            return CUActionResult(
                success=True,
                action=CUAction.HOTKEY,
                message=f"组合键 {'+'.join(normalized)}",
                duration_ms=(time.time() - t0) * 1000,
            )
        except Exception as e:
            self.stats["failures"] += 1
            return CUActionResult(
                success=False, action=CUAction.HOTKEY, error=str(e)
            )

    # ── 窗口 ──────────────────────────────────

    def get_active_window(self) -> Dict:
        """当前活动窗口"""
        try:
            import pygetwindow as gw
            w = gw.getActiveWindow()
            if not w:
                return {}
            return {
                "title": w.title,
                "left": w.left,
                "top": w.top,
                "width": w.width,
                "height": w.height,
            }
        except Exception as e:
            logger.debug(f"获取窗口失败: {e}")
            return {}

    def list_windows(self, visible_only: bool = True) -> List[Dict]:
        """列出所有窗口

        过滤掉：
          · 无标题的
          · 系统工具窗口（弹出、隐私声明、输入体验等）
          · 重复的
        """
        try:
            import pygetwindow as gw

            # 系统噪声窗口关键词
            noise = (
                "OrayPrivacyWnd", "SpeedBall", "LeAsWpTipWin",
                "Windows 输入体验", "弹出窗口", "Program Manager",
                "MSCTFIME", "Default IME", "Cua.",
            )

            windows = []
            seen = set()

            for w in gw.getAllWindows():
                if visible_only and (not w.title or not w.visible):
                    continue

                title = w.title.strip()
                if not title:
                    continue

                # 过滤噪声
                if any(n in title for n in noise):
                    continue

                # 过滤过小的（工具窗口）
                try:
                    if w.width < 200 or w.height < 100:
                        continue
                except Exception:
                    pass

                # 去重
                if title in seen:
                    continue
                seen.add(title)

                windows.append({
                    "title": title,
                    "left": w.left,
                    "top": w.top,
                    "width": w.width,
                    "height": w.height,
                    "active": bool(getattr(w, "isActive", False)),
                })

            # 活动窗口排最前
            windows.sort(key=lambda x: (not x["active"], -x["width"]))

            return windows
        except Exception:
            return []

    def focus_window(self, title_contains: str) -> CUActionResult:
        """按标题模糊匹配，切换到目标窗口

        用 Win32 API 强制前台，比 pygetwindow.activate() 可靠得多。
        成功后记住 hwnd，后续滚动和点击都针对这个窗口。
        """
        t0 = time.time()

        try:
            found = self._find_hwnd(title_contains)

            if not found:
                return CUActionResult(
                    success=False,
                    action=CUAction.FOCUS_WINDOW,
                    error=f"找不到标题含「{title_contains}」的窗口",
                    data={"available": [
                        w["title"][:50] for w in self.list_windows()[:12]
                    ]},
                )

            hwnd, title = found

            # 强制前台（多次尝试）
            visible = False
            for attempt in range(3):
                ok = self._force_focus(hwnd)
                time.sleep(0.2)

                # 不盲信 API，查真实可见性
                if self._ensure_visible(hwnd):
                    visible = True
                    break

                logger.debug(
                    f"第 {attempt + 1} 次尝试后窗口仍不可见"
                )
                time.sleep(0.15)

            if visible:
                self._target_window = hwnd

            return CUActionResult(
                success=visible,
                action=CUAction.FOCUS_WINDOW,
                message=f"切换到「{title}」" if visible else "",
                error="" if visible else (
                    f"找到「{title}」但无法置于前台"
                    "（可能被全屏应用遮挡，请手动点一下该窗口）"
                ),
                data={
                    "title": title,
                    "hwnd": hwnd,
                    "visible": visible,
                },
                duration_ms=(time.time() - t0) * 1000,
            )

        except Exception as e:
            return CUActionResult(
                success=False, action=CUAction.FOCUS_WINDOW, error=str(e)
            )

    def launch_app(self, name: str) -> CUActionResult:
        """启动应用"""
        import subprocess
        t0 = time.time()
        try:
            # Windows: start 命令
            subprocess.Popen(
                ["cmd", "/c", "start", "", name],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(1.2)
            return CUActionResult(
                success=True,
                action=CUAction.LAUNCH_APP,
                message=f"启动 {name}",
                duration_ms=(time.time() - t0) * 1000,
            )
        except Exception as e:
            return CUActionResult(
                success=False, action=CUAction.LAUNCH_APP, error=str(e)
            )

    # ── 截屏 ──────────────────────────────────

    def screenshot(self, max_width: int = 0) -> Optional[bytes]:
        """截屏，返回 PNG bytes

        Args:
            max_width: 最大宽度，超过则缩放（0 = 不缩放）
                       发给视觉模型时必须降采样，4K 原图 6MB 会超限
        """
        data = self._raw_screenshot()
        if not data or max_width <= 0:
            return data

        return self._downscale(data, max_width)

    def _raw_screenshot(self) -> Optional[bytes]:
        """原始截屏"""
        # 优先 mss（快）
        try:
            import mss
            import io
            from PIL import Image

            with mss.mss() as sct:
                monitor = sct.monitors[0]
                img = sct.grab(monitor)
                pil = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
                buf = io.BytesIO()
                pil.save(buf, format="PNG", optimize=False)
                return buf.getvalue()
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"mss 截屏失败: {e}")

        # 退回 pyautogui
        try:
            import io
            shot = self.pag.screenshot()
            buf = io.BytesIO()
            shot.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as e:
            logger.error(f"截屏失败: {e}")
            return None

    def _downscale(self, png_bytes: bytes, max_width: int) -> bytes:
        """缩放 PNG"""
        try:
            import io
            from PIL import Image

            img = Image.open(io.BytesIO(png_bytes))
            if img.width <= max_width:
                return png_bytes

            ratio = max_width / img.width
            new_size = (max_width, int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as e:
            logger.debug(f"缩放失败: {e}")
            return png_bytes

    def _screen_hash(self) -> str:
        """截屏指纹（用于比较变化）

        必须降采样：4K 全图 hash 要几百毫秒，缩放后 <20ms。
        而且降采样后仍然能检测到内容变化。
        """
        try:
            import io
            import mss
            from PIL import Image

            with mss.mss() as sct:
                monitor = sct.monitors[0]
                img = sct.grab(monitor)
                pil = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
                # 缩到 320 宽，灰度化，转 bytes
                small = pil.resize((320, int(320 * pil.height / pil.width)))
                gray = small.convert("L")
                return hashlib.md5(gray.tobytes()).hexdigest()
        except Exception:
            pass

        data = self.screenshot()
        if not data:
            return ""
        return hashlib.md5(data[::97]).hexdigest()

    # ── 安全 ──────────────────────────────────

    def _in_forbidden(self, x: int, y: int) -> bool:
        for (x1, y1, x2, y2) in self._forbidden_zones:
            if x1 <= x <= x2 and y1 <= y <= y2:
                return True
        return False

    def panic(self):
        """紧急停止：把鼠标挪到角落触发 FAILSAFE"""
        try:
            self.pag.moveTo(0, 0)
        except Exception:
            pass

    def get_stats(self) -> Dict:
        return {
            "screen": f"{self._screen_size[0]}x{self._screen_size[1]}",
            "safe_mode": self.safe_mode,
            **self.stats,
        }


# ══════════════════════════════════════════════════════════
#  语音意图 → 电脑动作 映射
# ══════════════════════════════════════════════════════════

@dataclass
class VoiceIntent:
    """从语音里解析出的意图"""
    action: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    raw_text: str = ""
    needs_context: bool = False     # 是否需要问用户确认


class VoiceIntentParser:
    """语音意图解析器（规则层）

    先做一层快速规则解析，命中就走，不命中交给 LLM。

    为什么需要规则层：
      "往下翻" → LLM 要 500ms+，规则 0ms
      高频简单指令走规则，体验才跟得上嘴。
    """

    # 滚动
    SCROLL_DOWN = ("往下翻", "向下翻", "往下滚", "向下滚", "下面", "下翻",
                   "翻一页", "下一页", "继续往下", "滚动下去", "往下去")
    SCROLL_UP = ("往上翻", "向上翻", "往上滚", "向上滚", "上面", "上翻",
                 "上一页", "回到上面", "滚动上去")
    SCROLL_BOTTOM = ("翻到底", "到最底", "滚到底", "到底部", "最后面",
                     "拉到最下面", "翻到最后")
    SCROLL_TOP = ("回到顶部", "翻到顶", "最上面", "回到最上面", "拉到最上面")

    # 点击
    CLICK_WORDS = ("点击", "点一下", "按下", "点开", "单击", "点")
    DOUBLE_CLICK_WORDS = ("双击", "点两下")
    RIGHT_CLICK_WORDS = ("右键", "右击")

    # 输入
    TYPE_WORDS = ("输入", "打字", "填写", "填入", "写下")

    # 按键
    ENTER_WORDS = ("回车", "确认", "确定", "发送", "搜索")
    ESC_WORDS = ("退出", "取消", "关闭弹窗", "返回", "esc")

    # 组合键
    HOTKEY_PATTERNS = {
        "复制": ("ctrl", "c"),
        "粘贴": ("ctrl", "v"),
        "剪切": ("ctrl", "x"),
        "撤销": ("ctrl", "z"),
        "重做": ("ctrl", "y"),
        "全选": ("ctrl", "a"),
        "保存": ("ctrl", "s"),
        "查找": ("ctrl", "f"),
        "关闭窗口": ("alt", "f4"),
        "关闭标签": ("ctrl", "w"),
        "新标签": ("ctrl", "t"),
        "切换窗口": ("alt", "tab"),
        "刷新": ("f5",),
    }

    # 窗口
    FOCUS_WORDS = ("切换到", "切到", "打开窗口", "切回", "跳到")

    @classmethod
    def parse(cls, text: str) -> Optional[VoiceIntent]:
        """解析意图，返回 None 表示规则层无法处理"""
        t = text.strip()
        tl = t.lower()

        # 翻到底/顶（优先，因为包含"翻到"这种会被误判的）
        if any(k in t for k in cls.SCROLL_BOTTOM):
            return VoiceIntent(
                action="scroll_until",
                params={"direction": "bottom"},
                confidence=0.95,
                raw_text=t,
            )

        if any(k in t for k in cls.SCROLL_TOP):
            return VoiceIntent(
                action="scroll_until",
                params={"direction": "top"},
                confidence=0.95,
                raw_text=t,
            )

        # 滚动（带数量解析）
        if any(k in t for k in cls.SCROLL_DOWN):
            amount = cls._extract_amount(t)
            return VoiceIntent(
                action="scroll",
                params={"pixels": amount or 480, "direction": "down"},
                confidence=0.9,
                raw_text=t,
            )

        if any(k in t for k in cls.SCROLL_UP):
            amount = cls._extract_amount(t)
            return VoiceIntent(
                action="scroll",
                params={"pixels": -(amount or 480), "direction": "up"},
                confidence=0.9,
                raw_text=t,
            )

        # 组合键（优先于单键）
        for word, keys in cls.HOTKEY_PATTERNS.items():
            if word in t:
                return VoiceIntent(
                    action="hotkey",
                    params={"keys": list(keys)},
                    confidence=0.9,
                    raw_text=t,
                )

        # 双击
        if any(k in t for k in cls.DOUBLE_CLICK_WORDS):
            target = cls._extract_target(t)
            if target:
                return VoiceIntent(
                    action="double_click_text",
                    params={"text": target},
                    confidence=0.85,
                    raw_text=t,
                )
            return VoiceIntent(
                action="double_click",
                params={},
                confidence=0.7,
                raw_text=t,
                needs_context=True,
            )

        # 右键
        if any(k in t for k in cls.RIGHT_CLICK_WORDS):
            target = cls._extract_target(t)
            return VoiceIntent(
                action="right_click",
                params={"text": target} if target else {},
                confidence=0.85,
                raw_text=t,
            )

        # 输入
        for w in cls.TYPE_WORDS:
            if w in t:
                content = cls._extract_type_content(t, w)
                if content:
                    return VoiceIntent(
                        action="type",
                        params={"text": content},
                        confidence=0.9,
                        raw_text=t,
                    )

        # 回车/确认
        if any(k in t for k in cls.ENTER_WORDS):
            if len(t) < 12:      # 短句才当按键，长句可能是别的事
                return VoiceIntent(
                    action="press",
                    params={"key": "enter"},
                    confidence=0.8,
                    raw_text=t,
                )

        # 退出/取消
        if any(k in t for k in cls.ESC_WORDS):
            return VoiceIntent(
                action="press",
                params={"key": "esc"},
                confidence=0.8,
                raw_text=t,
            )

        # 点击（带目标文字）
        if any(k in t for k in cls.CLICK_WORDS):
            target = cls._extract_target(t)
            if target:
                return VoiceIntent(
                    action="click_text",
                    params={"text": target},
                    confidence=0.85,
                    raw_text=t,
                )
            return VoiceIntent(
                action="click",
                params={},
                confidence=0.6,
                raw_text=t,
                needs_context=True,
            )

        # 窗口切换
        if any(k in t for k in cls.FOCUS_WORDS):
            target = cls._extract_target(t)
            if target:
                return VoiceIntent(
                    action="focus_window",
                    params={"title": target},
                    confidence=0.85,
                    raw_text=t,
                )

        return None

    @classmethod
    def _extract_amount(cls, text: str) -> Optional[int]:
        """从文字里抽数量"""
        import re

        # "一点点" / "一点"
        if any(k in text for k in ("一点", "少许", "小")):
            return 240

        # "一大" / "大幅"
        if any(k in text for k in ("一大", "大幅", "很多", "多")):
            return 900

        # 数字 + 单位
        m = re.search(r"(\d+)\s*(屏|页|次|行|像素|px)?", text)
        if m:
            n = int(m.group(1))
            unit = m.group(2) or ""
            if unit in ("屏", "页"):
                return n * 800
            if unit == "行":
                return n * 60
            if unit in ("像素", "px"):
                return n
            return n * 240       # 默认一次 = 240px

        # 中文数字
        cn = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        m = re.search(r"([一二两三四五六七八九十])\s*(屏|页|次|行)", text)
        if m:
            n = cn.get(m.group(1), 1)
            unit = m.group(2)
            return n * (800 if unit in ("屏", "页") else 60)

        return None

    @classmethod
    def _extract_target(cls, text: str) -> str:
        """从"点击登录按钮"里抽出"登录\""""
        import re

        # 去掉动作词
        action_words = (
            "点击", "点一下", "双击", "右键", "右击", "按下",
            "点开", "单击", "点", "切换到", "切到", "打开窗口",
            "切回", "跳到",
        )
        t = text
        for w in action_words:
            t = t.replace(w, "")

        # 去掉尾部通用词
        for suffix in ("按钮", "按键", "链接", "图标", "那个", "这个", "一下",
                       "窗口", "标签页", "标签", "页签"):
            t = t.replace(suffix, "")

        t = t.strip(" 　的了吧呢啊，,。.")

        # 太短没意义
        if len(t) < 1 or len(t) > 40:
            return ""

        return t

    @classmethod
    def _extract_type_content(cls, text: str, trigger: str) -> str:
        """从"输入你好世界"里抽出"你好世界\""""
        import re

        idx = text.find(trigger)
        if idx < 0:
            return ""

        content = text[idx + len(trigger):]

        # 去掉冒号引号
        content = content.strip(" 　：:，,\"'“”‘’")

        # 去掉尾部语气词
        for suffix in ("然后回车", "回车", "并搜索", "搜索", "吧", "呢", "啊"):
            if content.endswith(suffix):
                content = content[:-len(suffix)].strip()

        # 太短可能是"输入框"这种名词
        if len(content) < 1:
            return ""

        # "输入框"这种不是内容
        if content in ("框", "文字", "内容", "文本", "东西"):
            return ""

        return content


def get_computer_status() -> Dict:
    """电脑操作环境状态"""
    deps = {}
    for m in ("pyautogui", "pyperclip", "pygetwindow", "mss", "PIL"):
        try:
            __import__(m)
            deps[m] = True
        except ImportError:
            deps[m] = False

    w, h = get_screen_size()

    return {
        "screen_size": f"{w}x{h}",
        "dependencies": deps,
        "ready": all(deps.values()),
        "hint": (
            "电脑操作就绪"
            if all(deps.values())
            else "缺少依赖: " + ", ".join(k for k, v in deps.items() if not v)
        ),
    }