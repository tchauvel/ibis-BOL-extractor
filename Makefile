# ─────────────────────────────────────────────────────────────────────────────
# Ibis Logistics Extractor — Developer Makefile
# Usage: make <target>
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: install install-dev run test lint format clean help

# Default Python — override with: make run PYTHON=python3.13
PYTHON ?= python3

help:           ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

venv:           ## Create virtual environment (Python 3.12)
	python3.12 -m venv .venv

install:        ## Install production dependencies into .venv
	.venv/bin/pip install -r requirements.txt -q

install-dev:    ## Install production + development dependencies into .venv
	.venv/bin/pip install -r requirements.txt ".[dev]" -q

setup:          ## First-time project setup: create venv, install deps, copy .env
	$(MAKE) venv
	$(MAKE) install-dev
	@test -f .env || (cp .env.example .env && echo "Created .env — fill in GEMINI_API_KEY")

run:            ## Start the development server (with hot reload)
	.venv/bin/uvicorn api:app --reload --host 127.0.0.1 --port 8000

run-prod:       ## Start the production server (no reload)
	.venv/bin/uvicorn api:app --host 0.0.0.0 --port 8000 --workers 2

test:           ## Run the test suite
	$(PYTHON) -m pytest tests/ -v

test-cov:       ## Run tests with coverage report
	$(PYTHON) -m pytest tests/ -v --cov=. --cov-report=term-missing --cov-report=html

lint:           ## Check code style with ruff
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:         ## Auto-format code with ruff
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check --fix .

clean:          ## Remove compiled Python files and test artefacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov coverage.xml
