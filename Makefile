# ============================================================
# Self-Documenting Zero-Knowledge MCP Server
# Makefile — Developer convenience commands
# ============================================================

.PHONY: help install seed run sse test dev clean

# Default target
help:
	@echo ""
	@echo "  Self-Documenting Zero-Knowledge MCP Server"
	@echo "  ─────────────────────────────────────────"
	@echo "  make install  →  Install Python dependencies"
	@echo "  make seed     →  Seed the demo legacy database"
	@echo "  make run      →  Run server (stdio transport)"
	@echo "  make sse      →  Run server (SSE on port 8080)"
	@echo "  make test     →  Run all tests with pytest"
	@echo "  make dev      →  Launch MCP Inspector"
	@echo "  make clean    →  Remove cache files"
	@echo ""

install:
	pip install -r requirements.txt

seed:
	python server.py --seed

run:
	python server.py

sse:
	python server.py --transport sse --port 8080

test:
	python -m pytest tests/ -v

dev:
	mcp dev server.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -name "*.pyc" -delete
	find . -name ".pytest_cache" -exec rm -rf {} +
	@echo "Cache cleaned."
