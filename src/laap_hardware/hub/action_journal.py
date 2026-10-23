"""动作日志与撤销 — 让 Aris 动手之后能收回

## 核心难点：不是所有动作都可逆

这是必须先讲清楚的一件事。GUI 操作的可逆性差异极大：

| 动作 | 可逆？ | 怎么撤 |
|------|:-----:|--------|
| 滚动 | ✓ | 反向滚动即可 |
| 窗口切换 | ✓ | 切回原窗口 |
| 输入文字 | ✓ | Ctrl+Z（大多数应用） |
| 删除文字 | ✓ | Ctrl+Z |
| 单击按钮 | ✗ | 点了就点了，没法"取消点击" |
| 双击打开文件 | ✗ | 可以关掉打开的程序，但有副作用 |
| 提交表单 | ✗ | 数据已经发出去了 |
| 发送消息 | ✗ | 收件人已经看到了 |
| 启动应用 | △ | 可以关掉，但可能有未保存数据 |
| 关闭窗口 | ✗ | 可能丢数据 |

所以本模块做两件事：

  1. **事前判断**：执行前就知道这个动作能不能撤
  2. **诚实撤销**：能撤的真撤，不能撤的明确说"这个撤不回来"

## 为什么这个设计重要

"我能撤销"这句话如果说了做不到，比不说更危险——
用户会以为在安全网里，实际上没有。

所以宁可说"这一步撤不回来"，也不假装能撤。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laaper.hub.journal")


class Undoability(str, Enum):
    """可撤销程度"""
    SAFE = "safe"              # 完全可逆，随便撤
    LIKELY = "likely"          # 大概率可逆（Ctrl+Z 通常有效）
    PARTIAL = "partial"        # 部分可逆，可能有副作用
    NEVER = "never"            # 不可逆，撤了就出问题


@dataclass
class ActionRecord:
    """一条动作记录"""
    record_id: str = field(default_factory=lambda: f"ar_{uuid.uuid4().hex[:8]}")
    seq: int = 0

    action: str = ""
    params: Dict[str, Any] = field(default_factory=dict)

    # 撤销信息
    undoability: str = Undoability.NEVER
    undo_hint: str = ""                       # 撤销提示（如 "ctrl+z"）
    undo_params: Dict[str, Any] = field(default_factory=dict)

    # 状态快照
    screen_before: str = ""                   # 屏幕指纹
    screen_after: str = ""
    window_before: str = ""                   # 窗口标题
    window_after: str = ""

    # 元数据
    success: bool = False
    undone: bool = False
    undone_at: float = 0.0
    created_at: float = field(default_factory=time.time)
    note: str = ""

    def to_dict(self) -> Dict:
        return {
            "record_id": self.record_id,
            "seq": self.seq,
            "action": self.action,
            "params": self.params,
            "undoability": self.undoability,
            "undo_hint": self.undo_hint,
            "success": self.success,
            "undone": self.undone,
            "window_before": self.window_before,
            "window_after": self.window_after,
            "created_at": self.created_at,
        }

    @property
    def can_undo(self) -> bool:
        return (
            not self.undone
            and self.undoability != Undoability.NEVER
            and self.success
        )


@dataclass
class UndoResult:
    """撤销结果"""
    success: bool
    undone_count: int = 0
    message: str = ""
    skipped: List[Dict] = field(default_factory=list)
    error: str = ""


# ══════════════════════════════════════════════════════════
#  可逆性判定表
# ══════════════════════════════════════════════════════════

def classify_undoability(action: str, params: Dict) -> tuple:
    """判断动作的可逆性

    Returns:
        (Undoability, undo_hint, undo_params)
    """
    action = action.lower()

    # ── 滚动：完全可逆 ──
    if action == "scroll":
        pixels = params.get("pixels", 0)
        return (
            Undoability.SAFE,
            f"反向滚动 {pixels}px",
            {"pixels": -pixels},
        )

    if action == "scroll_until":
        direction = params.get("direction", "bottom")
        reverse = "top" if direction in ("bottom", "down") else "bottom"
        return (
            Undoability.SAFE,
            f"滚回{direction == 'top' and '底' or '顶'}部",
            {"direction": reverse},
        )

    # ── 窗口切换：可逆 ──
    if action == "focus_window":
        return (
            Undoability.SAFE,
            f"切回原窗口",
            {"restore_previous": True},
        )

    # ── 输入文字：大概率可逆 ──
    if action == "type":
        return (
            Undoability.LIKELY,
            "Ctrl+Z 撤销输入（多数应用有效）",
            {"hotkey": ["ctrl", "z"]},
        )

    # ── 按键 ──
    if action == "press":
        key = params.get("key", "").lower()
        # 回车常常触发提交，不可逆
        if key in ("enter", "return"):
            return (
                Undoability.PARTIAL,
                "回车可能已提交，Ctrl+Z 试试",
                {"hotkey": ["ctrl", "z"]},
            )
        if key in ("delete", "backspace"):
            return (
                Undoability.LIKELY,
                "Ctrl+Z 恢复删除",
                {"hotkey": ["ctrl", "z"]},
            )
        return (
            Undoability.PARTIAL,
            "按键通常无副作用",
            {},
        )

    # ── 组合键 ──
    if action == "hotkey":
        keys = params.get("keys", [])
        kl = "+".join(str(k).lower() for k in keys)

        # 这些是纯读操作，无副作用
        if kl in ("ctrl+c", "ctrl+a", "ctrl+f"):
            return (Undoability.SAFE, "复制/全选/查找无副作用", {})

        # 撤销本身
        if kl == "ctrl+z":
            return (Undoability.NEVER, "撤销操作本身不可再撤销", {})

        # 保存：文件已写盘
        if kl == "ctrl+s":
            return (
                Undoability.NEVER,
                "已保存到磁盘，无法通过撤销恢复原内容",
                {},
            )

        # 关闭：可能丢数据
        if kl in ("alt+f4", "ctrl+w"):
            return (
                Undoability.NEVER,
                "关闭窗口可能丢失未保存数据",
                {},
            )

        return (
            Undoability.PARTIAL,
            "组合键可能有副作用",
            {},
        )

    # ── 点击：基本不可逆 ──
    if action in ("click", "click_text", "double_click", "right_click"):
        return (
            Undoability.NEVER,
            "点击已发生，无法撤销（可尝试浏览器后退）",
            {"hotkey": ["alt", "left"]} if params.get("target") else {},
        )

    # ── 启动应用：部分可逆 ──
    if action == "launch_app":
        return (
            Undoability.PARTIAL,
            "可以关闭应用，但可能有未保存数据",
            {},
        )

    # ── 其他 ──
    return (Undoability.NEVER, "未知动作，不做撤销尝试", {})


# ══════════════════════════════════════════════════════════
#  动作日志
# ══════════════════════════════════════════════════════════

class ActionJournal:
    """动作日志 — 记录每一步，支持撤销

    用法:
        journal = ActionJournal()

        journal.record("scroll", {"pixels": 480}, success=True)
        journal.record("type", {"text": "你好"}, success=True)

        # 撤销最近一步
        result = journal.undo_last(cu)
        print(result.message)

        # 撤销全部
        result = journal.undo_all(cu)
    """

    def __init__(
        self,
        cu: Any = None,
        max_records: int = 200,
        persist_path: Optional[str] = None,
    ):
        self.cu = cu
        self.max_records = max_records
        self.records: List[ActionRecord] = []
        self._seq = 0
        self._path = Path(persist_path) if persist_path else None

        # 上一个窗口（用于 undo focus_window）
        self._previous_window: str = ""

    def set_cu(self, cu: Any):
        """挂载 ComputerUse"""
        self.cu = cu

    # ── 记录 ──────────────────────────────────

    def record(
        self,
        action: str,
        params: Dict[str, Any],
        success: bool = True,
        undoable: Optional[bool] = None,
        undo_hint: str = "",
        screen_before: str = "",
        screen_after: str = "",
        note: str = "",
    ) -> ActionRecord:
        """记录一个动作"""
        self._seq += 1

        undoability, auto_hint, undo_params = classify_undoability(action, params)

        rec = ActionRecord(
            seq=self._seq,
            action=action,
            params=params,
            undoability=undoability,
            undo_hint=undo_hint or auto_hint,
            undo_params=undo_params,
            screen_before=screen_before,
            screen_after=screen_after,
            success=success,
            note=note,
        )

        # 记录窗口状态
        if self.cu:
            try:
                rec.window_before = self._previous_window or \
                    self.cu.get_active_window().get("title", "")
                rec.window_after = self.cu.get_active_window().get("title", "")
                if action == "focus_window":
                    self._previous_window = rec.window_before
            except Exception:
                pass

        self.records.append(rec)

        # 裁剪
        if len(self.records) > self.max_records:
            self.records = self.records[-self.max_records:]

        return rec

    # ── 撤销 ──────────────────────────────────

    def undo_last(self) -> UndoResult:
        """撤销最近一个可撤销的动作"""
        for rec in reversed(self.records):
            if rec.can_undo:
                return self._undo_record(rec)

        # 没有可撤销的
        if self.records:
            last = self.records[-1]
            return UndoResult(
                success=False,
                message=f"最近的「{last.action}」不可撤销：{last.undo_hint}",
                skipped=[last.to_dict()],
            )

        return UndoResult(success=False, message="没有动作可撤销")

    def undo_count(self, count: int) -> UndoResult:
        """撤销最近 N 个可撤销动作"""
        undone = 0
        skipped = []
        messages = []

        for rec in reversed(self.records):
            if undone >= count:
                break

            if rec.can_undo:
                r = self._undo_record(rec)
                if r.success:
                    undone += 1
                    messages.append(r.message)
                else:
                    skipped.append({"action": rec.action, "reason": r.error})
            elif not rec.undone:
                skipped.append({
                    "action": rec.action,
                    "reason": rec.undo_hint or "不可撤销",
                })

        return UndoResult(
            success=undone > 0,
            undone_count=undone,
            message=(
                f"撤销了 {undone} 步" + (
                    f"，跳过 {len(skipped)} 步不可撤销的" if skipped else ""
                )
            ),
            skipped=skipped,
        )

    def undo_all(self) -> UndoResult:
        """撤销所有可撤销动作（从最近往前）"""
        return self.undo_count(len(self.records))

    def undo_to(self, seq: int) -> UndoResult:
        """撤销到某个序号之后（不含该序号）"""
        count = sum(
            1 for r in self.records
            if r.seq > seq and r.can_undo
        )
        if count == 0:
            return UndoResult(
                success=False,
                message=f"序号 {seq} 之后没有可撤销的动作",
            )
        return self.undo_count(count)

    def _undo_record(self, rec: ActionRecord) -> UndoResult:
        """执行单个撤销"""
        if not self.cu:
            return UndoResult(
                success=False,
                error="未挂载 ComputerUse，无法执行撤销",
            )

        try:
            action = rec.action.lower()
            params = rec.undo_params

            # ── 滚动：反向滚 ──
            if action in ("scroll", "scroll_until"):
                if "pixels" in params:
                    r = self.cu.scroll_pixels(params["pixels"])
                elif "direction" in params:
                    r = self.cu.scroll_until(params["direction"])
                else:
                    return UndoResult(False, error="滚动撤销缺少参数")

                if r.success:
                    rec.undone = True
                    rec.undone_at = time.time()
                    return UndoResult(
                        success=True,
                        undone_count=1,
                        message=f"已反向滚动",
                    )
                return UndoResult(False, error=r.error)

            # ── 窗口切换：切回原窗口 ──
            if action == "focus_window":
                title = rec.window_before
                if not title:
                    return UndoResult(False, error="没有原窗口记录")

                r = self.cu.focus_window(title)
                if r.success:
                    rec.undone = True
                    rec.undone_at = time.time()
                    return UndoResult(
                        success=True,
                        undone_count=1,
                        message=f"已切回「{title}」",
                    )
                return UndoResult(False, error=r.error)

            # ── 键盘：按 undo_params 里的 hotkey ──
            if "hotkey" in params:
                keys = params["hotkey"]
                # 先确保焦点在对的地方
                if rec.window_after:
                    try:
                        self.cu.focus_window(rec.window_after)
                        time.sleep(0.2)
                    except Exception:
                        pass

                r = self.cu.hotkey(*keys)
                if r.success:
                    rec.undone = True
                    rec.undone_at = time.time()
                    return UndoResult(
                        success=True,
                        undone_count=1,
                        message=f"已按 {'+'.join(keys)} 撤销",
                    )
                return UndoResult(False, error=r.error)

            return UndoResult(
                success=False,
                error=f"「{action}」没有可执行的撤销方案",
            )

        except Exception as e:
            logger.exception("撤销异常")
            return UndoResult(False, error=f"{type(e).__name__}: {e}")

    # ── 查询 ──────────────────────────────────

    def recent(self, n: int = 10) -> List[Dict]:
        """最近 n 条"""
        return [r.to_dict() for r in self.records[-n:]]

    def undoable_count(self) -> int:
        return sum(1 for r in self.records if r.can_undo)

    def summarize(self) -> str:
        """给人看的摘要"""
        if not self.records:
            return "还没有执行任何动作"

        undoable = self.undoable_count()
        never = sum(
            1 for r in self.records
            if r.undoability == Undoability.NEVER and not r.undone
        )

        parts = [f"共 {len(self.records)} 个动作，{undoable} 个可撤销"]
        if never:
            parts.append(f"{never} 个不可撤销")

        return "，".join(parts)

    def get_undoable_list(self) -> List[Dict]:
        """列出可撤销的动作"""
        return [
            {
                "seq": r.seq,
                "action": r.action,
                "hint": r.undo_hint,
            }
            for r in self.records
            if r.can_undo
        ]

    def get_blocked_list(self) -> List[Dict]:
        """列出不可撤销的动作（诚实告知用户）"""
        return [
            {
                "seq": r.seq,
                "action": r.action,
                "why": r.undo_hint,
            }
            for r in self.records
            if r.undoability == Undoability.NEVER and not r.undone
        ]

    def clear(self):
        """清空日志"""
        self.records.clear()
        self._seq = 0

    # ── 持久化 ──────────────────────────────────

    def save(self, path: Optional[str] = None):
        """保存到文件"""
        p = Path(path) if path else self._path
        if not p:
            return False

        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "records": [r.to_dict() for r in self.records],
                "saved_at": time.time(),
            }
            p.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except Exception as e:
            logger.error(f"保存日志失败: {e}")
            return False

    def load(self, path: Optional[str] = None) -> bool:
        """从文件加载"""
        p = Path(path) if path else self._path
        if not p or not p.exists():
            return False

        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            for d in data.get("records", []):
                rec = ActionRecord(
                    record_id=d.get("record_id", ""),
                    seq=d.get("seq", 0),
                    action=d.get("action", ""),
                    params=d.get("params", {}),
                    undoability=d.get("undoability", Undoability.NEVER),
                    undo_hint=d.get("undo_hint", ""),
                    success=d.get("success", False),
                    undone=d.get("undone", False),
                )
                self.records.append(rec)
                self._seq = max(self._seq, rec.seq)
            return True
        except Exception as e:
            logger.error(f"加载日志失败: {e}")
            return False


# ══════════════════════════════════════════════════════════
#  安全策略：执行前拦截
# ══════════════════════════════════════════════════════════

class SafetyPolicy:
    """安全策略 — 危险动作执行前拦截

    设计原则：**默认可撤销的放行，不可撤销的要确认。**

    但语音交互里没法每次都问"你确定吗"。
    所以分两级：
      · 高危（发消息、提交订单、删除文件）→ 必须确认
      · 一般（点击、输入、滚动）→ 直接执行，但记入日志
    """

    # 高危关键词
    HIGH_RISK_KEYWORDS = (
        "发送", "提交", "支付", "付款", "购买", "下单", "转账",
        "删除", "清空", "格式化", "卸载",
        "send", "submit", "pay", "buy", "delete", "remove",
        "confirm", "确定",
    )

    def __init__(
        self,
        require_confirm_for_risky: bool = True,
        forbidden_zones: Optional[List] = None,
    ):
        self.require_confirm_for_risky = require_confirm_for_risky
        self.forbidden_zones = forbidden_zones or []

        # 待确认队列
        self._pending_confirm: Optional[Dict] = None

    def check(
        self,
        action: str,
        params: Dict,
        element_name: str = "",
    ) -> tuple:
        """检查动作是否安全

        Returns:
            (是否放行, 原因, 是否需要确认)
        """
        action = action.lower()

        # 输入高危词到输入框
        if action == "type":
            text = str(params.get("text", ""))
            # 输入内容本身不是危险动作（只是打字）
            return True, "", False

        # 点击高危目标
        if action in ("click", "click_text"):
            target = element_name or str(params.get("target", ""))

            for kw in self.HIGH_RISK_KEYWORDS:
                if kw in target:
                    if self.require_confirm_for_risky:
                        return (
                            False,
                            f"目标「{target}」含高危词「{kw}」",
                            True,
                        )
                    return (
                        True,
                        f"目标含高危词「{kw}」（已关闭确认）",
                        False,
                    )

        # 回车常常等于提交
        if action == "press":
            key = str(params.get("key", "")).lower()
            if key in ("enter", "return") and self.require_confirm_for_risky:
                # 回车不一定要确认，但记一笔
                return True, "回车可能触发提交", False

        # 组合键
        if action == "hotkey":
            keys = params.get("keys", [])
            kl = "+".join(str(k).lower() for k in keys)

            if kl in ("alt+f4", "ctrl+w") and self.require_confirm_for_risky:
                return False, f"「{kl}」可能丢失未保存数据", True

        return True, "", False

    async def confirm(
        self,
        action: str,
        params: Dict,
        reason: str,
        voice_ask: Optional[Any] = None,
    ) -> bool:
        """请求确认

        Args:
            voice_ask: 语音询问回调（async），如果没有则返回 False（保守拒绝）

        Returns:
            是否确认执行
        """
        if not voice_ask:
            logger.warning(
                f"高危动作需要确认但没有语音通道，保守拒绝: {action} {reason}"
            )
            return False

        try:
            answer = await voice_ask(
                f"这一步是「{action}」，{reason}。要执行吗？"
            )

            # 解析回答
            yes_words = ("是", "好", "对", "确定", "可以", "执行", "继续", "yes", "ok")
            return any(w in str(answer).lower() for w in yes_words)

        except Exception as e:
            logger.error(f"确认失败: {e}")
            return False


# ══════════════════════════════════════════════════════════
#  接入中枢
# ══════════════════════════════════════════════════════════

def register_journal_handlers(
    hub: Any,
    pc_node: str = "pc-01",
    journal: Optional[ActionJournal] = None,
    cu: Any = None,
) -> Dict[str, Any]:
    """把撤销能力注册到中枢"""
    journal = journal or ActionJournal(cu=cu)

    async def undo_last(params: Dict) -> Dict:
        r = journal.undo_last()
        return {
            "success": r.success,
            "data": {
                "message": r.message,
                "undone": r.undone_count,
                "skipped": r.skipped,
            },
            "error": "" if r.success else r.message,
        }

    hub.transport.register_handler(pc_node, "undo_last", undo_last)
    hub.transport.register_handler(pc_node, "undo", undo_last)

    async def undo_all(params: Dict) -> Dict:
        r = journal.undo_all()
        return {
            "success": r.success,
            "data": {
                "message": r.message,
                "undone": r.undone_count,
                "skipped": r.skipped,
            },
            "error": "" if r.success else r.message,
        }

    hub.transport.register_handler(pc_node, "undo_all", undo_all)

    async def undo_summary(params: Dict) -> Dict:
        return {
            "success": True,
            "data": {
                "summary": journal.summarize(),
                "recent": journal.recent(8),
                "undoable": journal.get_undoable_list()[-5:],
                "blocked": journal.get_blocked_list()[-5:],
            },
        }

    hub.transport.register_handler(pc_node, "undo_summary", undo_summary)

    return {
        "journal": journal,
        "handlers": ["undo_last", "undo", "undo_all", "undo_summary"],
    }