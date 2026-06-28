# Gateway Enhancement Agent

Standalone **local** Python agent that compares your AI gateway platform against competitor capability profiles, prioritizes gaps, and drives a full **SDLC loop** — without embedding tooling inside the gateway codebase and **without any cloud service dependency**.

| Document | Audience |
|----------|----------|
| **[docs/DESIGN.md](docs/DESIGN.md)** | Architecture, runtime modes, data planes, gap prioritization |
| **[docs/ARCHITECTURE_BEST_PRACTICES.md](docs/ARCHITECTURE_BEST_PRACTICES.md)** | Security, CISO, cloud, agentic, parallelism, components, microservices |

## What it does

Each cycle runs these phases against `TARGET_REPO` (your gateway checkout):

1. **Discover** — inventory routes, tests, governance docs
2. **Analyze** — scored gap matrix, competitor capability coverage, backlog update
3. **Design** — implementation brief with role-lens checklist
4. **Implement** — parallel local-LLM subagents (backend, tests, UI, docs) + synthesizer merge into TARGET_REPO
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

## Local providers

| Phase | Provider | Notes |
|-------|----------|-------|
| **Discover — web research** | Free public docs + local rule-based extraction | `config/competitor_research.json`; no Ollama, no paid APIs |
| **Implement / review / synthesizer** | [Ollama](https://ollama.com) | `config/local_llm.json`, `config/parallel_workers.json` |

### Web research (discover)

Fetches allowlisted public documentation (LiteLLM, Portkey, Kong, Helicone), extracts capabilities via keyword/route matching, caches results for 7 days. Force refresh: `make research-competitors`.

### Ollama agents (implement)

1. Install [Ollama](https://ollama.com) (uses Metal GPU on Apple Silicon, CPU fallback).
2. Pull a coding model: `ollama pull qwen2.5-coder:7b`
3. Check readiness: `make llm-status`

Each implement phase runs **parallel subagents** (independent Ollama workers) then a **synthesizer** merges their file outputs. Configure `PARALLEL_IMPLEMENT=0` for single-pass mode. See `config/parallel_workers.json`.

## Summary email (every 2 hours)

Sends a gateway status report every 2 hours via **macOS local Postfix** (`127.0.0.1:25`, no credentials) or a remote relay.

1. **Local (default):** ensure Postfix is running — `sudo postfix start` if needed
2. Set recipient in `.env`: `WEEKLY_EMAIL_TO=you@example.com`
3. Local SMTP settings: `SMTP_MODE=local`, `SMTP_HOST=127.0.0.1`, `SMTP_PORT=25`
4. Preview: `make weekly-report`
5. Send now: `make send-weekly-report`
6. Schedule: included in `make login-install` or `make weekly-email-install`

For Gmail relay instead, set `SMTP_MODE=relay` with `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`.

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
| `LOCAL_LLM_MODEL` | Ollama model for implement/review/synthesizer agents |
| `LOCAL_LLM_AUTO_IMPLEMENT` | `1` = apply LLM patches to TARGET_REPO |
| `COMPETITOR_WEB_RESEARCH` | `1` = fetch free public docs in discover phase |
| `COMPETITOR_RESEARCH_MODE` | `local` = rule-based extraction (default; no Ollama) |

## Open source

This project is **open source** software released under the [MIT License](LICENSE). See [docs/DISCLAIMER.md](docs/DISCLAIMER.md).
