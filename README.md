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

Open <http://127.0.0.1:8080>. Health is available at <http://127.0.0.1:8080/health>.

The named volume preserves ledgers, transactions, and uploaded receipts across container recreation. The container runs as the unprivileged `app` user and does not require an external AI token in demo mode.

## Environment variables

Copy `.env.example` when integrating a real provider. The demo parser and deterministic insight engine work without credentials.

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

## MVP boundaries

The current release demonstrates natural-language bookkeeping, multiple ledgers, deterministic categorization, receipt upload and association, dashboard analytics, and AI-style financial explanations. A real LLM/OCR provider, bank sync, investment management, and complex budgeting are intentionally adapter-ready but outside this validation slice.
