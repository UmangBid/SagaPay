FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml /app/pyproject.toml
COPY finpay /app/finpay
RUN pip install --no-cache-dir .
COPY alembic /app/alembic
COPY scripts /app/scripts

ENV PYTHONUNBUFFERED=1
