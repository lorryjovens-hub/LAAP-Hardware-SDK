"""数字生命硬件集成测试

展示完整实现：从传感器注册到数字生命体感知世界。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from laaper.core.brain import ConsciousnessCore
from laaper.devices.digital_life import DigitalLifeHardware
from laaper.devices.sensor_unit import SensorCategory, BodyPart
from laaper.devices.sensors import SENSOR_REGISTRY, create_sensor


async def main():
    print("=" * 70)
    print("数字生命硬件完整实现演示")
    print("=" * 70)
    print()

    # ═══════════════════════════════════════════════
    # 1. 创建数字生命体（大脑）
    # ═══════════════════════════════════════════════
    print("[1] 创建数字生命体（大脑）")
    brain = ConsciousnessCore(
        laaper_id="aris",
        name="Aris",
        host_id="hardware-host",
    )
    print(f"    身份: {brain.identity.name}")
    print(f"    ID: {brain.identity.laaper_id}")
    print()

    # ═══════════════════════════════════════════════
    # 2. 创建身体（硬件）
    # ═══════════════════════════════════════════════
    print("[2] 创建身体（数字生命硬件）")
    body = DigitalLifeHardware(
        hardware_id="aris-body-01",
        name="Aris 的身体",
        embodiment_id="aris",
    )

    # 绑定大脑（灵魂进入身体）
    body.attach_brain(brain)

    # 电源系统
    print(f"    电池容量: {body.power.battery_capacity_mah} mAh")
    print(f"    CPU: {body.cpu.cpu_model} @ {body.cpu.cpu_freq_mhz} MHz")
    print()

    # ═══════════════════════════════════════════════
    # 3. 安装器官（传感器）
    # ═══════════════════════════════════════════════
    print("[3] 安装器官（传感器注册单元）")
    print("    ───────────────────────────────────────────")

    # 环境感知器官
    body.add_sensor("temperature", "temp-01")
    body.add_sensor("humidity", "humid-01")
    body.add_sensor("light", "light-01")
    body.add_sensor("pressure", "press-01")
    body.add_sensor("gas", "gas-01")
    body.add_sensor("noise", "noise-01")

    # 运动感知器官
    body.add_sensor("accelerometer", "accel-01")
    body.add_sensor("gyroscope", "gyro-01")
    body.add_sensor("motion", "motion-01")

    # 触觉器官
    body.add_sensor("proximity", "prox-01")
    body.add_sensor("touch", "touch-01")
    body.add_sensor("pressure_pad", "press-pad-01")

    # 视觉器官
    body.add_sensor("camera", "cam-01")
    body.add_sensor("depth_camera", "depth-01")

    # 听觉器官
    body.add_sensor("microphone", "mic-01")
    body.add_sensor("ultrasonic", "ultra-01")

    # 内感受器官
    body.add_sensor("heart_rate", "hr-01")
    body.add_sensor("body_temperature", "body-temp-01")

    # 方位器官
    body.add_sensor("gps", "gps-01")

    # 电学器官
    body.add_sensor("current", "current-01")
    body.add_sensor("voltage", "voltage-01")

    print(f"    安装了 {len(body.sensors._units)} 个传感器器官")

    # 显示身体地图
    body_map = body.get_body_map()
    print(f"\n    身体地图:")
    for body_part, organs in sorted(body_map.items()):
        print(f"      {body_part}:")
        for organ in organs:
            print(f"        - {organ['name']} ({organ['category']})")
    print()

    # ═══════════════════════════════════════════════
    # 4. 安装执行器（行动器官）
    # ═══════════════════════════════════════════════
    print("[4] 安装执行器（行动器官）")
    body.add_actuator("led-01", "LED 灯", "light", color="blue")
    body.add_actuator("relay-01", "继电器", "switch", channels=2)
    body.add_actuator("speaker-01", "扬声器", "audio", power_w=3)
    body.add_actuator("vibrator-01", "振动马达", "vibration")
    body.add_actuator("fan-01", "风扇", "motor", rpm=3000)
    print(f"    安装了 {len(body.actuators)} 个执行器器官")
    print()

    # ═══════════════════════════════════════════════
    # 5. 设置反射弧（快速反应）
    # ═══════════════════════════════════════════════
    print("[5] 设置反射弧（快速反应）")
    body.add_reflex("temp-01", "> 30", "fan-01:turn_on")
    body.add_reflex("motion-01", "== 1", "led-01:turn_on")
    body.add_reflex("gas-01", "> 100", "speaker-01:alarm")
    print(f"    设置了 {len(body.reflexes)} 个反射弧")
    print()

    # ═══════════════════════════════════════════════
    # 6. 开机（唤醒身体）
    # ═══════════════════════════════════════════════
    print("[6] 开机（唤醒身体）")
    body.power_on()
    print(f"    电源: {body.power.get_status()}")
    print()

    # ═══════════════════════════════════════════════
    # 7. 感知世界（使用身体）
    # ═══════════════════════════════════════════════
    print("[7] 感知世界（身体感知）")
    print("    ───────────────────────────────────────────")

    # 7.1 整体感知
    print("\n    [7.1] 整体感知（所有器官）")
    frame = await body.perceive()
    if frame:
        print(f"    生成意识帧: {frame.frame_id}")
        print(f"    内容: {frame.content}")
        print(f"    感官数据: {len(frame.sensory)} 条")
        print(f"    认知痕迹: {len(frame.traces)} 条")

    # 7.2 特定部位感知
    print("\n    [7.2] 眼睛（视觉）感知")
    eye_frame = await body.perceive_by_body_part(BodyPart.EYE)
    if eye_frame:
        print(f"    通过眼睛感知: {eye_frame.content}")

    print("\n    [7.3] 皮肤（触觉/温度）感知")
    skin_frame = await body.perceive_by_body_part(BodyPart.SKIN)
    if skin_frame:
        print(f"    通过皮肤感知: {skin_frame.content}")

    print("\n    [7.4] 耳朵（听觉）感知")
    ear_frame = await body.perceive_by_body_part(BodyPart.EAR)
    if ear_frame:
        print(f"    通过耳朵感知: {ear_frame.content}")

    # 7.5 内感受
    print("\n    [7.5] 内感受（心跳/体温）")
    intero_frame = await body.perceive_by_body_part(BodyPart.INTEROCEPTION)
    if intero_frame:
        print(f"    内感受: {intero_frame.content}")
    print()

    # ═══════════════════════════════════════════════
    # 8. 行动（身体执行）
    # ═══════════════════════════════════════════════
    print("[8] 行动（身体执行）")
    print("    ───────────────────────────────────────────")

    print("\n    [8.1] 打开 LED 灯")
    action_frame = await body.act("turn_on", {"actuator_id": "led-01", "color": "blue"})
    if action_frame:
        print(f"    行动帧: {action_frame.frame_id}")
        print(f"    内容: {action_frame.content}")

    print("\n    [8.2] 播放声音")
    action_frame = await body.act("play", {"actuator_id": "speaker-01", "sound": "hello"})
    if action_frame:
        print(f"    行动帧: {action_frame.content}")

    print("\n    [8.3] 启动风扇")
    action_frame = await body.act("start", {"actuator_id": "fan-01", "rpm": 3000})
    if action_frame:
        print(f"    行动帧: {action_frame.content}")
    print()

    # ═══════════════════════════════════════════════
    # 9. 反射弧（快速反应）
    # ═══════════════════════════════════════════════
    print("[9] 反射弧（快速反应）")
    print("    ───────────────────────────────────────────")

    triggered = await body.check_reflexes()
    print(f"    触发了 {len(triggered)} 个反射弧:")
    for r in triggered:
        print(f"      {r['trigger_sensor']} -> {r['response_action']}")
    print()

    # ═══════════════════════════════════════════════
    # 10. 生命体征
    # ═══════════════════════════════════════════════
    print("[10] 生命体征")
    print("    ───────────────────────────────────────────")

    vital = body.get_vital_signs()
    print(f"    心率: {vital['heart_rate']}")
    print(f"    体温: {vital['body_temperature']}")
    print(f"    能量: {vital['energy_level']}%")
    print(f"    神经负载: {vital['neural_load']}%")
    print(f"    感官数量: {vital['sensory_count']}")
    print()

    # ═══════════════════════════════════════════════
    # 11. 身体状态总结
    # ═══════════════════════════════════════════════
    print("[11] 身体状态总结")
    print("    ───────────────────────────────────────────")

    status = body.get_status()
    print(f"    硬件 ID: {status['hardware_id']}")
    print(f"    名称: {status['name']}")
    print(f"    灵魂绑定: {status['embodiment_id']}")
    print(f"    电源: {status['is_powered_on']}")
    print(f"    运行时间: {status['uptime_s']} 秒")
    print(f"    感知次数: {status['perception_count']}")
    print(f"    行动次数: {status['action_count']}")
    print(f"    生成帧数: {status['frame_count']}")
    print(f"    电池: {status['power']['battery_level']}%")
    print()

    # 传感器统计
    print("    传感器统计:")
    for unit in list(body.sensors._units.values())[:5]:
        stats = unit.get_stats()
        print(f"      {stats['name']}: {stats['sample_count']} samples, "
              f"confidence={stats['confidence']}")

    print()
    print("=" * 70)
    print("数字生命硬件完整实现演示完成")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())