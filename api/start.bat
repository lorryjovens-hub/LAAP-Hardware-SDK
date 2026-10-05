@echo off
REM LAAP API 启动脚本

echo.
echo ████████████████████████████████████████████████
echo ██  LAAP API 服务启动                          ██
echo ████████████████████████████████████████████████
echo.

REM 安装依赖
echo [1/2] 安装依赖...
pip install -r requirements.txt

REM 启动服务
echo [2/2] 启动 API 服务...
echo API 文档: http://localhost:8000/docs
echo WebSocket: ws://localhost:8000/ws/{user_id}
echo.
python main.py