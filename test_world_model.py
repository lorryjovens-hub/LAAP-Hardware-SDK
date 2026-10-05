"""世界模型 + LAAP-EB 桥接 集成测试"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from laaper.world.model import WorldModel, CausalRelation, PhysicsLaw
from laaper.integration.eb_bridge import EBBridge


async def main():
    print("=" * 70)
    print("世界模型 + LAAP-EB 桥接 测试")
    print("=" * 70)
    print()

    # ═══════════════════════════════════════════════
    # 1. 世界模型
    # ═══════════════════════════════════════════════
    print("[1] 世界模型（因果理解）")
    print("    ───────────────────────────────────────────")

    world = WorldModel(model_id="aris-world")

    # 记录事件序列
    world.record_event("evt_1", "温度升高", {"temperature": 35}, entities=["room"])
    world.record_event("evt_2", "风扇启动", {"fan_speed": 3000}, entities=["fan", "room"])
    world.record_event("evt_3", "温度下降", {"temperature": 28}, entities=["room"])
    world.record_event("evt_4", "风扇停止", {"fan_speed": 0}, entities=["fan"])

    # 手动学习因果
    world.learn_causality("evt_1", "evt_2", CausalRelation.CAUSES, strength=0.9)
    world.learn_causality("evt_2", "evt_3", CausalRelation.CAUSES, strength=0.8)

    print(f"    记录事件: {world.total_events}")
    print(f"    因果边: {world.total_causal_edges}")

    # 因果链
    chain = world.get_causal_chain("evt_3")
    print(f"    evt_3 的因果链: {len(chain)} 条边")

    # 根本原因
    roots = world.get_root_causes("evt_3")
    print(f"    evt_3 的根本原因: {roots}")

    # 预测
    prediction = world.predict_next({"temperature": 40})
    if prediction:
        print(f"    预测: {prediction.event_type} (置信度={prediction.confidence:.2f})")
    else:
        print(f"    预测: 无模式匹配")

    # 反事实
    result = world.counterfactual({"temperature": 20}, "evt_2")
    print(f"    反事实: 温度20°C时，风扇会启动吗？{result['would_happen']}")
    print(f"      原因: {result['reasons']}")

    # 抽象概念
    concept = world.abstract_concept("降温事件", ["evt_1", "evt_3"])
    print(f"    抽象概念: {concept['name']}")
    print(f"      共同实体: {concept['common_entities']}")

    # 物理定律
    world.learn_physics_law(PhysicsLaw.THERMODYNAMICS, {"k": 0.1, "T_env": 22.0})
    state = world.apply_physics(PhysicsLaw.THERMODYNAMICS, {"temperature": 35})
    print(f"    物理预测: 35°C -> {state['temperature']:.1f}°C")

    print()

    # ═══════════════════════════════════════════════
    # 2. LAAP-EB 桥接
    # ═══════════════════════════════════════════════
    print("[2] LAAP-EB 感知桥接")
    print("    ───────────────────────────────────────────")

    bridge = EBBridge(laaper_id="aris")

    # EB 传来的感知
    qualia1 = bridge.receive_eb_perception("temperature", 35, body_part="skin")
    qualia2 = bridge.receive_eb_perception("pressure", 3.2, body_part="hand")
    qualia3 = bridge.receive_eb_perception("light", 8000, body_part="eye")
    qualia4 = bridge.receive_eb_perception("sound", 75, body_part="ear")

    print(f"    接收 EB 感知: {len(bridge._qualiae_cache)} 个")
    print(f"      温度: {qualia1.description} (valence={qualia1.valence:+.1f})")
    print(f"      压力: {qualia2.description} (valence={qualia2.valence:+.1f})")
    print(f"      光照: {qualia3.description} (valence={qualia3.valence:+.1f})")
    print(f"      声音: {qualia4.description} (valence={qualia4.valence:+.1f})")

    # 转换成意识帧
    frame = bridge.to_consciousness_frame()
    if frame:
        print(f"\n    转换成意识帧: {frame.frame_id}")
        print(f"      内容: {frame.content}")
        print(f"      感官数据: {len(frame.sensory)} 条")
        print(f"      认知痕迹: {len(frame.traces)} 条")

    # 融合感知
    fused = bridge.fuse_perceptions()
    if fused:
        print(f"\n    跨模态融合: {fused.concept}")
        print(f"      描述: {fused.description}")
        print(f"      置信度: {fused.confidence:.2f}")

    # EB 行动
    action = bridge.to_eb_action("turn_on", {"actuator": "fan", "speed": 3000})
    print(f"\n    EB 行动: {action['action_type']}")
    print(f"      参数: {action['params']}")

    state = bridge.get_eb_state()
    print(f"\n    EB 状态: {state}")
    print()

    # ═══════════════════════════════════════════════
    # 3. 完整流程
    # ═══════════════════════════════════════════════
    print("[3] 完整流程（感知→理解→决策→行动）")
    print("    ───────────────────────────────────────────")

    # 模拟 EB 感知到危险
    bridge.receive_eb_perception("temperature", 80, body_part="skin")  # 高温
    bridge.receive_eb_perception("gas", 500, body_part="nose")         # 异味

    frame = bridge.to_consciousness_frame("感知到高温和异味！")
    fused = bridge.fuse_perceptions()

    if fused:
        print(f"    融合感知: {fused.concept}")
        print(f"      危险等级: {fused.emotional_arousal:.1f}")
        print(f"      建议行动: {fused.inferred_action}")

    # 世界模型记录
    world.record_event("evt_5", "高温危险", {"temperature": 80}, entities=["room", "person"])
    world.record_event("evt_6", "需要降温", {"action": "cool_down"}, entities=["person"])

    # 预测下一步
    prediction = world.predict_next({"temperature": 80})
    if prediction:
        print(f"    世界模型预测: {prediction.event_type}")

    print()
    print("=" * 70)
    print("世界模型 + LAAP-EB 桥接 测试完成")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())