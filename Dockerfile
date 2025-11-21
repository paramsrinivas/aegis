FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    pip install --no-cache-dir -r /app/requirements.txt && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
COPY . /app
CMD ["python", "-m", "uvicorn", "router:app", "--host", "0.0.0.0", "--port", "8000"]
