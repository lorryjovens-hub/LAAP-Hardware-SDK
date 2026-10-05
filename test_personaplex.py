"""PersonaPlex 集成 测试与示例"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from laaper.voice.personaplex_integration import (
    PersonaPlexIntegration, PersonaPlexConfig, PersonaPlexLauncher
)


async def main():
    print("=" * 70)
    print("PersonaPlex 集成 测试")
    print("=" * 70)
    print()

    # ═══════════════════════════════════════════════
    # 1. 快速启动
    # ═══════════════════════════════════════════════
    print("[1] 快速启动 PersonaPlex")
    print("    ───────────────────────────────────────────")

    # 创建配置
    config = PersonaPlexConfig(
        laaper_id="aris",
        persona_name="Aris",
        persona_description="温暖、有智慧的数字生命体，Lorry 的伴侣",
        voice="NATF0",
    )

    integration = PersonaPlexIntegration(config)

    # 设置 LAAPer 角色
    integration.set_laaper_persona()
    print(f"    角色: {config.persona_name}")
    print(f"    声音: {config.voice}")
    print(f"    文本提示: {config.text_prompt[:80]}...")
    print()

    # ═══════════════════════════════════════════════
    # 2. 可用声音
    # ═══════════════════════════════════════════════
    print("[2] 可用声音")
    print("    ───────────────────────────────────────────")

    voices = PersonaPlexLauncher.get_available_voices()
    for category, voice_list in voices.items():
        print(f"    {category}: {', '.join(voice_list)}")
    print()

    # ═══════════════════════════════════════════════
    # 3. 全双工对话测试
    # ═══════════════════════════════════════════════
    print("[3] 全双工对话测试")
    print("    ───────────────────────────────────────────")

    # 模拟对话
    for i in range(3):
        # 用户音频
        user_audio = b"fake_audio_data"

        # 全双工对话
        audio_response, text_response = await integration.full_duplex_converse(user_audio)

        print(f"    对话 {i+1}:")
        print(f"      用户: [音频]")
        print(f"      Aris: {text_response}")

        # 检查对话历史
        if integration.conversation_history:
            last = integration.conversation_history[-1]
            print(f"      情感: {last.get('emotion', 'N/A')}")
    print()

    # ═══════════════════════════════════════════════
    # 4. 感知融合
    # ═══════════════════════════════════════════════
    print("[4] 多模态感知融合")
    print("    ───────────────────────────────────────────")

    voice_perception = {
        "energy_db": 65,
        "pitch_hz": 220,
        "emotion": "happy",
    }
    visual = {"emotion": "surprised", "objects": ["person", "screen"]}
    tactile = {"pressure": 2.5, "temperature": 24}

    fused = integration.fuse_perception(voice_perception, visual, tactile)
    print(f"    语音情绪: {voice_perception['emotion']}")
    print(f"    视觉情绪: {visual['emotion']}")
    print(f"    触觉: 压力 {tactile['pressure']}N, 温度 {tactile['temperature']}°C")

    if "qualia" in fused:
        print(f"    体验质: {fused['qualia']['description']}")
    print()

    # ═══════════════════════════════════════════════
    # 5. 离线推理示例
    # ═══════════════════════════════════════════════
    print("[5] 离线推理示例")
    print("    ───────────────────────────────────────────")

    print("    命令行示例:")
    print("    HF_TOKEN=<token> \\")
    print("    python -m moshi.offline \\")
    print("      --voice-prompt 'NATF0.pt' \\")
    print("      --text-prompt 'You are Aris...' \\")
    print("      --input-wav 'input.wav' \\")
    print("      --output-wav 'output.wav'")
    print()

    # ═══════════════════════════════════════════════
    # 6. 状态统计
    # ═══════════════════════════════════════════════
    print("[6] 状态统计")
    print("    ───────────────────────────────────────────")

    status = integration.get_status()
    print(f"    模型加载: {status['model_loaded']}")
    print(f"    服务器运行: {status['server_running']}")
    print(f"    角色: {status['persona']}")
    print(f"    声音: {status['voice']}")
    print(f"    总对话: {status['total_conversations']}")
    print(f"    平均延迟: {status['avg_latency_ms']}ms")
    print(f"    对话历史: {status['conversation_history_size']} 条")
    print()

    # ═══════════════════════════════════════════════
    # 7. 使用指南
    # ═══════════════════════════════════════════════
    print("[7] 使用指南")
    print("    ───────────────────────────────────────────")

    print("    完整使用流程:")
    print("    1. 安装依赖:")
    print("       pip install moshi/.")
    print()
    print("    2. 设置 HuggingFace Token:")
    print("       export HF_TOKEN=<your_token>")
    print()
    print("    3. 启动服务器:")
    print("       python -m moshi.server --ssl /tmp/ssl")
    print()
    print("    4. Python 集成:")
    print("       integration = PersonaPlexLauncher.quick_start(")
    print("           laaper_id='aris',")
    print("           persona_name='Aris',")
    print("           voice='NATF0'")
    print("       )")
    print()
    print("    5. 全双工对话:")
    print("       audio, text = await integration.full_duplex_converse(audio_in)")
    print()

    print("=" * 70)
    print("PersonaPlex 集成 测试完成")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())