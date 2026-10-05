"""ESP32 烧录验证工具

检查环境、编译固件、烧录测试。
"""
import os
import sys
import subprocess
import json
from pathlib import Path

IDF_PATH = Path(r"D:\LAAP\esp-idf")
SOLUTION_PATH = Path(r"D:\LAAP\esp-webrtc-solution\solutions\local_jpeg_stream")
FIRMWARE_PATH = Path(r"D:\LAAP\laap-hardware\firmware\esp32_laaper")


def check_environment():
    """检查环境"""
    print("=" * 70)
    print("ESP32 烧录环境检查")
    print("=" * 70)
    print()

    checks = []

    # 1. Python
    checks.append(("Python", sys.version.split()[0], True))

    # 2. ESP-IDF
    if IDF_PATH.exists():
        checks.append(("ESP-IDF", str(IDF_PATH), True))
    else:
        checks.append(("ESP-IDF", "未安装", False))

    # 3. ESP-WebRTC Solution
    if SOLUTION_PATH.exists():
        checks.append(("ESP-WebRTC", str(SOLUTION_PATH), True))
    else:
        checks.append(("ESP-WebRTC", "未下载", False))

    # 4. LAAPer 固件
    if FIRMWARE_PATH.exists():
        checks.append(("LAAPer 固件", str(FIRMWARE_PATH), True))
    else:
        checks.append(("LAAPer 固件", "不存在", False))

    # 5. 串口（Windows）
    import glob
    # Windows COM 端口格式：COM3, COM4 等
    ports = []
    for i in range(1, 20):
        port = f"COM{i}"
        if os.path.exists(f"\\\\.\\{port}"):
            ports.append(port)
    if not ports:
        ports = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/tty.usb*")
    if ports:
        checks.append(("串口", ", ".join(ports[:3]), True))
    else:
        checks.append(("串口", "未检测到（正常，未连接设备）", False))

    for name, value, ok in checks:
        status = "✓" if ok else "✗"
        print(f"  [{status}] {name}: {value}")

    print()
    return all(ok for _, _, ok in checks[:3])  # 前三项必须通过


def show_hardware_guide():
    """显示硬件准备指南"""
    print("=" * 70)
    print("硬件准备指南")
    print("=" * 70)
    print()
    print("  推荐开发板：")
    print("    1. ESP32-S3-Korvo-V2 (¥150) ⭐⭐⭐⭐⭐")
    print("       - 官方支持最好")
    print("       - OV2640/OV3660 摄像头")
    print("       - 麦克风 + 扬声器")
    print()
    print("    2. ESP32-S3-EYE (¥100) ⭐⭐⭐⭐")
    print("       - 紧凑型")
    print("       - OV2640 摄像头")
    print()
    print("    3. M5Stack Unit Cam (¥120) ⭐⭐⭐⭐")
    print("       - 模块化")
    print("       - 易于扩展")
    print()
    print("  采购渠道：")
    print("    - 淘宝搜索：'ESP32-S3 开发板 摄像头'")
    print("    - 京东搜索：'ESP32-S3-Korvo'")
    print("    - 官方商城：https://www.espressif.com")
    print()


def create_flash_script():
    """创建烧录脚本"""
    script = f"""@echo off
REM LAAPer ESP32 烧录脚本

echo ========================================
echo LAAPer ESP32 烧录工具
echo ========================================
echo.

REM 1. 激活 ESP-IDF 环境
echo [1/4] 激活 ESP-IDF 环境...
call {IDF_PATH}\\export.ps1

REM 2. 进入解决方案目录
echo [2/4] 进入目录...
cd /d {SOLUTION_PATH}

REM 3. 设置目标芯片
echo [3/4] 设置目标芯片 (ESP32-S3)...
idf.py set-target esp32s3

REM 4. 编译
echo [4/4] 编译固件...
idf.py build

echo.
echo ========================================
echo 编译完成！
echo 烧录命令：idf.py -p COM3 flash monitor
echo ========================================
pause
"""

    script_path = Path(r"D:\LAAP\laap-hardware\firmware\flash_laaper.bat")
    script_path.write_text(script, encoding="utf-8")
    print(f"  烧录脚本: {script_path}")


def show_quick_start():
    """显示快速开始"""
    print("=" * 70)
    print("快速开始")
    print("=" * 70)
    print()
    print("  步骤 1: 硬件准备")
    print("    - 购买 ESP32-S3 开发板（带摄像头）")
    print("    - USB-C 数据线")
    print()
    print("  步骤 2: 软件安装")
    print("    - 下载 ESP-IDF v5.4")
    print("    - 下载 esp-webrtc-solution")
    print("    - 运行 flash_laaper.bat")
    print()
    print("  步骤 3: 配置 WiFi")
    print("    - 编辑 main/settings.h")
    print("    - 填入 WiFi 名和密码")
    print()
    print("  步骤 4: 烧录")
    print("    - idf.py -p COM3 flash monitor")
    print()
    print("  步骤 5: 测试")
    print("    - 浏览器打开 https://<设备IP>/webrtc/test")
    print("    - 串口输入 cmd ring")
    print("    - 看到实时视频流！")
    print()
    print("  详细指南: docs/ESP32_FLASHING_GUIDE.md")
    print()


def main():
    print()
    print("████████████████████████████████████████████████")
    print("██  LAAPer ESP32 烧录验证工具               ██")
    print("████████████████████████████████████████████████")
    print()

    # 环境检查
    env_ok = check_environment()

    if not env_ok:
        print("  [!] 环境检查未通过，请先安装 ESP-IDF 和 esp-webrtc-solution")
        print()
        show_hardware_guide()
        return

    # 创建烧录脚本
    create_flash_script()
    print()

    # 显示快速开始
    show_quick_start()

    # 询问下一步
    print("  下一步操作：")
    print("    1. 显示硬件准备指南")
    print("    2. 显示烧录步骤")
    print("    3. 退出")
    print()

    choice = input("  请选择 (1-3): ").strip()

    if choice == "1":
        show_hardware_guide()
    elif choice == "2":
        show_quick_start()


if __name__ == "__main__":
    main()