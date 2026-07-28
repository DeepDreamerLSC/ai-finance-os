ARG PYTHON_BASE_IMAGE=python:3.12-slim
FROM ${PYTHON_BASE_IMAGE}

USER root

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    UPLOAD_DIR=/app/data/uploads

WORKDIR /app

RUN (getent group app >/dev/null || groupadd --system app) \
    && (id -u app >/dev/null 2>&1 || useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app) \
    && mkdir -p /app/data/uploads \
    && chown -R app:app /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY --chown=app:app alembic /app/alembic
COPY --chown=app:app alembic.ini /app/alembic.ini
COPY --chown=app:app app /app/app
COPY --chown=app:app scripts /app/scripts
COPY --chown=app:app web /app/web
COPY --chown=app:app .env.example /app/.env.example

RUN chmod 0755 /app/scripts/start.sh

USER app

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=8 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2).read()"

CMD ["/app/scripts/start.sh"]
