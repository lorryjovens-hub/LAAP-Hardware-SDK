# LAAP 语音控制电脑 — 实现文档

> 小智硬件说话，电脑真的动起来：鼠标、键盘、滚轮

---

## 一、完整链路

```
小智硬件麦克风
    ↓ ASR（SenseNova）
"往下翻"
    ↓ 意图识别（规则 0ms → LLM 兜底）
ComputerUse（滚轮 / 键盘）
    ↓ 执行
    ↓ 截图验证
"翻好了"
    ↓ TTS
小智硬件扬声器
```

---

## 二、三层意图识别

| 层 | 耗时 | 覆盖 | 实现 |
|---|------|------|------|
| **规则** | 0ms | 约 80% 高频指令 | `VoiceIntentParser` |
| **元素定位** | 50-500ms | "点登录按钮" 里的目标在哪 | UIA / 视觉 |
| **LLM** | 500-2000ms | 复杂自然语言 | DeepSeek |

### 规则层实测（21/21 正确）

```
往下翻          → scroll        {pixels: 480, direction: down}
往下翻一点       → scroll        {pixels: 240}
往下翻三屏       → scroll        {pixels: 2400}
往上翻          → scroll        {pixels: -480}
翻到底          → scroll_until  {direction: bottom}
回到顶部         → scroll_until  {direction: top}
点击登录按钮      → click_text    {text: 登录}
输入你好世界      → type          {text: 你好世界}
回车           → press         {key: enter}
复制           → hotkey        {keys: [ctrl, c]}
全选           → hotkey        {keys: [ctrl, a]}
关闭标签         → hotkey        {keys: [ctrl, w]}
双击那个文件      → double_click_text {text: 文件}
切换到微信        → focus_window  {title: 微信}
```

---

## 三、解决的真实问题

### 问题 1：中文输入不工作

`pyautogui.typewrite("你好")` 什么都不发生，因为 typewrite 只发 ASCII 键码。

**方案：剪贴板 + Ctrl+V**

```python
pyperclip.copy(text)
pyautogui.hotkey("ctrl", "v")
# 延迟 0.5s 后恢复原剪贴板，不污染用户剪贴板
```

实测：`输入 LAAP测试` → 281ms 成功。

---

### 问题 2：滚轮事件发错地方

`pyautogui.scroll()` 把滚轮发给**鼠标当前所在位置**。鼠标停在角落，页面纹丝不动。

**方案：滚动前把鼠标移到内容区中央**

```python
def _ensure_scroll_target(self):
    # 优先用显式指定的目标窗口矩形
    if self._target_window:
        rect = self._get_window_rect(self._target_window)
    else:
        rect = 前台窗口矩形
    # 移到中心偏上（避开标题栏和底部状态栏）
    self.pag.moveTo(rect.center_x, rect.top + rect.height * 0.45)
```

---

### 问题 3：Windows 前台锁

`pygetwindow.activate()` 会**返回成功但实际没抢到焦点**。Windows 有前台锁防止弹窗骚扰。

**方案：Win32 API 三级破解**

```python
def _force_focus(self, hwnd):
    # 1. 模拟 ALT 键（解除前台锁的经典技巧）
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)

    # 2. BringWindowToTop + SetForegroundWindow
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)

    # 3. 还不行就 AttachThreadInput 挂到前台线程输入队列
    user32.AttachThreadInput(cur_thread, fg_thread, True)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(cur_thread, fg_thread, False)
```

**关键：不盲信 API，用 `WindowFromPoint` 查真实可见性**

```python
def _ensure_visible(self, hwnd):
    # 引擎说"在前台"不算数，查那个坐标上到底是哪个窗口
    hwnd_at_point = user32.WindowFromPoint(POINT(x, y))
    root = user32.GetAncestor(hwnd_at_point, GA_ROOT)
    return root == hwnd
```

---

### 问题 4：滚轮在某些应用完全无效

**实证结果：**

| 应用 | 滚轮 | 键盘 |
|------|:----:|:----:|
| Windows 11 新版记事本（WinUI） | ✗ | ✓ |
| classic Win32 应用 | ✓ | ✓ |
| 部分 Electron 应用 | ✗ | ✓ |

WM_MOUSEWHEEL 直接 PostMessage 到窗口也不行。

**方案：自动降级到键盘**

```python
def scroll_until(self, direction):
    # 阶段 1：试滚轮
    wheel_result = self._scroll_until_wheel(...)

    if 真的翻动了:
        return wheel_result

    # 阶段 2：滚轮无效 → 键盘
    kb_result = self._scroll_until_keyboard(down, ...)
    if kb_result 有变化:
        kb_result.data["fallback_from_wheel"] = True
        return kb_result

    # 键盘也翻不动 → 真的在边界
    return wheel_result
```

键盘方案用 `Ctrl+End` / `Ctrl+Home` 一步到位，比逐页翻快得多。

**实测：**
```
翻到底    → 1.9s  已经在底了   [keyboard+降级]
回到顶部   → 1.8s  已经在顶了   [keyboard+降级]
往下翻    → 106ms 往下翻了     [wheel]
往下翻    → 106ms               (顶底对比差异 0.2494)
```

---

### 问题 5：怎么确认动作真的生效

**不能只信返回值。** 发送成功不等于效果发生。

**方案：截图对比（分带检测）**

```python
def _diff_bands(a, b, bands=8):
    """分带比较，不看全图平均

    整屏平均差异会被静态区域稀释：
      YouTube 中间 60% 是视频播放器，滚动时它不动
      整屏平均可能只有 1%，但下方列表已经滚了好几屏
    """
    把图像切成 8 个横带
    返回 (最大带差异, 各带差异列表)
```

阈值设计：
- `change_threshold = 0.004`（0.4%）
- 要求**连续 2 步**都低于阈值才算到边界

实测对照：
```
PageDown 后：max_band = 0.259   ← 明显变化
静止两帧：  max_band = 0.00003 ← 噪声级
```

---

## 四、元素定位：她说"点登录按钮"怎么找到

| 策略 | 精度 | 速度 | 适用 |
|------|------|------|------|
| **Windows UIA** | 精确（拿真实控件坐标） | 快（C++ 原生搜索） | 原生应用 |
| **视觉模型** | 归一化坐标 | 慢（1-3s） | UIA 找不到时 |
| 失败 | 诚实报告 | 快 | 不瞎点 |

### UIA 搜索的关键

不要用 Python 递归遍历（太慢、深度不够）。用原生搜索：

```python
ctrls = root.Control(
    searchDepth=20,
    ControlType=uia.ControlType.Button,
    SubName=text,       # 模糊匹配
)
```

比 Python 递归快 20-50 倍，深度也够。

### 为什么不让视觉兜底一切都好

UIA 找不到时（比如网页 canvas、游戏画面），用视觉模型看截图。
但如果视觉也说没有，**必须诚实说"没找到"，不能瞎点**。点错地方比点不到更糟。

---

## 五、安全设计

| 机制 | 说明 |
|------|------|
| **FAILSAFE** | 鼠标甩到屏幕左上角可紧急中断 |
| **保护区** | 可配置禁止点击区域（误触危险按钮） |
| **可见性校验** | 窗口不可见时不截图、不比较，避免误判 |
| **诚实报错** | 找不到元素 / 无法置前，都明确告知 |
| **动作留痕** | 所有动作记录在 `agent.history` |

---

## 六、文件

| 文件 | 作用 |
|------|------|
| `laaper/hub/computer_use.py` | 鼠标键盘操作 + 意图解析 + 滚动闭环 |
| `laaper/hub/voice_computer.py` | 语音驱动 Agent + 元素定位 |
| `laaper/hub/voice_bridge.py` | 语音桥接（ASR/TTS） |

---

## 七、依赖

```bash
pip install pyautogui pyperclip pygetwindow mss uiautomation pillow
```

实测环境：Windows 10.0.26200 / 3840x2160 / Python 3.11

---

## 八、实测数据

```
环境就绪：pyautogui + pyperclip + pygetwindow + mss + uiautomation 全部 OK
屏幕：3840x2160（4K，已开 DPI 感知）

意图解析：21/21 正确
真实动作：9/9 成功
  翻到底      1896ms  [keyboard+降级]
  回到顶部     1848ms  [keyboard+降级]
  往下翻       106ms  [wheel]
  往上翻       106ms  [wheel]
  输入中文      281ms  [clipboard]
  全选         66ms  [hotkey]
  复制         63ms  [hotkey]
  回车         61ms  [press]
  撤销         65ms  [hotkey]

滚动验证：顶部 vs 底部差异 0.2494（明显变化）
        重复翻到底后差异 0.0002（同一位置）
```

---

## 九、还没做的

| 缺口 | 说明 |
|------|------|
| 语音流直连 | ASR/TTS 通道建好，但没和小智 broker 的音频流对接 |
| 多步任务 | 现在一次一个动作，复杂任务要走 `BrowserAgentLoop` 的模式 |
| 视觉验证闭环 | 动作后只看像素变化，没让视觉模型确认"做对了吗" |
| 撤销机制 | 操作不可回滚，只能靠人工 |
