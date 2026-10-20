"""Offline simulated Sepolia providers. NOT real blockchain nodes."""
import os
from fastapi import FastAPI, HTTPException

app = FastAPI(title="ChainSentinel local RPC simulator")


@app.post("/")
async def mock_rpc(body: dict):
    if os.getenv("MOCK_FAIL") == "1":
        raise HTTPException(503, "Injected outage")
    method = body.get("method")
    result = {
        "eth_chainId": hex(int(os.getenv("MOCK_CHAIN_ID", "11155111"))),
        "eth_blockNumber": hex(int(os.getenv("MOCK_BLOCK", "1000"))),
        "net_version": os.getenv("MOCK_CHAIN_ID", "11155111"),
    }.get(method)
    if result is None:
        return {"jsonrpc": "2.0", "id": body.get("id"),
                "error": {"code": -32601, "message": "Method not implemented in simulator"}}
    return {"jsonrpc": "2.0", "id": body.get("id"), "result": result}
