"""BSP 板级定义检查器

没有 ESP-IDF 编译器时，BSP 最容易出的错不是语法，是**配置不一致**：

  1. Kconfig 里列了板子，boards/ 下没目录 → 选了就编译失败
  2. board_pins.h 里两个功能抢同一个 GPIO → 真机上神秘故障
  3. bsp_info_t 声明了 BSP_CAP_DISPLAY 但没实现 bsp_display_init
     → 运行时报"声明支持但未实现"
  4. 声明的 display_w/h 与实际初始化参数不符

这四类错误编译器都不报，只有烧到板子上才发现。

用法：
    python tools/bsp_doctor.py
    python tools/bsp_doctor.py --verbose
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
BSP = ROOT / "components" / "bsp"
BOARDS = BSP / "boards"

# 能力位 → 必须实现的强符号函数
CAP_REQUIRES = {
    "BSP_CAP_DISPLAY":   ["bsp_display_init"],
    "BSP_CAP_TOUCH":     ["bsp_touch_init"],
    "BSP_CAP_AUDIO_OUT": ["bsp_audio_init"],
    "BSP_CAP_AUDIO_IN":  ["bsp_audio_init"],
    "BSP_CAP_SERVO":     ["bsp_servo_init", "bsp_servo_set_angle"],
    "BSP_CAP_I2C":       ["bsp_i2c_init"],
    "BSP_CAP_BATTERY":   ["bsp_battery_percent"],
}

# 引脚宏名里出现这些关键词 → 视为「不同功能」
FUNC_HINTS = [
    ("LCD_SCLK", "显示"), ("LCD_MOSI", "显示"), ("LCD_CS", "显示"),
    ("LCD_DC", "显示"), ("LCD_RST", "显示"), ("LCD_BL", "显示"),
    ("SERVO", "舵机"), ("TOUCH", "触摸"),
    ("I2S_BCLK", "音频"), ("I2S_LRCK", "音频"), ("I2S_DOUT", "音频"),
    ("I2S_DIN", "音频"), ("I2S_MCLK", "音频"),
    ("IMU_SDA", "IMU"), ("IMU_SCL", "IMU"),
    ("CAM_", "摄像头"), ("BATTERY", "电池"),
    ("I2C_SDA", "I2C"), ("I2C_SCL", "I2C"),
    ("BUTTON", "按键"),
]


def func_of(macro: str) -> str:
    for key, f in FUNC_HINTS:
        if key in macro:
            return f
    return "其他"


@dataclass
class BoardReport:
    name: str
    has_board_c: bool = False
    has_pins: bool = False
    caps: Set[str] = field(default_factory=set)
    defined_funcs: Set[str] = field(default_factory=set)
    pins: Dict[int, List[Tuple[str, str, bool]]] = field(default_factory=dict)
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def scan_board(d: Path) -> BoardReport:
    r = BoardReport(name=d.name)
    bc = d / "board.c"
    bp = d / "board_pins.h"

    r.has_board_c = bc.exists()
    r.has_pins = bp.exists()

    if not r.has_board_c:
        r.issues.append("缺 board.c")
        return r

    src = bc.read_text(encoding="utf-8", errors="replace")

    # 1. 必须提供 bsp_board_info
    if "bsp_board_info" not in src:
        r.issues.append("未定义 bsp_board_info()")

    # 2. 收集 caps
    for m in re.finditer(r"BSP_CAP_\w+", src):
        r.caps.add(m.group(0))

    # 3. 收集定义的强符号（非 weak）
    for m in re.finditer(
            r"^(?!.*__attribute__\s*\(\(\s*weak)\s*"
            r"(?:esp_err_t|void|bool|int|uint16_t|uint8_t|uint32_t)\s+\*?\s*"
            r"(bsp_\w+)\s*\(",
            src, re.MULTILINE):
        r.defined_funcs.add(m.group(1))

    # 4. 声明了能力但没实现
    for cap, reqs in CAP_REQUIRES.items():
        if cap in r.caps:
            for fn in reqs:
                if fn not in r.defined_funcs:
                    r.warnings.append(
                        f"声明 {cap} 但未实现 {fn}()（会走到弱默认实现）")

    # 5. 显示尺寸一致性
    m_info = re.search(r"\.display_w\s*=\s*(\d+).*?\.display_h\s*=\s*(\d+)",
                       src, re.DOTALL)
    if m_info and bp.exists():
        pins_src = bp.read_text(encoding="utf-8", errors="replace")
        for name, val in (("W", m_info.group(1)), ("H", m_info.group(2))):
            m_def = re.search(rf"#define\s+BSP_LCD_{name}\s+(\d+)", pins_src)
            if m_def and m_def.group(1) != val:
                r.warnings.append(
                    f"display_{name.lower()} 信息里是 {val}，"
                    f"board_pins.h 里是 {m_def.group(1)}")

    # 6. 引脚冲突（最关键）
    if bp.exists():
        pins_src = bp.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(
                r"#define\s+(BSP_\w+)\s+GPIO_NUM_(\d+)([^\n]*)", pins_src):
            macro, num, tail = m.group(1), int(m.group(2)), m.group(3)
            # 行尾带 VERIFY 标记 → 已知待核对，不算硬错误
            verify = "VERIFY" in tail
            r.pins.setdefault(num, []).append((macro, func_of(macro), verify))

        for num, users in sorted(r.pins.items()):
            if len(users) < 2:
                continue
            funcs = {u[1] for u in users}
            macros = ", ".join(u[0] for u in users)
            if len(funcs) > 1:
                msg = f"GPIO{num} 被多个功能占用: {macros} → {' / '.join(funcs)}"
                # 只要有一个引脚标了 VERIFY，就降为警告
                if any(u[2] for u in users):
                    r.warnings.append(msg + "（引脚标了 VERIFY，待核对）")
                else:
                    r.issues.append(msg)
            else:
                r.warnings.append(f"GPIO{num} 同功能多宏: {macros}")

    # 7. 待核对引脚清单
    for num, users in sorted(r.pins.items()):
        for macro, func, verify in users:
            if verify:
                r.warnings.append(f"{macro} (GPIO{num}, {func}) 标了 VERIFY，需对原理图确认")

    return r


def check_kconfig(reports: List[BoardReport]) -> List[str]:
    """Kconfig 里列的板子与 boards/ 目录是否一致"""
    kc = BSP / "Kconfig"
    if not kc.exists():
        return ["缺 Kconfig"]

    src = kc.read_text(encoding="utf-8", errors="replace")
    ids = re.findall(r'default\s+"(\w+)"\s+if\s+BSP_BOARD_', src)
    dirs = {r.name for r in reports}

    issues = []
    for i in ids:
        if i not in dirs:
            issues.append(f"Kconfig 声明板子 '{i}' 但 boards/{i}/ 不存在")
    for d in dirs:
        if d not in ids:
            issues.append(f"boards/{d}/ 存在但 Kconfig 未声明")
    return issues


def main() -> int:
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    print("=" * 68)
    print("LAAP BSP 板级定义检查")
    print("=" * 68)

    if not BOARDS.exists():
        print(f"✗ 找不到 {BOARDS}")
        return 1

    dirs = sorted(d for d in BOARDS.iterdir() if d.is_dir())
    print(f"发现 {len(dirs)} 块板子\n")

    reports = [scan_board(d) for d in dirs]

    all_issues: List[str] = []

    for r in reports:
        status = "✓" if not r.issues else "✗"
        caps_n = len(r.caps)
        print(f"{status} {r.name:20s} 能力 {caps_n} 项  "
              f"函数 {len(r.defined_funcs)} 个  "
              f"引脚 {len(r.pins)} 个")

        if verbose:
            print(f"    能力: {' '.join(sorted(c.replace('BSP_CAP_','') for c in r.caps))}")
            print(f"    实现: {' '.join(sorted(r.defined_funcs))}")

        for w in r.warnings:
            print(f"    ⚠ {w}")
        for i in r.issues:
            print(f"    ✗ {i}")
            all_issues.append(f"[{r.name}] {i}")

    print()
    kc_issues = check_kconfig(reports)
    if kc_issues:
        print("Kconfig 一致性:")
        for i in kc_issues:
            print(f"  ✗ {i}")
            all_issues.append(i)
    else:
        print("Kconfig 一致性: ✓")

    # 汇总统计
    print()
    total_pins = sum(len(r.pins) for r in reports)
    total_funcs = sum(len(r.defined_funcs) for r in reports)
    total_caps = sum(len(r.caps) for r in reports)
    print(f"合计: {len(reports)} 块板 / {total_pins} 个引脚定义 / "
          f"{total_funcs} 个板级函数 / {total_caps} 项能力声明")

    print()
    if all_issues:
        print(f"发现 {len(all_issues)} 个问题：")
        for i in all_issues:
            print(f"  ✗ {i}")
        return 1

    print("✓ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())