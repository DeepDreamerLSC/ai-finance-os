FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    DATA_DIR=/app/data \
    AI_PROVIDER=demo \
    LOG_LEVEL=INFO

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /app/data /app/web /app/app \
    && chown -R app:app /app

COPY --chown=app:app app /app/app
COPY --chown=app:app web /app/web
COPY --chown=app:app .env.example /app/.env.example

USER app

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8080') + '/health', timeout=2).read()"

CMD ["python", "-m", "app.server"]
