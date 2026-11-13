FROM ghcr.io/astral-sh/uv:0.10.12 AS uv
FROM python:3.12-slim

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_NO_DEV=1 UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/backend"
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project
COPY alembic.ini ./
COPY backend ./backend
COPY fixtures ./fixtures
RUN useradd --system --no-create-home inquest
USER inquest

EXPOSE 8000
CMD ["uvicorn", "inquest.main:app", "--host", "0.0.0.0", "--port", "8000"]
