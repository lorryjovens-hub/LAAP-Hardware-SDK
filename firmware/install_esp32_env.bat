@echo off
REM LAAPer ESP32 开发环境一键安装脚本
REM 适用于 Windows

echo.
echo ████████████████████████████████████████████████
echo ██  LAAPer ESP32 开发环境安装                  ██
echo ████████████████████████████████████████████████
echo.

REM 设置变量
set IDF_PATH=D:\LAAP\esp-idf
set IDF_TOOLS_PATH=D:\LAAP\esp-idf-tools
set SOLUTION_PATH=D:\LAAP\esp-webrtc-solution

REM 1. 检查 Git
echo [1/6] 检查 Git...
git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Git 未安装
    echo     请从 https://git-scm.com 下载安装 Git
    pause
    exit /b 1
)
echo [OK] Git 已安装

REM 2. 检查 Python
echo [2/6] 检查 Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Python 未安装
    echo     请从 https://python.org 下载安装 Python 3.11+
    pause
    exit /b 1
)
echo [OK] Python 已安装

REM 3. 下载 ESP-IDF
echo [3/6] 下载 ESP-IDF v5.4...
if not exist "%IDF_PATH%" (
    git clone -b v5.4 --recursive https://github.com/espressif/esp-idf.git "%IDF_PATH%"
) else (
    echo [OK] ESP-IDF 已存在
)

REM 4. 安装 ESP-IDF 工具
echo [4/6] 安装 ESP-IDF 工具...
cd /d "%IDF_PATH%"
call install.ps1 esp32s3
if %errorlevel% neq 0 (
    echo [X] ESP-IDF 工具安装失败
    pause
    exit /b 1
)
echo [OK] ESP-IDF 工具安装完成

REM 5. 下载 ESP-WebRTC Solution
echo [5/6] 下载 ESP-WebRTC Solution...
if not exist "%SOLUTION_PATH%" (
    git clone --recursive https://github.com/espressif/esp-webrtc-solution.git "%SOLUTION_PATH%"
) else (
    echo [OK] ESP-WebRTC Solution 已存在
)

REM 6. 配置 LAAPer 固件
echo [6/6] 配置 LAAPer 固件...
copy /Y "D:\LAAP\laap-hardware\firmware\esp32_laaper\laaper_perception.*" "%SOLUTION_PATH%\solutions\local_jpeg_stream\main\"
echo [OK] LAAPer 固件配置完成

echo.
echo ████████████████████████████████████████████████
echo ██  安装完成！                                  ██
echo ████████████████████████████████████████████████
echo.
echo  下一步：
echo    1. 修改 WiFi 配置
echo       编辑 %SOLUTION_PATH%\solutions\local_jpeg_stream\main\settings.h
echo.
echo    2. 编译固件
echo       运行 D:\LAAP\laap-hardware\firmware\flash_laaper.bat
echo.
echo    3. 烧录测试
echo       idf.py -p COM3 flash monitor
echo.
echo  详细指南：docs\ESP32_FLASHING_GUIDE.md
echo.
pause