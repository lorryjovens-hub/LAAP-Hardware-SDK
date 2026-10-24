# LDP — LAAP Device Protocol v1.0

> 硬件统一接入协议。四类机器人（宠物/狗/车/桌面）共用一套消息。

---

## 设计目标

1. **LAAP 不需要知道对面是什么身体** —— 只说「前进/坐下/看着我」
2. **能力协商** —— 设备上线声明自己会什么，LAAP 据此派活
3. **可复用现有传输** —— 不新造轮子，跑在已有的三端链路上

---

## 传输层

| 通道 | 地址 | 用途 |
|------|------|------|
| 局域网 | `ws://<ip>:8765` | 同一 WiFi，延迟 <10ms |
| 云端中继 | `wss://api.laap.cn/ws` | 跨网（设备在外面） |
| 屏幕流 | `ws://<ip>:8766` | 只给需要屏幕的设备（P4 终端） |

**编码约定**
- 文本帧 = JSON（LDP 消息）
- 二进制帧 = 音频（Opus 16k/20ms）或图像（4 字节长度头 + JPEG）

---

## 消息格式

```json
{
  "kind": "motion.move",
  "device_id": "pet-01",
  "msg_id": "ldp_a1b2c3d4e5",
  "ts": 1792823766.12,
  "payload": { "vx": 150, "vy": 0, "omega": 0 },
  "ack_required": false,
  "reply_to": ""
}
```

---

## 消息族

### 一、注册（设备 → LAAP）

#### `hello`
设备上线第一句话，声明身份与能力。

```json
{
  "kind": "hello",
  "device_id": "dog-01",
  "payload": {
    "device_id": "dog-01",
    "name": "LAAP 机械狗",
    "kind": "dog",
    "capabilities": {
      "sensors": ["imu", "touch", "distance"],
      "actuators": ["motion"],
      "poses": ["stand", "sit", "home", "wave"],
      "motion": "quadruped",
      "joints": 12,
      "dialogue": true
    },
    "protocol": "ldp/1.0"
  }
}
```

**kind 取值**：`car` / `dog` / `pet` / `desktop`

#### `hello_ack`（LAAP → 设备）

```json
{"kind": "hello_ack", "payload": {"stream": "960px@15fps", "audio": true}}
```

#### `heartbeat`
设备每 25 秒一次；LAAP 45 秒收不到判离线。

```json
{"kind": "heartbeat", "device_id": "dog-01", "payload": {"ts": 1792823766}}
```

---

### 二、感知（设备 → LAAP）

#### `percept`

```json
{
  "kind": "percept",
  "device_id": "dog-01",
  "payload": {
    "sensor": "imu",
    "data": {"roll": 1.2, "pitch": -0.8, "yaw": 45.0}
  }
}
```

| sensor | 数据 | 谁会上报 |
|--------|------|---------|
| `imu` | roll/pitch/yaw | 全部 |
| `touch` | {zone, pressed} | 宠物/狗（摸头反应） |
| `distance` | {mm} | 车/狗（避障） |
| `image` | {payload_ref} | 有摄像头的 |
| `audio` | {payload_ref} | 全部 |
| `battery` | {percent, voltage} | 全部 |

---

### 三、运动（LAAP → 设备）

#### `motion.move` 速度控制

```json
{"kind": "motion.move", "payload": {"vx": 150, "vy": 0, "omega": 30}}
```

| 字段 | 含义 | 单位 | 注 |
|------|------|------|-----|
| vx | 前后速度 | mm/s | 正=前 |
| vy | 横移速度 | mm/s | 车不支持（忽略） |
| omega | 转向角速度 | deg/s | 正=左转 |

#### `motion.pose` 命名姿态

```json
{"kind": "motion.pose", "payload": {"name": "sit"}}
```

| kind | 支持的姿态 |
|------|-----------|
| car | stop / home |
| dog | stand / sit / home / wave |
| pet | home / look_up / look_down / think / sleep / nod |

> **能力协商的意义**：宠物没有 `sit`，LAAP 下发前先查 `capabilities.poses`，
> 不在列表里就降级表达（比如用 `look_down` + 语音"我坐下啦"）。

#### `motion.action` 复合动作

```json
{"kind": "motion.action", "payload": {"name": "shake_hands", "params": {"repeat": 2}}}
```

留给复杂动作（跳舞、握手序列）。设备不认识就回 `error`。

#### `motion.stop` 急停

```json
{"kind": "motion.stop", "payload": {}}
```

**必须无条件响应**，优先级最高。

---

### 四、对话（双向）

#### `dialogue.text`

```json
{"kind": "dialogue.text", "payload": {"role": "assistant", "text": "好的，我过来了"}}
```

#### `dialogue.state`

让设备知道该做什么表情/动画：

```json
{"kind": "dialogue.state", "payload": {"state": "thinking"}}
```

| state | 设备表现 |
|-------|---------|
| `listening` | 看向用户、耳朵竖起、屏幕波纹 |
| `thinking` | 微微偏头、眼睛转动 |
| `speaking` | 播报 + 口型/屏幕波形 |
| `idle` | 呼吸动画、偶尔眨眼 |

---

### 五、状态（设备 → LAAP）

#### `state.report`

```json
{
  "kind": "state.report",
  "device_id": "dog-01",
  "payload": {
    "battery": 87,
    "motion": {"gait": "trot", "phase": 0.34},
    "pose": "stand",
    "uptime_s": 3600
  }
}
```

---

## 语义映射表（中文 → 运动指令）

LAAP 侧内置，设备侧不用管：

| 中文 | 指令 |
|------|------|
| 前进 / 往前走 / 走 | `{"cmd":"move","vx":150}` |
| 快点前进 | `{"cmd":"move","vx":300}` |
| 后退 / 倒 | `{"cmd":"move","vx":-150}` |
| 左转 / 往左 | `{"cmd":"move","omega":60}` |
| 右转 / 往右 | `{"cmd":"move","omega":-60}` |
| 坐下 / 坐着 | `{"cmd":"pose","name":"sit"}` |
| 站起来 / 起立 | `{"cmd":"pose","name":"stand"}` |
| 打个招呼 / 挥手 | `{"cmd":"pose","name":"wave"}` |
| 看着我 / 抬头 | `{"cmd":"pose","name":"look_up"}` |
| 停 / 别动 | `{"cmd":"stop"}` |

---

## 错误处理

```json
{"kind": "error", "payload": {"code": "unsupported_pose", "detail": "pet has no 'sit'"}}
```

| code | 含义 |
|------|------|
| `unsupported_pose` | 姿态不支持 |
| `unreachable` | 运动学不可达（狗腿够不到） |
| `busy` | 正在执行别的动作 |
| `low_battery` | 电量过低拒绝动作 |

---

## 可靠性

| 机制 | 做法 |
|------|------|
| 心跳 | 设备 25s 一次，LAAP 45s 判离线 |
| 急停优先 | `motion.stop` 不走队列，立即执行 |
| 消息去重 | `msg_id` + 5 分钟缓存 |
| 断线重连 | 指数退避 1→30s |
| 离线缓存 | 中继暂存 100 条 / 5 分钟 |

---

## 最小实现清单（写固件时按这个逐项打勾）

- [ ] WS 连接 + hello 注册（带 capabilities）
- [ ] heartbeat 定时器（25s）
- [ ] 解析 `motion.move` → 驱动电机/舵机
- [ ] 解析 `motion.pose` → 姿态表查表
- [ ] 解析 `motion.stop` → 立即刹车（最高优先级）
- [ ] 解析 `dialogue.state` → 表情/动画切换
- [ ] 上报 `percept`（至少 imu + battery）
- [ ] 上报 `state.report`（5s 一次）
- [ ] 不认识的 kind 回 `error`，不要静默丢弃
