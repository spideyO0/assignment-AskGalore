SHELL := /bin/bash
VENV  := coa_mapper/.venv
PY    := $(VENV)/bin/python
PIP   := $(VENV)/bin/pip

.DEFAULT_GOAL := help

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

$(VENV): ## Create the virtualenv
	python3 -m venv $(VENV)

install: $(VENV) ## Install the package with dev + lint extras
	$(PIP) install -q -e "coa_mapper[dev,lint]"

format: ## Auto-format (isort then black)
	$(VENV)/bin/isort coa_mapper/src coa_mapper/tests
	$(VENV)/bin/black coa_mapper/src coa_mapper/tests

lint: ## ruff + black --check + mypy, no mutations
	$(VENV)/bin/ruff check coa_mapper/src coa_mapper/tests
	$(VENV)/bin/black --check coa_mapper/src coa_mapper/tests
	cd coa_mapper && .venv/bin/mypy

test: ## Run the test suite
	cd coa_mapper && .venv/bin/python -m pytest tests/ -q

coverage: ## Test suite with branch coverage
	cd coa_mapper && .venv/bin/python -m pytest tests/ -q \
		--cov=coa_mapper --cov-report=term-missing --cov-report=html

run: ## Run the mapper over inputs/ into output/
	cd coa_mapper && .venv/bin/coa-mapper run --config config.yaml || \
		test $$? -eq 1  # exit 1 = pass with disclosed exceptions, expected on this data

reproduce: ## Prove the committed output/ is exactly what a fresh run produces
	@tmp=$$(mktemp -d); \
	cd coa_mapper && .venv/bin/coa-mapper run --config config.yaml --out $$tmp >/dev/null 2>&1 || true; \
	cd ..; \
	if diff -rq output $$tmp >/dev/null; then \
		echo "output/ reproduces byte-for-byte"; rm -rf $$tmp; \
	else \
		echo "DRIFT between committed output/ and a fresh run:"; diff -r output $$tmp; rm -rf $$tmp; exit 1; \
	fi

check: lint test reproduce ## Everything CI runs

clean: ## Remove caches and build artifacts
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf coa_mapper/.pytest_cache coa_mapper/.ruff_cache coa_mapper/.mypy_cache \
		coa_mapper/htmlcov coa_mapper/.coverage coa_mapper/output_test_run

.PHONY: help install format lint test coverage run reproduce check clean
