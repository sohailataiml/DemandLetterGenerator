PY ?= python
NPM ?= npm
WEB := apps/web

.DEFAULT_GOAL := help

.PHONY: help setup up api web test test-api test-web migrate migration downgrade \
        demo backfill gate fixtures lint clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## Install backend and frontend dependencies
	$(PY) -m pip install -r requirements.txt
	cd $(WEB) && $(NPM) install

up: ## Run the API (see `make web` for the UI, in another shell)
	$(PY) -m uvicorn app.main:app --reload --app-dir apps/api --port 8000

api: up ## Alias for `up`

web: ## Run the review UI
	cd $(WEB) && $(NPM) run dev

test: test-api test-web ## Run every test

test-api: ## Backend tests
	$(PY) -m pytest

test-web: ## Frontend tests
	cd $(WEB) && $(NPM) test

gate: ## Run the quality gate and print the scorecard
	$(PY) scripts/quality_gate.py

migrate: ## Apply all migrations
	$(PY) -m alembic upgrade head

migration: ## Autogenerate a migration: make migration m="add x"
	@test -n "$(m)" || (echo 'usage: make migration m="what changed"' && exit 1)
	$(PY) -m alembic revision --autogenerate -m "$(m)"

downgrade: ## Roll back one migration
	$(PY) -m alembic downgrade -1

demo: ## Seed a demo case (needs the API's database, not the API itself)
	$(PY) scripts/demo_case.py

backfill: ## Add page geometry and citation precision to existing documents
	$(PY) scripts/backfill_provenance.py

fixtures: ## Rebuild the golden template, expected document and PDF fixture
	$(PY) scripts/build_golden_fixture.py
	$(PY) scripts/build_golden_expected.py
	$(PY) scripts/build_pdf_fixture.py

clean: ## Remove local databases, storage and caches
	rm -rf var .pytest_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
