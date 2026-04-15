import os
import httpx

AVE_API_KEY = os.environ.get("AVE_API_KEY", "")
AVE_DATA_BASE = os.environ.get("AVE_DATA_BASE", "https://data.ave-api.xyz/v2")

async def api_get(path, params=None, timeout=15):
    url = AVE_DATA_BASE.rstrip("/") + "/" + path.lstrip("/")
    headers = {}
    if AVE_API_KEY:
        headers["X-API-KEY"] = AVE_API_KEY
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.get(url, params=params or {}, headers=headers)

