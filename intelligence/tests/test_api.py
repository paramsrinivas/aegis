import asyncio
import pytest
from unittest.mock import patch
from app.main import investigate
from fastapi import HTTPException

class Response:
    def raise_for_status(self): pass
    def json(self): return {'backend1': {'healthy': 1, 'ewma_ms': 140}, 'backend2': {'healthy': 0, 'ewma_ms': None}}
class Client:
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def get(self, url): return Response()

def test_incident():
    with patch('app.main.httpx.AsyncClient', return_value=Client()):
        result = asyncio.run(investigate(100))
    assert result['severity'] == 'high'
    assert len(result['findings']) == 2
    assert result['actions_executed'] == []
