# Gateway Enhancement Agent

Standalone **local** Python agent that compares your AI gateway platform against competitor capability profiles, prioritizes gaps, and drives a full **SDLC loop** — without embedding tooling inside the gateway codebase and **without any cloud service dependency**.

| Document | Audience |
|----------|----------|
| **[docs/USAGE.md](docs/USAGE.md)** | Operators and developers — installation, commands, scheduling, troubleshooting |
| **[docs/DESIGN.md](docs/DESIGN.md)** | Architecture, runtime modes, data planes, gap prioritization |

## What it does

Each cycle runs these phases against `TARGET_REPO` (your gateway checkout):

1. **Discover** — inventory routes, tests, governance docs
2. **Analyze** — scored gap matrix, competitor capability coverage, backlog update
3. **Design** — implementation brief with role-lens checklist
4. **Implement** — local Ollama (CPU/GPU) writes code into TARGET_REPO; no Cursor or cloud API
5. **Validate** — agent self-tests + TARGET_REPO gates (foreground only)
6. **Document** — governance sync checklist
7. **Release prep** — release decision draft

Artifacts land in `artifacts/cycle-XXXX/` (or Application Support when scheduled).

## Quick start

```bash
cd "/Users/sk/Desktop/untitled folder/gateway-enhancement-agent"

cp .env.example .env
# Edit .env — quote paths with spaces:
#   TARGET_REPO="/Users/sk/Desktop/untitled folder/new design"

make install

gateway-agent discover
gateway-agent analyze
gateway-agent run          # full SDLC cycle → artifacts/cycle-XXXX/
```

After implementing a work order in the gateway repo:

```bash
make validate              # agent pytest + gateway gates
```

For LaunchAgent scheduling, mirror sync, and troubleshooting, see **[docs/USAGE.md](docs/USAGE.md)**.

## Architecture

```
gateway-enhancement-agent/          orchestrator (this repo)
├── docs/USAGE.md                     operator guide (commands, scheduling)
├── docs/DESIGN.md                    architecture + runtime modes
├── config/competitors.json           capability profiles + route_hints
└── artifacts/cycle-XXXX/             gap matrix, coverage, work orders

TARGET_REPO/                          gateway platform (read + agent edits)
```

## macOS auto-start (recommended)

```bash
make login-install     # LaunchAgent: starts on login, KeepAlive, hourly loop
make agent-status
make sync-mirror       # refresh governance mirror after doc changes
make login-uninstall   # stop auto-start
```

Background cycles skip TARGET_REPO pytest (Desktop permissions). Run **`make validate`** in foreground after the local LLM applies changes.

## Local AI (Ollama — no Cursor, no cloud)

1. Install [Ollama](https://ollama.com) (uses Metal GPU on Apple Silicon, CPU fallback).
2. Pull a coding model: `ollama pull qwen2.5-coder:7b`
3. Check readiness: `make llm-status`

Each implement phase sends context to Ollama and writes files under `TARGET_REPO`. Configure `LOCAL_LLM_*` in `.env` or `config/local_llm.json`. Details: [docs/USAGE.md § Foreground vs background](docs/USAGE.md#foreground-vs-background-modes).

## Commands

| Command | Purpose |
|---------|---------|
| `gateway-agent run` | Full SDLC cycle |
| `gateway-agent validate` | Agent tests + gateway gates |
| `gateway-agent coverage` | Competitor capability coverage matrix |
| `gateway-agent backlog` | Enhancement backlog across cycles |
| `gateway-agent sync-mirror` | Copy governance docs to launchd-safe mirror |
| `gateway-agent design` | Print architecture document |
| `gateway-agent llm-status` | Check Ollama model availability |

Full command reference with examples: **[docs/USAGE.md](docs/USAGE.md)**.

## Configuration

| Variable | Purpose |
|----------|---------|
| `TARGET_REPO` | Absolute path to gateway platform checkout |
| `LOOP_INTERVAL_SECONDS` | Loop interval (default `3600`) |
| `AGENT_DATA_DIR` | Writable state/artifacts (Application Support when scheduled) |
| `make login-install` | Schedule on Mac login |
| `LOCAL_LLM_MODEL` | Ollama model for code generation |
| `LOCAL_LLM_AUTO_IMPLEMENT` | `1` = apply LLM patches to TARGET_REPO |

## Open source

This project is **open source** software released under the [MIT License](LICENSE). See [docs/DISCLAIMER.md](docs/DISCLAIMER.md).
