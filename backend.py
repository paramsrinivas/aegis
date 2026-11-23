import asyncio
import os
import random
from fastapi import FastAPI, HTTPException
import uvicorn

app = FastAPI()
MEAN_MS = float(os.getenv("MEAN_MS", "50"))
STD_MS = float(os.getenv("STD_MS", "10"))
FAIL_RATE = float(os.getenv("FAIL_RATE", "0.0"))

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

@app.get("/infer")
async def infer():
    delay = max(0.0, random.gauss(MEAN_MS, STD_MS) / 1000.0)
    await asyncio.sleep(delay)
    if random.random() < FAIL_RATE:
        raise HTTPException(503, "Simulated backend failure")
    return {"status": "ok", "latency_ms": round(delay * 1000, 3),
            "backend": os.getenv("BACKEND_NAME", "backend")}

@app.get("/predict")
async def predict():
    return await infer()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8101")))
