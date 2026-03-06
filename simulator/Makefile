PYTHON ?= python3
PORT ?= 8079
RELEASE_NOTES_FILE ?= release-notes-draft.md

.PHONY: install dev run test lint format release-check release-notes

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

release-check:
	$(PYTHON) scripts/release_tools.py check

release-notes:
	$(PYTHON) scripts/release_tools.py notes --output $(RELEASE_NOTES_FILE)
