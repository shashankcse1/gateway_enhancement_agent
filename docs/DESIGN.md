# Gateway Enhancement Agent — Design

For installation, CLI commands, LaunchAgent setup, and troubleshooting, see **[USAGE.md](USAGE.md)**.

## Purpose

Local orchestrator that closes the loop between **competitor capability expectations**, **gateway governance inventory**, and **operator implementation** — without embedding tooling in the gateway repo or calling cloud APIs.

## System context

```
┌─────────────────────────────────────────────────────────────────┐
│  gateway-enhancement-agent (this repo)                          │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │ config/     │  │ SDLC pipeline │  │ artifacts + backlog    │ │
│  │ competitors │→ │ discover      │→ │ cycle-XXXX/            │ │
│  │ validation  │  │ analyze       │  │ backlog.json           │ │
│  └─────────────┘  │ design        │  └────────────────────────┘ │
│                   │ implement     │                              │
│                   │ validate      │                              │
│                   │ document      │                              │
│                   │ release_prep  │                              │
└───────────────────┬─────────────────────────────────────────────┘
                    │ read / validate (subprocess)
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  TARGET_REPO (gateway platform)                                 │
│  backend/app/routers/gateway.py                                 │
│  backend/docs/governance/api-inventory-and-ui-map.md            │
│  frontend/ + pytest + smoke scripts                             │
└─────────────────────────────────────────────────────────────────┘
```

## Runtime modes

| Mode | Trigger | Validation | Mirror | Use case |
|------|---------|------------|--------|----------|
| **Foreground** | `gateway-agent run`, `make validate` | Agent self-tests + TARGET_REPO gates | Optional | Before merge / manual cycle |
| **Background** | LaunchAgent loop, `AGENT_BACKGROUND_MODE=1` | Skipped (analysis only) | Required | Hourly gap detection + work orders |
| **Loop (daemon)** | `make daemon-start` | Same as background if env set | Recommended | Dev session without launchd |

Background mode intentionally **does not** run gateway pytest from launchd — Desktop path permissions and long runtimes make that unreliable. Run `make validate` in foreground after implementing a work order.

## Legal

This project is open source under the [MIT License](../LICENSE). See [DISCLAIMER.md](DISCLAIMER.md) for warranty and liability terms.

## Data planes

| Plane | Location | Writable | launchd-safe |
|-------|----------|----------|--------------|
| **Source** | Project checkout (may be on Desktop) | Yes (git) | No — use symlink `~/.gateway-enhancement-agent-src` |
| **Data** | `AGENT_DATA_DIR` or `.runtime/` | Yes | Yes — `~/Library/Application Support/gateway-enhancement-agent` |
| **Config (installed)** | `AGENT_CONFIG_DIR` or `config/` | Install copies to Application Support | Yes |
| **Mirror** | `TARGET_REPO_MIRROR` | `make sync-mirror` | Yes — governance + gateway.py snapshot |

## SDLC phases

1. **Discover** — route count, test files, API inventory Partial/Gap rows, competitor profiles
2. **Analyze** — prioritized gap matrix + capability coverage matrix + backlog update
3. **Design** — brief with competitor context, role-lens checklist, acceptance criteria
4. **Implement** — `CodeImplementer` calls **local Ollama** (Metal GPU / CPU) to patch TARGET_REPO
5. **Validate** — tiered gates (see `config/agent_self_tests.json`, `config/validation_gates.json`)
6. **Document** — governance sync checklist
7. **Release prep** — release decision draft with validation posture

## Gap prioritization

Score = base priority (Gap=10, Partial=20, optimization=30) minus competitor boosts.

- Inventory **Gap** rows outrank **Partial**
- Routes matching competitor `route_hints` with priority 1 get −5 score boost
- Gaps seen in ≥3 cycles without closure get −3 boost (staleness)
- Backlog item marked `deferred` is excluded from top-gap selection

## Backlog lifecycle

```
open → scheduled (picked for work order) → closed | deferred
```

Stored in `AGENT_DATA_DIR/.runtime/backlog.json`. `gateway-agent backlog` lists items.

## Extension points

- **competitors.json** — add profiles, capabilities, `route_hints`
- **validation_gates.json** — add TARGET_REPO commands
- **sdlc_phases.json** — documentation of phase contract (not executed dynamically)
- **prompt_emitter.py** — work order templates

## macOS scheduling

Preferred: `make login-install` → LaunchAgent with `KeepAlive` + `RunAtLoad`.

Install copies package + config to Application Support and syncs governance mirror. Re-run `make sync-mirror` after gateway governance changes.

## Security

- No network fetch for competitor data
- No secrets in artifacts
- TARGET_REPO validation runs locally with operator's existing toolchain
- Work orders reference `backend/AGENTS.md` role-lens contract
