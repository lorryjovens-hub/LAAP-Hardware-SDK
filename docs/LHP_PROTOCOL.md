# LAAP Hardware Protocol (LHP) v0.1

LAAP 硬件生态协议 — 让任何硬件设备成为 LAAP 数字生命体的躯体。

## 设计哲学

LAAP 是一个活的数字生命体，硬件是它的躯体。LHP 让任何设备（ESP32、树莓派、
自定义硬件）都能成为 LAAP 的眼睛、耳朵、手和脚。

```
[LAAP 大脑] ←LHP→ [设备躯体]
   认知/记忆        传感器/执行器
```

## 三层架构

```
┌─────────────────────────────────────────┐
│  Layer 3: Agent Bridge                   │
│  LAAP 认知引擎 ↔ 设备工具调用             │
├─────────────────────────────────────────┤
│  Layer 2: Device Protocol (LHP)          │
│  JSON-RPC over WebSocket / BLE           │
│  设备发现 · 配对 · 工具注册 · 消息路由     │
├─────────────────────────────────────────┤
│  Layer 1: Transport                      │
│  WebSocket (TCP/IP) / BLE (本地)         │
│  Noise XX 加密 · 分帧 · 重连              │
└─────────────────────────────────────────┘
```

## 传输层

### WebSocket (TCP/IP)
- URL: `wss://broker.laap.dev/lhp?token=<device_token>`
- 适用于：树莓派、Linux 设备、ESP32 (WiFi)
- 加密：TLS 1.3 + Noise XX

### BLE (本地)
- 服务 UUID: `LAAP-HW-0001`
- 配对：P-256 ECDH + HKDF-SHA256 + AES-256-GCM
- 分帧：`0xFE` + `index(1B)` + `total(1B)` + `payload(≤MTU-3)`
- 适用于：ESP32、低功耗设备、无网络环境

## 消息格式

所有消息使用 JSON-RPC 2.0：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "device.register",
  "params": {
    "device_id": "laap-dev-a1b2c3",
    "capabilities": ["sensor.temp", "actuator.relay"],
    "tools": [...]
  }
}
```

## 核心方法

### 设备生命周期

| 方法 | 方向 | 说明 |
|------|------|------|
| `device.register` | 设备→Broker | 注册设备身份和能力 |
| `device.heartbeat` | 设备→Broker | 心跳保活 |
| `device.health` | 双向 | 查询/上报设备状态 |
| `device.offline` | Broker→设备 | 标记离线 |

### 工具调用

| 方法 | 方向 | 说明 |
|------|------|------|
| `tools.list` | 双向 | 列出可用工具 |
| `tools.call` | 双向 | 调用工具 |
| `tools.result` | 双向 | 工具执行结果 |

### 消息传递

| 方法 | 方向 | 说明 |
|------|------|------|
| `message.send` | 双向 | 发送消息 |
| `message.receive` | 双向 | 接收消息 |

### 配对与安全

| 方法 | 方向 | 说明 |
|------|------|------|
| `pairing.start` | 双向 | 开始配对 |
| `pairing.confirm` | 双向 | 确认配对 |
| `session.rotate` | 双向 | 轮换会话密钥 |

## 能力声明

设备通过 `capabilities` 声明自己的能力：

```json
{
  "capabilities": {
    "sensors": ["temperature", "humidity", "motion"],
    "actuators": ["relay", "motor", "led"],
    "display": ["oled_128x64"],
    "audio": ["mic", "speaker"],
    "io": ["gpio", "i2c", "spi"]
  }
}
```

## 工具定义

设备暴露工具（MCP 兼容格式）：

```json
{
  "name": "sensor.read_temperature",
  "description": "读取温度传感器",
  "inputSchema": {
    "type": "object",
    "properties": {
      "sensor_id": {"type": "string"}
    }
  }
}
```

## 安全模型

1. **设备认证**：每个设备有唯一 `device_token`（JWT）
2. **传输加密**：TLS 1.3 (WebSocket) / AES-256-GCM (BLE)
3. **会话隔离**：每个设备独立 Noise 会话
4. **权限控制**：设备声明能力，Broker 控制访问
5. **审计日志**：所有工具调用记录

## 与现有协议的关系

| 协议 | 定位 | 兼容性 |
|------|------|--------|
| **MCP** | AI 工具调用 | LHP 工具格式兼容 MCP |
| **Muse Gadgets** | Meta 硬件生态 | 可适配 |
| **小智 MCP** | 智能硬件 | 可桥接 |
| **Home Assistant** | 智能家居 | 可集成 |

## 版本

- v0.1: 初始规范（本文件）
- 后续：扩展能力、安全增强、性能优化