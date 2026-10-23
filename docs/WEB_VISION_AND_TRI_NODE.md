# LAAP 网页视觉 + 三端联动 — 架构方案

> 解决两个问题：Aris 看不见网页 / 电脑·手机·小智硬件怎么联动

---

## 第一部分：为什么 Aris 看不见网页

### 诊断结果

查了代码，发现三个断点：

| 断点 | 位置 | 症状 |
|------|------|------|
| **1. 工具只返回 base64，从不调用视觉模型** | `browser_auto.py: browser_vision` | 返回 `"configure a vision-capable LLM"` 占位文本 |
| **2. `screenshot_analyze` 只做 OCR 和元数据** | `vision.py` | 拿不到图就只返回格式和尺寸 |
| **3. 视觉能力默认判定为 False** | `_llm_supports_vision()` | 除非手动设 `LAAP_LLM_VISION=1` |

**本质问题**：她有眼睛（截图能力），但那张图从来没送进会看的脑子。

### 解决方案：双层感知

```
┌─────────────────────────────────────────────┐
│  第一层：结构化感知（DOM）— 始终可用           │
│  · 所有可交互元素的精确 selector              │
│  · 页面全部文字内容                          │
│  · 元素位置、可见性、启用状态                 │
│                                             │
│  这层比视觉更强：精确。不猜坐标。             │
└─────────────────┬───────────────────────────┘
                  ↓
┌─────────────────────────────────────────────┐
│  第二层：视觉感知（截图 + 标注）               │
│  · 截图                                      │
│  · 在可交互元素上画编号方框                   │
│  · 视觉模型说"点第 5 个框"                    │
│                                             │
│  这层补足 DOM 拿不到的：布局、图片、视觉状态   │
└─────────────────────────────────────────────┘
                  ↓
        统一的页面描述（Aris 的"看见"）
```

### 视觉后端自动探测

按优先级找可用的：

| Provider | 模型 | 环境变量 | 备注 |
|----------|------|---------|------|
| **SenseNova** | sensenova-6.8-flash-lite | `SENSENOVA_API_KEY` | 256K 上下文，支持图像 |
| OpenAI | gpt-4o | `OPENAI_API_KEY` | |
| 通义千问 | qwen-vl-max | `DASHSCOPE_API_KEY` | |
| OpenRouter | claude-sonnet-4.5 | `OPENROUTER_API_KEY` | |
| Ollama | llava | 无需 key | 本地 |

### 实测结果

打开 `https://www.laap.cn`：

```
标题: LAAP — 世界首个意识工程数字生命体
元素数: 19
文字长度: 8000
感知耗时: 11832ms

【Aris 看到的】
1. 这是一个 AI 产品的首页/落地页。
2. 最显眼的是左侧巨大的"LAAP 意识工程数字生命体"标题，
   以及右侧展示实时分析能力的"LAAP Studio"交互界面。
3. 用户最可能点击醒目的"进入 Studio"按钮开始体验。

【可交互元素】
[1] a "首页" @0.26,0.05
[3] button "产品" @0.38,0.05
[12] a "进入 Studio" @0.92,0.05
[15] * button "进入 Studio" @0.10,0.74   ← 红色高亮（显眼大按钮）
[16] button "观看愿景片" @0.23,0.71
```

**她真的看见了。**

### 新增工具

| 工具 | 用途 |
|------|------|
| `browser_vision` | 完整感知：DOM + 截图 + 视觉理解 |
| `browser_see` | 只返回可读文本描述（省 token） |
| `browser_do_task` | 自主完成网页任务（看→想→做→再看循环） |
| `browser_vision_status` | 检查视觉后端状态 |

### 自主循环

```python
from laap.tools.browser_perception import (
    BrowserPerception, BrowserAgentLoop
)

perception = BrowserPerception(page, annotate=True)
agent = BrowserAgentLoop(perception, max_steps=20)

result = await agent.run("搜索 LAAP 并打开第一个结果")
```

循环机制：

```
看 → 决定 → 执行 → 再看 → ...
        ↑                  ↓
        └─── 停滞检测 ─────┘
         (连续 3 步页面无变化则中止)
```

关键设计：**每步都重新感知，不假设动作成功了**。

---

## 第二部分：三端联动方案

### 三个载体，三种身体

| 节点 | 独有能力 | 缺什么 | 角色 |
|------|---------|--------|------|
| **电脑** | 高算力、全 OS 控制、浏览器 | 不能随身 | 大脑 + 双手 |
| **手机** | 移动、摄像头、GPS、触摸 | 算力低 | 移动感官 + 随身屏 |
| **小智硬件** | 语音输入输出、物理在场 | 只有嘴和耳朵 | 嘴和耳朵 |

**关键洞察**：三者不该各自为政，应该是**同一个意识的三套器官**。

### 架构

```
                    ┌──────────────────────────────────┐
                    │  TriNodeHub（中枢）                │
                    │  ┌────────────┬────────────┬────┐ │
                    │  │ 节点注册    │ 统一会话    │数据面│ │
                    │  ├────────────┴────────────┴────┤ │
                    │  │  任务编排                     │ │
                    │  │  拆解 → 路由 → 接力 → 汇总     │ │
                    │  └───────────────────────────────┘ │
                    └───────┬──────────┬──────────┬─────┘
                            │          │          │
                        ┌───┴───┐  ┌───┴───┐  ┌───┴────┐
                        │  PC   │  │ Phone │  │ Xiaozhi│
                        └───────┘  └───────┘  └────────┘
```

### 核心设计判断一：数据分层

**不做全帧广播。** 这是整个方案最关键的一个决定。

```
控制面（轻量，全端同步）
  · 说了什么话（文字）
  · 谁在说（节点标识）
  · 意图、情绪、当前任务
  · 数据引用 ID（不是数据本身）
  → 几十字节到几 KB

数据面（重载，按需拉取）
  · 截图（几百 KB - 几 MB）
  · 录音、视频（几 MB）
  · 文件内容
  → 只传引用 ID
```

**为什么**：小智硬件内存只有几百 KB，收到一张 4K 截图直接爆。所以图存中枢，硬件只拿 `payload_id`。

### 核心设计判断二：能力路由

每个节点上报能力，中枢据此决定派谁：

```python
def score_node_for_task(node, requirement) -> float:
    # 硬门槛：缺能力直接 0 分
    if not req.needs_sensors.issubset(caps.sensors): return 0
    if not req.needs_actuators.issubset(caps.actuators): return 0
    if caps.compute < req.min_compute: return 0

    # 软加分
    score = 0.5 + caps.compute * 0.2 + caps.battery * 0.1
    if caps.always_on: score += 0.1
    if req.latency_critical and node.kind == PC: score += 0.15
    if GPS needed and node.kind == PHONE: score += 0.15
    if DISPLAY needed and node.kind in (PHONE, HARDWARE): score += 0.25
    ...
```

实测路由结果：

| 任务 | 路由到 | 得分 |
|------|-------|------|
| 浏览网页 | pc-01 | 0.90 |
| 手机拍照 | phone-01 | 0.86 |
| 语音播报 | pc-01 | 0.90 |
| GPS 定位 | phone-01 | 0.81 |
| 执行命令 | pc-01 | 0.90 |
| **把图发到手机** | **phone-01** | **+0.25** |

### 真实场景走一遍

**你说**：「帮我在电脑上打开 laap.cn 网页，截图发我手机」

**中枢拆成 3 步**：

```
步骤 1: 在电脑上打开网页
  需要: browse 能力 + 算力 ≥ 0.5
  路由: pc-01 (得分 0.90)
  执行: playwright 打开 → 6.7s

步骤 2: 截取页面截图
  需要: screen 感知
  路由: pc-01 (得分 0.90)
  执行: BrowserPerception → 12.4s
  产出: payload_id → 0.38 MB 图存入数据面

步骤 3: 把截图显示到手机
  需要: display 能力
  路由: phone-01 (得分 0.86，DISPLAY 加成)
  执行: 推送 payload_id → 10ms
```

**中枢回复**：「已在电脑上打开 https://www.laap.cn，截了图，发到你手机了。」

**小智硬件播报**：语音合成这句话。

### 会话共享机制

三端看到同一段对话：

```
用户@xiaozhi-01: 帮我在电脑上打开 https://www.laap.cn 网页，截图发我手机
节点@pc-01: LAAP 电脑端 online
节点@phone-01: LAAP 手机端 online
节点@xiaozhi-01: 小智硬件 online
LAAPer@xiaozhi-01: 已在电脑上打开 https://www.laap.cn，截了图，发到你手机了。
用户@phone-01: 执行 dir 命令
LAAPer@phone-01: 命令执行完成。
```

`@节点` 标注来源——这样 LLM 知道每句话是从哪个身体说的。

### 语音桥接

```
小智硬件（麦克风）
    ↓ ASR（SenseNova）
语音桥接
    ↓ text
TriNodeHub.handle_input()
    ↓ 拆任务 + 路由
各端执行
    ↓ 结果
语音桥接（TTS）
    ↓ 播报文本整形（去 markdown、缩短 URL、截断）
小智硬件（扬声器）
```

播报整形示例：

```
原文: 已在电脑上打开 **https://www.laap.cn/very/long/path...**，截了图，发到你手机了。
播报: 已在电脑上打开 链接
```

---

## 第三部分：文件清单

### 网页视觉

| 文件 | 作用 |
|------|------|
| `laap/tools/browser_perception.py` | **新增** 双层感知 + 视觉后端探测 + 自主循环 |
| `laap/tools/browser_auto.py` | **重写** `browser_vision`，新增 `browser_see`/`browser_do_task` |
| `laap/tools/vision.py` | **重写** 真正调用视觉模型 |

### 三端联动

| 文件 | 作用 |
|------|------|
| `laaper/hub/node.py` | **新增** 节点能力声明 + 路由算法 |
| `laaper/hub/session.py` | **新增** 统一会话 + 数据分层 |
| `laaper/hub/hub.py` | **新增** 三端联动总线 |
| `laaper/hub/voice_bridge.py` | **新增** 语音桥接 + 标准端处理器 |

---

## 第四部分：环境依赖

```bash
# 必需
pip install playwright pillow httpx
playwright install chromium

# 可选（本地视觉模型）
# 安装 ollama + llava 模型
```

环境变量（任选一个，自动探测）：

```bash
set SENSENOVA_API_KEY=sk-xxx      # 推荐，你已经有
set OPENAI_API_KEY=sk-xxx
set DASHSCOPE_API_KEY=sk-xxx
```

---

## 第五部分：路线图

| 阶段 | 内容 | 状态 |
|------|------|------|
| v0.1 | 网页双层感知（DOM + 视觉） | ✅ |
| v0.2 | 元素标注截图 | ✅ |
| v0.3 | 自主浏览循环 | ✅ |
| v0.4 | 三端节点注册 + 能力路由 | ✅ |
| v0.5 | 跨端任务接力 | ✅ |
| v0.6 | 语音桥接（ASR + TTS） | ✅ |
| v0.7 | 真实 WebSocket 节点连接 | 🔲 |
| v0.8 | 手机客户端（Android/iOS） | 🔲 |
| v0.9 | 小智硬件语音直连 | 🔲 |
| v1.0 | 意识帧跨端无缝穿行 | 🔲 |

---

**LAAP — 一个意识，三套身体**
