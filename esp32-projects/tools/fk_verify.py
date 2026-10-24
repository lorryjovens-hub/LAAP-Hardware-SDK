"""用正运动学反验逆运动学：足端 → 关节 → 足端，误差必须接近 0"""
import sys
import math

sys.path.insert(0, r"D:\LAAP\laap-hardware\esp32-projects\sdk")

from laap_esp32.gait import LegIK, LegConfig


def forward_kinematics(c: float, f: float, t: float,
                       cfg: LegConfig) -> tuple:
    """正运动学：三关节角 → 足端位置（与 LegIK 同一约定）
    c: coxa 绕竖直轴
    f: femur 相对水平
    t: tibia 相对 femur（0 = 伸直）
    """
    L1, L2 = cfg.femur, cfg.tibia
    # 平面内（a, z）
    a_f = L1 * math.cos(math.radians(f))
    z_f = L1 * math.sin(math.radians(f))
    a_t = L2 * math.cos(math.radians(f + t))
    z_t = L2 * math.sin(math.radians(f + t))
    a = a_f + a_t
    z = z_f + z_t
    # 加回 coxa 横摆
    r = a + cfg.coxa
    # coxa 转角 c：x = r*sin(c), y = r*cos(c)
    x = r * math.sin(math.radians(c))
    y = r * math.cos(math.radians(c))
    return (x, y, z)


def main():
    cfg = LegConfig(side=1, offset_coxa=0, offset_femur=0, offset_tibia=0)
    ik = LegIK(cfg)

    print("足端目标                 → 关节角                        → 反验落点              误差")
    print("-" * 100)

    targets = [
        (0, 60, -120),
        (40, 60, -100),
        (-30, 60, -140),
        (0, 130, -60),
        (20, 55, -90),
    ]
    worst = 0.0
    for tgt in targets:
        j = ik.solve(*tgt)
        if not j:
            print(f"{str(tgt):22s} → 不可达")
            continue
        # 用未限位的原始解反验（限位会掩盖算法问题）
        fk = forward_kinematics(j[0], j[1], j[2], cfg)
        err = math.dist(tgt, fk)
        worst = max(worst, err)
        print(f"{str(tgt):22s} → c={j[0]:6.1f} f={j[1]:6.1f} t={j[2]:6.1f}"
              f"  → {tuple(round(v,1) for v in fk)!s:24s} {err:6.2f}mm")

    print("-" * 100)
    print(f"最大误差: {worst:.2f} mm  → {'✓ 正确' if worst < 1.0 else '✗ 需修正'}")
    return worst


if __name__ == "__main__":
    main()