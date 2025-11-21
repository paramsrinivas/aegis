# backend.py
import os
import random
import time
from fastapi import FastAPI
import uvicorn

app = FastAPI()

# Simulated latency parameters from env
MEAN_MS = float(os.getenv("MEAN_MS", "50"))
STD_MS = float(os.getenv("STD_MS", "10"))
FAIL_RATE = float(os.getenv("FAIL_RATE", "0.0"))

@app.get("/predict")
async def predict():
    # simulate latency
    delay = max(0.0, random.gauss(MEAN_MS, STD_MS) / 1000.0)
    time.sleep(delay)
    if random.random() < FAIL_RATE:
        return {"status": "error", "msg": "simulated failure"}
    return {"status": "ok", "latency_s": delay, "backend": os.getenv("BACKEND_NAME", "backend")}

if __name__ == "__main__":
    uvicorn.run("backend:app", host="0.0.0.0", port=int(os.getenv("PORT", 8101)), log_level="info")

