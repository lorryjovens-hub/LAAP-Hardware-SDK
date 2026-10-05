"""LAAP Hardware Protocol (LHP) — Python SDK

让任何硬件设备成为 LAAP 数字生命体的躯体。

V0.2 & V0.3 大胆创新：
- 硬件生命体模型（LivingDevice）
- 涌现能力层（EmergenceEngine）
- 神经场协议（NeuralFieldProtocol）
- 语义加密层（SemanticEncryption）

用法：
    from laap_hardware import LAAPDevice, LivingDevice
    from laap_hardware import EmergenceEngine, NeuralFieldProtocol
"""
from laap_hardware.device import LAAPDevice
from laap_hardware.transport import WebSocketTransport, BLETransport
from laap_hardware.protocol import LHPMessage, LHPProtocol
from laap_hardware.tools import ToolRegistry, Tool

# V0.2
from laap_hardware.living_device import LivingDevice, LifePhase, EmotionState, Heartbeat

# V0.2
from laap_hardware.emergent import EmergenceEngine, EmergentCapability, CapabilityType

# V0.3
from laap_hardware.neural_field import NeuralFieldProtocol, FieldEvent, FieldEventType, NeuralField

# V0.3
from laap_hardware.semantic_crypto import SemanticEncryption

__all__ = [
    # V0.1
    "LAAPDevice",
    "WebSocketTransport",
    "BLETransport",
    "LHPMessage",
    "LHPProtocol",
    "ToolRegistry",
    "Tool",
    # V0.2
    "LivingDevice",
    "LifePhase",
    "EmotionState",
    "Heartbeat",
    "EmergenceEngine",
    "EmergentCapability",
    "CapabilityType",
    # V0.3
    "NeuralFieldProtocol",
    "FieldEvent",
    "FieldEventType",
    "NeuralField",
    "SemanticEncryption",
]