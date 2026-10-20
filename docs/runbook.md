# Incident runbook

## No eligible providers / 503
1. `curl -s http://localhost:8000/v1/providers` to inspect lag and health.
2. Confirm expected `EXPECTED_CHAIN_ID` (Sepolia: 11155111).
3. Check provider limits, credentials, DNS, TLS, network egress and sync status.
4. Verify at least one endpoint is within the allowed lag; investigate disagreements.
5. Do not bypass chain ID validation to silence alerts.

## Inject and demonstrate a failure (offline simulator)
1. `docker compose up --build -d`
2. `curl -s localhost:8000/v1/providers`
3. `docker compose stop mock-secondary` (gateway should still use mock-primary)
4. `curl -s -X POST localhost:8000/rpc -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}'`
5. `docker compose start mock-secondary` and recheck providers.

## Security
Treat upstream RPC URLs as credentials when they contain API tokens.
Keep them in environment secrets, not Git, and avoid logging them. This gateway
blocks `eth_sendRawTransaction` intentionally to prevent unsafe replay.
