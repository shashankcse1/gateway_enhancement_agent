# Gateway Enhancement Agent

Standalone **local** Python agent that compares your AI gateway platform against competitor capability profiles, prioritizes gaps, and drives a full **SDLC loop** — without embedding tooling inside the gateway codebase and **without any cloud service dependency**.

See **[docs/DESIGN.md](docs/DESIGN.md)** for architecture, runtime modes, data planes, and gap prioritization.

## What it does

Each cycle runs these phases against `TARGET_REPO` (your gateway checkout):

1. **Discover** — inventory routes, tests, governance docs
2. **Analyze** — scored gap matrix, competitor capability coverage, backlog update
3. **Design** — implementation brief with role-lens checklist
4. **Implement** — emits `agent_work_order.md` for Cursor Agent
5. **Validate** — agent self-tests + TARGET_REPO gates (foreground only)
6. **Document** — governance sync checklist
7. **Release prep** — release decision draft

Artifacts land in `artifacts/cycle-XXXX/` (or Application Support when scheduled).

## Quick start

```bash
cd "/path/to/gateway-enhancement-agent"
cp .env.example .env   # set TARGET_REPO="/path/to/gateway"

pip install -e ".[dev]"

gateway-agent discover
gateway-agent analyze
gateway-agent coverage    # competitor capability vs inventory
gateway-agent backlog     # persistent gap backlog
gateway-agent run         # full SDLC cycle
```

## Architecture

```
gateway-enhancement-agent/          orchestrator (this repo)
├── docs/DESIGN.md                  architecture + runtime modes
├── config/competitors.json         capability profiles + route_hints
└── artifacts/cycle-XXXX/           gap matrix, coverage, work orders

TARGET_REPO/                        gateway platform (read + agent edits)
```

## macOS auto-start (recommended)

```bash
make login-install     # LaunchAgent: starts on login, KeepAlive, hourly loop
make agent-status
make sync-mirror       # refresh governance mirror after doc changes
make login-uninstall   # stop auto-start
```

Background cycles skip TARGET_REPO pytest (Desktop permissions). Run **`make validate`** in foreground after implementing a work order.

## Commands

| Command | Purpose |
|---------|---------|
| `gateway-agent run` | Full SDLC cycle |
| `gateway-agent validate` | Agent tests + gateway gates |
| `gateway-agent coverage` | Competitor capability coverage matrix |
| `gateway-agent backlog` | Enhancement backlog across cycles |
| `gateway-agent sync-mirror` | Copy governance docs to launchd-safe mirror |
| `gateway-agent design` | Print architecture document |
| `make login-install` | Schedule on Mac login |

## Configuration

| Variable | Purpose |
|----------|---------|
| `TARGET_REPO` | Absolute path to gateway platform checkout |
| `LOOP_INTERVAL_SECONDS` | Loop interval (default `3600`) |
| `AGENT_DATA_DIR` | Writable state/artifacts (Application Support when scheduled) |
| `TARGET_REPO_MIRROR` | Governance mirror for background reads |

Edit `config/competitors.json` to add competitors, capabilities, and `route_hints`.

## License

Internal use for gateway platform sustainment.
