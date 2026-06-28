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
4. **Implement** — emits `agent_work_order.md` for Cursor Agent
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

Background cycles skip TARGET_REPO pytest (Desktop permissions). Run **`make validate`** in foreground after implementing a work order. Details: [docs/USAGE.md § Foreground vs background](docs/USAGE.md#foreground-vs-background-modes).

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

Full command reference with examples: **[docs/USAGE.md](docs/USAGE.md)**.

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
