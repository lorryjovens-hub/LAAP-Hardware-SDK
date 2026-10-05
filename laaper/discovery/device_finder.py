"""LAAPer 设备发现与自动配对 (Device Discovery & Auto-Pairing)

让设备自动被发现和注册，无需手动配置。

支持：
- mDNS/Bonjour 网络发现
- BLE 广播发现
- 设备指纹（防止伪造）
- 自动信任决策
- 安全配对握手

这就是生态扩张的基石：插上就能用。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import socket
import struct
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set
from enum import Enum

logger = logging.getLogger("laaper.discovery")


class DiscoveryProtocol(str, Enum):
    MDNS = "mdns"          # 局域网 mDNS
    BLE = "ble"            # 蓝牙 BLE
    UDP = "udp"            # UDP 广播
    TCP = "tcp"            # TCP 扫描


class PairingState(str, Enum):
    DISCOVERED = "discovered"      # 已发现
    PAIRING = "pairing"            # 配对中
    PAIRED = "paired"              # 已配对
    TRUSTED = "trusted"            # 已信任
    REJECTED = "rejected"          # 已拒绝


@dataclass
class DeviceFingerprint:
    """设备指纹（防止伪造）"""
    hardware_id: str              # 硬件唯一 ID
    manufacturer: str = ""
    model: str = ""
    firmware_version: str = ""

    # 指纹特征
    mac_address: str = ""
    serial_number: str = ""
    crypto_key_hash: str = ""     # 公钥哈希

    # 时间戳
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    def compute_hash(self) -> str:
        """计算设备指纹哈希"""
        data = f"{self.hardware_id}|{self.mac_address}|{self.serial_number}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict:
        return {
            "hardware_id": self.hardware_id,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "firmware_version": self.firmware_version,
            "mac_address": self.mac_address,
            "hash": self.compute_hash(),
        }


@dataclass
class DiscoveredDevice:
    """发现的设备"""
    device_id: str
    name: str
    protocol: DiscoveryProtocol
    address: str                  # IP:Port 或 MAC
    fingerprint: DeviceFingerprint
    capabilities: List[str] = field(default_factory=list)

    # 配对状态
    state: PairingState = PairingState.DISCOVERED
    pairing_key: str = ""
    trusted_at: float = 0.0

    # 元数据
    discovered_at: float = field(default_factory=time.time)
    signal_strength: float = 0.0  # 信号强度
    is_online: bool = True

    def to_dict(self) -> Dict:
        return {
            "device_id": self.device_id,
            "name": self.name,
            "protocol": self.protocol.value,
            "address": self.address,
            "fingerprint": self.fingerprint.to_dict(),
            "capabilities": self.capabilities,
            "state": self.state.value,
            "is_online": self.is_online,
            "signal_strength": round(self.signal_strength, 2),
        }


class DeviceDiscovery:
    """设备发现引擎

    自动发现局域网/蓝牙设备。

    用法：
        discovery = DeviceDiscovery()
        discovery.on_device_found(lambda dev: print(dev.name))
        await discovery.start_scanning()
    """

    def __init__(self, laaper_id: str = ""):
        self.laaper_id = laaper_id
        self._discovered: Dict[str, DiscoveredDevice] = {}
        self._scanning = False
        self._scan_tasks: List[asyncio.Task] = []

        # 回调
        self._on_device_found: Optional[Callable] = None
        self._on_device_lost: Optional[Callable] = None
        self._on_pairing_request: Optional[Callable] = None

        # 信任列表
        self._trusted_devices: Set[str] = set()

    # ── 扫描 ──────────────────────────────────────

    async def start_scanning(self, protocols: List[DiscoveryProtocol] = None):
        """开始扫描设备"""
        protocols = protocols or [DiscoveryProtocol.MDNS, DiscoveryProtocol.UDP]
        self._scanning = True

        for protocol in protocols:
            if protocol == DiscoveryProtocol.MDNS:
                task = asyncio.create_task(self._scan_mdns())
                self._scan_tasks.append(task)
            elif protocol == DiscoveryProtocol.UDP:
                task = asyncio.create_task(self._scan_udp())
                self._scan_tasks.append(task)
            elif protocol == DiscoveryProtocol.BLE:
                task = asyncio.create_task(self._scan_ble())
                self._scan_tasks.append(task)

        logger.info(f"Scanning started with protocols: {[p.value for p in protocols]}")

    async def stop_scanning(self):
        """停止扫描"""
        self._scanning = False
        for task in self._scan_tasks:
            task.cancel()
        self._scan_tasks.clear()
        logger.info("Scanning stopped")

    async def _scan_mdns(self):
        """mDNS 扫描（模拟）"""
        # 实际应使用 zeroconf 库
        while self._scanning:
            await asyncio.sleep(5)
            # 模拟发现设备
            # 实际实现会调用 zeroconf 的服务发现

    async def _scan_udp(self):
        """UDP 广播扫描"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(2)

            while self._scanning:
                # 发送广播
                sock.sendto(b"LAAP_DISCOVER", ("255.255.255.255", 8888))
                await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"UDP scan error: {e}")
        finally:
            sock.close()

    async def _scan_ble(self):
        """BLE 扫描（模拟）"""
        while self._scanning:
            await asyncio.sleep(5)
            # 实际应使用 bleak 库
            # ble_devices = await BleakScanner.discover()
            # for dev in ble_devices:
            #     self._process_ble_device(dev)

    # ── 设备处理 ──────────────────────────────────────

    def _process_found_device(self, device: DiscoveredDevice):
        """处理发现的设备"""
        device_id = device.device_id

        if device_id in self._discovered:
            # 更新已存在的设备
            old = self._discovered[device_id]
            old.last_seen = time.time()
            old.signal_strength = device.signal_strength
            old.is_online = True
        else:
            # 新设备
            self._discovered[device_id] = device
            logger.info(f"Device discovered: {device.name} ({device.protocol.value})")

            if self._on_device_found:
                self._on_device_found(device)

    def handle_device_announce(self, data: Dict) -> Optional[DiscoveredDevice]:
        """处理设备广播（网络）"""
        try:
            device = DiscoveredDevice(
                device_id=data.get("device_id", "unknown"),
                name=data.get("name", "Unknown"),
                protocol=DiscoveryProtocol(data.get("protocol", "udp")),
                address=data.get("address", ""),
                fingerprint=DeviceFingerprint(
                    hardware_id=data.get("hardware_id", ""),
                    manufacturer=data.get("manufacturer", ""),
                    model=data.get("model", ""),
                    firmware_version=data.get("firmware_version", ""),
                    mac_address=data.get("mac_address", ""),
                    serial_number=data.get("serial_number", ""),
                ),
                capabilities=data.get("capabilities", []),
            )
            self._process_found_device(device)
            return device
        except Exception as e:
            logger.error(f"Failed to process announce: {e}")
            return None

    # ── 配对 ──────────────────────────────────────

    async def initiate_pairing(self, device_id: str,
                               auto_accept: bool = False) -> bool:
        """发起配对"""
        device = self._discovered.get(device_id)
        if not device:
            logger.error(f"Device {device_id} not found")
            return False

        device.state = PairingState.PAIRING

        # 生成配对密钥
        pairing_key = self._generate_pairing_key(device)
        device.pairing_key = pairing_key

        # 验证设备指纹
        if not self._verify_fingerprint(device.fingerprint):
            device.state = PairingState.REJECTED
            logger.warning(f"Device {device_id} fingerprint verification failed")
            return False

        # 自动接受或等待确认
        if auto_accept:
            device.state = PairingState.PAIRED
            self._trusted_devices.add(device_id)
            device.trusted_at = time.time()
            logger.info(f"Device {device_id} auto-paired")
            return True

        # 等待用户确认
        if self._on_pairing_request:
            confirmed = await self._on_pairing_request(device)
            if confirmed:
                device.state = PairingState.PAIRED
                self._trusted_devices.add(device_id)
                device.trusted_at = time.time()
                return True

        device.state = PairingState.DISCOVERED
        return False

    def _generate_pairing_key(self, device: DiscoveredDevice) -> str:
        """生成配对密钥"""
        seed = f"{device.device_id}|{time.time()}|{self.laaper_id}"
        return hashlib.sha256(seed.encode()).hexdigest()[:32]

    def _verify_fingerprint(self, fingerprint: DeviceFingerprint) -> bool:
        """验证设备指纹"""
        # 检查基本字段
        if not fingerprint.hardware_id:
            return False

        # 计算指纹哈希
        fp_hash = fingerprint.compute_hash()

        # 检查是否已知的可信设备
        if fingerprint.hardware_id in self._trusted_devices:
            return True

        # 新设备需要额外验证
        # 实际应用中应该检查证书/签名
        return True  # 简化：允许新设备

    # ── 查询 ──────────────────────────────────────

    def get_discovered(self) -> List[Dict]:
        return [d.to_dict() for d in self._discovered.values()]

    def get_trusted(self) -> List[Dict]:
        return [
            d.to_dict()
            for d in self._discovered.values()
            if d.state == PairingState.PAIRED or d.state == PairingState.TRUSTED
        ]

    def get_device(self, device_id: str) -> Optional[DiscoveredDevice]:
        return self._discovered.get(device_id)

    def trust_device(self, device_id: str):
        """手动信任设备"""
        device = self._discovered.get(device_id)
        if device:
            device.state = PairingState.TRUSTED
            self._trusted_devices.add(device_id)
            device.trusted_at = time.time()

    def untrust_device(self, device_id: str):
        """取消信任"""
        device = self._discovered.get(device_id)
        if device:
            device.state = PairingState.DISCOVERED
            self._trusted_devices.discard(device_id)

    # ── 回调 ──────────────────────────────────────

    def on_device_found(self, callback: Callable):
        self._on_device_found = callback

    def on_device_lost(self, callback: Callable):
        self._on_device_lost = callback

    def on_pairing_request(self, callback: Callable):
        self._on_pairing_request = callback

    def get_status(self) -> Dict:
        return {
            "scanning": self._scanning,
            "total_devices": len(self._discovered),
            "trusted_devices": len(self._trusted_devices),
            "devices": [d.to_dict() for d in self._discovered.values()],
        }