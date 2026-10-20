PYTHON ?= python3
.PHONY: install test run up down logs demo build
install:
	$(PYTHON) -m pip install -r requirements-dev.txt
test:
	$(PYTHON) -m pytest -q
run:
	$(PYTHON) -m uvicorn app.main:app --host 127.0.0.1 --port 8000
up:
	docker compose up --build -d
down:
	docker compose down
logs:
	docker compose logs -f gateway
demo:
	bash scripts/demo.sh
build:
	docker build -t chainsentinel:local .
