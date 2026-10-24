"""步态可视化 — 把足端轨迹和支撑/摆动相画成 SVG，肉眼验证步态是否合理

用途：
  · 确认 trot 的对角步态真的对角（LF+RR 同相）
  · 确认支撑相足端贴地、摆动相抬起
  · 确认摆动相回到前点（不会越走越偏）

跑法：python tools/gait_animate.py
输出：gait_trot.svg / gait_walk.svg
"""
import sys
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "sdk"))

from laap_esp32.gait import (
    QuadrupedGait, GaitType, GaitParams, LEG_NAMES,
    GAIT_PHASE, GAIT_DUTY,
)

COLORS = {
    "LF": "#22d3ee", "RF": "#f472b6",
    "LR": "#a78bfa", "RR": "#fbbf24",
}


def export_svg(gait_type: GaitType, steps: int = 60, out: str = "") -> str:
    """把一条腿的（或四腿的）足端轨迹导出 SVG"""
    g = QuadrupedGait(gait_type, GaitParams(period_s=0.5, step_height=30,
                                           body_height=120, stance_reach=60))
    dt = 0.5 / steps
    traces = {n: [] for n in LEG_NAMES}
    phases = {n: [] for n in LEG_NAMES}

    for i in range(steps + 1):
        # 手动推进看足端（复用私有方法拿轨迹）
        g.phase = (i / steps) % 1.0
        for name in LEG_NAMES:
            duty = GAIT_DUTY[gait_type]
            off = GAIT_PHASE[gait_type][name]
            lp = (g.phase + off) % 1.0
            x, y, z = g._foot_position(name, lp, duty, 60.0, 0.0, 0.0)
            traces[name].append((x, y, z))
            phases[name].append("stance" if lp < duty else "swing")

    # SVG 画布：横轴 = 前进方向 x（mm），纵轴 = 高度 z（mm，向上为正）
    W, H = 760, 300
    mx = 40
    xs = [p[0] for n in LEG_NAMES for p in traces[n]]
    zs = [p[2] for n in LEG_NAMES for p in traces[n]]
    xr = max(1.0, (max(xs) - min(xs)) / 2) * 1.3
    z0, z1 = min(zs) - 10, max(zs) + 10

    def sx(x):      # x → 屏幕横坐标（中心 380）
        return W / 2 + (x / xr) * (W / 2 - mx * 2)

    def sy(z):      # z → 屏幕纵坐标（上下翻转）
        return H - mx - ((z - z0) / (z1 - z0)) * (H - mx * 2)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}">',
        '<rect width="100%" height="100%" fill="#0a0e17"/>',
        # 地面线
        f'<line x1="{mx}" y1="{sy(z0)}" x2="{W-mx}" y2="{sy(z0)}" '
        f'stroke="#334155" stroke-dasharray="4 4"/>',
        f'<text x="{mx}" y="{sy(z0)-6}" fill="#475569" font-size="11">地面</text>',
    ]

    # 每条腿画轨迹：支撑相实线，摆动相虚线点
    for name in LEG_NAMES:
        c = COLORS[name]
        for i in range(len(traces[name]) - 1):
            x1, _, z1v = traces[name][i]
            x2, _, z2v = traces[name][i + 1]
            swing = phases[name][i] == "swing"
            parts.append(
                f'<line x1="{sx(x1):.1f}" y1="{sy(z1v):.1f}" '
                f'x2="{sx(x2):.1f}" y2="{sy(z2v):.1f}" '
                f'stroke="{c}" stroke-width="{2.4 if swing else 1.2}" '
                f'opacity="{1.0 if swing else 0.45}"/>'
            )
        # 腿标签（取最后一个点）
        lx, _, lz = traces[name][-1]
        parts.append(
            f'<text x="{sx(lx):.1f}" y="{sy(lz)-8:.1f}" fill="{c}" '
            f'font-size="11" font-weight="700">{name}</text>'
        )

    # 图例
    parts.append(
        f'<text x="{mx}" y="24" fill="#22d3ee" font-size="14" font-weight="700">'
        f'{gait_type.value.upper()} 步态 · 足端轨迹</text>'
    )
    parts.append(
        f'<text x="{mx}" y="42" fill="#64748b" font-size="11">'
        f'虚线点=摆动相（抬腿） · 淡实线=支撑相（贴地推） · 相位 '
        f'LF={GAIT_PHASE[gait_type]["LF"]} RF={GAIT_PHASE[gait_type]["RF"]} '
        f'duty={GAIT_DUTY[gait_type]}</text>'
    )
    parts.append("</svg>")

    svg = "\n".join(parts)
    if out:
        Path(out).write_text(svg, encoding="utf-8")
    return svg


def text_preview(gait_type: GaitType, steps: int = 24):
    """终端也能看：打印四腿的 支撑(S) / 摆动(W) 时序图"""
    duty = GAIT_DUTY[gait_type]
    off = GAIT_PHASE[gait_type]
    print(f"\n{gait_type.value.upper()} 步态时序（一格 = 1/{steps} 周期）")
    print("     " + "".join(str((i // 10) % 10) for i in range(steps)))
    for name in LEG_NAMES:
        row = ""
        for i in range(steps):
            lp = ((i / steps) + off[name]) % 1.0
            row += "S" if lp < duty else "W"
        print(f"  {name}  {row}")
    print(f"  （S=支撑相贴地 W=摆动相抬腿，占空比 {duty}）")


def main():
    outdir = Path(__file__).parent
    print("步态可视化")
    print("=" * 50)

    for gt in (GaitType.TROT, GaitType.WALK, GaitType.PACE):
        text_preview(gt, 24)
        p = outdir / f"gait_{gt.value}.svg"
        export_svg(gt, steps=60, out=str(p))
        print(f"  → 已导出 {p.name}")

    print()
    print("检查要点：")
    print("  1. TROT 里 LF 和 RR 应该同时 S 同时 W（对角）")
    print("  2. WALK 里任一时刻应有 3 条腿在 S")
    print("  3. 摆动相轨迹应形成向上的弧（抬腿）")


if __name__ == "__main__":
    main()