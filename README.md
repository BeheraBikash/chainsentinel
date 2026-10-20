# ChainSentinel — Web3 Infrastructure Reliability Lab

**Ethereum RPC observability, failover, containerization, Kubernetes and SRE incident simulation.**

A hands-on, security-conscious Web3 DevOps portfolio project. This first release includes a
read-only Ethereum JSON-RPC gateway, multi-provider health checks, chain-ID validation,
block-lag eligibility, Prometheus metrics, Grafana datasource, GitHub Actions CI,
Docker Compose, a provisioned Grafana dashboard, GHCR publishing on main, Kubernetes manifests, a Helm chart, and Prometheus alert rules. It runs offline with two explicitly simulated
Sepolia RPC backends—no wallet, token, paid service or cloud infrastructure required.

## 5-minute local demo

Requirements: Docker with Compose plugin.

```bash
docker compose up --build -d
curl -s http://localhost:8000/healthz
curl -s http://localhost:8000/v1/providers
curl -s -X POST http://localhost:8000/rpc \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}'
docker compose stop mock-secondary
curl -s http://localhost:8000/v1/providers
curl -s -X POST http://localhost:8000/rpc \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"eth_blockNumber","params":[]}'
docker compose start mock-secondary
# Or run the complete demo with: bash scripts/demo.sh
```

- API documentation: http://localhost:8000/docs
- Metrics: http://localhost:8000/metrics
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (provisioned **ChainSentinel** dashboard; local viewer access only)

## Real Sepolia RPC providers

For a non-simulated demo, set `RPC_ENDPOINTS` to two authorized Sepolia HTTP RPC
URLs, `EXPECTED_CHAIN_ID=11155111`, and run `uvicorn app.main:app --port 8000`.
Never commit credentials. Testnet configuration does not grant mainnet access.

## Engineering highlights

- **Failover**: only allowlisted, read-only JSON-RPC methods are forwarded; transport
  errors can trigger a retry at another eligible provider.
- **Correct network**: checks `eth_chainId` before selecting a provider.
- **Freshness**: blocks stale providers whose heads lag farther than a configured margin.
- **Ops**: container health probes, non-root UID, resource budgets, secrets from Kubernetes Secret.
- **Monitoring**: Prometheus counters, histograms and gauges; Grafana datasource.
- **Delivery**: GitHub Actions runs unit tests and builds a container on PRs and main, then publishes a commit-SHA image to GHCR on main.

## Helm deployment (existing Kubernetes cluster required)

Create a Kubernetes Secret with `RPC_ENDPOINTS` (use real authorized Sepolia
endpoints). Avoid placing credentials in Git, shell command history, or Helm values.

```bash
kubectl create namespace chainsentinel --dry-run=client -o yaml | kubectl apply -f -
# On your own computer, create .env.k8s with one line:
# RPC_ENDPOINTS=https://YOUR_SEPOLIA_PROVIDER_A,https://YOUR_SEPOLIA_PROVIDER_B
chmod 600 .env.k8s
kubectl -n chainsentinel create secret generic chainsentinel-rpc --from-env-file=.env.k8s
rm .env.k8s
helm upgrade --install chainsentinel helm/chainsentinel -n chainsentinel \
  --set image.repository=ghcr.io/YOUR_GITHUB_USERNAME/chainsentinel \
  --set image.tag=YOUR_COMMIT_SHA
kubectl -n chainsentinel port-forward svc/chainsentinel 8000:80
```

This chart uses external RPC endpoints; the local Docker-only simulator is not deployed to Kubernetes.
ServiceMonitor is optional and requires the Prometheus Operator CRDs. Raw Kubernetes
manifests in `k8s/` are an alternative, not another required installation step.

## Roadmap (not yet implemented)

- [ ] HPA and traffic-based scaling
- [ ] Pager integration and measured SLO / error budget
- [ ] Terraform AWS deployment with budget guardrails and OIDC-based CI
- [ ] Real Sepolia execution+consensus node, with JWT-authenticated Engine API
- [ ] Beacon finality, peer count and reorg tracking
- [ ] Load tests, chaos experiments, evidence screenshots and write-ups
- [ ] Authentication, quotas, rate limits, circuit breakers and provider probe caching

## Documentation

- [Architecture](docs/architecture.md)
- [SRE Incident Runbook](docs/runbook.md)
- [Reliability objectives](docs/slo.md)

**Scope:** educational infrastructure lab, not audited production RPC infrastructure.
The local Grafana deployment deliberately allows anonymous viewer access on localhost only.
The mock services do not sync or validate real blockchain data.

## Publish to your personal GitHub (after MFA)

```bash
cd chainsentinel
git init
git add .
git commit -m "feat: build Web3 Ethereum RPC reliability lab"
git branch -M main
gh auth login
gh repo create chainsentinel --public --source=. --remote=origin --push
```

Never publish mock failure demonstrations as real blockchain downtime. Replace GHCR image
owner placeholders before deploying, and do not upload `.env`, token-bearing URLs,
or wallet/private-key data.
