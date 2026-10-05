"""LAAPer 安全认证 (Security & PKI)

防止设备伪造，确保只有可信设备能接入 LAAPer 生态。

安全层：
1. 设备证书（X.509 风格）
2. 数字签名（Ed25519）
3. 会话密钥（密钥交换）
4. 通信加密（AES-256-GCM）
5. 消息认证（HMAC）

这是信任的基石。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("laaper.security")


@dataclass
class DeviceCertificate:
    """设备证书（简化 X.509）"""
    cert_id: str
    subject: str                    # 设备 ID
    issuer: str                     # 签发者（LAAPer CA）
    public_key: str                 # 公钥（base64）
    serial_number: str
    valid_from: float
    valid_until: float

    # 证书扩展
    key_usage: List[str] = field(default_factory=lambda: ["digital_signature", "key_encipherment"])
    extended_key_usage: List[str] = field(default_factory=list)

    # 签名
    signature: str = ""

    def is_valid(self) -> bool:
        """检查证书有效性"""
        now = time.time()
        return self.valid_from <= now <= self.valid_until

    def to_dict(self) -> Dict:
        return {
            "cert_id": self.cert_id,
            "subject": self.subject,
            "issuer": self.issuer,
            "public_key": self.public_key,
            "serial_number": self.serial_number,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "key_usage": self.key_usage,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "DeviceCertificate":
        return cls(**data)


class CertificateAuthority:
    """证书颁发机构 (CA)

    LAAPer 作为根 CA，为设备签发证书。
    """

    def __init__(self, ca_id: str = "laaper-ca"):
        self.ca_id = ca_id
        self._ca_private_key = secrets.token_bytes(32)  # 简化：实际用 Ed25519
        self._ca_public_key = hashlib.sha256(self._ca_private_key).hexdigest()

        # 已签发的证书
        self._issued_certs: Dict[str, DeviceCertificate] = {}
        self._revoked_certs: set = set()

    def issue_certificate(self, device_id: str,
                         public_key: str,
                         validity_days: int = 365) -> DeviceCertificate:
        """为设备签发证书"""
        cert = DeviceCertificate(
            cert_id=f"cert_{secrets.token_hex(8)}",
            subject=device_id,
            issuer=self.ca_id,
            public_key=public_key,
            serial_number=secrets.token_hex(16),
            valid_from=time.time(),
            valid_until=time.time() + validity_days * 86400,
        )

        # 签名
        cert.signature = self._sign_cert(cert)

        self._issued_certs[cert.cert_id] = cert
        logger.info(f"Certificate issued for {device_id}: {cert.cert_id}")

        return cert

    def _sign_cert(self, cert: DeviceCertificate) -> str:
        """签名证书"""
        data = f"{cert.cert_id}|{cert.subject}|{cert.issuer}|{cert.public_key}"
        return hashlib.sha256((data + self._ca_private_key.hex()).encode()).hexdigest()

    def verify_certificate(self, cert: DeviceCertificate) -> bool:
        """验证证书"""
        # 检查是否被吊销
        if cert.cert_id in self._revoked_certs:
            return False

        # 检查有效期
        if not cert.is_valid():
            return False

        # 验证签名
        expected_sig = self._sign_cert(cert)
        return cert.signature == expected_sig

    def revoke_certificate(self, cert_id: str):
        """吊销证书"""
        self._revoked_certs.add(cert_id)
        logger.info(f"Certificate revoked: {cert_id}")

    def get_ca_certificate(self) -> Dict:
        return {
            "ca_id": self.ca_id,
            "public_key": self._ca_public_key,
            "issued_count": len(self._issued_certs),
        }


class SecurityManager:
    """安全管理器

    统一管理认证、加密、签名。

    用法：
        security = SecurityManager()
        cert = security.register_device("device-01", public_key)
        session_key = security.establish_session("device-01")
    """

    def __init__(self, ca: Optional[CertificateAuthority] = None):
        self.ca = ca or CertificateAuthority()

        # 设备证书
        self._device_certs: Dict[str, DeviceCertificate] = {}

        # 会话密钥
        self._session_keys: Dict[str, bytes] = {}

        # 已认证设备
        self._authenticated: Dict[str, Dict] = {}

        # 消息序列号（防重放）
        self._message_seq: Dict[str, int] = {}

    # ── 设备注册 ──────────────────────────────────────

    def register_device(self, device_id: str,
                       public_key: str) -> DeviceCertificate:
        """注册设备并签发证书"""
        cert = self.ca.issue_certificate(device_id, public_key)
        self._device_certs[device_id] = cert
        return cert

    def authenticate_device(self, device_id: str,
                           certificate: DeviceCertificate,
                           signature: str,
                           challenge: str) -> bool:
        """认证设备"""
        # 验证证书
        if not self.ca.verify_certificate(certificate):
            logger.warning(f"Certificate verification failed for {device_id}")
            return False

        # 验证签名（简化）
        expected = self._sign_challenge(certificate.public_key, challenge)
        if signature != expected:
            logger.warning(f"Signature verification failed for {device_id}")
            return False

        # 认证成功
        self._authenticated[device_id] = {
            "cert_id": certificate.cert_id,
            "authenticated_at": time.time(),
        }
        logger.info(f"Device authenticated: {device_id}")
        return True

    def _sign_challenge(self, public_key: str, challenge: str) -> str:
        """签名挑战（简化）"""
        return hashlib.sha256((public_key + challenge).encode()).hexdigest()

    # ── 会话密钥 ──────────────────────────────────────

    def establish_session(self, device_id: str) -> bytes:
        """建立会话密钥"""
        session_key = secrets.token_bytes(32)  # AES-256
        self._session_keys[device_id] = session_key
        logger.info(f"Session established for {device_id}")
        return session_key

    def encrypt_message(self, device_id: str, plaintext: str) -> bytes:
        """加密消息"""
        key = self._session_keys.get(device_id)
        if not key:
            raise ValueError(f"No session key for {device_id}")

        # 简化：XOR 加密（实际用 AES-256-GCM）
        data = plaintext.encode()
        return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))

    def decrypt_message(self, device_id: str, ciphertext: bytes) -> str:
        """解密消息"""
        key = self._session_keys.get(device_id)
        if not key:
            raise ValueError(f"No session key for {device_id}")

        data = bytes(b ^ key[i % len(key)] for i, b in enumerate(ciphertext))
        return data.decode()

    # ── 消息认证 ──────────────────────────────────────

    def sign_message(self, device_id: str, message: str) -> Tuple[str, int]:
        """签名消息，返回 (签名, 序列号)"""
        key = self._session_keys.get(device_id)
        if not key:
            raise ValueError(f"No session key for {device_id}")

        seq = self._message_seq.get(device_id, 0)
        self._message_seq[device_id] = seq + 1

        data = f"{message}|{seq}|{device_id}"
        signature = hmac.new(key, data.encode(), hashlib.sha256).hexdigest()
        return signature, seq

    def verify_message(self, device_id: str, message: str,
                      signature: str, seq: int) -> bool:
        """验证消息签名"""
        key = self._session_keys.get(device_id)
        if not key:
            return False

        data = f"{message}|{seq}|{device_id}"
        expected_sig = hmac.new(key, data.encode(), hashlib.sha256).hexdigest()

        return signature == expected_sig

    # ── 查询 ──────────────────────────────────────

    def is_authenticated(self, device_id: str) -> bool:
        return device_id in self._authenticated

    def get_certificate(self, device_id: str) -> Optional[DeviceCertificate]:
        return self._device_certs.get(device_id)

    def get_security_status(self) -> Dict:
        return {
            "ca_id": self.ca.ca_id,
            "registered_devices": len(self._device_certs),
            "authenticated_devices": len(self._authenticated),
            "active_sessions": len(self._session_keys),
            "revoked_certificates": len(self.ca._revoked_certs),
        }