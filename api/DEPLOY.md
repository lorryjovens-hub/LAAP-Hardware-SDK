# LAAP API 部署配置

## 环境变量

```bash
# Cloudflare Workers
VITE_API_URL=https://api.laap.cn

# 本地开发
VITE_API_URL=http://localhost:8000
```

## 部署到 Cloudflare Workers

### 1. 安装 Wrangler CLI

```bash
npm install -g wrangler
wrangler login
```

### 2. 创建 KV 命名空间

```bash
wrangler kv:namespace create LAAP_DB
# 记录返回的 ID，填入 wrangler.toml
```

### 3. 配置环境变量

```bash
wrangler secret put JWT_SECRET
# 输入你的密钥
```

### 4. 部署

```bash
# 部署到开发环境
wrangler dev

# 部署到生产环境
wrangler deploy
```

### 5. 配置自定义域名

```bash
wrangler route add "api.laap.cn/*"
```

## 前端配置

创建 `.env.production`:

```env
VITE_API_URL=https://api.laap.cn
```

创建 `.env.development`:

```env
VITE_API_URL=http://localhost:8000
```

## 完整部署流程

```bash
# 1. 后端
cd api/
wrangler deploy

# 2. 前端
cd ../laap-console/
npm run build
# 上传 dist/ 到 Cloudflare Pages
```

## API 文档

部署后访问：`https://api.laap.cn/docs`

## 监控

Cloudflare Dashboard: https://dash.cloudflare.com

## 安全

- ✅ HTTPS 强制
- ✅ CORS 配置
- ✅ JWT Token 认证
- ✅ DDoS 防护
- ✅ WAF 规则