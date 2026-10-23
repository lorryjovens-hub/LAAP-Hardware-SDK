# 手机控制方案 — 完整技术文档

> 覆盖 iOS / Android 双平台，含小智 MCP 稳定性加固

---

## 一、为什么 ESP32 能控制手机？

**ESP32 不"黑"手机，它在绕 iOS 沙盒的两道墙。**

### iOS 沙盒的限制

```
拦住任何 App：
  ① 不能截别的 App 的屏幕
  ② 不能往别的 App 注入触摸
```

### 但 iOS 允许

```
① AirPlay 投屏出去 —— 对任何接收器开放
② 外接 USB 鼠标/键盘 —— 配辅助触控，指针就是手指
```

### ESP32 的角色

```
              ┌─────────────────────────┐
              │     ESP32-S3 硬件        │
              │                         │
  眼睛 ←──────┤ AirPlay 接收器           │
  手指 ───────┤ USB HID 鼠标/键盘        │
              └──────────┬──────────────┘
                         │ USB-C
                    ┌────┴────┐
                    │ iPhone  │
                    └─────────┘
```

**沙盒的墙被物理层绕过去了。**

---

## 二、iOS vs Android：安卓是降维打击

| 维度 | iOS | **Android** |
|------|-----|-------------|
| 截屏 | AirPlay 投屏（需 ESP32） | `adb exec-out screencap` |
| 点击 | USB HID（需 ESP32） | `adb shell input tap` |
| **UI 元素** | ❌ 靠视觉猜 | ✅ **`uiautomator dump` 直接给坐标** |
| 连接方式 | 必须 USB 插 ESP32 | ✅ **无线调试，连 ESP32 都不要** |
| 速度 | 30-100ms | **10-30ms** |
| 门槛 | 开辅助触控 | 开 USB 调试 |

### 关键优势：UI 元素树

Android 可以直接 dump 出所有元素：

```xml
<node text="设置" bounds="[120,240][360,320]" clickable="true" />
<node text="确定" bounds="[540,1800][800,1880]" clickable="true" />
```

**不用视觉模型猜坐标，直接拿到精确位置。** 这是 iOS 做不到的。

### 安卓开源方案调研

| 项目 | 工具数 | 特点 |
|------|-------|------|
| **scrcpy-mcp** | 44 | 完整 MCP 服务器，10-50x 速度，~33ms 截屏 |
| **droidrun** | - | 完整手机 agent 框架 |
| **NeuralBridge** | - | 亚 10ms 响应，无 root |
| **uiautomator2** | - | Python UI 自动化经典库 |

---

## 三、LAAP 手机控制架构

```
用户说话「帮我订明早8点的闹钟」
        ↓
┌───────────────────────────────────────────┐
│  LAAP 认知引擎                              │
│  · 全双工语音（Persona75ms）                │
│  · 意图理解（PSI 循环）                     │
│  · 记忆（记住你的习惯）                     │
└───────────────┬───────────────────────────┘
                ↓ MCP 工具
┌───────────────────────────────────────────┐
│  UnifiedPhoneController                    │
│  ┌─────────────┬──────────────────────┐   │
│  │  Android    │  iOS                  │   │
│  │  ADB 直连   │  AirPlay + ESP32 HID  │   │
│  └─────────────┴──────────────────────┘   │
└───────────────┬───────────────────────────┘
                ↓
┌───────────────────────────────────────────┐
│  手机屏幕                                   │
└───────────────────────────────────────────┘
```

---

## 四、模块清单

| 模块 | 用途 | 状态 |
|------|------|------|
| `types.py` | 数据类型 + 协议转换 | ✅ |
| `bridge.py` | iOS ESP32 TCP 桥接 | ✅ |
| `controller.py` | 手机控制抽象 | ✅ |
| `vision_loop.py` | 视觉-动作闭环 | ✅ |
| `mcp_tools.py` | 9 个 MCP 工具 | ✅ |
| `android.py` | **Android ADB 控制** | ✅ 新增 |
| `vision_model.py` | **视觉模型客户端** | ✅ 新增 |
| `airplay.py` | **AirPlay 接收** | ✅ 新增 |
| `unified.py` | **统一控制器** | ✅ 新增 |

---

## 五、视觉模型支持

自动检测环境变量，优先使用可用的：

| Provider | 模型 | 环境变量 |
|----------|------|---------|
| OpenAI | gpt-4o | `OPENAI_API_KEY` |
| Anthropic | claude-sonnet-4 | `ANTHROPIC_API_KEY` |
| 通义千问 | qwen-vl-max | `DASHSCOPE_API_KEY` |
| Ollama (本地) | llava | 无需 key |

---

## 六、小智 MCP 稳定性加固

### 诊断结果（实测）

原版 `XiaozhiBridge` 缺失：

| 能力 | 原版 | 加固版 |
|------|------|--------|
| 自动重连 | ❌ | ✅ |
| 心跳保活 | ⚠️ 有但不检查 | ✅ |
| 任务队列 | ❌ | ✅ |
| 断点续传 | ❌ | ✅ |
| 连接健康检查 | ❌ | ✅ |
| 指数退避 | ❌ | ✅ |

### 这就是"不稳定、做不了复杂任务"的根因

```
复杂任务需要多轮工具调用
        ↓
中途一次断线
        ↓
原版：整个任务失败，进度全丢
加固版：任务暂停 → 自动重连 → 从断点继续
```

### 加固方案

```python
from laap.xiaozhi_stable import StableXiaozhiBridge

bridge = StableXiaozhiBridge()
await bridge.start()

# 提交任务（自动排队 + 断点续传）
task_id = await bridge.submit_task("整理今天的日程并设提醒")

# 查询健康状态
health = bridge.health()
# {
#   "online_devices": 1,
#   "devices": {"xiaozhi-2045678": {"health_score": 85.3, ...}},
#   "tasks": {"running": 1, "paused": 0, ...}
# }
```

### 重连策略

```
第 1 次: 1s
第 2 次: 2s
第 3 次: 4s
第 4 次: 8s
第 5 次: 16s
第 6 次: 32s (封顶 60s)
每次 ±30% 抖动（防重连风暴）
```

---

## 七、小智设备查询的真相

### 架构限制

小智 MCP 是**反向架构**：

```
正常 MCP:  Agent → 问服务器 → 服务器返回工具列表
小智 MCP:  Broker → 问 Agent → Agent 返回工具列表
```

**所以我们查不到"有几台小智设备在线"**——只能看到设备通过 broker 调用我们的工具。

### 当前配置

```json
{
  "xiaozhi-2045678": {
    "url": "wss://api.xiaozhi.me/mcp/?token=...",
    "transport": "websocket_server"
  }
}
```

只有 **1 台**设备。如果要加更多，在 `~/.laap/mcp/servers.json` 里加。

### 怎么知道设备在线？

设备会主动调用 `device_status` / `device_heartbeat`，通过回调知道。加固版已支持多设备并发监控。

---

## 八、快速开始

### Android（推荐，最简单）

```bash
# 1. 安装 adb
# Windows: 下载 Android Platform Tools
# macOS: brew install android-platform-tools
# Linux: sudo apt install adb

# 2. 手机开启 USB 调试
# 设置 → 关于手机 → 连点版本号 7 次
# 设置 → 开发者选项 → USB 调试

# 3. 连接
adb devices
```

```python
from phone.android import AndroidController

android = AndroidController()
await android.connect()

# 截屏
frame = await android.screenshot()

# dump UI 元素（精确坐标！）
elements = await android.dump_ui()

# 按文字点击 — 不用猜坐标
await android.tap_text("设置")
```

### iOS

```bash
# 1. 烧录固件
cd firmware/esp32_phone
idf.py build flash

# 2. 插到手机，开辅助触控
# 设置 → 辅助功能 → 触控 → 辅助触控

# 3. 跑演示
python demo_phone_control.py --real
```

### AirPlay 投屏（iOS 眼睛）

```bash
# 安装 UxPlay
# Windows: 下载 release
# macOS: brew install uxplay
# Linux: sudo apt install uxplay
```

```python
from phone.airplay import AirPlayReceiver

receiver = AirPlayReceiver()
await receiver.start()
# 手机：控制中心 → 屏幕镜像 → 选择 LAAP-Aris
frame = await receiver.get_frame()
```

---

## 九、安全边界

| 风险 | 缓解 |
|------|------|
| 鼠标卡住 | 心跳 750ms 超时自动释放 |
| 动作卡死 | 2500ms 强制释放 |
| 任务跑飞 | 连续 3 步失败中止 |
| 高危操作 | 建议加人工确认（转账/删除/发消息） |
| ADB 权限 | 只在自己设备上开启调试 |

---

## 十、路线图

| 阶段 | 内容 | 状态 |
|------|------|------|
| v0.1 | iOS HID + 视觉闭环 | ✅ |
| v0.2 | Android ADB 控制 | ✅ |
| v0.3 | 视觉模型多商适配 | ✅ |
| v0.4 | AirPlay 接收 | ✅ |
| v0.5 | 小智稳定性加固 | ✅ |
| v0.6 | Android 无线调试 | 🔲 |
| v0.7 | ESP32 自实现 AirPlay | 🔲 |
| v1.0 | 多设备协同 | 🔲 |

---

**LAAP — 让数字生命体拥有双手**