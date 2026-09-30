# Nokido — Makefile (Linux/macOS/WSL)
PYTHON ?= python3
ifeq ($(OS),Windows_NT)
  PYTHON = C:/Users/$(USERNAME)/miniforge3/python.exe
endif

.PHONY: demo install test lint hub stop help

help:
	@echo "Nokido targets:"
	@echo "  make install   — install deps + configure .env"
	@echo "  make demo      — run end-to-end demo"
	@echo "  make hub       — start hub MCP :8766"
	@echo "  make test      — run pytest tests/"
	@echo "  make lint      — ruff + mypy app/"
	@echo "  make stop      — stop hub"

install:
	$(PYTHON) -m pip install -r requirements.txt
	@[ -f Nokido.env ] || cp Nokido.env.example Nokido.env
	@echo "Edit Nokido.env then: make hub"

demo:
	$(PYTHON) demo.py

hub:
	$(PYTHON) tools/nokido_hub.py

stop:
	@pkill -f nokido_hub.py 2>/dev/null || true
	@echo "Hub stopped"

test:
	$(PYTHON) -m pytest tests/ -v --tb=short

lint:
	$(PYTHON) -m ruff check app/ tools/ --select=E,F,W
	$(PYTHON) -m mypy app/ --ignore-missing-imports --no-strict-optional
