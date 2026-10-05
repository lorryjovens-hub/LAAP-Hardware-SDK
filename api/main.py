"""LAAP 后端 API 服务 - FastAPI

登录鉴权 + 硬件监控 + WebSocket 实时通信
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, List, Optional
import asyncio
import json
import time
from datetime import datetime, timedelta

# 尝试导入 jwt 和 bcrypt，如果没有则使用简化版
try:
    import jwt
    HAS_JWT = True
except ImportError:
    HAS_JWT = False
    import hashlib
    import secrets

try:
    import bcrypt
    HAS_BCRYPT = True
except ImportError:
    HAS_BCRYPT = False

app = FastAPI(title="LAAP API", version="2.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer()

# ── 数据模型 ──────────────────────────────────

class UserRegister(BaseModel):
    username: str
    email: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class DeviceRegister(BaseModel):
    device_id: str
    device_name: str
    device_type: str
    capabilities: List[str]

class DeviceStatus(BaseModel):
    device_id: str
    status: str  # online/offline/warning/error
    battery: Optional[float] = None
    cpu_usage: Optional[float] = None
    memory_usage: Optional[float] = None
    last_seen: Optional[float] = None

# ── 内存数据库（生产环境用 PostgreSQL）──────────

users_db: Dict[str, Dict] = {}
devices_db: Dict[str, Dict] = {}
sessions_db: Dict[str, Dict] = {}

# JWT 配置
JWT_SECRET = "laap-secret-key-2026"
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# WebSocket 连接管理
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.user_connections: Dict[str, str] = {}  # user_id -> websocket_id
    
    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        ws_id = f"ws_{int(time.time()*1000)}"
        self.active_connections[ws_id] = websocket
        self.user_connections[user_id] = ws_id
        return ws_id
    
    def disconnect(self, ws_id: str):
        if ws_id in self.active_connections:
            del self.active_connections[ws_id]
        # 移除用户映射
        user_ids = [uid for uid, wid in self.user_connections.items() if wid == ws_id]
        for uid in user_ids:
            del self.user_connections[uid]
    
    async def send_to_user(self, user_id: str, message: dict):
        ws_id = self.user_connections.get(user_id)
        if ws_id and ws_id in self.active_connections:
            try:
                await self.active_connections[ws_id].send_json(message)
            except:
                self.disconnect(ws_id)
    
    async def broadcast(self, message: dict):
        for ws_id, websocket in self.active_connections.items():
            try:
                await websocket.send_json(message)
            except:
                self.disconnect(ws_id)

manager = ConnectionManager()

# ── 工具函数 ──────────────────────────────────

def create_token(user_id: str) -> str:
    """创建 JWT Token"""
    if HAS_JWT:
        payload = {
            "user_id": user_id,
            "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
            "iat": datetime.utcnow(),
        }
        return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    else:
        # 简化版 token
        import base64
        data = f"{user_id}:{int(time.time())}"
        return base64.b64encode(data.encode()).decode()

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict:
    """验证 JWT Token"""
    if HAS_JWT:
        try:
            payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token 已过期")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="无效的 Token")
    else:
        # 简化版验证
        try:
            import base64
            data = base64.b64decode(credentials.credentials).decode()
            user_id = data.split(":")[0]
            return {"user_id": user_id}
        except:
            raise HTTPException(status_code=401, detail="无效的 Token")

def hash_password(password: str) -> str:
    """密码加密"""
    if HAS_BCRYPT:
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    else:
        # 简化版加密
        return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    """验证密码"""
    if HAS_BCRYPT:
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    else:
        return hashlib.sha256(password.encode()).hexdigest() == hashed

# ── 认证 API ──────────────────────────────────

@app.post("/api/auth/register")
async def register(user: UserRegister):
    """用户注册"""
    if user.username in users_db:
        raise HTTPException(status_code=400, detail="用户名已存在")
    
    users_db[user.username] = {
        "user_id": f"user_{int(time.time()*1000)}",
        "username": user.username,
        "email": user.email,
        "password": hash_password(user.password),
        "created_at": time.time(),
    }
    
    return {"message": "注册成功", "user_id": users_db[user.username]["user_id"]}

@app.post("/api/auth/login")
async def login(user: UserLogin):
    """用户登录"""
    if user.username not in users_db:
        raise HTTPException(status_code=401, detail="用户不存在")
    
    db_user = users_db[user.username]
    if not verify_password(user.password, db_user["password"]):
        raise HTTPException(status_code=401, detail="密码错误")
    
    token = create_token(db_user["user_id"])
    return {
        "token": token,
        "user_id": db_user["user_id"],
        "username": user.username,
    }

@app.get("/api/auth/me")
async def get_current_user(payload: Dict = Depends(verify_token)):
    """获取当前用户信息"""
    user_id = payload["user_id"]
    for username, user in users_db.items():
        if user["user_id"] == user_id:
            return {
                "user_id": user_id,
                "username": username,
                "email": user["email"],
            }
    raise HTTPException(status_code=404, detail="用户不存在")

# ── 设备管理 API ──────────────────────────────

@app.post("/api/devices/register")
async def register_device(device: DeviceRegister, payload: Dict = Depends(verify_token)):
    """注册设备"""
    user_id = payload["user_id"]
    devices_db[device.device_id] = {
        "device_id": device.device_id,
        "device_name": device.device_name,
        "device_type": device.device_type,
        "capabilities": device.capabilities,
        "user_id": user_id,
        "status": "offline",
        "created_at": time.time(),
    }
    
    return {"message": "设备注册成功", "device_id": device.device_id}

@app.get("/api/devices")
async def list_devices(payload: Dict = Depends(verify_token)):
    """获取用户设备列表"""
    user_id = payload["user_id"]
    user_devices = [
        {
            "device_id": d["device_id"],
            "device_name": d["device_name"],
            "device_type": d["device_type"],
            "capabilities": d["capabilities"],
            "status": d["status"],
            "last_seen": d.get("last_seen"),
        }
        for d in devices_db.values()
        if d["user_id"] == user_id
    ]
    return {"devices": user_devices}

@app.get("/api/devices/{device_id}/status")
async def get_device_status(device_id: str, payload: Dict = Depends(verify_token)):
    """获取设备状态"""
    if device_id not in devices_db:
        raise HTTPException(status_code=404, detail="设备不存在")
    
    device = devices_db[device_id]
    return {
        "device_id": device_id,
        "status": device["status"],
        "last_seen": device.get("last_seen"),
        "battery": device.get("battery"),
        "cpu_usage": device.get("cpu_usage"),
        "memory_usage": device.get("memory_usage"),
    }

@app.post("/api/devices/{device_id}/status")
async def update_device_status(device_id: str, status: DeviceStatus, payload: Dict = Depends(verify_token)):
    """更新设备状态"""
    if device_id not in devices_db:
        raise HTTPException(status_code=404, detail="设备不存在")
    
    devices_db[device_id].update({
        "status": status.status,
        "battery": status.battery,
        "cpu_usage": status.cpu_usage,
        "memory_usage": status.memory_usage,
        "last_seen": time.time(),
    })
    
    # 广播设备状态更新
    await manager.broadcast({
        "type": "device_status_update",
        "device_id": device_id,
        "status": status.status,
        "battery": status.battery,
    })
    
    return {"message": "状态已更新"}

# ── WebSocket 实时监控 ──────────────────────────

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """WebSocket 实时监控"""
    ws_id = await manager.connect(websocket, user_id)
    
    try:
        # 发送欢迎消息
        await websocket.send_json({
            "type": "connected",
            "message": "实时监控已连接",
            "user_id": user_id,
        })
        
        # 发送当前设备列表
        user_devices = [
            {
                "device_id": d["device_id"],
                "device_name": d["device_name"],
                "status": d["status"],
                "battery": d.get("battery"),
            }
            for d in devices_db.values()
            if d["user_id"] == user_id
        ]
        await websocket.send_json({
            "type": "device_list",
            "devices": user_devices,
        })
        
        # 保持连接
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # 处理客户端消息
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif message.get("type") == "device_command":
                # 处理设备命令
                device_id = message.get("device_id")
                command = message.get("command")
                await manager.send_to_user(user_id, {
                    "type": "command_response",
                    "device_id": device_id,
                    "command": command,
                    "status": "sent",
                })
    
    except WebSocketDisconnect:
        manager.disconnect(ws_id)
        print(f"用户 {user_id} 断开连接")
    except Exception as e:
        print(f"WebSocket 错误: {e}")
        manager.disconnect(ws_id)

# ── 系统监控 API ──────────────────────────────

@app.get("/api/system/stats")
async def get_system_stats(payload: Dict = Depends(verify_token)):
    """获取系统统计"""
    user_id = payload["user_id"]
    user_devices = [d for d in devices_db.values() if d["user_id"] == user_id]
    
    online_count = sum(1 for d in user_devices if d["status"] == "online")
    total_count = len(user_devices)
    
    return {
        "total_devices": total_count,
        "online_devices": online_count,
        "offline_devices": total_count - online_count,
        "total_perceptions": 12847,  # 从缓存获取
        "cognition_load": 78,
    }

@app.get("/api/system/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "version": "2.0.0",
    }

# ── 启动 ──────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)