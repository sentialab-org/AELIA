SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

UV ?= uv

.DEFAULT_GOAL := backend

.PHONY: help sync doctor init quality adapter-schema \
	connector-preflight discord-selfbot-install discord-selfbot-test \
	discord-selfbot-run discord-selfbot-start discord-officialbot-install \
	discord-officialbot-test discord-officialbot-run discord-officialbot-start \
	telegram-officialbot-install telegram-officialbot-test \
	telegram-officialbot-run telegram-officialbot-start platforms-test \
	backend dev-all

help:
	@echo "Targets:"
	@echo "  make / make backend      Start only the independent runtime backend"
	@echo "  make sync            Install locked dependencies"
	@echo "  make doctor          Validate config and persona integrity"
	@echo "  make init            Initialize the SQLite database"
	@echo "  make quality         Run the complete quality gate"
	@echo "  make adapter-schema  Print active and future connector schemas"
	@echo "  make connector-preflight  Verify the example connector manifest"
	@echo "  make discord-selfbot-install  Install the isolated Node connector"
	@echo "  make discord-selfbot-test     Test the isolated Node connector"
	@echo "  make discord-selfbot-run      Start only the Discord selfbot gate"
	@echo "  make discord-selfbot-start    Compatibility alias for discord-selfbot-run"
	@echo "  make discord-officialbot-install  Install the Discord bot connector"
	@echo "  make discord-officialbot-test     Test the Discord bot connector"
	@echo "  make discord-officialbot-run     Start only the Discord bot gate"
	@echo "  make discord-officialbot-start   Compatibility alias for discord-officialbot-run"
	@echo "  make telegram-officialbot-install Install the Telegram bot connector"
	@echo "  make telegram-officialbot-test    Test the Telegram bot connector"
	@echo "  make telegram-officialbot-run    Start only the Telegram bot gate"
	@echo "  make telegram-officialbot-start  Compatibility alias for telegram-officialbot-run"
	@echo "  make dev-all                     Supervise independently running backend + selfbot"
	@echo "  make platforms-test               Test all Node platform connectors"
	@echo ""
	@echo "Frozen V1: cd legacy/v1-rust && make help"

sync:
	@$(UV) sync --frozen --all-groups

backend:
	$(UV) run --frozen aelia-backend

doctor:
	@$(UV) run --frozen aelia config doctor

init:
	@$(UV) run --frozen aelia db init

quality: sync
	$(UV) run --frozen ruff format --check .
	$(UV) run --frozen ruff check .
	$(UV) run --frozen mypy src tests
	$(UV) run --frozen pytest -q
	node --check platforms/node-common/config.js
	node --check platforms/node-common/journal.js
	node --check platforms/node-common/runtime-client.js
	node --check platforms/node-common/kernel-client.js
	node --check platforms/node-common/receipts.js
	npm --prefix platforms/discord-selfbot run check
	npm --prefix platforms/discord-selfbot test
	npm --prefix platforms/discord-officialbot run check
	npm --prefix platforms/discord-officialbot test
	npm --prefix platforms/telegram-officialbot run check
	npm --prefix platforms/telegram-officialbot test

adapter-schema:
	@$(UV) run --frozen aelia adapter schema

connector-preflight:
	@$(UV) run --frozen aelia adapter connector-preflight \
		tests/fixtures/adapter/connector_capabilities.json

discord-selfbot-install:
	npm --prefix platforms/discord-selfbot ci

discord-selfbot-test:
	npm --prefix platforms/discord-selfbot run check
	npm --prefix platforms/discord-selfbot test
	@$(UV) run --frozen aelia adapter connector-preflight \
		platforms/discord-selfbot/capabilities.json

discord-selfbot-run:
	npm --prefix platforms/discord-selfbot start

discord-selfbot-start: discord-selfbot-run

discord-officialbot-install:
	npm --prefix platforms/discord-officialbot ci

discord-officialbot-test:
	npm --prefix platforms/discord-officialbot run check
	npm --prefix platforms/discord-officialbot test
	@$(UV) run --frozen aelia adapter connector-preflight \
		platforms/discord-officialbot/capabilities.json

discord-officialbot-run:
	npm --prefix platforms/discord-officialbot start

discord-officialbot-start: discord-officialbot-run

telegram-officialbot-install:
	npm --prefix platforms/telegram-officialbot ci

telegram-officialbot-test:
	npm --prefix platforms/telegram-officialbot run check
	npm --prefix platforms/telegram-officialbot test
	@$(UV) run --frozen aelia adapter connector-preflight \
		platforms/telegram-officialbot/capabilities.json

telegram-officialbot-run:
	npm --prefix platforms/telegram-officialbot start

telegram-officialbot-start: telegram-officialbot-run

platforms-test: discord-selfbot-test discord-officialbot-test \
	telegram-officialbot-test

dev-all:
	set -e; \
	$(MAKE) backend & backend_pid=$$!; \
	trap 'kill $$backend_pid 2>/dev/null || true' INT TERM EXIT; \
	$(MAKE) discord-selfbot-run; \
	wait $$backend_pid
