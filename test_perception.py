"""感知映射系统集成测试

展示：物理量 → 体验质 → 跨模态融合 → 持久化 → 网络传输
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from laaper.perception.encoder import SensoryEncoder, QualiaType, SensoryModality
from laaper.perception.fusion import CrossModalFusion
from laaper.persistence.store import MemoryStore


async def main():
    print("=" * 70)
    print("感知映射系统集成测试")
    print("=" * 70)
    print()

    # ═══════════════════════════════════════════════
    # 1. 感官编码器
    # ═══════════════════════════════════════════════
    print("[1] 感官编码器（物理量 → 体验质）")
    print("    ───────────────────────────────────────────")

    encoder = SensoryEncoder()

    # 温度感知
    print("\n    温度感知:")
    for temp in [5, 12, 18, 23, 28, 35, 50]:
        qualia = encoder.encode_temperature(temp)
        print(f"      {temp:3d}°C -> {qualia.description:8s} "
              f"(valence={qualia.valence:+.1f}, {qualia.metaphor})")

    # 压力感知
    print("\n    压力感知:")
    for force in [0.05, 0.5, 2.5, 8, 25]:
        qualia = encoder.encode_pressure(force)
        print(f"      {force:5.1f}N -> {qualia.description:12s} "
              f"(valence={qualia.valence:+.1f}, {qualia.metaphor})")

    # 亮度感知
    print("\n    亮度感知:")
    for lux in [5, 50, 500, 5000, 50000]:
        qualia = encoder.encode_brightness(lux)
        print(f"      {lux:6d}lux -> {qualia.description:12s} "
              f"(valence={qualia.valence:+.1f})")

    # 声音感知
    print("\n    声音感知:")
    for db in [20, 40, 60, 80, 100]:
        qualia = encoder.encode_sound(db)
        print(f"      {db:3d}dB -> {qualia.description:12s} "
              f"(valence={qualia.valence:+.1f})")
    print()

    # ═══════════════════════════════════════════════
    # 2. 跨模态融合
    # ═══════════════════════════════════════════════
    print("[2] 跨模态融合（多感官 → 统一认知）")
    print("    ───────────────────────────────────────────")

    fusion = CrossModalFusion()

    # 场景 1：火
    print("\n    场景 1: 火")
    fire_qualiae = [
        encoder.encode_temperature(55),      # 热
        encoder.encode_brightness(8000),      # 亮
        encoder.encode_smell(150, 0.1),       # 烧焦味
        encoder.encode_sound(75),             # 噼啪声
    ]
    perception = fusion.fuse(fire_qualiae)
    if perception:
        print(f"      概念: {perception.concept}")
        print(f"      描述: {perception.description}")
        print(f"      隐喻: {perception.metaphor}")
        print(f"      原因: {perception.inferred_cause}")
        print(f"      行动: {perception.inferred_action}")
        print(f"      置信度: {perception.confidence:.2f}")

    # 场景 2：危险
    print("\n    场景 2: 危险")
    danger_qualiae = [
        encoder.encode_pain(0.9),             # 剧痛
        encoder.encode_motion(12),            # 剧烈运动
        encoder.encode_sound(100),            # 震耳
    ]
    perception = fusion.fuse(danger_qualiae)
    if perception:
        print(f"      概念: {perception.concept}")
        print(f"      描述: {perception.description}")
        print(f"      行动: {perception.inferred_action}")

    # 场景 3：舒适
    print("\n    场景 3: 舒适")
    comfort_qualiae = [
        encoder.encode_temperature(23),       # 舒适
        encoder.encode_pressure(0.5),         # 轻触
        encoder.encode_brightness(500),       # 适中
        encoder.encode_sound(35),             # 安静
    ]
    perception = fusion.fuse(comfort_qualiae)
    if perception:
        print(f"      概念: {perception.concept}")
        print(f"      描述: {perception.description}")
        print(f"      行动: {perception.inferred_action}")
    print()

    # ═══════════════════════════════════════════════
    # 3. 持久化存储
    # ═══════════════════════════════════════════════
    print("[3] 持久化存储（跨重启记忆）")
    print("    ───────────────────────────────────────────")

    store = MemoryStore(data_dir=str(Path(__file__).parent / ".test_data"))

    # 保存记忆
    store.save_memory({
        "memory_id": "mem_001",
        "laaper_id": "aris",
        "type": "perception",
        "content": "感知到火的温暖和噼啪声",
        "importance": 0.9,
        "tags": ["fire", "warm", "danger"],
    })

    store.save_memory({
        "memory_id": "mem_002",
        "laaper_id": "aris",
        "type": "experience",
        "content": "在舒适的环境中感到放松",
        "importance": 0.7,
        "tags": ["comfort", "relax"],
    })

    # 回忆
    memories = store.recall_memories("aris", query="火")
    print(f"    回忆'火': {len(memories)} 条")
    for m in memories:
        print(f"      - {m['content']}")

    memories = store.recall_memories("aris", query="舒适")
    print(f"    回忆'舒适': {len(memories)} 条")

    stats = store.get_stats()
    print(f"    存储统计: {stats['total_memories']} 条记忆")
    print()

    # ═══════════════════════════════════════════════
    # 4. 神经编码
    # ═══════════════════════════════════════════════
    print("[4] 神经编码（统一格式）")
    print("    ───────────────────────────────────────────")

    qualia = encoder.encode_temperature(55)
    neural_code = encoder.encode_to_neural(qualia, "temp_skin", 1234567890.0)
    print(f"    体验质: {qualia.description} -> 神经编码:")
    print(f"      感官 ID: {neural_code.sensory_id}")
    print(f"      脉冲频率: {neural_code.spike_rate:.1f} Hz")
    print(f"      幅度: {neural_code.amplitude:.3f}")
    print(f"      模式长度: {len(neural_code.spike_pattern)}")
    print()

    # ═══════════════════════════════════════════════
    # 5. 感知统计
    # ═══════════════════════════════════════════════
    print("[5] 感知统计")
    print("    ───────────────────────────────────────────")

    all_qualiae = []
    for temp in range(0, 55, 5):
        all_qualiae.append(encoder.encode_temperature(temp))
    for force in [0, 1, 5, 15, 30]:
        all_qualiae.append(encoder.encode_pressure(force))

    modalities = {}
    for q in all_qualiae:
        modalities.setdefault(q.modality.value, []).append(q)

    print(f"    编码了 {len(all_qualiae)} 个体验质")
    for modality, qualiae_list in modalities.items():
        avg_valence = sum(q.valence for q in qualiae_list) / len(qualiae_list)
        print(f"      {modality}: {len(qualiae_list)} 个, 平均 valence={avg_valence:+.2f}")

    print()
    print("=" * 70)
    print("感知映射系统集成测试完成")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())