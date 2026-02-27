PYTHON ?= python3
PORT ?= 8079

.PHONY: install dev run test lint format

install:
	$(PYTHON) -m pip install -e .

dev:
	$(PYTHON) -m pip install -e .[dev]

run:
	uvicorn helpdesk_sim.main:app --host 0.0.0.0 --port $(PORT)

test:
	pytest

lint:
	ruff check src tests

format:
	ruff check --fix src tests
