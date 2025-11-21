FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir fastapi uvicorn httpx prometheus-client
EXPOSE 8101
CMD ["python", "app.py"]
