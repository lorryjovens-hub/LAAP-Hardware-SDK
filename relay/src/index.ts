/**
 * LAAP 三端联动云端中继 — Cloudflare Worker + Durable Objects
 *
 * ## 为什么需要这个
 *
 * 局域网直连只解决"同一 WiFi"。你在外面用手机控家里电脑，
 * 需要一个公网可达的会合点。这个 Worker 就是那个会合点。
 *
 * ## 架构
 *
 *   家里的中枢  ──WSS──┐
 *                      ├──▶  Durable Object（按 user_id 分片）
 *   外面的手机  ──WSS──┘         · 记住谁在线
 *                               · 转发消息
 *                               · 离线暂存
 *
 * ## 关键设计
 *
 * **按 user_id 分片**：每个用户的节点会合到同一个 DO 实例。
 * 用户 A 的节点物理上不可能碰到用户 B 的消息。
 *
 * **角色区分**：中枢是 hub，其他都是 node。消息按 to_node 转发。
 *
 * **离线暂存**：节点不在线时消息进 DO 存储，上线补发（最多 100 条）。
 */

export interface Env {
  LAAP_HUB: DurableObjectNamespace;
  JWT_SECRET: string;
  ENVIRONMENT: string;
}

// ── 认证 ──────────────────────────────────────────────

async function verifyJWT(token: string, secret: string): Promise<any | null> {
  if (!token) return null;

  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;

    const [headerB64, payloadB64, signatureB64] = parts;

    // 验证签名（HS256）
    const encoder = new TextEncoder();
    const key = await crypto.subtle.importKey(
      'raw',
      encoder.encode(secret),
      { name: 'HMAC', hash: 'SHA-256' },
      false,
      ['verify']
    );

    const signingInput = `${headerB64}.${payloadB64}`;

    // base64url → bytes
    const sigB64 = signatureB64.replace(/-/g, '+').replace(/_/g, '/');
    const sigPadded = sigB64 + '='.repeat((4 - (sigB64.length % 4)) % 4);
    const sigBytes = Uint8Array.from(atob(sigPadded), c => c.charCodeAt(0));

    const valid = await crypto.subtle.verify(
      'HMAC',
      key,
      sigBytes,
      encoder.encode(signingInput)
    );

    if (!valid) return null;

    // 解析 payload
    const payloadPadded = payloadB64.replace(/-/g, '+').replace(/_/g, '/')
      + '='.repeat((4 - (payloadB64.length % 4)) % 4);
    const payload = JSON.parse(atob(payloadPadded));

    // 过期检查
    if (payload.exp && payload.exp * 1000 < Date.now()) {
      return null;
    }

    return payload;
  } catch (e) {
    console.error('JWT verify failed:', e);
    return null;
  }
}

// ── Durable Object：按用户分片的会合点 ─────────────────

export class LAAPHubRoom {
  state: DurableObjectState;
  env: Env;

  // 连接表：node_id → WebSocket
  sessions: Map<string, WebSocket> = new Map();
  // 角色表：node_id → "hub" | "node"
  roles: Map<string, string> = new Map();

  constructor(state: DurableObjectState, env: Env) {
    this.state = state;
    this.env = env;

    // 恢复连接信息（DO 重启后）
    this.state.blockConcurrencyWhile(async () => {
      const stored = await this.state.storage.get<Record<string, string>>('roles');
      if (stored) {
        for (const [k, v] of Object.entries(stored)) {
          this.roles.set(k, v);
        }
      }
    });
  }

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);

    // ── HTTP 状态查询 ──
    if (url.pathname.endsWith('/status')) {
      return Response.json({
        connections: this.sessions.size,
        nodes: Array.from(this.sessions.keys()),
        roles: Object.fromEntries(this.roles),
        queued: await this.getQueuedCount(),
      });
    }

    // ── WebSocket 升级 ──
    const upgradeHeader = request.headers.get('Upgrade');
    if (!upgradeHeader || upgradeHeader.toLowerCase() !== 'websocket') {
      return new Response('Expected WebSocket upgrade', { status: 426 });
    }

    // 认证
    const token = url.searchParams.get('token') || '';
    const payload = await verifyJWT(token, this.env.JWT_SECRET);

    if (!payload) {
      return new Response('Unauthorized', { status: 401 });
    }

    const userId = payload.sub || payload.user_id || 'anonymous';
    const nodeId = url.searchParams.get('node_id') || `node_${Date.now()}`;
    const role = url.searchParams.get('role') || 'node';

    // 生成 WebSocket 对
    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);

    this.handleSession(server, nodeId, role, userId);

    return new Response(null, {
      status: 101,
      webSocket: client,
    });
  }

  handleSession(ws: WebSocket, nodeId: string, role: string, userId: string) {
    ws.accept();

    // 同名节点顶替旧连接
    const existing = this.sessions.get(nodeId);
    if (existing) {
      try {
        existing.close(1000, 'replaced by new connection');
      } catch (e) { /* ignore */ }
    }

    this.sessions.set(nodeId, ws);
    this.roles.set(nodeId, role);

    // 持久化角色
    this.state.storage.put('roles', Object.fromEntries(this.roles));

    console.log(`[${userId}] ${role} connected: ${nodeId} (total ${this.sessions.size})`);

    // 补发离线消息
    this.flushQueue(nodeId, ws);

    // 通知其他节点
    this.broadcast({
      kind: 'node_state',
      payload: { node_id: nodeId, role, event: 'online' },
      from_node: 'hub',
    }, nodeId);

    ws.addEventListener('message', async (event) => {
      try {
        const raw = typeof event.data === 'string'
          ? event.data
          : new TextDecoder().decode(event.data);

        let msg: any;
        try {
          msg = JSON.parse(raw);
        } catch {
          ws.send(JSON.stringify({
            kind: 'error',
            payload: { error: 'invalid json' },
          }));
          return;
        }

        // 补填来源
        if (!msg.from_node) msg.from_node = nodeId;

        // 心跳回应
        if (msg.kind === 'heartbeat') {
          ws.send(JSON.stringify({
            kind: 'ack',
            payload: { heartbeat: true, ts: Date.now() / 1000 },
            from_node: 'relay',
          }));
          return;
        }

        // 握手
        if (msg.kind === 'hello') {
          ws.send(JSON.stringify({
            kind: 'ack',
            payload: {
              relayed: true,
              node_id: nodeId,
              peers: Array.from(this.sessions.keys()),
              ts: Date.now() / 1000,
            },
            from_node: 'relay',
          }));
          return;
        }

        // 路由
        const toNode = msg.to_node || '';

        if (toNode && this.sessions.has(toNode)) {
          // 直接转发
          const target = this.sessions.get(toNode)!;
          try {
            target.send(JSON.stringify(msg));
          } catch (e) {
            console.error(`forward to ${toNode} failed:`, e);
            this.sessions.delete(toNode);
            await this.enqueue(toNode, msg);
          }
        } else if (toNode) {
          // 目标不在线，暂存
          await this.enqueue(toNode, msg);
          console.log(`queued for offline node ${toNode}`);
        } else {
          // 无指定目标，广播
          this.broadcast(msg, nodeId);
        }

      } catch (e) {
        console.error('message handling error:', e);
      }
    });

    ws.addEventListener('close', () => {
      this.sessions.delete(nodeId);
      this.roles.delete(nodeId);
      this.state.storage.put('roles', Object.fromEntries(this.roles));

      console.log(`disconnected: ${nodeId} (total ${this.sessions.size})`);

      this.broadcast({
        kind: 'node_state',
        payload: { node_id: nodeId, event: 'offline' },
        from_node: 'hub',
      }, nodeId);
    });

    ws.addEventListener('error', (e) => {
      console.error(`ws error ${nodeId}:`, e);
    });
  }

  broadcast(msg: any, exclude?: string) {
    const raw = JSON.stringify(msg);
    for (const [nid, ws] of this.sessions.entries()) {
      if (nid === exclude) continue;
      try {
        ws.send(raw);
      } catch (e) {
        this.sessions.delete(nid);
      }
    }
  }

  // ── 离线消息队列 ──────────────────────────────

  async enqueue(nodeId: string, msg: any) {
    const key = `queue:${nodeId}`;
    const queue = (await this.state.storage.get<any[]>(key)) || [];

    // 上限 100 条
    if (queue.length >= 100) {
      queue.shift();
    }

    queue.push({
      msg,
      ts: Date.now(),
    });

    await this.state.storage.put(key, queue);
  }

  async flushQueue(nodeId: string, ws: WebSocket) {
    const key = `queue:${nodeId}`;
    const queue = (await this.state.storage.get<any[]>(key)) || [];

    if (queue.length === 0) return;

    // 只补发 5 分钟内的
    const cutoff = Date.now() - 5 * 60 * 1000;
    const valid = queue.filter(q => q.ts > cutoff);

    for (const item of valid) {
      try {
        ws.send(JSON.stringify(item.msg));
      } catch (e) {
        break;
      }
    }

    await this.state.storage.delete(key);
    console.log(`flushed ${valid.length} queued messages to ${nodeId}`);
  }

  async getQueuedCount(): Promise<number> {
    const list = await this.state.storage.list({ prefix: 'queue:' });
    let total = 0;
    for (const [, q] of list.entries()) {
      total += (q as any[]).length;
    }
    return total;
  }
}

// ── Worker 入口 ──────────────────────────────────────

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // CORS
    const corsHeaders = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    };

    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    // ── 健康检查 ──
    if (url.pathname === '/health' || url.pathname === '/ws/health') {
      return Response.json({
        status: 'healthy',
        service: 'laap-tri-node-relay',
        version: '1.0.0',
        environment: env.ENVIRONMENT || 'production',
        ts: new Date().toISOString(),
      }, { headers: corsHeaders });
    }

    // ── 签发 token（开发用，生产应由主 API 签） ──
    if (url.pathname === '/ws/token' && request.method === 'POST') {
      try {
        const body = await request.json<{ user_id: string }>();
        const userId = body.user_id;

        if (!userId) {
          return Response.json({ error: 'user_id required' }, {
            status: 400, headers: corsHeaders,
          });
        }

        const token = await signJWT(
          { sub: userId, iat: Math.floor(Date.now() / 1000) },
          env.JWT_SECRET,
          86400
        );

        return Response.json({ token, expires_in: 86400 }, {
          headers: corsHeaders,
        });
      } catch (e) {
        return Response.json({ error: String(e) }, {
          status: 500, headers: corsHeaders,
        });
      }
    }

    // ── WebSocket 路由 ──
    if (url.pathname === '/ws' || url.pathname.startsWith('/ws/')) {
      // 认证
      const token = url.searchParams.get('token') || '';
      const payload = await verifyJWT(token, env.JWT_SECRET);

      if (!payload) {
        return Response.json(
          { error: 'unauthorized', hint: 'need ?token=<jwt>' },
          { status: 401, headers: corsHeaders }
        );
      }

      const userId = payload.sub || payload.user_id || 'anonymous';

      // 按 user_id 分片到 DO
      const doId = env.LAAP_HUB.idFromName(`user:${userId}`);
      const stub = env.LAAP_HUB.get(doId);

      return stub.fetch(request);
    }

    return Response.json({
      service: 'LAAP Tri-Node Relay',
      endpoints: {
        health: 'GET /ws/health',
        token: 'POST /ws/token',
        websocket: 'GET /ws?token=<jwt>&node_id=<id>&role=<hub|node>',
      },
    }, { headers: corsHeaders });
  },
};

// ── JWT 签发 ──────────────────────────────────────

async function signJWT(
  payload: any,
  secret: string,
  expiresInSeconds: number
): Promise<string> {
  const header = { alg: 'HS256', typ: 'JWT' };
  const now = Math.floor(Date.now() / 1000);
  const fullPayload = { ...payload, iat: now, exp: now + expiresInSeconds };

  const b64url = (obj: any) => {
    const str = JSON.stringify(obj);
    const bytes = new TextEncoder().encode(str);
    let binary = '';
    for (const b of bytes) binary += String.fromCharCode(b);
    return btoa(binary)
      .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  };

  const headerB64 = b64url(header);
  const payloadB64 = b64url(fullPayload);
  const signingInput = `${headerB64}.${payloadB64}`;

  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw',
    encoder.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  );

  const sig = await crypto.subtle.sign('HMAC', key, encoder.encode(signingInput));
  const sigBytes = new Uint8Array(sig);
  let sigBinary = '';
  for (const b of sigBytes) sigBinary += String.fromCharCode(b);
  const sigB64 = btoa(sigBinary)
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

  return `${signingInput}.${sigB64}`;
}
