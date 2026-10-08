UV ?= uv
export PLAYWRIGHT_BROWSERS_PATH := $(CURDIR)/.browser-cache

.PHONY: setup sandbox verify evidence schema submission-check
setup:
	$(UV) sync --locked --extra dev
	$(UV) run playwright install chromium
sandbox:
	$(UV) run capabilities sandbox
verify:
	$(UV) run --extra dev ruff check src tests scripts
	$(UV) run --extra dev ruff format --check src tests scripts
	$(UV) run --extra dev mypy src
	$(UV) run --extra dev pytest -q
	$(UV) run python scripts/check_submission.py --offline
evidence:
	$(UV) run python scripts/offline_evidence.py --out runs/offline-evidence
schema:
	$(UV) run capabilities schema
submission-check:
	$(UV) run python scripts/check_submission.py
