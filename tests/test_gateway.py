import asyncio

import httpx
import pytest

from app.gateway import Gateway, GatewayError
from app.main import create_app


def transport_factory(broken_second=False, wrong_chain_second=False, lag=2):
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        payload = __import__("json").loads(request.content)
        if host == "secondary" and broken_second:
            return httpx.Response(503)
        method = payload["method"]
        heights = {"primary": 1000, "secondary": 1000 + lag}
        result = {
            "eth_chainId": hex(1 if host == "secondary" and wrong_chain_second else 11155111),
            "eth_blockNumber": hex(heights[host]),
        }.get(method, "0x0")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": result})
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_selects_latest_healthy_provider():
    async with httpx.AsyncClient(transport=transport_factory()) as client:
        gateway = Gateway(["http://primary/", "http://secondary/"], client=client)
        status = await gateway.status()
        assert [p.eligible for p in status] == [True, True]
        result = await gateway.proxy({"jsonrpc": "2.0", "id": 4, "method": "eth_blockNumber", "params": []})
        assert result["result"] == "0x3ea"  # block 1002


@pytest.mark.asyncio
async def test_wrong_chain_is_rejected():
    async with httpx.AsyncClient(transport=transport_factory(wrong_chain_second=True)) as client:
        gateway = Gateway(["http://primary/", "http://secondary/"], client=client)
        status = await gateway.status()
        assert status[1].eligible is False
        assert status[1].error == "ValueError"
        result = await gateway.proxy({"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []})
        assert result["result"] == "0x3e8"


@pytest.mark.asyncio
async def test_lagging_provider_is_excluded():
    async with httpx.AsyncClient(transport=transport_factory(lag=50)) as client:
        gateway = Gateway(["http://primary/", "http://secondary/"], max_lag=5, client=client)
        assert [p.eligible for p in await gateway.status()] == [False, True]


@pytest.mark.asyncio
async def test_outage_falls_back_to_primary():
    async with httpx.AsyncClient(transport=transport_factory(broken_second=True)) as client:
        gateway = Gateway(["http://primary/", "http://secondary/"], client=client)
        result = await gateway.proxy({"jsonrpc": "2.0", "id": 2, "method": "eth_blockNumber", "params": []})
        assert result["result"] == "0x3e8"


@pytest.mark.asyncio
async def test_transaction_broadcast_is_denied():
    async with httpx.AsyncClient(transport=transport_factory()) as client:
        gateway = Gateway(["http://primary/"], client=client)
        with pytest.raises(ValueError, match="read-only"):
            await gateway.proxy({"jsonrpc": "2.0", "id": 1, "method": "eth_sendRawTransaction", "params": []})


@pytest.mark.asyncio
async def test_no_healthy_provider():
    async with httpx.AsyncClient(transport=transport_factory(broken_second=True)) as client:
        gateway = Gateway(["http://secondary/"], client=client)
        with pytest.raises(GatewayError):
            await gateway.proxy({"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []})


@pytest.mark.asyncio
async def test_api_health_and_proxy():
    async with httpx.AsyncClient(transport=transport_factory()) as provider_client:
        gateway = Gateway(["http://primary/", "http://secondary/"], client=provider_client)
        app = create_app(gateway)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                assert (await client.get("/healthz")).status_code == 200
                assert (await client.get("/readyz")).status_code == 200
                response = await client.post("/rpc", json={"jsonrpc": "2.0", "id": 5,
                    "method": "eth_blockNumber", "params": []})
                assert response.json()["result"] == "0x3ea"
                assert "chainsentinel_provider_up" in (await client.get("/metrics")).text
                assert (await client.post("/rpc", json={"jsonrpc": "2.0", "id": 6,
                    "method": "eth_sendRawTransaction", "params": []})).status_code == 400


@pytest.mark.asyncio
async def test_failover_if_preferred_provider_dies_between_probe_and_read():
    seen = []
    def handler(request):
        import json
        body = json.loads(request.content)
        seen.append((request.url.host, body["method"]))
        if request.url.host == "secondary" and body["method"] == "eth_getBalance":
            return httpx.Response(503)
        if body["method"] == "eth_chainId":
            result = hex(11155111)
        elif body["method"] == "eth_blockNumber":
            result = hex(1002 if request.url.host == "secondary" else 1000)
        else:
            result = "0x8"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = Gateway(["http://primary/", "http://secondary/"], client=client)
        response = await gateway.proxy({"jsonrpc": "2.0", "id": "x", "method": "eth_getBalance", "params": ["0xabc", "latest"]})
        assert response["result"] == "0x8"
        assert [(host, method) for host, method in seen if method == "eth_getBalance"] == [
            ("secondary", "eth_getBalance"), ("primary", "eth_getBalance")]


@pytest.mark.asyncio
async def test_high_cost_method_is_denied():
    async with httpx.AsyncClient(transport=transport_factory()) as client:
        gateway = Gateway(["http://primary/"], client=client)
        with pytest.raises(ValueError, match="read-only"):
            await gateway.proxy({"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": []})


@pytest.mark.asyncio
async def test_extra_fields_not_forwarded():
    forwarded = []
    def handler(request):
        import json
        body = json.loads(request.content)
        forwarded.append(body)
        res = "0xaa36a7" if body["method"] == "eth_chainId" else "0x3e8"
        return httpx.Response(200, json={"jsonrpc":"2.0", "id":body["id"], "result":res})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = Gateway(["http://primary/"], client=client)
        await gateway.proxy({"jsonrpc":"2.0", "id":9, "method":"eth_blockNumber", "params":[], "unexpected":"untrusted"})
        assert all("unexpected" not in req for req in forwarded)
