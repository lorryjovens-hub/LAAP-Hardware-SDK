"""设备发现 + 安全认证 集成测试"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from laaper.discovery.device_finder import DeviceDiscovery, DeviceFingerprint, PairingState
from laaper.security.certificates import CertificateAuthority, SecurityManager


async def main():
    print("=" * 70)
    print("设备发现 + 安全认证 测试")
    print("=" * 70)
    print()

    # ═══════════════════════════════════════════════
    # 1. 安全认证
    # ═══════════════════════════════════════════════
    print("[1] 安全认证 (PKI)")
    print("    ───────────────────────────────────────────")

    security = SecurityManager()

    # 注册设备
    cert1 = security.register_device("esp32-body-01", "public_key_123")
    cert2 = security.register_device("raspi-01", "public_key_456")

    print(f"    CA: {security.ca.ca_id}")
    print(f"    注册设备: {len(security._device_certs)}")
    print(f"    证书 1: {cert1.cert_id[:20]}...")
    print(f"    证书 2: {cert2.cert_id[:20]}...")

    # 认证设备
    challenge = "challenge_12345"
    signature = security._sign_challenge("public_key_123", challenge)
    auth_result = security.authenticate_device("esp32-body-01", cert1, signature, challenge)
    print(f"    认证 esp32-body-01: {auth_result}")

    # 建立会话
    session_key = security.establish_session("esp32-body-01")
    print(f"    会话密钥: {len(session_key)} bytes")

    # 加密通信
    plaintext = "感知到温度 22.5°C"
    ciphertext = security.encrypt_message("esp32-body-01", plaintext)
    decrypted = security.decrypt_message("esp32-body-01", ciphertext)
    print(f"    加密: {plaintext} -> {len(ciphertext)} bytes")
    print(f"    解密: {decrypted}")

    # 消息签名
    sig, seq = security.sign_message("esp32-body-01", plaintext)
    verified = security.verify_message("esp32-body-01", plaintext, sig, seq)
    print(f"    消息签名验证: {verified}")

    status = security.get_security_status()
    print(f"    安全状态: {status}")
    print()

    # ═══════════════════════════════════════════════
    # 2. 设备发现
    # ═══════════════════════════════════════════════
    print("[2] 设备发现")
    print("    ───────────────────────────────────────────")

    discovery = DeviceDiscovery(laaper_id="aris")

    # 模拟发现设备
    device1 = discovery.handle_device_announce({
        "device_id": "esp32-body-01",
        "name": "ESP32 身体",
        "protocol": "udp",
        "address": "192.168.1.100:8888",
        "hardware_id": "ESP32-S3-001",
        "manufacturer": "Espressif",
        "model": "ESP32-S3",
        "firmware_version": "1.0.0",
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "capabilities": ["temperature", "pressure", "light"],
    })

    device2 = discovery.handle_device_announce({
        "device_id": "raspi-01",
        "name": "树莓派大脑",
        "protocol": "udp",
        "address": "192.168.1.101:8888",
        "hardware_id": "RPI4-001",
        "manufacturer": "Raspberry Pi",
        "model": "Raspberry Pi 4",
        "firmware_version": "2.0.0",
        "capabilities": ["camera", "microphone", "gps"],
    })

    discovered = discovery.get_discovered()
    print(f"    发现 {len(discovered)} 个设备:")
    for d in discovered:
        print(f"      - {d['name']} ({d['protocol']})")
        print(f"        能力: {d['capabilities']}")

    # 自动配对
    print(f"\n    自动配对:")
    paired = await discovery.initiate_pairing("esp32-body-01", auto_accept=True)
    print(f"      esp32-body-01: {paired}")

    paired = await discovery.initiate_pairing("raspi-01", auto_accept=True)
    print(f"      raspi-01: {paired}")

    trusted = discovery.get_trusted()
    print(f"\n    已信任设备: {len(trusted)}")
    for d in trusted:
        print(f"      - {d['name']} ({d['state']})")

    status = discovery.get_status()
    print(f"\n    发现状态: {status['total_devices']} devices, {status['trusted_devices']} trusted")
    print()

    # ═══════════════════════════════════════════════
    # 3. 完整安全流程
    # ═══════════════════════════════════════════════
    print("[3] 完整安全流程（发现→认证→加密→通信）")
    print("    ───────────────────────────────────────────")

    # 设备证书
    device_cert = security.get_certificate("esp32-body-01")
    if device_cert:
        print(f"    设备证书:")
        print(f"      主体: {device_cert.subject}")
        print(f"      签发者: {device_cert.issuer}")
        print(f"      有效期: {device_cert.valid_until - time.time():.0f} 秒")
        print(f"      签名: {device_cert.signature[:20]}...")

    # 加密通信
    sensor_data = '{"temperature": 22.5, "pressure": 3.2}'
    encrypted = security.encrypt_message("esp32-body-01", sensor_data)
    signature, seq = security.sign_message("esp32-body-01", sensor_data)

    print(f"\n    加密通信:")
    print(f"      原始: {sensor_data}")
    print(f"      加密: {len(encrypted)} bytes")
    print(f"      签名: {signature[:32]}...")
    print(f"      验证: {security.verify_message('esp32-body-01', sensor_data, signature, seq)}")

    print()
    print("=" * 70)
    print("设备发现 + 安全认证 测试完成")
    print("=" * 70)


import time

if __name__ == "__main__":
    asyncio.run(main())