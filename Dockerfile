# Образ сайта EGE-TUTOR-2027 для сервера (ADR-0013).
# Собирается на сервере из публичного репозитория; секретов и личных данных внутри нет:
# база и пароль лежат в томе /data, секрет подписи cookie — в переменной окружения.
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

# Сначала только зависимости: этот слой пересобирается, лишь когда меняется uv.lock.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY config ./config
COPY content ./content
RUN uv sync --locked --no-dev

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin ege \
    && mkdir /data && chown ege:ege /data
USER ege

ENV PATH=/opt/venv/bin:$PATH \
    EGE_TUTOR_DATA_DIR=/data \
    FORWARDED_ALLOW_IPS=*

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"

CMD ["ege-web", "serve", "--host", "0.0.0.0", "--port", "8000"]
