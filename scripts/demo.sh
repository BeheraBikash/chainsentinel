#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
echo "Starting the offline RPC providers and observability stack..."
docker compose up --build -d
echo "Waiting for RPC gateway..."
ready=0
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/readyz >/dev/null; then ready=1; break; fi
  sleep 2
done
if [ "$ready" -eq 0 ]; then
  echo "Gateway not ready; inspect docker compose logs gateway" >&2
  exit 1
fi
echo "BEFORE: provider status and block height (secondary at block 1002)"
curl -fsS http://127.0.0.1:8000/v1/providers; echo
curl -fsS http://127.0.0.1:8000/rpc -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}'; echo
echo "Injecting outage: stopping the secondary provider..."
docker compose stop mock-secondary
echo "AFTER: gateway should fail over to primary at block 1000"
curl -fsS http://127.0.0.1:8000/v1/providers; echo
curl -fsS http://127.0.0.1:8000/rpc -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":2,"method":"eth_blockNumber","params":[]}'; echo
echo "Restoring the secondary provider..."
docker compose start mock-secondary
echo "Grafana: http://127.0.0.1:3000 ; Prometheus: http://127.0.0.1:9090"
