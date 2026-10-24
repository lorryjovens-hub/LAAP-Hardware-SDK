"""LAAP ESP32 SDK 自检：IK + 步态 + 运动抽象 + 协议"""
import sys
import json

sys.path.insert(0, r"D:\LAAP\laap-hardware\esp32-projects\sdk")


def main():
    from laap_esp32 import (
        LegIK, LegConfig, QuadrupedGait, GaitType, GaitParams,
        DifferentialDrive, PanTiltController, RobotSpec,
        LDPProtocol,
    )
    from laap_esp32.motion import QuadrupedMotion, make_controller
    from laap_esp32.gait import self_test as gait_selftest
    from laap_esp32.protocol import self_test as ldp_selftest

    print("=" * 68)
    print("  LAAP ESP32 SDK 自检")
    print("=" * 68)
    print()

    # ── 1. 单腿 IK ──
    print("[1] 单腿逆运动学（coxa40 / femur80 / tibia100）")
    ik = LegIK(LegConfig())
    for pos in [(0, 60, -120), (40, 60, -100), (-30, 60, -140), (0, 130, -60)]:
        r = ik.solve(*pos)
        if r:
            print(f"    足端 {str(pos):22s} → 关节 c={r[0]:6.1f} f={r[1]:6.1f} t={r[2]:6.1f}")
        else:
            print(f"    足端 {str(pos):22s} → 不可达")
    # 不可达用例
    far = ik.solve(0, 400, -120)
    print(f"    足端 (0,400,-120)        → {'不可达（正确）' if far is None else '竟然可达?'}")
    print()

    # ── 2. 步态自检 ──
    print("[2] Trot 步态一圈（25 步）")
    st = gait_selftest(25)
    print(f"    {json.dumps(st, ensure_ascii=False)}")
    print()

    # ── 3. 三种步态对比 ──
    print("[3] 三种步态（四腿相位偏移）")
    for gt in (GaitType.TROT, GaitType.WALK, GaitType.PACE):
        g = QuadrupedGait(gt, GaitParams())
        # 跑 1 步看相位
        joints = g.step(dt=0.02, vx=50)
        ok = all(v is not None for v in joints.values())
        from laap_esp32.gait import GAIT_PHASE, GAIT_DUTY
        print(f"    {gt.value:6s} 相位={GAIT_PHASE[gt]} 占空比={GAIT_DUTY[gt]}")
        print(f"           四腿可达: {'✓' if ok else '✗'}")
    print()

    # ── 4. 姿态动作 ──
    print("[4] 姿态（机械狗）")
    g = QuadrupedGait(GaitType.TROT)
    for pose_name in ("stand", "sit"):
        j = g.stand() if pose_name == "stand" else g.sit()
        avail = sum(1 for v in j.values() if v)
        print(f"    {pose_name:6s} → {avail}/4 腿有解")
    wave = g.wave(0.3)
    print(f"    wave   → RF 抬起: {wave['RF']}")
    print()

    # ── 5. 运动抽象（三类身体统一接口）──
    print("[5] 运动抽象统一接口")
    for kind in ("car", "dog", "pet"):
        m = make_controller(kind)
        m.move(vx=100, omega=30)
        cmd = m.tick(0.02)
        print(f"    {kind:4s} → {cmd['type']:14s} {json.dumps({k: v for k, v in cmd.items() if k != 'joints'}, ensure_ascii=False)[:90]}")
    print()

    # ── 6. 差速里程计 ──
    print("[6] 差速里程计（左轮 100 / 右轮 150 mm/s，跑 1 秒）")
    car = DifferentialDrive(RobotSpec(kind="car"))
    pose = (0.0, 0.0, 0.0)
    for _ in range(50):
        pose = car.odometry(0.02, 100, 150, pose)
    print(f"    位姿: x={pose[0]:.1f}mm y={pose[1]:.1f}mm θ={pose[2]:.1f}°")
    print()

    # ── 7. 云台（生命感）──
    print("[7] 云台姿态平滑（look_at + 一阶低通）")
    pt = PanTiltController()
    pt.look_at(dx=200, dy=100, distance=500)
    print(f"    目标: pan={pt._target_pan:.1f}° tilt={pt._target_tilt:.1f}°")
    for i in range(3):
        c = pt.tick(0.05)
        print(f"      第{i+1}周期 → pan={c['pan_deg']:.1f}° tilt={c['tilt_deg']:.1f}°")
    print()

    # ── 8. LDP 协议 ──
    print("[8] LDP 统一协议")
    lt = ldp_selftest()
    print(f"    hello: {lt['hello_ok']} | percept: {lt['percept_ok']} | move: {lt['move_ok']}")
    print(f"    能力声明: {json.dumps(lt['caps'], ensure_ascii=False)}")
    print(f"    中文→运动:")
    for text, r in lt["semantic"].items():
        print(f"      「{text}」→ {r}")
    print()

    # ── 9. 四足 MotionController 封装 ──
    print("[9] 四足统一接口（walk 指令）")
    qm = QuadrupedMotion()
    qm.move(vx=80, omega=20)
    cmd = qm.tick(0.02)
    print(f"    gait={cmd['gait']} phase={cmd['phase']}")
    print(f"    joints: {json.dumps(cmd['joints'], ensure_ascii=False)[:110]}")
    print()
    qm.pose("sit")
    print(f"    pose(sit) → {json.dumps(qm.tick(0.02)['joints'], ensure_ascii=False)[:90]}")
    print()

    print("=" * 68)
    print("  SDK 自检完成")
    print("=" * 68)


if __name__ == "__main__":
    main()