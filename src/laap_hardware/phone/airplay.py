"""AirPlay 接收器 — iOS 的"眼睛"

让 LAAP 服务器接收 iPhone 的投屏画面。

## 实现路线选择（重要）

有两条路：

### 路线 A：ESP32 实现 AirPlay 接收
- 优点：不需要电脑，ESP32 自己收
- 缺点：AirPlay 协议栈复杂（RTSP + FairPlay + AES + RTP），ESP32 内存吃紧
- 参考：onehumanbeing/esp32-iphone-agent 做到了

### 路线 B：LAAP 服务器实现 AirPlay 接收（推荐）
- 优点：Python 生态成熟（UxPlay / PyAV / ffmpeg），稳定、好调试
- 缺点：需要 LAAP 服务器和手机在同一 Wi-Fi（本来就是这样）
- **关键洞察：LAAP 本来就跑在电脑/服务器上，AirPlay 在主机收是完全合理的**

本模块实现路线 B。

## 架构

    iPhone ──AirPlay──▶ LAAP 服务器 (本模块)
                             │
                             ├─▶ 解码 H.264
                             ├─▶ 提取帧
                             └─▶ 送给视觉模型

    LAAP 服务器 ──HID 命令──▶ ESP32 ──USB──▶ iPhone（点击）

这样 ESP32 只负责"手指"，不负责"眼睛"，简单可靠。

## 依赖

- UxPlay (推荐)：https://github.com/FDH2/UxPlay
- 或 PyAV：pip install av
- 或 ffmpeg
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional

from phone.types import ScreenFrame

logger = logging.getLogger("laap.phone.airplay")


@dataclass
class AirPlayConfig:
    """AirPlay 配置"""
    # 接收器名称（手机投屏列表里显示的名字）
    receiver_name: str = "LAAP-Aris"

    # 端口
    rtsp_port: int = 5000
    video_port: int = 7100
    audio_port: int = 7000

    # 输出
    output_width: int = 720        # 降低分辨率省带宽
    output_fps: int = 15
    frame_format: str = "jpeg"

    # UxPlay 路径
    uxplay_path: str = "uxplay"

    # 临时目录
    work_dir: str = ""


class AirPlayReceiver:
    """AirPlay 接收器 — 接收 iPhone 投屏

    用法:
        receiver = AirPlayReceiver()
        await receiver.start()

        # 手机打开控制中心 → 屏幕镜像 → 选择 LAAP-Aris

        # 获取帧
        frame = await receiver.get_frame()
    """

    def __init__(self, config: Optional[AirPlayConfig] = None):
        self.config = config or AirPlayConfig()
        self._process: Optional[subprocess.Popen] = None
        self._running = False
        self._frame_callback: Optional[Callable] = None
        self._latest_frame: Optional[ScreenFrame] = None
        self._work_dir = Path(self.config.work_dir or tempfile.mkdtemp(prefix="laap_airplay_"))

    def _find_uxplay(self) -> Optional[str]:
        """查找 UxPlay 可执行文件"""
        # 显式配置
        if Path(self.config.uxplay_path).exists():
            return self.config.uxplay_path

        # PATH 中查找
        found = shutil.which(self.config.uxplay_path)
        if found:
            return found

        # 常见路径
        candidates = [
            "/usr/local/bin/uxplay",
            "/usr/bin/uxplay",
            "C:/Program Files/UxPlay/uxplay.exe",
            "D:/LAAP/tools/uxplay/uxplay.exe",
        ]
        for c in candidates:
            if Path(c).exists():
                return c

        return None

    async def start(self) -> bool:
        """启动接收器"""
        uxplay = self._find_uxplay()
        if not uxplay:
            logger.error(
                "找不到 UxPlay。安装方式:\n"
                "  Windows: 下载 https://github.com/FDH2/UxPlay/releases\n"
                "  macOS:   brew install uxplay\n"
                "  Linux:   sudo apt install uxplay"
            )
            return False

        # 构建命令
        cmd = [
            uxplay,
            "-n", self.config.receiver_name,      # 接收器名称
            "-nh",                                 # 不显示帮助
            "-vs", "h264",                         # 视频编码
            "-fs",                                 # 全屏
            "-fps", str(self.config.output_fps),
            "-s", f"{self.config.output_width}x0",  # 分辨率（0 = 自动）
            # 输出到命名管道，供我们读取
            "-vp", str(self._work_dir / "video.h264"),
        ]

        try:
            logger.info(f"启动 AirPlay 接收器: {self.config.receiver_name}")
            logger.info(f"命令: {' '.join(cmd)}")

            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self._work_dir),
            )
            self._running = True

            # 启动帧提取任务
            asyncio.create_task(self._extract_frames_loop())

            logger.info(
                f"AirPlay 接收器已启动。\n"
                f"在 iPhone 上：控制中心 → 屏幕镜像 → 选择「{self.config.receiver_name}」"
            )
            return True

        except Exception as e:
            logger.error(f"启动失败: {e}")
            return False

    async def _extract_frames_loop(self):
        """从 H.264 流提取帧"""
        try:
            import av  # PyAV
        except ImportError:
            logger.warning(
                "未安装 PyAV，无法解码帧。安装: pip install av"
            )
            return

        video_path = self._work_dir / "video.h264"

        while self._running:
            if not video_path.exists() or video_path.stat().st_size == 0:
                await asyncio.sleep(0.5)
                continue

            try:
                container = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: av.open(str(video_path))
                )

                for frame in container.decode(video=0):
                    if not self._running:
                        break

                    # 转成 JPEG
                    img = frame.to_image()
                    img = img.resize((
                        self.config.output_width,
                        int(img.height * self.config.output_width / img.width),
                    ))

                    from io import BytesIO
                    buf = BytesIO()
                    img.save(buf, format="JPEG", quality=75)

                    screen_frame = ScreenFrame(
                        frame_id=f"airplay_{frame.pts}",
                        data=buf.getvalue(),
                        width=img.width,
                        height=img.height,
                        format="jpeg",
                    )
                    self._latest_frame = screen_frame

                    if self._frame_callback:
                        try:
                            await self._frame_callback(screen_frame)
                        except Exception as e:
                            logger.error(f"帧回调异常: {e}")

                container.close()

            except Exception as e:
                logger.debug(f"帧提取异常: {e}")

            await asyncio.sleep(0.1)

    async def get_frame(self) -> Optional[ScreenFrame]:
        """获取最新帧"""
        return self._latest_frame

    async def stop(self):
        """停止接收器"""
        self._running = False
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
        logger.info("AirPlay 接收器已停止")

    @property
    def running(self) -> bool:
        return self._running

    def on_frame(self, callback: Callable):
        """注册帧回调"""
        self._frame_callback = callback

    def get_status(self) -> Dict:
        return {
            "running": self._running,
            "receiver_name": self.config.receiver_name,
            "has_frame": self._latest_frame is not None,
            "frame_size_kb": (
                self._latest_frame.size_kb() if self._latest_frame else 0
            ),
            "work_dir": str(self._work_dir),
        }


# ── ESP32 录制 H.264 的替代方案说明 ──────────────────────────────────

ESP32_AIRPLAY_NOTE = """
## ESP32 自实现 AirPlay 接收（进阶路线）

如果你想不用电脑，让 ESP32 自己收 AirPlay，需要实现：

### 1. mDNS 广播
```
_airplay._tcp.local     (AirPlay 服务)
_raop._tcp.local        (音频传输)
```

### 2. RTSP 握手
手机发起 SETUP，需要回应：
- `ANNOUNCE` (SDP 协商)
- `SETUP` (建立流)
- `RECORD` (开始传输)

### 3. FairPlay 绕过
AirPlay 有 FairPlay 加密，但屏幕镜像用 `et=0,4` 参数可以协商不加密。

### 4. RTP 流接收
- 视频: H.264 over RTP (端口 7100)
- 音频: AAC/ALAC over RTP (端口 7000)

### 5. 转发
ESP32 不解码，只把 H.264 裸流通过 Wi-Fi/BLE 转给 LAAP。

### 参考实现
- onehumanbeing/esp32-iphone-agent (做到了)
- UxPlay (C++, 完整参考)
- RPiPlay (树莓派版)

### 为什么不推荐一开始就做
AirPlay 协议栈 + FairPlay + RTP 解包，在 ESP32 上约需 3-6 个月打磨。
先用 LAAP 服务器收投屏，能把产品跑起来，后面再优化。

### 折衷方案
如果必须无电脑：树莓派 Zero 2 W (¥150) 跑 UxPlay，比 ESP32 现实得多。
"""