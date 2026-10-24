# LAAP 三端互通协议 — 注册 · 感知 · 操纵

> 小智硬件 ↔ 手机 ↔ 电脑：互相注册、感知、操纵的完整规范
> 中继：`wss://api.laap.cn/ws`（Cloudflare Worker + Durable Objects）

---

## 一、角色

| 节点 | node_id | role | 有什么 |
|------|---------|------|--------|
| 电脑 | `pc-hub` | hub | 高算力、浏览器、键鼠、终端 |
| 手机 | `phone-01` | node | GPS、相机、通知、振动、喇叭 |
| 小智硬件 | `xiaozhi-01` | node | 麦克风、扬声器、温度/湿度、继电器 |

**hub 和 node 是对等的**——谁都能给谁派活。hub 额外维护全局注册表。

---

## 二、三种消息（协议核心）

### 1. 注册 `register`

节点上线时广播自己的能力，其他人据此知道"找谁干活"：

```json
{
  "kind": "register",
  "from_node": "phone-01",
  "to_node": "*",
  "payload": {
    "node_id": "phone-01",
    "name": "LAAP 手机",
    "role": "node",
    "capabilities": {
      "sensors":    ["gps", "camera", "screen", "notification", "battery"],
      "actuators":  ["open_app", "vibrate", "notify", "speak", "read_gps"],
      "resources":  {"compute": 0.4, "battery": 0.85}
    }
  }
}
```

- 连通时发一次 + 每次重连后重发
- 中继同时广播 `node_state`（online/offline），所有人实时知道谁在

### 2. 感知 `perception`

节点主动上报传感器/状态，或应请求回答：

```json
{
  "kind": "perception",
  "from_node": "phone-01",
  "to_node": "pc-hub",
  "payload": {"sensor": "gps", "data": {"lat": 31.23, "lng": 121.47}}
}
```

| sensor | 谁报 | 数据 |
|--------|------|------|
| gps | 手机 | lat/lng/accuracy |
| temperature | 小智 | 26.5 °C |
| battery | 手机/硬件 | 电量百分比 |
| system | 任何 | model/battery/screen_on |

### 3. 操纵 `task_assign` / `task_result`

任意节点互相派活，做完回执：

```json
// 请求
{"kind": "task_assign", "from_node": "pc-hub", "to_node": "phone-01",
 "payload": {"request_id": "req_123", "action": "vibrate", "params": {"duration": 300}}}

// 回执
{"kind": "task_result", "from_node": "phone-01", "to_node": "pc-hub",
 "payload": {"request_id": "req_123", "success": true, "result": {"vibrated": true}}}
```

`request_id` 用于配对——谁发的活，谁的回应只有自己能认领。

---

## 三、每个节点的动作与感知（能力表）

### 电脑 `pc-hub`（TriNodeDaemon）

| action | 干的事 |
|--------|--------|
| `voice_command` | 自然语言控制电脑（语音意图层全覆盖） |
| `computer_task` | 多步任务（LLM 规划，看→想→做→验） |
| `pc_scroll` / `pc_click` / `pc_type` / `pc_key` / `pc_hotkey` | 鼠标键盘 |
| `pc_look` | 描述屏幕 |
| `pc_focus` / `pc_windows` | 窗口管理 |
| `pc_undo` / `pc_history` | 撤销 |
| `describe_screen` | 只读：当前窗口 + 控件 |

### 手机 `phone-01`（RelayNodeClient，已完成）

| action | 实现 |
|--------|------|
| `open_app` | 启动任意应用（package） |
| `open_url` | 浏览器打开链接 |
| `vibrate` | 振动（需 VIBRATE 权限，已加 manifest） |
| `notify` | 本地通知 |
| `system_status` | 型号/电量/屏幕状态 |
| `read_gps` | 单次定位 |
| `speak` | Android TTS 朗读 |
| `take_photo` | 唤起相机 |

### 小智硬件 `xiaozhi-01`

| action | 干的事 |
|--------|--------|
| `say` | TTS 说话（edge-tts / 硬件扬声器） |
| `hear` | 开启一轮录音并 ASR 回文字 |
| `temperature` / `humidity` | 环境传感器 |
| `relay_on` / `relay_off` | 继电器（控制家电） |

---

## 四、完整流程示例

### 例 1：手机说"打开电脑上的浏览器"

```
用户对手机说话
  ↓ 手机语音 → (未来) 或直接 UI 触发
phone-01 → task_assign {action: "voice_command", params: {text: "打开浏览器"}} → pc-hub
  ↓ 电脑执行（真实鼠标键盘）
pc-hub → task_result {success: true, result: {reply: "打开浏览器了"}}
  ↓ 手机显示/朗读
```

### 例 2：小智硬件说"手机振动一下"

```
xiaozhi-01 → task_assign {action: "vibrate", params: {duration: 500}} → phone-01
  ↓ 手机振动 + 通知
phone-01 → task_result {success: true}
xiaozhi-01 扬声器："手机已经振动了"
```

### 例 3：电脑问小智"现在几度"

```
pc-hub → task_assign {action: "temperature"} → xiaozhi-01
xiaozhi-01 → task_result {success: true, result: {temperature: 26.5, unit: "°C"}}
pc-hub 会话记录 + 可执行后续判断
```

---

## 五、可靠性

| 机制 | 实现 |
|------|------|
| 认证 | JWT（URL token），中继按 user_id 分片隔离 |
| 重连 | 指数退避 1→30s（手机）/ 1→60s（电脑） |
| 请求配对 | request_id：发起方认领自己的回执 |
| 心跳 | 每 25 秒 heartbeat，45 秒无消息判定离线 |
| 恢复 | 重连后自动重发 register，注册表重建 |
| 幂等 | task_result 按 request_id 去重（同活不回两次） |
| 离线 | 中继暂存 100 条 / 5 分钟，重连补发 |

---

## 六、已完成的工程

### Python（电脑侧 + 协议）
- `laaper/hub/tri_node_daemon.py` —— PC 守护节点（连中继 + 局域网 + 处理三端消息）
- `laaper/hub/transport.py` —— 消息信封/幂等/重连
- `laaper/hub/node.py` —— 能力声明与路由
- `laaper/hub/computer_use.py` —— 电脑手
- 端到端通过：注册 ✅ 感知 ✅ 手机↔电脑双向操纵 ✅

### Kotlin（手机侧）
- `RelayNodeClient.kt` —— **新增**：中继客户端（注册/心跳/任务执行/重连）
- `XiaozhiLaapMobile.kt` —— **补全**：全部 15 个 TODO → 真实现（拨号/短信/开App/振动/通知/相机/TTS）
- `AndroidManifest.xml` —— 补 VIBRATE 权限

### 中继
- `api.laap.cn/ws` 已部署，6/6 端到端

---

## 七、还缺什么 / 下一步

| 项 | 说明 |
|----|------|
| Mobile 接线 | RelayNodeClient 建好了，但没接进 UI（需在设置页加"三端联动"入口 + 用户填中继 token） |
| 小智硬件侧 | Python 侧有 `xiaozhi_audio_stream`（自收音频）；三端协议里的 `say/hear` 待具体到硬件固件对接 |
| 语音闭环 | 手机说话→三端联动 需要把 ASR（本地 whisper 或手机自带）接进 RelayNodeClient |
| 真机验证 | APK 装机后跑一轮 例1/例2 的实际链路 |
| iOS 侧 | `RelayNodeClient` 是 Kotlin，iOS 需要 Swift 等价物 |

**做一个完整的三端"说话→操作→反馈"闭环，是下一步的验收标准。**