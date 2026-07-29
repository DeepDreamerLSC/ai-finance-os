# AI Personal Finance OS

AI 原生个人财务助手。当前版本提供手机号验证码登录、30 天设备会话、自然语言记账、多账本、图片凭证、财务看板和用户级数据隔离。

## 架构

- `finance-app`：FastAPI + 原生 HTML/CSS/JavaScript
- `finance-postgres`：用户、会话、账本、交易和凭证元数据
- `finance-redis`：验证码、冷却时间、发送频控和一次性校验状态
- `finance-uploads`：原始凭证文件；只能通过带 Bearer Token 的接口读取

浏览器只把短期 Access Token 保存在内存中。30 天 Refresh Token 使用随机值、数据库哈希存储、`HttpOnly` Cookie 和每次续签轮换，不会写入 `localStorage`。

## 本地启动

```bash
cp .env.example .env
docker compose -f compose.e2e.yaml up --build -d
docker compose -f compose.e2e.yaml ps
```

打开 <http://127.0.0.1:18082>。E2E 配置使用固定测试验证码 `123456`、独立 PostgreSQL/Redis/上传数据卷，只用于本地测试，不能用于生产环境。

健康检查：

```bash
curl --fail http://127.0.0.1:18082/health
```

停止服务但保留数据：

```bash
docker compose -f compose.e2e.yaml down --volumes
```

只有明确要删除 PostgreSQL、Redis 和凭证数据时，才附加 `--volumes`。

## 生产配置

复制 `.env.example`，至少提供以下配置：

| 配置 | 用途 |
| --- | --- |
| `APP_ENV=production` | 启用生产安全检查 |
| `POSTGRES_PASSWORD` | PostgreSQL 独立强密码 |
| `JWT_SECRET_KEY` | 至少 32 字符的独立随机密钥 |
| `SMS_CODE_PEPPER` | 与 JWT 密钥不同的验证码哈希密钥 |
| `COOKIE_SECURE=true` | 只通过 HTTPS 发送长期会话 Cookie |
| `FRONTEND_ORIGIN=https://finance.chiraliumai.cn` | Cookie 写操作的可信来源 |
| `SMS_ACCESS_KEY` / `SMS_SECRET_KEY` | 阿里云短信认证 |
| `SMS_SIGN_NAME` | 已审核短信签名 |
| `SMS_TEMPLATE_CODE_LOGIN` | 已审核登录验证码模板 |
| `SMS_REMOTE_ENABLED=true` | 启用真实短信 |
| `SMS_DEV_FORCE_LOCAL=false` | 禁止本地验证码实现 |
| `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY` | 异常频率后的人机验证 |

生产环境会拒绝弱 JWT 密钥、不安全 Cookie、开发验证码、缺失短信配置或缺失 Turnstile 配置，并在启动阶段直接失败。

不要把 `.env`、云厂商密钥或实际验证码提交到 Git。短信接口包含手机号分钟冷却、手机号小时/每日、IP 小时、系统每日上限、最大验证次数、一次性消费和异常阈值 Turnstile。

## 数据库迁移

容器启动时自动执行：

```bash
python -m alembic upgrade head
```

旧版 JSON 数据不会自动归属给首个登录用户。必须由操作者明确指定所有者：

```bash
docker compose exec finance-app python scripts/import_legacy_state.py \
  --phone 13800138000 \
  --state-file /path/in/container/state.json \
  --upload-root /path/in/container/uploads
```

目标手机号需要先登录一次创建账户。导入程序只把数据写入显式指定的账户。

## 验证

后端与安全边界：

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
```

前端纯函数：

```bash
npm ci
npm run test:frontend
```

容器启动后运行桌面和移动端 Playwright：

```bash
npm run test:e2e
```

覆盖范围包括验证码冷却与小时/每日/全局频控、错误与过期验证码、并发一次性消费、自动创建用户、30 天会话和轮换、注销与设备撤销、跨来源保护、API 数据隔离、登录恢复、无效会话回退以及浏览器层双用户账本隔离。

## 产品边界

本版本保留确定性的本地 Finance Agent，用于演示自然语言解析、分类与洞察。真实 LLM/OCR、银行同步、投资管理和复杂预算不在当前登录与多租户验证范围内。
