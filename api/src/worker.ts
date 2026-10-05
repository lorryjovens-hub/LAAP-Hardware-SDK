/**
 * LAAP API - Cloudflare Workers 版本
 * 
 * 登录鉴权 + 设备管理 + WebSocket 实时监控
 */

// ── 类型定义 ──────────────────────────────────

interface Env {
  LAAP_DB: KVNamespace;
  JWT_SECRET: string;
  API_VERSION: string;
}

interface User {
  user_id: string;
  username: string;
  email: string;
  password_hash: string;
  created_at: number;
}

interface Device {
  device_id: string;
  device_name: string;
  device_type: string;
  capabilities: string[];
  user_id: string;
  status: string;
  battery?: number;
  cpu_usage?: number;
  memory_usage?: number;
  last_seen?: number;
  created_at: number;
}

// ── 工具函数 ──────────────────────────────────

function createToken(userId: string, secret: string): string {
  const header = { alg: 'HS256', typ: 'JWT' };
  const payload = {
    user_id: userId,
    exp: Math.floor(Date.now() / 1000) + (24 * 60 * 60), // 24小时
    iat: Math.floor(Date.now() / 1000),
  };
  
  const encoder = new TextEncoder();
  const headerBase64 = btoa(JSON.stringify(header));
  const payloadBase64 = btoa(JSON.stringify(payload));
  const signature = btoa(`${headerBase64}.${payloadBase64}.${secret}`);
  
  return `${headerBase64}.${payloadBase64}.${signature}`;
}

function verifyToken(token: string, secret: string): any {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    
    const payload = JSON.parse(atob(parts[1]));
    
    // 检查过期
    if (payload.exp && payload.exp < Date.now() / 1000) {
      return null;
    }
    
    return payload;
  } catch {
    return null;
  }
}

async function hashPassword(password: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(password);
  const hash = await crypto.subtle.digest('SHA-256', data);
  return btoa(String.fromCharCode(...new Uint8Array(hash)));
}

async function verifyPassword(password: string, hash: string): Promise<boolean> {
  const hashed = await hashPassword(password);
  return hashed === hash;
}

// ── CORS 配置 ──────────────────────────────────

function getCorsHeaders(): HeadersInit {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    'Access-Control-Max-Age': '86400',
  };
}

// ── 路由处理 ──────────────────────────────────

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;
    
    // CORS 预检
    if (method === 'OPTIONS') {
      return new Response(null, { headers: getCorsHeaders() });
    }
    
    // 路由匹配
    try {
      // 健康检查
      if (path === '/api/system/health') {
        return new Response(
          JSON.stringify({ status: 'healthy', timestamp: Date.now() }),
          { headers: { ...getCorsHeaders(), 'Content-Type': 'application/json' } }
        );
      }
      
      // 用户注册
      if (path === '/api/auth/register' && method === 'POST') {
        const body = await request.json();
        const { username, email, password } = body;
        
        // 检查用户是否存在
        const existing = await env.LAAP_DB.get(`user:${username}`);
        if (existing) {
          return new Response(
            JSON.stringify({ detail: '用户名已存在' }),
            { status: 400, headers: { ...getCorsHeaders(), 'Content-Type': 'application/json' } }
          );
        }
        
        // 创建用户
        const user: User = {
          user_id: `user_${Date.now()}`,
          username,
          email,
          password_hash: await hashPassword(password),
          created_at: Date.now(),
        };
        
        await env.LAAP_DB.put(`user:${username}`, JSON.stringify(user));
        await env.LAAP_DB.put(`user_id:${user.user_id}`, username);
        
        return new Response(
          JSON.stringify({ message: '注册成功', user_id: user.user_id }),
          { headers: { ...getCorsHeaders(), 'Content-Type': 'application/json' } }
        );
      }
      
      // 用户登录
      if (path === '/api/auth/login' && method === 'POST') {
        const body = await request.json();
        const { username, password } = body;
        
        const userJson = await env.LAAP_DB.get(`user:${username}`);
        if (!userJson) {
          return new Response(
            JSON.stringify({ detail: '用户不存在' }),
            { status: 401, headers: { ...getCorsHeaders(), 'Content-Type': 'application/json' } }
          );
        }
        
        const user: User = JSON.parse(userJson);
        
        if (!(await verifyPassword(password, user.password_hash))) {
          return new Response(
            JSON.stringify({ detail: '密码错误' }),
            { status: 401, headers: { ...getCorsHeaders(), 'Content-Type': 'application/json' } }
          );
        }
        
        const token = createToken(user.user_id, env.JWT_SECRET);
        
        return new Response(
          JSON.stringify({ token, user_id: user.user_id, username: user.username }),
          { headers: { ...getCorsHeaders(), 'Content-Type': 'application/json' } }
        );
      }
      
      // 获取设备列表
      if (path === '/api/devices' && method === 'GET') {
        const authHeader = request.headers.get('Authorization');
        if (!authHeader) {
          return new Response(
            JSON.stringify({ detail: '未授权' }),
            { status: 401, headers: { ...getCorsHeaders(), 'Content-Type': 'application/json' } }
          );
        }
        
        const token = authHeader.replace('Bearer ', '');
        const payload = verifyToken(token, env.JWT_SECRET);
        
        if (!payload) {
          return new Response(
            JSON.stringify({ detail: '无效的 Token' }),
            { status: 401, headers: { ...getCorsHeaders(), 'Content-Type': 'application/json' } }
          );
        }
        
        // 获取用户设备（简化版，实际应该用索引）
        const devices: Device[] = [];
        const list = await env.LAAP_DB.list({ prefix: 'device:' });
        
        for (const key of list.keys) {
          const deviceJson = await env.LAAP_DB.get(key.name);
          if (deviceJson) {
            const device: Device = JSON.parse(deviceJson);
            if (device.user_id === payload.user_id) {
              devices.push(device);
            }
          }
        }
        
        return new Response(
          JSON.stringify({ devices }),
          { headers: { ...getCorsHeaders(), 'Content-Type': 'application/json' } }
        );
      }
      
      // 404
      return new Response(
        JSON.stringify({ detail: 'Not Found' }),
        { status: 404, headers: { ...getCorsHeaders(), 'Content-Type': 'application/json' } }
      );
      
    } catch (error) {
      return new Response(
        JSON.stringify({ detail: 'Internal Server Error' }),
        { status: 500, headers: { ...getCorsHeaders(), 'Content-Type': 'application/json' } }
      );
    }
  },
  
  // WebSocket 处理
  async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer, env: Env) {
    // WebSocket 实时通信逻辑
  },
} satisfies ExportedHandler<Env>;