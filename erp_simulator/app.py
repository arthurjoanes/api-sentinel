import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

app = FastAPI(docs_url=None, redoc_url=None)
MODE_FILE = Path("/faults/erp-mode")


@app.get("/health/live")
async def live() -> dict:
    return {"status": "ok"}


@app.get("/availability/{store_id}/{sku}", response_model=None)
async def availability(
    store_id: int, sku: str
) -> JSONResponse | StreamingResponse | RedirectResponse:
    mode = await asyncio.to_thread(MODE_FILE.read_text) if MODE_FILE.exists() else "normal"
    mode = mode.strip()
    if mode == "slow":
        await asyncio.sleep(2)
    if mode == "error":
        return JSONResponse({"error": "falha controlada"}, status_code=503)
    if mode == "invalid":
        return JSONResponse({"store_id": store_id, "sku": sku, "available": -1})
    if mode == "redirect":
        return RedirectResponse("http://erp:8080/health/live")
    if mode == "oversize":
        return JSONResponse({"padding": "x" * 16000})
    if mode == "trickle":

        async def chunks() -> AsyncIterator[bytes]:
            for _ in range(30):
                yield b" "
                await asyncio.sleep(0.1)

        return StreamingResponse(chunks(), media_type="application/json")
    return JSONResponse({"store_id": store_id, "sku": sku, "available": 20 + store_id})
