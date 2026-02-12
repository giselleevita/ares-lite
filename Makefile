SHELL := /bin/zsh

BACKEND_DIR := backend
FRONTEND_DIR := frontend
VENV := $(BACKEND_DIR)/.venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: setup dev demo dataset backend frontend test clean

setup:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r $(BACKEND_DIR)/requirements.txt
	cd $(FRONTEND_DIR) && npm install

dev:
	./scripts/dev.sh

demo:
	./scripts/demo.sh

dataset:
	python3 scripts/generate_synthetic_dataset.py

backend:
	cd $(BACKEND_DIR) && .venv/bin/uvicorn main:app --reload --host 127.0.0.1 --port 8000

frontend:
	cd $(FRONTEND_DIR) && npm run dev -- --host 127.0.0.1 --port 5173

test:
	cd $(BACKEND_DIR) && .venv/bin/python -m pytest -q

clean:
	rm -rf $(VENV)
	rm -rf $(FRONTEND_DIR)/node_modules $(FRONTEND_DIR)/dist
