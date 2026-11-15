FROM ghcr.io/astral-sh/uv:0.10.12 AS uv
FROM python:3.12-slim

COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV UV_NO_DEV=1 UV_PYTHON_DOWNLOADS=never \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/backend"
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project
COPY alembic.ini ./
COPY backend ./backend
COPY fixtures ./fixtures
COPY models ./models
COPY policies ./policies
RUN useradd --system --no-create-home inquest \
    && install -d -o inquest /app/cache
USER inquest

EXPOSE 8000
CMD ["uvicorn", "inquest.main:app", "--host", "0.0.0.0", "--no-proxy-headers", "--no-access-log", "--port", "8000"]
