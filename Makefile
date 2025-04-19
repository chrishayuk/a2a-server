SHELL := /usr/bin/env bash

.PHONY: help check-pdm install generate-models test lint format build clean serve client

help:
	@echo "Usage: make [target]"
	@echo
	@echo "Available targets:"
	@echo "  install          Install project & dev dependencies via pdm"
	@echo "  generate-models  Regenerate Pydantic models from JSON schema"
	@echo "  test             Run pytest suite"
	@echo "  lint             Run flake8 on src/ and tests/"
	@echo "  format           Run black on src/ and tests/"
	@echo "  build            Build sdist & wheel via pdm"
	@echo "  clean            Remove build artifacts, caches & temp files"
	@echo "  serve            Run the A2A server (uv run a2a-server)"
	@echo "  client           Show the A2A client help (uv run a2a-client)"

# ensure pdm is on PATH
check-pdm:
	@command -v pdm >/dev/null 2>&1 || { \
	  echo >&2 "Error: pdm is not installed. Install it with pip install pdm"; \
	  exit 1; \
	}

install: check-pdm
	pdm install

serve: check-pdm
	uv run a2a-server

client: check-pdm
	uv run a2a-client --help
	pdm install -E client
	uv run a2a-client --help
	uv run a2a-client --help

generate-models: check-pdm
	pdm run generate-models

test: check-pdm
	pdm run pytest

lint: check-pdm
	pdm run flake8 src tests

format: check-pdm
	pdm run black src tests

build: check-pdm
	pdm build

clean:
	# purge PDM cache & lock
	@command -v pdm >/dev/null 2>&1 && pdm cache purge || true
	# remove lock file
	rm -f python.lock
	# remove build artifacts
	rm -rf build dist *.egg-info
	# remove pytest / pycache
	rm -rf .pytest_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +
	# remove any fixed schemas
	rm -f spec/*_fixed.json

