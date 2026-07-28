# AI Personal Finance OS

AI-native personal finance assistant MVP inspired by the product concept deck in the parent workspace.

The MVP is intentionally dependency-light: a Python standard-library API serves a responsive web UI, stores demo data in JSON, and exposes adapter boundaries for a real model/OCR provider later.

## Run locally

```bash
python3 -m app.server
```

Open <http://127.0.0.1:8080>. The local server writes runtime data to `./runtime/data` unless `DATA_DIR` is set.

## Run with Docker

Build and start the standalone image:

```bash
docker build -t ai-finance-os:local .
docker run --rm \
  --name ai-finance-os \
  -p 8080:8080 \
  -v ai-finance-os-data:/app/data \
  ai-finance-os:local
```

Or use Compose:

```bash
docker compose up --build -d
docker compose ps
```

Stop and clean up the demo container with `docker compose down`. Add `--volumes` only when you intentionally want to remove the local demo data.

Open <http://127.0.0.1:8080>. Health is available at <http://127.0.0.1:8080/health>.

The named volume preserves ledgers, transactions, and uploaded receipts across container recreation. The container runs as the unprivileged `app` user and does not require an external AI token in demo mode.

## Environment variables

Copy `.env.example` when integrating a real provider. The demo parser and deterministic insight engine work without credentials.

To connect a real provider later, implement the `FinanceAgent` adapter in `app/server.py` and inject `AI_PROVIDER`, `AI_API_URL`, and `AI_API_TOKEN` at runtime. The browser never receives the token.

| Variable | Default | Purpose |
| --- | --- | --- |
| `HOST` | `0.0.0.0` in Docker | Bind address for the HTTP server |
| `PORT` | `8080` | HTTP port |
| `DATA_DIR` | `./runtime/data` locally, `/app/data` in Docker | JSON state and uploads |
| `AI_PROVIDER` | `demo` | `demo` or future provider adapter |
| `AI_API_URL` | empty | Future provider endpoint |
| `AI_API_TOKEN` | empty | Runtime-injected provider token; never bake into an image |
| `LOG_LEVEL` | `INFO` | Server log level |

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests cover command parsing, multiple-record extraction, deterministic insights, JSON persistence, and transaction edit/delete behavior. Container smoke checks should be run after the Docker daemon is available.

## Product interaction checklist

- **AI 对话**：输入“刚刚停车112元，帮我记一下”或“创建2026账本，把停车费112元记录进去，再把4月份销冠奖金500元放进去。”；系统先展示结构化预览，确认后才写入。
- **智能账本**：通过侧栏切换账本，支持搜索、收入/支出筛选、交易详情、编辑和删除。
- **图片凭证**：在图片凭证页选择或拖入 PNG/JPG/WEBP（单张不超过 8MB），查看进度，编辑识别结果后关联交易；原始图片保存在 `/app/data/uploads`。
- **Dashboard / 问答**：趋势、分类占比、现金流和最近交易都由 JSON 数据计算；在 AI 对话中询问“为什么这个月花这么多？”会得到历史平均差额、原因和建议。

## Container verification

The following checks were executed against the containerized app, not a host-only development server:

```bash
docker build -t ai-finance-os:local .
docker run -d --name ai-finance-os \
  -p 8080:8080 \
  -v ai-finance-os-data:/app/data \
  ai-finance-os:local
docker inspect ai-finance-os
curl http://127.0.0.1:8080/health
```

When the host's port 8080 is already occupied, map a different host port while keeping the container port unchanged:

```bash
docker run -d --name ai-finance-os-demo \
  -p 18081:8080 \
  -v ai-finance-os-demo-data:/app/data \
  ai-finance-os:local
```

The verified local demo is available at <http://127.0.0.1:18081>. The image also builds and responds to health/parsing smoke checks with `--platform linux/amd64` on an ARM development host.

To verify persistence, create a ledger, transaction, and receipt, stop and remove the container (keep the named volume), then recreate it with the same `-v` mapping. The state file and `/app/data/uploads` contents should be available immediately after the second container becomes healthy.

## MVP boundaries

The current release demonstrates natural-language bookkeeping, multiple ledgers, deterministic categorization, receipt upload and association, dashboard analytics, and AI-style financial explanations. A real LLM/OCR provider, bank sync, investment management, and complex budgeting are intentionally adapter-ready but outside this validation slice.
