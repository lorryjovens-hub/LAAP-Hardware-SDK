# LAAP 云端中继部署说明

> P0 已部署完成：`https://laap-relay.lorryjovens.workers.dev`

---

## 一、部署状态

| 项目 | 值 |
|------|-----|
| Worker 名称 | `laap-relay` |
| 部署地址 | `https://laap-relay.lorryjovens.workers.dev` |
| WebSocket | `wss://laap-relay.lorryjovens.workers.dev/ws` |
| Version ID | `d2645b15-198d-4c12-b61c-2923bf687385` |
| Durable Object | `LAAPHubRoom`（按 user_id 分片） |
| 路由 | 全局（待绑自定义域名） |

---

## 二、接口

### 健康检查
```bash
GET /ws/health
```
```json
{
  "status": "healthy",
  "service": "laap-tri-node-relay",
  "version": "1.0.0",
  "environment": "production"
}
```

### 签发 Token（开发用，生产应由主 API 签）
```bash
POST /ws/token
Content-Type: application/json

{"user_id": "lorry"}
```
```json
{"token": "eyJhbGci...", "expires_in": 86400}
```

### WebSocket 连接
```
wss://laap-relay.lorryjovens.workers.dev/ws?token=<JWT>&node_id=<id>&role=<hub|node>
```

参数：
- `token`：JWT（必须）
- `node_id`：节点标识，如 `pc-hub`、`phone-01`、`xiaozhi-01`
- `role`：`hub` 或 `node`

---

## 三、端到端测试结果

```
[1] 中枢连接              ✓ 握手 peers=['pc-hub']
[2] 手机连接              ✓ peers=['pc-hub','phone-01']
                          中枢收到上线通知
[3] 中枢 → 手机 派任务     ✓ 手机收到 task_assign
[4] 手机 → 中枢 回结果     ✓ 中枢收到 task_result
[5] 心跳                  ✓ 回应 {heartbeat: true}
[6] 离线消息暂存           ✓ 手机重连后收到暂存消息
```

---

## 四、架构

```
   家里的中枢 (role=hub)  ──WSS──┐
                                 ├──▶  LAAPHubRoom (Durable Object)
   外面的手机 (role=node) ──WSS──┘      按 user_id 分片
                                         · 记住谁在线
                                         · 按 to_node 转发
                                         · 离线暂存最多 100 条
                                         · 5 分钟过期
```

### 关键设计

**1. 按 user_id 分片**
```typescript
const doId = env.LAAP_HUB.idFromName(`user:${userId}`);
```
用户 A 的节点物理上不可能碰到用户 B 的消息。

**2. 同名节点顶替**
同一 node_id 重连时，旧连接自动关闭。避免一个节点多连接状态不一致。

**3. 离线暂存**
```typescript
if (queue.length >= 100) queue.shift();   // 上限
queue.push({ msg, ts: Date.now() });
```
重连后只补发 5 分钟内的消息。

**4. 心跳回应**
服务端直接回 ACK，不转发给其他节点，省带宽。

---

## 五、绑定自定义域名（待做）

目标：`wss://api.laap.cn/ws`

步骤：
1. Cloudflare 面板 → Workers & Pages → `laap-relay`
2. Settings → Domains & Routes → Add custom domain
3. 输入 `api.laap.cn`
4. Cloudflare 自动配 DNS 和证书

或者用 wrangler：
```bash
cd D:\LAAP\laap-hardware\relay
npx wrangler domains add api.laap.cn
```

---

## 六、本地开发

```bash
cd D:\LAAP\laap-hardware\relay

# 安装依赖
npm install

# 本地跑（默认 http://localhost:8787）
npx wrangler dev

# 设置 secret
npx wrangler secret put JWT_SECRET

# 部署
npx wrangler deploy

# 看日志
npx wrangler tail
```

---

## 七、Python 侧接入

```python
from laaper.hub.transport import TransportManager, TransportConfig

mgr = TransportManager(hub, TransportConfig(
    mode="auto",
    lan_port=8765,
    cloud_url="wss://laap-relay.lorryjovens.workers.dev/ws",
    cloud_token="<JWT>",
))

# 启动局域网服务
await mgr.start_server()

# 连接云端节点
conn = await mgr.connect_node(
    node_id="phone-01",
    lan_hint="192.168.1.100:8765",   # 局域网优先
    cloud_url="wss://laap-relay.lorryjovens.workers.dev/ws",
    token="<JWT>",
    prefer="auto",                    # 自动选通道
)
```

---

## 八、成本估算

Cloudflare Workers 免费额度：
- 100,000 请求/天
- Durable Objects：SQLite 版有免费额度

按三端每秒 1 次心跳算：
```
3 节点 × 86400 秒 = 259,200 次/天
```
**超过免费额度**。心跳间隔应该调大：

建议：心跳 25 秒一次
```
3 × 86400 / 25 = 10,368 次/天
```
远低于免费额度。

付费版：$5/月 + Durable Objects 用量。

---

## 九、安全待补

| 项 | 现状 | 生产要求 |
|---|------|---------|
| JWT 签发 | Worker 内 `/ws/token` 开放签名 | 由主 API 签，Worker 只验签 |
| 密钥管理 | wrangler secret | 保持（已隔离） |
| Token 有效期 | 24 小时 | 缩短到 1 小时 + refresh token |
| 设备绑定 | 无 | 每个 node_id 绑定设备指纹 |
| 限流 | 无 | 按 user_id 限连接数 |
| 审计 | 有 console.log | 接 Analytics Engine 存库 |
