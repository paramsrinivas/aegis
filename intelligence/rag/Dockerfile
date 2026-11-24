
FROM python:3.12-slim

WORKDIR /app

COPY rag/requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r /app/requirements.txt

COPY rag /app/rag
COPY runbooks /app/runbooks

RUN useradd --create-home --uid 10001 aegis

USER aegis

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "rag.ingest"]

