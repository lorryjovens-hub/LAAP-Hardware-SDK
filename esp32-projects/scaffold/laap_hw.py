"""LAAP 硬件脚手架 — 一条命令生成完整 IDF 工程项目

## 为什么需要脚手架

每次开新机器人，都要从头写：WiFi 连接、WS 客户端、LDP 协议分发、
运动控制骨架、表情/显示、构建配置…… 这套东西在四个项目里 90% 重复。

脚手架把这些抽成模板，一条命令生成，只改「硬件差异」部分。

## 用法

    # 生成桌面宠物工程
    python -m scaffold.laap_hw new pet --name my-pet --out D:/my-pet

    # 生成机器狗工程（12 舵机版）
    python -m scaffold.laap_hw new dog --name my-dog

    # 列出可用模板
    python -m scaffold.laap_hw list

    # 检查生成的工程（引脚/配置完整性）
    python -m scaffold.laap_hw doctor D:/my-pet
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


# ══════════════════════════════════════════════════════════
#  模板定义
# ══════════════════════════════════════════════════════════

@dataclass
class Template:
    """一个机器人模板"""
    kind: str
    title: str
    chip: str
    desc: str
    files: List[str] = field(default_factory=list)      # 需要复制的源文件
    pins: Dict[str, str] = field(default_factory=dict)  # 默认引脚


TEMPLATES: Dict[str, Template] = {
    "pet": Template(
        kind="pet",
        title="LAAP 桌面宠物",
        chip="esp32s3",
        desc="圆屏眼睛 + 双舵机云台 + 语音（最推荐的起步项目）",
        files=["display.c", "display.h", "motion.c", "motion.h",
               "audio.c", "audio.h", "touch.c", "touch.h",
               "network.c", "network.h", "main.c"],
        pins={
            "LCD_SCLK": "12", "LCD_MOSI": "11", "LCD_CS": "10",
            "LCD_DC": "9", "LCD_RST": "8", "LCD_BL": "7",
            "SERVO_PAN": "4", "SERVO_TILT": "5",
            "TOUCH": "6",
            "I2S_BCLK": "18", "I2S_LRCK": "17",
            "I2S_DOUT": "19", "I2S_DIN": "16",
        },
    ),
    "car": Template(
        kind="car",
        title="LAAP 机器车",
        chip="esp32s3",
        desc="差速底盘 + 编码器 PID + 超声避障",
        files=["motor.c", "motor.h", "odom.c", "odom.h",
               "sonar.c", "sonar.h", "network.c", "network.h", "main_car.c"],
        pins={
            "MOTOR_PWMA": "4", "MOTOR_AIN1": "5", "MOTOR_AIN2": "6",
            "MOTOR_PWMB": "7", "MOTOR_BIN1": "15", "MOTOR_BIN2": "16",
            "ENC_L_A": "9", "ENC_L_B": "11",
            "ENC_R_A": "10", "ENC_R_B": "12",
            "IMU_SDA": "8", "IMU_SCL": "18",
            "SONAR_TRIG": "17", "SONAR_ECHO": "21",
        },
    ),
    "dog": Template(
        kind="dog",
        title="LAAP 机械狗",
        chip="esp32s3",
        desc="12 舵机四足 + IK + trot/walk/pace 步态",
        files=["leg.c", "leg.h", "gait.c", "gait.h",
               "servo.c", "servo.h", "imu.c", "imu.h",
               "network.c", "network.h", "main_dog.c"],
        pins={
            "PCA9685_SDA": "8", "PCA9685_SCL": "18",
            "IMU_SDA": "8", "IMU_SCL": "18",
        },
    ),
    "desktop": Template(
        kind="desktop",
        title="LAAP 桌面机器人",
        chip="esp32s3",
        desc="宠物 + 车 合体（云台 + 底盘 + 表情 + 语音）",
        files=[],   # 组合式：复制 pet + car 的模块
        pins={},
    ),
}


# ══════════════════════════════════════════════════════════
#  生成
# ══════════════════════════════════════════════════════════

SRC_ROOT = Path(__file__).resolve().parent.parent  # esp32-projects/

# 模板源文件从这些目录找
SOURCE_DIRS = [
    SRC_ROOT / "projects" / "pet_robot" / "firmware" / "main",
    SRC_ROOT / "projects" / "robot_car" / "firmware" / "main",
    SRC_ROOT / "projects" / "robot_dog" / "firmware" / "main",
]

FOOTER_CMAKE = """# CMakeLists.txt — {title}
cmake_minimum_required(VERSION 3.16)
include($ENV{{IDF_PATH}}/tools/cmake/project.cmake)
project({proj})
"""

SDKCONFIG = """# {title} — 默认配置
CONFIG_IDF_TARGET="{chip}"

# PSRAM（LVGL / 图像缓冲需要）
CONFIG_SPIRAM=y
CONFIG_SPIRAM_SPEED_80M=y
CONFIG_ESPTOOLPY_FLASHSIZE_16MB=y

# LVGL
CONFIG_LV_COLOR_DEPTH_16=y
CONFIG_LV_MEM_CUSTOM=y

# 控制循环需要细 tick
CONFIG_FREERTOS_HZ=1000
"""

KCONFIG = """menu "LAAP {title}"

    config {K}_WIFI_SSID
        string "WiFi SSID"
        default "LAAP-Office"

    config {K}_WIFI_PASS
        string "WiFi Password"
        default "laap2026"

    config {K}_WS_HOST
        string "LAAP host (电脑 IP)"
        default "192.168.1.100"

    config {K}_WS_PORT
        int "LAAP port"
        default 8765

endmenu
"""

PINS_HEADER = """/*
 * laap_pins.h — 引脚映射（脚手架生成，按实际接线改）
 *
 * 换板子时只改这个文件，其它代码不用动。
 */
#pragma once
#include "driver/gpio.h"

{defines}
"""


def _find_source(fname: str) -> Optional[Path]:
    for d in SOURCE_DIRS:
        p = d / fname
        if p.exists():
            return p
    return None


def cmd_new(kind: str, name: str, out: str, force: bool = False) -> int:
    tpl = TEMPLATES.get(kind)
    if not tpl:
        print(f"未知模板: {kind}（可用: {', '.join(TEMPLATES)}）")
        return 1

    dst = Path(out).resolve()
    if dst.exists() and any(dst.iterdir()) and not force:
        print(f"目录已存在且非空: {dst}（加 --force 覆盖）")
        return 1

    main_dir = dst / "main"
    main_dir.mkdir(parents=True, exist_ok=True)

    # 1. 复制源文件
    copied, missing = [], []
    for fname in tpl.files:
        src = _find_source(fname)
        if src:
            shutil.copy2(src, main_dir / fname)
            copied.append(fname)
        else:
            missing.append(fname)

    # 2. 生成引脚提示（引脚已由 BSP 接管，这里只留说明）
    (main_dir / "BOARD.md").write_text(
        f"# 板子选择\n\n"
        f"本工程的引脚 **不在这里改**，由 LAAP BSP 管理。\n\n"
        f"```bash\n"
        f"idf.py menuconfig\n"
        f"# LAAP BSP → Board Selection\n"
        f"```\n\n"
        f"可选板子：\n\n"
        f"| 板子 | 说明 |\n"
        f"|------|------|\n"
        f"| `s3_round_gc9a01` | ESP32-S3 + GC9A01 圆屏宠物板（¥120） |\n"
        f"| `s3_korvo2` | 乐鑫语音板（双麦+功放，无舵机） |\n"
        f"| `s3_eye` | 乐鑫视觉板（摄像头，无扬声器） |\n"
        f"| `p4_lcd` | ESP32-P4 大屏终端（需外挂 C6） |\n"
        f"| `generic` | 自定义板（menuconfig 里填引脚） |\n\n"
        f"换板子只改 menuconfig，业务代码一行不动。\n",
        encoding="utf-8",
    )

    # 3. 构建文件
    (dst / "CMakeLists.txt").write_text(
        FOOTER_CMAKE.format(title=tpl.title, proj=name.replace("-", "_")),
        encoding="utf-8",
    )
    (dst / "sdkconfig.defaults").write_text(
        SDKCONFIG.format(title=tpl.title, chip=tpl.chip), encoding="utf-8"
    )
    (main_dir / "Kconfig.projbuild").write_text(
        KCONFIG.format(title=tpl.title, K=kind.upper()), encoding="utf-8"
    )

    # 4. 主 CMakeLists（main 组件）
    srcs = " ".join(f'"{f}"' for f in copied if f.endswith(".c"))
    (main_dir / "CMakeLists.txt").write_text(
        f'idf_component_register(\n'
        f'    SRCS {srcs}\n'
        f'    INCLUDE_DIRS "."\n'
        f'    REQUIRES bsp laap_core esp_wifi esp_event esp_netif nvs_flash\n'
        f'        esp_websocket_client json\n'
        f')\n',
        encoding="utf-8",
    )

    # 5. 说明文件
    (dst / "README.md").write_text(
        f"# {tpl.title}\n\n"
        f"{tpl.desc}\n\n"
        f"芯片: `{tpl.chip}`\n\n"
        f"## 构建\n\n"
        f"```bash\n"
        f"cd {dst.name}\n"
        f"idf.py set-target {tpl.chip}\n"
        f"idf.py menuconfig   # ① Board Selection ② WiFi + LAAP host\n"
        f"idf.py build flash monitor\n"
        f"```\n\n"
        f"## 硬件\n\n"
        f"引脚全部由 **LAAP BSP** 管理（`components/bsp/boards/`）。\n"
        f"换板子只改 menuconfig 的 Board Selection，业务代码不用动。\n"
        f"详见 `main/BOARD.md`。\n\n"
        f"## 已生成文件\n\n"
        + "\n".join(f"- `main/{f}`" for f in copied)
        + ("\n\n## 缺源文件（需手写）\n\n" + "\n".join(f"- {m}" for m in missing)
           if missing else ""),
        encoding="utf-8",
    )

    print(f"✓ 已生成 {tpl.title} → {dst}")
    print(f"  复制 {len(copied)} 个源文件" +
          (f"，缺 {len(missing)} 个: {missing}" if missing else ""))
    print()
    print("下一步：")
    print(f"  cd {dst}")
    print(f"  idf.py set-target {tpl.chip}")
    print(f"  idf.py menuconfig     # WiFi + 电脑 IP")
    print(f"  idf.py build flash monitor")
    return 0


def cmd_list() -> int:
    print("LAAP 硬件模板：\n")
    for k, t in TEMPLATES.items():
        print(f"  {k:8s} {t.title}")
        print(f"           {t.desc}")
        print(f"           芯片: {t.chip} | 引脚 {len(t.pins)} 个 | 源文件 {len(t.files)} 个")
        print()
    return 0


def cmd_doctor(path: str) -> int:
    """检查生成的工程是否完整"""
    root = Path(path).resolve()
    print(f"检查 {root}\n")
    problems = []

    for must in ("CMakeLists.txt", "sdkconfig.defaults", "main"):
        if not (root / must).exists():
            problems.append(f"缺 {must}")

    main_dir = root / "main"
    if main_dir.is_dir():
        c_files = list(main_dir.glob("*.c"))
        h_files = list(main_dir.glob("*.h"))
        print(f"  C 源文件: {len(c_files)}")
        print(f"  头文件  : {len(h_files)}")
        if not (main_dir / "CMakeLists.txt").exists():
            problems.append("main/CMakeLists.txt 缺失")
        # BSP 接管引脚：检查是否依赖 bsp 组件
        cm = (main_dir / "CMakeLists.txt")
        if cm.exists() and "bsp" not in cm.read_text(encoding="utf-8", errors="replace"):
            problems.append("main/CMakeLists.txt 未 REQUIRES bsp（引脚无处定义）")
        # 检查 main 入口
        if not any("app_main" in f.read_text(errors="replace") for f in c_files):
            problems.append("没有 app_main 入口")
        # 检查是否有 WS host 配置引用
        joined = "\n".join(f.read_text(errors="replace") for f in c_files)
        if "WS_HOST" not in joined and "CONFIG_" not in joined:
            problems.append("未引用 CONFIG_* 配置（WiFi/服务器地址可能写死）")

    print()
    if problems:
        print("发现问题：")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    print("✓ 工程结构完整，可以 idf.py build")
    return 0


def main():
    ap = argparse.ArgumentParser(
        prog="laap_hw", description="LAAP 硬件脚手架")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("new", help="生成新工程")
    p_new.add_argument("kind", choices=list(TEMPLATES.keys()))
    p_new.add_argument("--name", default="laap-robot")
    p_new.add_argument("--out", default="")
    p_new.add_argument("--force", action="store_true")

    sub.add_parser("list", help="列出模板")

    p_doc = sub.add_parser("doctor", help="检查工程完整性")
    p_doc.add_argument("path")

    args = ap.parse_args()

    if args.cmd == "new":
        out = args.out or f"./{args.name}"
        sys.exit(cmd_new(args.kind, args.name, out, args.force))
    elif args.cmd == "list":
        sys.exit(cmd_list())
    elif args.cmd == "doctor":
        sys.exit(cmd_doctor(args.path))


if __name__ == "__main__":
    main()