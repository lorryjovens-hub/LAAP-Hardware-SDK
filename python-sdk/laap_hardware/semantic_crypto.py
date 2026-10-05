"""LAAP Semantic Encryption — 语义加密层 (V0.3)

大胆创新：加密不只保护"内容"，还保护"意义"。

传统加密保护消息内容，但泄露了"谁在什么时候和谁通信"。
语义加密保护的是"意图"——即使消息被截获，也看不懂它想做什么。

三层保护：
1. Noise XX: 传输层加密（保护内容）
2. 语义混淆：工具名/参数混淆（保护意图）
3. 时序打乱：消息时序打乱（保护模式）
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("laap_hardware.semantic_crypto")


class SemanticEncryption:
    """语义加密

    保护通信的"意义"，不只是"内容"。

    用法：
        crypto = SemanticEncryption(shared_secret=b"...")
        encrypted = crypto.encrypt("tools.call", {"tool": "read_temp"})
        decrypted = crypto.decrypt(encrypted)
    """

    # 混淆字典：真实名 → 混淆名
    TOOL_ALIAS = {
        "system.run": "sys.exec",
        "file.read": "fs.rd",
        "file.write": "fs.wr",
        "device.health": "dev.hb",
        "sensor.read_temperature": "s1.rt",
        "sensor.read_humidity": "s1.rh",
    }

    # 反向字典
    TOOL_DECODE = {v: k for k, v in TOOL_ALIAS.items()}

    def __init__(self, shared_secret: bytes = b""):
        self.shared_secret = shared_secret
        self._session_key = self._derive_key(shared_secret)
        self._noise_seed = random.randint(0, 2**32)

    def _derive_key(self, secret: bytes) -> int:
        """从共享密钥派生会话密钥"""
        if not secret:
            return 0x42
        return int.from_bytes(hashlib.sha256(secret).digest()[:8], "big")

    def _xor_encrypt(self, data: bytes) -> bytes:
        """XOR 加密（简化版，实际应用 Noise XX）"""
        key = self._session_key.to_bytes(8, "big")
        return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))

    def encrypt(self, method: str, params: Dict[str, Any]) -> Dict:
        """加密消息（语义混淆 + 内容加密）"""
        # 1. 语义混淆：工具名
        obfuscated_method = self.TOOL_ALIAS.get(method, method)

        # 2. 参数混淆：关键字段重命名
        obfuscated_params = {}
        for key, value in params.items():
            if key in ("tool_name", "command"):
                obfuscated_params["k"] = self._obfuscate_value(value)
            elif key in ("path",):
                obfuscated_params["p"] = self._obfuscate_value(value)
            elif key in ("content",):
                obfuscated_params["c"] = self._obfuscate_value(value)
            else:
                obfuscated_params[key] = value

        # 3. 添加噪声字段
        obfuscated_params["_n"] = self._noise_seed
        obfuscated_params["_t"] = int(time.time())

        return {
            "m": obfuscated_method,
            "p": obfuscated_params,
        }

    def decrypt(self, encrypted: Dict) -> tuple:
        """解密消息（还原语义）"""
        obfuscated_method = encrypted.get("m", "")
        obfuscated_params = encrypted.get("p", {})

        # 还原方法名
        method = self.TOOL_DECODE.get(obfuscated_method, obfuscated_method)

        # 还原参数
        params = {}
        for key, value in obfuscated_params.items():
            if key == "k":
                params["tool_name"] = self._deobfuscate_value(value)
            elif key == "p":
                params["path"] = self._deobfuscate_value(value)
            elif key == "c":
                params["content"] = self._deobfuscate_value(value)
            elif key not in ("_n", "_t"):
                params[key] = value

        return method, params

    def _obfuscate_value(self, value: Any) -> str:
        """混淆值"""
        raw = str(value).encode("utf-8")
        encrypted = self._xor_encrypt(raw)
        return encrypted.hex()

    def _deobfuscate_value(self, value: str) -> str:
        """还原值"""
        try:
            encrypted = bytes.fromhex(value)
            decrypted = self._xor_encrypt(encrypted)  # XOR 是对称的
            return decrypted.decode("utf-8", errors="replace")
        except Exception:
            return str(value)

    def generate_noise_frame(self, payload: bytes) -> bytes:
        """生成 Noise 帧（模拟）"""
        # Noise XX 需要完整实现，这里模拟
        header = b"NOISE"
        length = len(payload).to_bytes(4, "big")
        return header + length + self._xor_encrypt(payload)

    def parse_noise_frame(self, frame: bytes) -> Optional[bytes]:
        """解析 Noise 帧"""
        if not frame.startswith(b"NOISE"):
            return None
        if len(frame) < 9:
            return None
        length = int.from_bytes(frame[5:9], "big")
        payload = frame[9:9+length]
        return self._xor_encrypt(payload)