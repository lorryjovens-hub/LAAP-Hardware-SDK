"""全双工语音感知对话 测试"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from laaper.voice.full_duplex import (
    FullDuplexVoiceEngine, XiaozhiIntegration, PersonaPlexIntegration,
    VoiceState, EmotionFromVoice, create_voice_system
)


async def main():
    print("=" * 70)
    print("全双工语音感知对话 测试")
    print("=" * 70)
    print()

    # ═══════════════════════════════════════════════
    # 1. 创建语音系统
    # ═══════════════════════════════════════════════
    print("[1] 创建全双工语音系统")
    print("    ───────────────────────────────────────────")

    system = create_voice_system(laaper_id="aris")
    engine = system["engine"]

    print(f"    角色: {engine.persona['name']}")
    print(f"    描述: {engine.persona['description']}")
    print(f"    说话风格: {engine.persona['speaking_style']}")
    print()

    # ═══════════════════════════════════════════════
    # 2. 处理用户语音
    # ═══════════════════════════════════════════════
    print("[2] 处理用户语音（感知）")
    print("    ───────────────────────────────────────────")

    # 模拟用户语音
    audio_data = b"fake_audio_data"
    perception = await engine.process_user_audio(audio_data)

    print(f"    转录: {perception.transcript}")
    print(f"    置信度: {perception.confidence}")
    print(f"    情感: {perception.emotion.value} ({perception.emotion_confidence})")
    print(f"    音高: {perception.pitch_hz} Hz")
    print(f"    能量: {perception.energy_db} dB")
    print(f"    意图: {perception.intent}")
    print(f"    效价: {perception.valence:+.2f}, 激活度: {perception.arousal:.2f}")
    print()

    # ═══════════════════════════════════════════════
    # 3. 生成回复（全双工）
    # ═══════════════════════════════════════════════
    print("[3] 生成回复（全双工）")
    print("    ───────────────────────────────────────────")

    response = await engine.generate_response(perception)

    print(f"    回复文本: {response.text}")
    print(f"    情感: {response.emotion.value}")
    print(f"    是回应声: {response.is_backchannel}")
    print(f"    是打断: {response.is_interruption}")
    print()

    # ═══════════════════════════════════════════════
    # 4. 打断测试
    # ═══════════════════════════════════════════════
    print("[4] 打断测试（全双工特性）")
    print("    ───────────────────────────────────────────")

    # 模拟急促说话（应该触发打断）
    urgent_audio = b"urgent_audio"
    urgent_perception = await engine.process_user_audio(urgent_audio)
    urgent_perception.energy_db = 85  # 高能量
    urgent_perception.pitch_hz = 350  # 高音高

    interrupt_response = await engine.generate_response(urgent_perception)
    print(f"    打断检测: {interrupt_response.is_interruption}")
    print(f"    应该暂停: {interrupt_response.should_pause}")
    print()

    # ═══════════════════════════════════════════════
    # 5. 多模态融合
    # ═══════════════════════════════════════════════
    print("[5] 多模态感知融合")
    print("    ───────────────────────────────────────────")

    # 语音 + 视觉 + 触觉
    visual = {"emotion": "surprised", "objects": ["person", "fire"]}
    tactile = {"pressure": 3.2, "temperature": 28}

    fused = engine.fuse_with_other_sensors(perception, visual, tactile)
    print(f"    语音情绪: {fused['voice']['emotion']}")
    print(f"    视觉情绪: {visual['emotion']}")
    print(f"    融合结果: {fused.get('overall_emotion', 'N/A')}")
    print()

    # ═══════════════════════════════════════════════
    # 6. 技术栈对比
    # ═══════════════════════════════════════════════
    print("[6] 技术栈对比")
    print("    ───────────────────────────────────────────")

    print("    小智方案（单工）:")
    print("      流程: 说话→识别→思考→合成→播放")
    print("      延迟: 500-2000ms")
    print("      打断: 不支持")
    print("      角色: 固定")
    print()
    print("    PersonaPlex（全双工）:")
    print("      流程: 同时听说（双流并发）")
    print("      延迟: 70ms（切换说话者）")
    print("      打断: 完美支持")
    print("      角色: 可定制（文本+语音）")
    print()
    print("    LAAPer 方案（融合）:")
    print("      流程: PersonaPlex + 小智硬件 + 感知融合")
    print("      延迟: <100ms")
    print("      打断: 支持")
    print("      角色: 可定制")
    print("      感知: 多模态融合（语音+视觉+触觉）")
    print("      情感: 韵律控制 + 情感识别")
    print()

    # ═══════════════════════════════════════════════
    # 7. 统计
    # ═══════════════════════════════════════════════
    print("[7] 统计")
    print("    ───────────────────────────────────────────")

    stats = engine.get_stats()
    print(f"    总交互: {stats['total_interactions']}")
    print(f"    打断次数: {stats['total_interruptions']}")
    print(f"    平均延迟: {stats['avg_response_latency_ms']}ms")
    print(f"    当前状态: {stats['state']}")
    print()

    print("=" * 70)
    print("全双工语音感知对话 测试完成")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())