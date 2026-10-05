"""实时音视频感知流 测试"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from laaper.media.perception_stream import (
    PerceptionStream, WebRTCReceiver,
    AVFrame, StreamType, AttentionLevel
)


async def main():
    print("=" * 70)
    print("实时音视频感知流 测试")
    print("=" * 70)
    print()

    # ═══════════════════════════════════════════════
    # 1. 创建感知流
    # ═══════════════════════════════════════════════
    print("[1] 创建感知流")
    print("    ───────────────────────────────────────────")

    stream = PerceptionStream(laaper_id="aris")

    # 添加流源
    await stream.add_video_source("cam-01", "wss://esp32.local/webrtc", "ESP32 摄像头")
    await stream.add_audio_source("mic-01", "wss://esp32.local/audio", "ESP32 麦克风")
    await stream.add_video_source("phone-cam", "wss://phone.local/webrtc", "手机摄像头")

    sources = stream.get_sources()
    print(f"    添加 {len(sources)} 个流源:")
    for s in sources:
        print(f"      - {s['name']} ({s['type']})")

    # 注册感知回调
    def on_perception(frame):
        if frame.qualia:
            print(f"      感知: {frame.qualia['description']} "
                  f"(attention={frame.attention.value})")

    stream.on_perception(on_perception)
    print()

    # ═══════════════════════════════════════════════
    # 2. 模拟接收帧
    # ═══════════════════════════════════════════════
    print("[2] 模拟接收音视频帧")
    print("    ───────────────────────────────────────────")

    # 创建模拟帧
    for i in range(10):
        # 视频帧
        video_frame = AVFrame(
            frame_id=f"frame_{i}",
            stream_type=StreamType.VIDEO,
            timestamp=time.time(),
            data=b"fake_video_data" * 1000,
            width=640,
            height=480,
            source_device="cam-01",
        )
        stream.push_frame(video_frame)

        # 音频帧
        audio_frame = AVFrame(
            frame_id=f"audio_{i}",
            stream_type=StreamType.AUDIO,
            timestamp=time.time(),
            data=b"fake_audio_data" * 500,
            sample_rate=48000,
            channels=1,
            source_device="mic-01",
        )
        stream.push_frame(audio_frame)

    # 启动处理
    await stream.start()
    await asyncio.sleep(1)  # 等待处理

    print()

    # ═══════════════════════════════════════════════
    # 3. 统计
    # ═══════════════════════════════════════════════
    print("[3] 感知流统计")
    print("    ───────────────────────────────────────────")

    stats = stream.get_stats()
    print(f"    总帧数: {stats['total_frames']}")
    print(f"    流源: {stats['sources']} (已连接: {stats['connected_sources']})")
    print(f"    注意力分布: {stats['attention_stats']}")
    print(f"    缓冲区: {stats['buffer_size']}")
    print()

    # ═══════════════════════════════════════════════
    # 4. WebRTC 接收器
    # ═══════════════════════════════════════════════
    print("[4] WebRTC 接收器")
    print("    ───────────────────────────────────────────")

    receiver = WebRTCReceiver(stream)

    # 连接 ESP32 WebRTC
    connected = await receiver.connect_source("esp32-cam", "wss://esp32.local/webrtc")
    print(f"    连接 ESP32: {connected}")

    conn_stats = receiver.get_connection_stats()
    print(f"    连接统计: {conn_stats}")

    # 停止
    await stream.stop()
    print()

    # ═══════════════════════════════════════════════
    # 5. 技术栈总结
    # ═══════════════════════════════════════════════
    print("[5] 技术栈总结")
    print("    ───────────────────────────────────────────")

    print("    服务端: aiortc (Python)")
    print("      - WebRTC/ORTC 实现")
    print("      - asyncio 原生")
    print("      - 直接对接 LAAPer 感知系统")
    print()
    print("    嵌入式: ESP-WebRTC SDK")
    print("      - Espressif 官方")
    print("      - ESP32 摄像头/麦克风")
    print("      - H264/JPEG + Opus")
    print()
    print("    汇聚层: Pion / LiveKit (可选)")
    print("      - 多设备汇聚")
    print("      - 大规模扩展")
    print()
    print("    关键特性:")
    print("      - 持续感知流（不是通话）")
    print("      - 实时体验质编码")
    print("      - 选择性注意力")
    print("      - 多设备融合")

    print()
    print("=" * 70)
    print("实时音视频感知流 测试完成")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())