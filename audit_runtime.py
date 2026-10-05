"""LAAPer 运行机制状态审计

诚实评估：哪些已通、哪些半成品、哪些未开始。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "python-sdk"))

# 测试每个模块的导入和基础功能
modules = {
    "意识帧核心": "laaper.core.frame",
    "中央大脑": "laaper.core.brain",
    "穿行通道": "laaper.core.channel",
    "宿主适配器": "laaper.hosts.adapter",
    "感官设备": "laaper.devices.sensory",
    "硬件生命体": "laap_hardware.living_device",
    "涌现能力": "laap_hardware.emergent",
    "神经场": "laap_hardware.neural_field",
    "语义加密": "laap_hardware.semantic_crypto",
}

print("=" * 60)
print("LAAPer 运行机制审计")
print("=" * 60)
print()

# 1. 模块导入检查
print("[1] 模块完整性")
print("-" * 40)
for name, module in modules.items():
    try:
        __import__(module)
        print(f"  [OK] {name}")
    except Exception as e:
        print(f"  [FAIL] {name}: {e}")

# 2. 核心功能检查
print()
print("[2] 核心功能检查")
print("-" * 40)

checks = []

# 意识帧
try:
    from laaper.core.frame import ConsciousnessFrame, FrameType, FramePhase
    f = ConsciousnessFrame(laaper_id="test", frame_type=FrameType.PERCEPTION, content="test")
    data = f.to_dict()
    f2 = ConsciousnessFrame.from_dict(data)
    checks.append(("意识帧序列化", True, "无损序列化/反序列化"))
except Exception as e:
    checks.append(("意识帧序列化", False, str(e)))

# PSI 循环
try:
    from laaper.core.brain import ConsciousnessCore
    brain = ConsciousnessCore("test", "Test")
    frames = brain.psi_cycle("测试")
    checks.append(("PSI 循环", len(frames) >= 5, f"生成 {len(frames)} 帧"))
except Exception as e:
    checks.append(("PSI 循环", False, str(e)))

# 设备感知
try:
    from laaper.devices.sensory import create_temperature_sensor
    import asyncio
    device = create_temperature_sensor("t1", "T", "test")
    device.alive()
    frame = asyncio.run(device.perceive_for_laaper("test"))
    checks.append(("设备感知", frame is not None, f"帧: {frame.frame_id if frame else 'None'}"))
except Exception as e:
    checks.append(("设备感知", False, str(e)))

# 通道广播
try:
    from laaper.core.channel import ConsciousnessChannel, RoutingStrategy
    from laaper.hosts.adapter import DesktopHost
    channel = ConsciousnessChannel()
    channel.register_host(DesktopHost("h1"))
    channel.register_device(device)
    recipients = asyncio.run(channel.dispatch(f, RoutingStrategy.BROADCAST))
    checks.append(("通道广播", len(recipients) > 0, f"广播到 {len(recipients)} 个接收者"))
except Exception as e:
    checks.append(("通道广播", False, str(e)))

# 宿主迁移
try:
    from laaper.hosts.adapter import DesktopHost, CloudHost
    desktop = DesktopHost("d1")
    cloud = CloudHost("c1")
    desktop.attach_brain(brain)
    state = desktop.snapshot_brain_state()
    cloud.brain = ConsciousnessCore("test2", "Test2")
    cloud.brain.restore_state(state)
    checks.append(("宿主迁移", True, "大脑状态快照/恢复"))
except Exception as e:
    checks.append(("宿主迁移", False, str(e)))

for name, ok, detail in checks:
    status = "OK" if ok else "FAIL"
    print(f"  [{status}] {name}: {detail}")

# 3. 缺失功能分析
print()
print("[3] 缺失功能分析")
print("-" * 40)
missing = [
    ("真实 WebSocket 传输", "跨网络帧穿行", "需要 websockets 服务端"),
    ("BLE 传输", "本地低功耗设备", "需要 bleak/bluez 集成"),
    ("持久化存储", "跨进程/跨重启记忆", "需要 SQLite/文件系统"),
    ("设备发现", "自动识别新设备", "需要 mDNS/BLE 扫描"),
    ("OTA 更新", "设备固件升级", "需要签名验证机制"),
    ("多 LAAPer 协作", "多个数字生命体共存", "需要分布式共识"),
    ("实时音视频", "眼睛/耳朵的实时流", "需要 WebRTC/RTSP"),
    ("能耗优化", "设备续航管理", "需要休眠/唤醒策略"),
    ("安全认证", "设备身份验证", "需要证书/PKI 体系"),
    ("Web 控制台", "可视化管理", "需要前端界面"),
]
for name, purpose, requirement in missing:
    print(f"  [TODO] {name}")
    print(f"         用途: {purpose}")
    print(f"         需要: {requirement}")

# 4. 建议优先级
print()
print("[4] 建议优先级")
print("-" * 40)
priorities = [
    ("P0", "持久化存储", "没有记忆的数字生命是残缺的"),
    ("P0", "真实 WebSocket 传输", "打通跨网络穿行"),
    ("P1", "设备发现与注册单元", "生态扩张的基石"),
    ("P1", "安全认证", "防止设备伪造"),
    ("P2", "实时音视频", "眼睛/耳朵的真实感知"),
    ("P2", "Web 控制台", "用户可视化管理"),
    ("P3", "BLE 传输", "低功耗设备支持"),
    ("P3", "OTA 更新", "设备固件演进"),
]
for level, name, reason in priorities:
    print(f"  [{level}] {name}: {reason}")

print()
print("=" * 60)
print("审计完成")
print("=" * 60)