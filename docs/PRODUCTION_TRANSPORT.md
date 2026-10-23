# LAAP 三端传输与生产级方案

> 回答：用什么传输、怎么上生产、DeepSeek 怎么适配

---

## 一、传输方案：WebSocket 双通道

### 逐项对比

| 方案 | 方向 | 延迟 | 断线恢复 | 结论 |
|------|------|------|---------|------|
| HTTP 轮询 | 单向请求 | 取决于轮询间隔 | 天然 | ❌ 资源浪费 |
| SSE | 只能服务器→客户端 | 中 | 自带重连 | ❌ 客户端没法推 |
| **WebSocket** | **双向全双工** | **局域网 <10ms** | 需自实现 | ✅ **主通道** |
| 蓝牙 BLE | 双向 | 中 | 需重连 | ⚠️ 只做配网 |
| MQTT | 双向 | 低 | 好 | ❌ 三端不够用，过度设计 |
| gRPC | 双向 | 低 | 需自实现 | ❌ 浏览器支持差 |

**结论：WebSocket 做主力。SSE 不用。BLE 只做配网引导。WiFi 只是底层管子。**

### 为什么不用 SSE

三端联动必须双向：
- 中枢推任务给节点（服务器→客户端）
- 节点上报感知和结果（客户端→服务器）

SSE 只有前者。硬要配一套 HTTP POST 反推，比 WS 更麻烦还更慢。

### 为什么 BLE 不能做主通道

BLE 4.2 实际带宽 20-50 kbps。
一张 720p JPEG（150 KB）要传约 30 秒。

**BLE 的正确用途：配网引导。** 手机第一次连的时候，通过 BLE 把 WiFi 密码和 token 传过去，之后全走 WiFi。

### 双通道架构

```
┌──────────────────────────────────────────────────────┐
│  通道 A：局域网直连 (LAN Direct)                       │
│                                                      │
│    ws://192.168.10.167:8765                          │
│                                                      │
│    · 延迟 <10ms                                       │
│    · 不经云端，隐私最好                                │
│    · 不耗流量                                         │
│    · 只在家/办公室同一 WiFi                            │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│  通道 B：云端中继 (Cloud Relay)                        │
│                                                      │
│    wss://api.laap.cn/ws                              │
│                                                      │
│    · 账号体系（JWT）                                   │
│    · 4G/5G/任何网络可达                                │
│    · Cloudflare + TLS                                │
│    · 延迟 30-150ms                                    │
└──────────────────────────────────────────────────────┘

选择策略：先试 A，3 秒超时降级到 B。
```

### 什么时候走哪条

| 场景 | 手机 | 电脑 | 硬件 | 通道 |
|------|------|------|------|------|
| 在家 | 家里WiFi | 家里 | 家里 | **全 A**，10ms |
| 外出 | 4G | 家里 | 家里 | 手机走 B，其余走 A |
| 全部外出 | 4G | 公司 | 公司 | **全 B** |

### 云服务器账号体系的作用

不只是"中继"，还干四件事：

**1. 跨网寻址**
你在外面，怎么找到家里的中枢？
```
中枢 → 连 wss://api.laap.cn/ws → JWT 认证 → 服务器记住
手机 → 连同一个服务器 → 服务器按 user_id 配对
```

**2. 设备归属**
每个节点绑定 user_id。**用户 A 的节点不能被用户 B 触达。**

**3. 离线消息**
节点不在线时暂存，上线补发。

**4. 审计**
所有跨网动作留痕，这是安全边界。

---

## 二、生产级要解决的 10 件事

### 1. 认证

| 通道 | 机制 |
|------|------|
| 局域网 | 预共享密钥（`X-LAAP-Key`），可选 TLS |
| 云端 | JWT（HS256）+ 设备指纹 |

```python
TransportConfig(
    shared_key="your-lan-key",     # 局域网
    jwt_secret="your-jwt-secret",  # 云端
    require_auth=True,
)
```

### 2. 断线重连

指数退避 + 抖动：

```
第1次 1s → 2s → 4s → 8s → 16s → 32s → 60s(封顶)
每次 ±30% 抖动
```

局域网连 3 次不通自动降级到云端。

### 3. 消息顺序

每条消息带递增 `seq`：
- 收到 `seq <= last` → 判断为重放，丢弃
- 收到 `seq > last + 1` → 判断为丢包，告警

### 4. 幂等（最危险的那个）

**场景：**
```
手机执行「点击购买」
结果回传时网络断了
手机不知道，重连后重发
没有幂等保护 → 买了两次
```

**机制：**
```python
idempotency_key = sha256(from + to + kind + payload)[:24]
```
中枢 5 分钟内见过同样的 key → 直接返回缓存结果，不再执行。

实测：
```
第 1 次: 已执行=False
第 2 次: 已执行=True, 缓存结果={'bought': True}
✓ 重复动作被拦截，不会买两次
```

### 5. 背压控制

```python
max_queue_size=1000     # 队列上限
```
队列满了丢弃并告警，不让中枢内存爆。

### 6. 多租户隔离

`user_id` + `session_id` 双重校验。跨租户消息直接拒绝。

### 7. 可观测性

```json
{
  "messages_sent": 1523,
  "messages_received": 1498,
  "bytes_sent": 2345678,
  "errors": 2,
  "reconnects": 1,
  "latency_p50": 8.3,
  "latency_p95": 24.1,
  "latency_p99": 41.7
}
```

延迟用采样 + 分位数，不是平均值（平均值会掩盖长尾）。

### 8. 限流

`rate_limit_per_minute=300` 每节点。防恶意刷和设备失控。

### 9. 优雅降级

```
视觉模型 → DOM 文本 → 纯结构化
局域网    → 云端中继
LLM 规划  → 规则规划
```

每一层都有兜底。

### 10. 审计

```python
{
  "event": "task_result",
  "node_id": "phone-01",
  "task_id": "task_abc123",
  "success": true,
  "ts": 1792778000.0,
}
```

**谁在什么时候对哪个节点做了什么，全记录。这是安全边界，不是可选功能。**

---

## 三、DeepSeek 适配：不用视觉也能操作电脑

### 关键洞察

人眼有两条通路：

```
腹侧通路（ventral）: "这是什么"  → 需要图像识别
背侧通路（dorsal）  : "在哪、怎么够" → 只需要空间关系
```

**操作计算机主要用背侧通路。** 你不需要认出"这是个按钮"，你只需要知道"那里有个可点的东西"。

而我们的结构化感知层（DOM）给的正是背侧信息：

| 需要什么 | DOM 给了什么 |
|---------|-------------|
| 这是什么元素 | `tag=button, text="登录"` |
| 在哪 | `@0.50,0.10` 归一化坐标 |
| 能点吗 | `enabled=true, clickable=true` |
| 唯一标识 | `#login-btn` CSS selector |

**这已经足够精准操作，而且比视觉更强：**

| 维度 | 纯视觉 | DOM + 文本 |
|------|--------|-----------|
| 坐标精度 | 猜，容易错 | 精确 |
| 文字识别 | OCR 可能错 | 原文 |
| token 成本 | 图像 token（高） | 文本 token（低 10x） |
| 延迟 | 视觉模型调用 | 文本模型调用（快 3-5x） |
| 复杂布局 | 容易漏 | 完整树 |

### 所以 DeepSeek 完全够用

DeepSeek 没有视觉 API，但有了 DOM 感知，它做 Computer Use **比视觉方案更好**。

实测 planner：

```
输入: 帮我打开 laap.cn 截图发我手机
理解: 在电脑上打开 laap.cn 并截图，然后把截图发到手机上显示
步骤: 3
  - browse:     在电脑浏览器打开 laap.cn
  - screenshot: 对打开的网页截屏
  - display:    把截图推送到手机端显示
```

```
输入: 把刚才那张图发给我妈
理解: 用户想把图发给联系人"妈"，但当前没有消息发送能力，
      且无法确定"刚才那张图"是哪一张。
步骤: 0   ← 正确地拒绝了
```

```
输入: 手机上看看有没有新消息
理解: 系统没有读取手机通知的能力（手机端只支持拍照、震动、
      GPS、触摸），无法读取通知内容。
步骤: 0   ← 又一个正确的拒绝
```

**能正确拒绝，比能执行更重要。** 规则 planner 做不到这个。

### 混合策略：什么时候才用视觉

```python
class HybridVisionStrategy:
    VISION_TRIGGERS = (
        "验证码", "图片", "颜色", "长什么样", "看起来",
        "布局", "图标", "logo", "照片", "截图", "画面",
    )
```

实测：

| 指令 | 策略 |
|------|------|
| 点击登录按钮 | DOM 优先（快、准） |
| 看看这个验证码是什么 | **视觉优先**（OCR 不可靠） |
| 页面上那个图片是什么 | **视觉优先** |
| 填写用户名 | DOM 优先 |

视觉只在**真的需要看图像内容**时才调用。这样 90% 的操作都不花视觉 token。

### 小智硬件结合

```
DeepSeek 规划
    ↓
小智硬件的能力：
  · 温度/湿度/压力传感器 → 环境感知帧
  · 麦克风 → 语音输入
  · 扬声器 → 语音输出
  · 继电器 → 控制物理设备
    ↓
"我有点热，告诉我温度"
→ 读小智温度传感器 → DeepSeek 理解上下文 → 语音播报
```

---

## 四、Android 接入：降维打击

### 为什么安卓比 iOS 简单一个数量级

| 维度 | iOS | Android |
|------|-----|---------|
| 截屏 | AirPlay 投屏（需 ESP32） | `adb exec-out screencap` |
| 点击 | USB HID（需 ESP32） | `adb shell input tap` |
| **UI 元素** | ❌ 只能视觉猜 | ✅ **`uiautomator dump` 精确坐标** |
| 连接 | 必须插线 | ✅ **无线调试** |
| 门槛 | 辅助触控 | USB 调试 |

### 核心优势：UI 元素树

```
<node text="设置" bounds="[120,240][360,320]" clickable="true" />
<node text="确定" bounds="[540,1800][800,1880]" clickable="true" />
```

**不用视觉模型猜坐标，直接拿到精确位置。**

### 已实现能力

| 动作 | adb 命令 |
|------|---------|
| 截屏 | `exec-out screencap -p` |
| UI dump | `shell uiautomator dump` |
| 点击 | `shell input tap x y` |
| 滑动 | `shell input swipe` |
| 输入 | `shell input text` |
| 按键 | `shell input keyevent` |
| 启动应用 | `shell monkey -p pkg` |
| 震动 | `shell cmd vibrator vibrate` |
| 电量 | `shell dumpsys battery` |
| 无线连接 | `connect ip:5555` |

### 使用

```bash
# 1. 手机开启 USB 调试
#    设置 → 关于手机 → 连点版本号 7 次
#    设置 → 开发者选项 → USB 调试

# 2. 插线，授权这台电脑（手机屏幕弹窗要点允许）
adb devices

# 3. 开启无线调试（可选，之后就免线）
adb tcpip 5555
adb connect 192.168.10.x:5555
```

```python
from laaper.hub import TriNodeHub, register_android_node

hub = TriNodeHub(laaper_id="aris")
hub.register_phone("phone-01")

result = await register_android_node(hub, "phone-01")
# result: {
#   "success": True,
#   "serial": "192.168.10.x:5555",
#   "screen": "1080x2400",
#   "handlers": ["screenshot", "ui_dump", "tap", "click", "type",
#                "swipe", "press_key", "launch_app", "vibrate", "battery"]
# }
```

然后手机就出现在节点列表里，中枢可以派任务给它。

---

## 五、文件清单

| 文件 | 作用 |
|------|------|
| `laaper/hub/llm_planner.py` | DeepSeek 任务规划 + Computer Use + 混合视觉策略 |
| `laaper/hub/transport.py` | 生产级传输（双通道 + 幂等 + 背压 + 审计） |
| `laaper/hub/android_node.py` | Android ADB 接入 |
| `laaper/hub/node.py` | 节点能力 + 路由 |
| `laaper/hub/session.py` | 统一会话 + 数据分层 |
| `laaper/hub/hub.py` | 三端总线 |
| `laaper/hub/voice_bridge.py` | 语音桥接 |

---

## 六、依赖环境

```bash
# Python 包
pip install websockets pyjwt playwright av pillow httpx

# 浏览器内核
playwright install chromium

# ADB（已装到 D:\LAAP\tools\platform-tools\）
# Windows: 下载 Android Platform Tools 解压
# macOS: brew install android-platform-tools
# Linux: sudo apt install adb
```

环境变量：

```bash
set DEEPSEEK_API_KEY=sk-xxx        # LLM 规划（主）
set SENSENOVA_API_KEY=sk-xxx       # 视觉兜底
set ADB_PATH=D:\path\to\adb.exe     # 可选，自动探测
```

---

## 七、上生产还要补的

| 缺口 | 优先级 | 说明 |
|------|-------|------|
| **云端中继服务** | P0 | `wss://api.laap.cn/ws` 还没部署，目前只有局域网可用 |
| **真实节点客户端** | P0 | 现在 Node 是进程内调用，要出真客户端（手机 App / 硬件固件） |
| **JWT 密钥管理** | P1 | 现在是明文配置，要换成密钥管理服务 |
| **消息持久化** | P1 | 离线消息现在只在内存 |
| **压力测试** | P1 | 没用真实并发压过 |
| **TLS 证书** | P1 | 局域网默认明文，生产要上 mTLS |
| **审计落盘** | P2 | 现在审计只在内存，要写库 |
| **灰度发布** | P2 | 多节点版本兼容策略 |

---

**LAAP — 一个意识，三套身体，一套神经系统**
