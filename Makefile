.PHONY: install test self-test validate run run-full loop status discover analyze

ROOT := $(shell pwd)
GATEWAY_REPO ?= /Users/sk/Desktop/untitled folder/new design
export TARGET_REPO := $(GATEWAY_REPO)

install:
	python3 -m pip install -e ".[dev]"

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
