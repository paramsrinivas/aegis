# manager_client.py
import httpx
import asyncio
from typing import Dict, Any

class ManagerClient:
    def __init__(self, host: str = "manager", port: int = 8001, timeout: float = 5.0):
        self.base = f"http://{host}:{port}"
        self._client = None
        self.timeout = timeout

    async def _get_client(self):
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def get_weights(self) -> Dict[str, Any]:
        client = await self._get_client()
        r = await client.get(f"{self.base}/weights")
        r.raise_for_status()
        return r.json()

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
