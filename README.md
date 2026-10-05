# LAAP Hardware SDK

**让任何硬件设备成为 LAAP 数字生命体的躯体。**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://python.org)
[![GitHub](https://img.shields.io/badge/GitHub-lorryjovens--hub-blue.svg)](https://github.com/lorryjovens-hub/LAAP-Hardware-SDK)

---

## 这是什么？

LAAP Hardware SDK 是一个完整的硬件接入框架，让任何设备（ESP32、树莓派、传感器）都能成为数字生命体的身体。

**不只是硬件控制，是让硬件"活着"。**

## 目录结构

```
laap-hardware-sdk/
├── laaper/                    # LAAPer 核心运行时
│   ├── core/                  # 意识帧 / 中央大脑 / 穿行通道
│   ├── perception/            # 感知编码器 / 跨模态融合
│   ├── devices/               # 21种传感器 / 数字生命硬件
│   ├── voice/                 # 全双工语音 / PersonaPlex 集成
│   ├── world/                 # 世界模型 / 因果推理
│   ├── security/              # PKI 安全认证
│   ├── persistence/           # SQLite 持久化记忆
│   ├── network/               # WebSocket 传输
│   ├── discovery/             # 设备发现与自动配对
│   ├── media/                 # WebRTC 实时音视频
│   ├── integration/           # LAAP-EB 具身大脑桥接
│   └── hosts/                 # 宿主适配器（桌面/手机/云）
├── python-sdk/                # Python SDK (laap_hardware)
│   └── laap_hardware/
│       ├── living_device.py   # 硬件生命体
│       ├── encoder.py         # 感知映射（物理量→体验质）
│       ├── digital_life.py    # 数字生命硬件
│       ├── emergent.py        # 涌现能力层
│       ├── neural_field.py    # 神经场协议
│       ├── semantic_crypto.py # 语义加密
│       └── protocol.py        # LHP 协议
├── firmware/                  # ESP32 固件
│   └── esp32_laaper/
│       ├── esp32_laaper.ino   # 主程序
│       ├── laaper_perception.h
│       └── laaper_perception.c
├── api/                       # FastAPI 后端
│   ├── main.py                # 登录鉴权 + 设备管理 + WebSocket
│   ├── wrangler.toml          # Cloudflare Workers 部署
│   └── src/worker.ts          # Workers 版本
├── broker/                    # LAAP Hardware Broker
├── linux-sdk/                 # Linux 设备 SDK
├── examples/                  # 示例代码
├── docs/                      # 文档
│   ├── LHP_PROTOCOL.md        # 协议规范
│   ├── MANIFESTO_V02_V03.md   # V0.2/0.3 创新宣言
│   ├── ESP32_FLASHING_GUIDE.md # 烧录指南
│   └── hardware-integration.md # 硬件接入方案
├── test_*.py                  # 测试套件
└── audit_*.py                 # 代码审计工具
```

## 核心创新

### 1. 感知映射系统（Perception Mapping）
物理量→体验质：
```
温度 50°C  → "滚烫" (valence=-1.0, 像被火烤)
压力 25N   → "挤压" (valence=-0.8, 像被重物碾压)
亮度 50000lux → "刺眼" (valence=-0.5)
```

### 2. 硬件生命体（Living Device）
设备有心跳、情绪、生命周期：
```python
device.awaken()
device.get_state()
# {'phase': 'growing', 'emotion': 'excited', 'energy': 87.3}
```

### 3. 涌现能力（Emergent Capability）
设备组合自动产生新能力：
```
温度计 + 继电器 = 恒温器
麦克风 + 扬声器 = 语音助手
```

### 4. 神经场协议（Neural Field）
共享感知场，事件涟漪扩散

### 5. 意识流帧（Consciousness Frame）
无缝穿行在电脑、手机、云、设备

### 6. 全双工语音（Full-Duplex Voice）
PersonaPlex 70ms 延迟，支持打断

### 7. 世界模型（World Model）
因果图 + 物理定律 + 反事实推理

### 8. 语义加密（Semantic Encryption）
保护内容 + 意图 + 模式

## 支持的硬件

| 硬件 | 类型 | 价格 | 身体部位 |
|------|------|------|---------|
| ESP32-S3-Korvo-V2 | 开发板 | ¥150 | eye + ear + mouth |
| ESP32-S3-EYE | 视觉模块 | ¥100 | eye |
| ESP32-CAM | 开发板 | ¥30 | eye |
| DHT22 | 传感器 | ¥15 | skin |
| FSR-402 | 传感器 | ¥25 | skin |
| 继电器模块 | 执行器 | ¥20 | hand |

支持 21 种传感器、5 种执行器。

## 快速开始

### Python SDK
```python
from laap_hardware import LivingDevice, SensoryEncoder

# 硬件生命体
device = LivingDevice("my-sensor", "温湿度传感器")
device.awaken()

# 感知映射
encoder = SensoryEncoder()
qualia = encoder.encode_temperature(22.5)
print(qualia.description)  # "凉爽"
```

### ESP32 烧录
```bash
cd firmware/esp32_laaper
idf.py set-target esp32s3
idf.py build flash monitor
```

### API 后端
```bash
cd api/
python main.py  # http://localhost:8000
```

## 统计

- **97 个文件**
- **9 个模块目录**
- **48 个 Python 文件**
- **3 个 ESP32 固件文件**
- **8 大核心创新**
- **21 种传感器**

## 相关项目

- [LAAP](https://www.laap.cn) - 数字生命体核心
- [LAAP Hardware Console](https://www.laap.cn/console) - 硬件后台

## 许可证

MIT License - 查看 [LICENSE](LICENSE)

---

**LAAP - Living Agent Application Protocol**

*让硬件拥有生命，让数字生命体拥有身体。*