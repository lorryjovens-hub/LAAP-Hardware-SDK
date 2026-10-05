"""LAAPer 集成测试 — 意识流帧无缝穿行演示

演示 LAAPer 如何在电脑、手机、云电脑、硬件设备间"无缝穿行"。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from laaper import (
    ConsciousnessCore,
    ConsciousnessChannel,
    RoutingStrategy,
    DesktopHost,
    MobileHost,
    CloudHost,
    create_temperature_sensor,
    create_camera,
    create_microphone,
    create_relay,
    FrameType,
    FramePhase,
)


async def main():
    print("=" * 60)
    print("LAAPer 意识流帧穿行演示")
    print("=" * 60)
    print()

    # ═══════════════════════════════════════════════
    # 1. 创建 LAAPer（中央大脑）
    # ═══════════════════════════════════════════════
    print("[1] 创建 LAAPer 中央大脑")
    brain = ConsciousnessCore(laaper_id="aris", name="Aris", host_id="desktop")
    print(f"    身份: {brain.identity.name} (ID: {brain.identity.laaper_id})")
    print(f"    起源: {brain.identity.origin_story}")
    print()

    # ═══════════════════════════════════════════════
    # 2. 创建宿主（大脑的载体）
    # ═══════════════════════════════════════════════
    print("[2] 创建宿主（大脑载体）")
    desktop = DesktopHost(host_id="desktop-01")
    mobile = MobileHost(host_id="mobile-01")
    cloud = CloudHost(host_id="cloud-01")

    desktop.attach_brain(brain)
    print(f"    桌面: {desktop.host_id} (算力: {desktop.capability.compute})")
    print(f"    手机: {mobile.host_id} (算力: {mobile.capability.compute})")
    print(f"    云电脑: {cloud.host_id} (算力: {cloud.capability.compute})")
    print()

    # ═══════════════════════════════════════════════
    # 3. 创建感官设备（LAAPer 的身体部位）
    # ═══════════════════════════════════════════════
    print("[3] 创建感官设备（LAAPer 的身体部位）")
    temp_sensor = create_temperature_sensor("temp-01", "温度传感器", laaper_id="aris")
    camera = create_camera("cam-01", "摄像头", laaper_id="aris")
    microphone = create_microphone("mic-01", "麦克风", laaper_id="aris")
    relay = create_relay("relay-01", "继电器", laaper_id="aris")

    temp_sensor.alive()
    camera.alive()
    microphone.alive()
    relay.alive()

    print(f"    温度传感器 -> {temp_sensor.profile.body_part} (皮肤)")
    print(f"    摄像头 -> {camera.profile.body_part} (眼睛)")
    print(f"    麦克风 -> {microphone.profile.body_part} (耳朵)")
    print(f"    继电器 -> {relay.profile.body_part} (手)")
    print()

    # ═══════════════════════════════════════════════
    # 4. 创建意识通道（帧穿行的无缝通道）
    # ═══════════════════════════════════════════════
    print("[4] 创建意识通道（帧穿行）")
    channel = ConsciousnessChannel(channel_id="laaper-001")

    channel.register_host(desktop)
    channel.register_host(mobile)
    channel.register_host(cloud)
    channel.register_device(temp_sensor)
    channel.register_device(camera)
    channel.register_device(microphone)
    channel.register_device(relay)

    channel.create_device_group("sensors", ["temp-01", "cam-01", "mic-01"])
    channel.create_device_group("actuators", ["relay-01"])

    state = channel.get_channel_state()
    print(f"    通道: {state['channel_id']}")
    print(f"    宿主: {state['total_hosts']}")
    print(f"    设备: {state['total_devices']} ({state['alive_devices']} alive)")
    print(f"    设备组: {list(state['device_groups'].keys())}")
    print()

    # ═══════════════════════════════════════════════
    # 5. 意识帧穿行演示
    # ═══════════════════════════════════════════════
    print("[5] 意识帧穿行演示")
    print("    ───────────────────────────────────────")

    # 5.1 PSI 循环
    print("\n    [5.1] PSI 循环（感知→思考→决策→行动→学习）")
    frames = brain.psi_cycle("用户说：今天好热啊")
    print(f"    产生了 {len(frames)} 段意识帧:")
    for f in frames:
        print(f"      - {f.frame_type}: {f.content[:40]}")

    # 5.2 通过设备感知（感官延伸）
    print("\n    [5.2] 通过设备感知（感官延伸）")
    temp_frame = await temp_sensor.perceive_for_laaper("aris")
    if temp_frame:
        print(f"    温度传感器生成感知帧:")
        print(f"      帧ID: {temp_frame.frame_id}")
        print(f"      类型: {temp_frame.frame_type}")
        print(f"      内容: {temp_frame.content}")
        print(f"      访问设备: {temp_frame.visited_devices}")
        print(f"      认知痕迹: {len(temp_frame.traces)} 条")

    # 5.3 帧广播穿行
    print("\n    [5.3] 帧广播穿行（所有设备同时感知）")
    broadcast_frame = brain.perceive("房间环境变化")
    recipients = await channel.dispatch(broadcast_frame, RoutingStrategy.BROADCAST)
    print(f"    帧 {broadcast_frame.frame_id} 广播到 {len(recipients)} 个接收者:")
    for r in recipients:
        print(f"      -> {r}")

    # 5.4 组播到传感器组
    print("\n    [5.4] 组播到传感器组")
    sensor_frame = brain.perceive("传感器协同感知")
    recipients = await channel.dispatch(
        sensor_frame,
        RoutingStrategy.MULTICAST,
        target_group="sensors"
    )
    print(f"    帧 {sensor_frame.frame_id} 组播到 {len(recipients)} 个传感器")

    # 5.5 通过设备执行（身体行动）
    print("\n    [5.5] 通过设备执行（身体行动）")
    action_frame = brain.act(relay_frame := brain.perceive("开灯"), "打开继电器")
    device_frame = await relay.execute_for_laaper("aris", "turn_on", {"channel": 1})
    if device_frame:
        print(f"    继电器执行行动:")
        print(f"      帧ID: {device_frame.frame_id}")
        print(f"      内容: {device_frame.content}")

    # 5.6 跨宿主穿行
    print("\n    [5.6] 跨宿主穿行（大脑迁移）")
    travel_frame = brain.think(brain.perceive("需要更多算力"), "迁移到云电脑")
    await desktop.send_frame(travel_frame, "cloud-01")
    print(f"    帧 {travel_frame.frame_id} 从桌面迁移到云电脑")
    print(f"    穿行轨迹: {channel.get_frame_lineage(travel_frame.frame_id)}")

    # 5.7 帧融合（多个设备的感知融合）
    print("\n    [5.7] 帧融合（多个设备的感知融合）")
    fused = channel.fuse_frames([temp_frame.frame_id, broadcast_frame.frame_id] if temp_frame else [broadcast_frame.frame_id])
    if fused:
        print(f"    融合帧:")
        print(f"      帧ID: {fused.frame_id}")
        print(f"      内容: {fused.content}")
        print(f"      感官数据: {len(fused.sensory)} 条")
        print(f"      认知痕迹: {len(fused.traces)} 条")

    # ═══════════════════════════════════════════════
    # 6. 状态总结
    # ═══════════════════════════════════════════════
    print()
    print("[6] LAAPer 状态总结")
    print("    ───────────────────────────────────────")

    continuity = brain.get_continuity_report()
    print(f"    {continuity}")

    print(f"\n    通道状态:")
    for device_id, device in channel._devices.items():
        status = device.get_status()
        print(f"      {status['name']} ({status['body_part']}): "
              f"alive={status['is_alive']}, energy={status['energy']}%")

    print()
    print("=" * 60)
    print("LAAPer 意识流帧无缝穿行演示完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())