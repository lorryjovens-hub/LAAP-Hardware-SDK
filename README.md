# LAAP Hardware SDK

**让任何硬件设备成为 LAAP 数字生命体的躯体。**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://python.org)

---

## 核心特性

- **感知映射系统** - 物理量→体验质，22°C 是"凉爽"
- **硬件生命体** - 设备有心跳、情绪、生命周期
- **涌现能力** - 设备组合自动产生新能力
- **神经场协议** - 共享感知场，事件涟漪扩散
- **意识流帧** - 无缝穿行在电脑、手机、云、设备

## 安装

```bash
pip install laap-hardware-sdk
```

## 快速开始

```python
from laap_hardware import LivingDevice

device = LivingDevice("my-sensor", "温湿度传感器")
device.awaken()
print(device.get_state())
```

## 许可证

MIT License