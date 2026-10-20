"""HTTP API and Prometheus metrics."""
import asyncio
import os
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.gateway import Gateway, GatewayError, gateway_from_env


def create_app(gateway: Gateway | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        _app.state.gateway = gateway or gateway_from_env()

        async def monitor() -> None:
            while True:
                await _app.state.gateway.status()
                await asyncio.sleep(float(os.getenv("PROBE_INTERVAL_SECONDS", "15")))

        task = asyncio.create_task(monitor())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            if gateway is None:
                await _app.state.gateway.close()

    app = FastAPI(title="ChainSentinel", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz():
        return {"status": "alive"}

    @app.get("/readyz")
    async def readyz():
        probes = await app.state.gateway.status()
        if not any(p.eligible for p in probes):
            raise HTTPException(503, detail="No eligible RPC provider")
        return {"status": "ready"}

    @app.get("/v1/providers")
    async def providers():
        return {"chain_id": app.state.gateway.chain_id,
                "providers": [p.public() for p in await app.state.gateway.status()]}

    @app.post("/rpc")
    async def rpc(body: dict[str, Any]):
        try:
            return await app.state.gateway.proxy(body)
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        except GatewayError as exc:
            raise HTTPException(503, detail=str(exc)) from exc

    @app.get("/metrics")
    async def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
