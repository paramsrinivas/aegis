FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN groupadd --system aegis \
    && useradd --system \
        --gid aegis \
        --create-home \
        aegis

COPY requirements.txt .

RUN python -m pip install --no-cache-dir \
    -r requirements.txt

COPY --chown=aegis:aegis app/ ./app/
COPY --chown=aegis:aegis dashboard/ ./dashboard/
COPY --chown=aegis:aegis runbooks/ ./runbooks/
COPY --chown=aegis:aegis .streamlit/ ./.streamlit/

RUN mkdir -p /app/data \
    && chown aegis:aegis /app/data

USER aegis

EXPOSE 8010 8501

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
