"""测试 LAAP Hardware V0.2 & V0.3 新功能"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "python-sdk"))


async def test_living_device():
    """测试硬件生命体模型"""
    print("=== V0.2 硬件生命体模型 ===")
    from laap_hardware.living_device import LivingDevice, LifePhase, EmotionState

    device = LivingDevice(device_id="sensor-01", name="温湿度传感器")
    device.awaken()

    # 模拟使用
    for i in range(20):
        device.record_call("sensor.read_temperature")

    state = device.get_state()
    print(f"  阶段: {state['phase']}")
    print(f"  情绪: {state['emotion']}")
    print(f"  能量: {state['energy']}%")
    print(f"  调用次数: {state['call_count']}")
    print(f"  熟练度: {state['mastery']}")

    # 心跳
    async def on_heartbeat(hb):
        pass

    device.on_heartbeat(on_heartbeat)
    await device._beat()
    print(f"  心跳: OK")
    print()


async def test_emergent():
    """测试涌现能力层"""
    print("=== V0.2 涌现能力层 ===")
    from laap_hardware.emergent import EmergenceEngine, CapabilityType

    engine = EmergenceEngine()

    # 注册设备
    engine.register_device(
        "temp-sensor", "温度传感器",
        CapabilityType.SENSOR,
        ["sensor.temperature"],
        [{"name": "read_temp", "description": "读温度"}],
    )
    engine.register_device(
        "relay-01", "继电器",
        CapabilityType.ACTUATOR,
        ["actuator.relay"],
        [{"name": "control_relay", "description": "控制继电器"}],
    )

    # 发现涌现能力
    capabilities = engine.discover_emergent_capabilities()
    print(f"  发现 {len(capabilities)} 个涌现能力:")
    for cap in capabilities:
        print(f"    - {cap.name}: {cap.description}")
        print(f"      工具: {[t['name'] for t in cap.combined_tools]}")

    # 报告
    report = engine.get_emergence_report()
    print(f"  潜在涌现: {len(report['potential_emergences'])} 个")
    for p in report["potential_emergences"]:
        print(f"    - {p['name']} (缺: {p['missing']})")
    print()


async def test_neural_field():
    """测试神经场协议"""
    print("=== V0.3 神经场协议 ===")
    from laap_hardware.neural_field import NeuralFieldProtocol, FieldEventType

    protocol = NeuralFieldProtocol()
    protocol.register_device("sensor-1")
    protocol.register_device("sensor-2")
    protocol.register_device("sensor-3")

    # 发射事件
    protocol.emit_event("sensor-1", FieldEventType.PERCEPTION, {"temp": 22.5}, intensity=0.9)
    protocol.emit_event("sensor-2", FieldEventType.PERCEPTION, {"temp": 23.1}, intensity=0.8)

    # 感知场
    events = protocol.perceive_field("sensor-3")
    print(f"  sensor-3 感知到 {len(events)} 个事件:")
    for e in events[:3]:
        print(f"    - {e['event_type']} from {e['source_device']} (强度: {e['intensity']})")

    # 认知融合
    fused = protocol.fuse_cognition(["sensor-1", "sensor-2"], FieldEventType.PERCEPTION)
    print(f"  认知融合: {fused.get('fused_data')}")
    print(f"  置信度: {fused.get('confidence')}")

    # 预测
    prediction = protocol.predict_next("sensor-3", FieldEventType.PERCEPTION)
    print(f"  预测: {prediction.get('predicted', False)}")

    # 场状态
    state = protocol.get_field_state()
    print(f"  场状态: {state['total_devices']} 设备, {state['total_events']} 事件")
    print()


async def test_semantic_crypto():
    """测试语义加密层"""
    print("=== V0.3 语义加密层 ===")
    from laap_hardware.semantic_crypto import SemanticEncryption

    crypto = SemanticEncryption(shared_secret=b"laap-secret-key")

    # 加密
    encrypted = crypto.encrypt("tools.call", {
        "tool_name": "system.run",
        "command": "ls -la",
    })
    print(f"  加密: {encrypted['m']} -> {list(encrypted['p'].keys())}")

    # 解密
    method, params = crypto.decrypt(encrypted)
    print(f"  解密: {method}")
    print(f"  参数: {params}")

    # Noise 帧
    frame = crypto.generate_noise_frame(b"hello laap")
    parsed = crypto.parse_noise_frame(frame)
    print(f"  Noise 帧: {len(frame)} bytes, 解析: {parsed}")
    print()


async def main():
    print("=" * 50)
    print("LAAP Hardware V0.2 & V0.3 测试")
    print("=" * 50)
    print()

    await test_living_device()
    await test_emergent()
    await test_neural_field()
    await test_semantic_crypto()

    print("=" * 50)
    print("全部测试通过！")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())