"""Read-only EVM JSON-RPC gateway with safe, health-based failover."""
import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
from prometheus_client import Counter, Gauge, Histogram

SAFE_METHODS = frozenset({
    "eth_chainId", "eth_blockNumber", "eth_getBalance", "eth_getCode",
    "eth_getBlockByNumber", "eth_getTransactionByHash",
    "eth_getTransactionReceipt", "net_version",
})

PROVIDER_UP = Gauge("chainsentinel_provider_up", "Provider eligible for read traffic", ["provider"])
PROVIDER_LAG = Gauge("chainsentinel_provider_block_lag", "Blocks behind highest healthy provider", ["provider"])
PROBE_SECONDS = Histogram("chainsentinel_probe_duration_seconds", "RPC probe latency", ["provider"])
REQUESTS = Counter("chainsentinel_rpc_requests_total", "RPC requests per outcome", ["outcome"])
FAILOVERS = Counter("chainsentinel_rpc_failovers_total", "Attempts using backup after provider failure")


@dataclass(frozen=True)
class Probe:
    provider: str
    index: int
    ok: bool
    height: int | None
    latency_ms: float | None
    error: str | None = None
    lag: int | None = None
    eligible: bool = False

    def public(self) -> dict[str, Any]:
        return {
            "provider": self.provider, "healthy": self.ok, "eligible": self.eligible,
            "block_height": self.height, "block_lag": self.lag,
            "latency_ms": self.latency_ms, "error": self.error,
        }


class GatewayError(Exception):
    pass


class Gateway:
    def __init__(self, endpoints: list[str], chain_id: int = 11155111,
                 max_lag: int = 5, timeout: float = 4.0,
                 client: httpx.AsyncClient | None = None):
        if not endpoints or any(not url.startswith(("http://", "https://")) for url in endpoints):
            raise ValueError("At least one valid HTTP(S) RPC endpoint is required")
        self.endpoints = endpoints
        self.chain_id = chain_id
        self.max_lag = max_lag
        self.client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def _call(self, index: int, method: str, params: list[Any] | None = None) -> dict:
        resp = await self.client.post(
            self.endpoints[index],
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []},
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict) or data.get("jsonrpc") != "2.0":
            raise ValueError("Invalid JSON-RPC response")
        return data

    async def _probe(self, index: int) -> Probe:
        provider = f"rpc_{index + 1}"
        start = time.monotonic()
        try:
            chain_resp, block_resp = await asyncio.gather(
                self._call(index, "eth_chainId"), self._call(index, "eth_blockNumber")
            )
            if "error" in chain_resp or "error" in block_resp:
                raise ValueError("Upstream JSON-RPC error")
            chain_id = int(chain_resp["result"], 16)
            height = int(block_resp["result"], 16)
            if chain_id != self.chain_id:
                raise ValueError(f"Wrong chain ID: {chain_id}")
            if height < 0:
                raise ValueError("Invalid block height")
            elapsed = (time.monotonic() - start) * 1000
            PROBE_SECONDS.labels(provider).observe(elapsed / 1000)
            return Probe(provider, index, True, height, round(elapsed, 2))
        except (httpx.HTTPError, ValueError, KeyError, TypeError, OverflowError) as exc:
            PROBE_SECONDS.labels(provider).observe(time.monotonic() - start)
            # Do not leak endpoint URL or API key via errors.
            return Probe(provider, index, False, None, None, type(exc).__name__)

    async def status(self) -> list[Probe]:
        probes = await asyncio.gather(*(self._probe(i) for i in range(len(self.endpoints))))
        heights = [p.height for p in probes if p.ok and p.height is not None]
        highest = max(heights) if heights else None
        out = []
        for p in probes:
            lag = (highest - p.height) if highest is not None and p.height is not None else None
            eligible = p.ok and lag is not None and lag <= self.max_lag
            result = Probe(p.provider, p.index, p.ok, p.height, p.latency_ms, p.error, lag, eligible)
            PROVIDER_UP.labels(p.provider).set(int(eligible))
            PROVIDER_LAG.labels(p.provider).set(lag if lag is not None else 0)
            out.append(result)
        return out

    async def proxy(self, body: dict[str, Any]) -> dict[str, Any]:
        method = body.get("method")
        if not isinstance(method, str) or method not in SAFE_METHODS:
            REQUESTS.labels("rejected").inc()
            raise ValueError("Only allowlisted read-only JSON-RPC methods are supported")
        if body.get("jsonrpc") != "2.0" or not isinstance(body.get("params", []), list):
            REQUESTS.labels("rejected").inc()
            raise ValueError("Invalid JSON-RPC request")
        req_id = body.get("id")
        if type(req_id) not in (int, str):
            REQUESTS.labels("rejected").inc()
            raise ValueError("JSON-RPC id must be an integer or string")
        # Reconstruct the request to avoid passing arbitrary client fields upstream.
        clean_body = {"jsonrpc": "2.0", "id": req_id, "method": method,
                      "params": body.get("params", [])}
        candidates = [p for p in await self.status() if p.eligible]
        # Prioritize fresh blocks, then latency, and only fail over on transport/protocol failure.
        candidates.sort(key=lambda p: (-p.height, p.latency_ms))
        for attempt, p in enumerate(candidates):
            if attempt:
                FAILOVERS.inc()
            try:
                resp = await self.client.post(self.endpoints[p.index], json=clean_body)
                resp.raise_for_status()
                payload = resp.json()
                if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0" or payload.get("id") != req_id:
                    raise ValueError("Invalid upstream JSON-RPC response")
                if "result" not in payload and "error" not in payload:
                    raise ValueError("Missing upstream result/error")
                REQUESTS.labels("upstream_rpc_error" if "error" in payload else "success").inc()
                return payload  # Application-layer RPC errors are returned, not retried.
            except (httpx.HTTPError, ValueError, TypeError):
                continue
        REQUESTS.labels("unavailable").inc()
        raise GatewayError("No RPC providers available")


def gateway_from_env() -> Gateway:
    endpoints = [s.strip() for s in os.getenv("RPC_ENDPOINTS", "").split(",") if s.strip()]
    return Gateway(endpoints, int(os.getenv("EXPECTED_CHAIN_ID", "11155111")),
                   int(os.getenv("MAX_BLOCK_LAG", "5")),
                   float(os.getenv("RPC_TIMEOUT_SECONDS", "4")))
