.PHONY: install test self-test validate run run-full loop status discover analyze schedule schedule-install schedule-uninstall daemon-start daemon-stop daemon-status execute

ROOT := $(shell pwd)
GATEWAY_REPO ?= /Users/sk/Desktop/untitled folder/new design
export TARGET_REPO := $(GATEWAY_REPO)

install:
	python3 -m pip install --user -e ".[dev]"

execute: run

schedule-install:
	bash ./scripts/install_schedule.sh

schedule-uninstall:
	bash ./scripts/uninstall_schedule.sh

schedule:
	@echo "Use: make schedule-install  (launchd, interval from .env)"
	@echo " Or: make daemon-start      (background loop)"

daemon-start:
	bash ./scripts/start_daemon.sh

daemon-stop:
	bash ./scripts/stop_daemon.sh

daemon-status:
	@if [ -f .runtime/daemon.pid ] && kill -0 $$(cat .runtime/daemon.pid) 2>/dev/null; then \
		echo "Daemon running PID $$(cat .runtime/daemon.pid)"; \
	else \
		echo "Daemon not running"; \
	fi
	@launchctl print gui/$$(id -u)/com.gateway.enhancement-agent 2>/dev/null | head -5 || echo "LaunchAgent not loaded"

test: self-test

self-test:
	python3 -m pytest -q tests

validate:
	python3 -m gateway_enhancement_agent validate

discover:
	python3 -m gateway_enhancement_agent discover

analyze:
	python3 -m gateway_enhancement_agent analyze

run:
	python3 -m gateway_enhancement_agent run

run-full: test validate run

loop:
	python3 -m gateway_enhancement_agent loop --interval $${LOOP_INTERVAL_SECONDS:-3600}

status:
	python3 -m gateway_enhancement_agent status
