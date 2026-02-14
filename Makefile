SHELL := /usr/bin/env bash

BACKEND_DIR := backend
FRONTEND_DIR := frontend
VENV := $(BACKEND_DIR)/.venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: setup dev demo dataset backend frontend test selfcheck clean docker-demo docker-selftest
.PHONY: doctor

setup:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r $(BACKEND_DIR)/requirements.txt
	cd $(FRONTEND_DIR) && npm install

doctor:
	@if [ -x "$(PYTHON)" ]; then \
		"$(PYTHON)" scripts/doctor.py; \
	else \
		python3 scripts/doctor.py; \
	fi

dev:
	./scripts/dev.sh

demo:
	./scripts/demo.sh

docker-demo:
	@DOCKER_BIN="docker"; \
	if ! command -v docker >/dev/null 2>&1 && [ -x "/Applications/Docker.app/Contents/Resources/bin/docker" ]; then \
		DOCKER_BIN="/Applications/Docker.app/Contents/Resources/bin/docker"; \
	fi; \
	if [ -x "$$(dirname $$DOCKER_BIN)/docker-credential-desktop" ]; then \
		export PATH="$$(dirname $$DOCKER_BIN):$$PATH"; \
	fi; \
	"$$DOCKER_BIN" compose -f docker/docker-compose.yml up --build

docker-selftest:
	./scripts/docker_selftest.sh

dataset:
	python3 scripts/generate_synthetic_dataset.py

backend:
	cd $(BACKEND_DIR) && .venv/bin/uvicorn main:app --reload --host 127.0.0.1 --port 8000

frontend:
	cd $(FRONTEND_DIR) && VITE_API_BASE="http://127.0.0.1:8000" npm run dev -- --host 127.0.0.1 --port 5173

test:
	cd $(BACKEND_DIR) && .venv/bin/python -m pytest -q

selfcheck:
	$(PYTHON) scripts/self_check.py

clean:
	rm -rf $(VENV)
	rm -rf $(FRONTEND_DIR)/node_modules $(FRONTEND_DIR)/dist
