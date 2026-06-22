# Gateway Enhancement Agent

Standalone **local** Python agent that compares your AI gateway platform against competitor capability profiles, prioritizes gaps, and drives a full **SDLC loop** — without embedding tooling inside the gateway codebase and **without any cloud service dependency**.

## What it does

Each cycle runs these phases against `TARGET_REPO` (your gateway checkout):

1. **Discover** — inventory routes, tests, governance docs
2. **Analyze** — gap matrix from API inventory + competitor profiles
3. **Design** — implementation brief aligned with target `AGENTS.md`
4. **Implement** — emits `agent_work_order.md` for Cursor Agent (you execute in the gateway repo)
5. **Validate** — local pytest, control coverage, smoke scripts in `TARGET_REPO`
6. **Document** — governance sync checklist
7. **Release prep** — release decision draft

Artifacts land in `artifacts/cycle-XXXX/` in **this** project only.

## Quick start

```bash
cd "/Users/sk/Desktop/untitled folder/gateway-enhancement-agent"

# Point at your gateway platform repo
cp .env.example .env
# Edit TARGET_REPO=/path/to/your/gateway-repo

pip install -e .

# One-shot discovery
gateway-agent discover
gateway-agent analyze

# Full SDLC cycle (analysis + work order + validation)
gateway-agent run

# Continuous competitor-check loop (default 1h interval)
gateway-agent loop --interval 3600 --max-cycles 5
```

## Architecture

```
gateway-enhancement-agent/     ← this project (orchestrator)
├── config/                    ← competitors, SDLC phases, validation gates
├── src/gateway_enhancement_agent/
└── artifacts/                 ← cycle outputs (gitignored)

TARGET_REPO/                   ← your gateway platform (read + agent edits)
├── backend/app/routers/gateway.py
├── backend/docs/governance/
└── frontend/
```

The orchestrator **never** ships inside the gateway repo. It only reads governance docs and runs validation commands there.

## Cursor IDE workflow

After `gateway-agent run`:

1. Open `artifacts/cycle-XXXX/agent_work_order.md`
2. Open **TARGET_REPO** in Cursor
3. Paste the work order into Agent chat (or use the project skill below)
4. When code is ready: `gateway-agent validate`

## Configuration

| Variable | Purpose |
|----------|---------|
| `TARGET_REPO` | Absolute path to gateway platform checkout |
| `LOOP_INTERVAL_SECONDS` | Sleep between loop cycles (default `3600`) |
| `MAX_CYCLES` | Stop after N cycles (`0` = unlimited) |

Edit `config/competitors.json` to add competitors or capabilities (local only — no web fetch).

Edit `config/validation_gates.json` to tune which commands run in `TARGET_REPO`.

## SDLC validation (mandatory)

Every `gateway-agent run` executes **two validation layers** unless `--skip-validation` is passed:

1. **Agent self-tests** — `pytest` on this project (`config/agent_self_tests.json`)
2. **Target repo gates** — gateway pytest, smoke scripts, control coverage (`config/validation_gates.json`)

```bash
make install          # Mac local install
make self-test        # agent unit tests only
make validate         # self-tests + gateway gates
gateway-agent run     # full SDLC cycle (includes validation)
```

Cycle **fails** if either validation layer fails. See `artifacts/cycle-XXXX/validation_report.md`.

## Schedule on macOS

**Recommended (while logged in):** background daemon loop

```bash
make daemon-start    # hourly cycles (LOOP_INTERVAL_SECONDS in .env)
make daemon-status
tail -f .runtime/daemon.log
make daemon-stop
```

**Optional:** macOS LaunchAgent (runs when logged in; may need Full Disk Access if project lives under Desktop)

```bash
make schedule-install
make schedule-uninstall
```

Default interval: **3600s** (1 hour). Edit `LOOP_INTERVAL_SECONDS` in `.env`.


## Project skill (optional)

Copy or symlink `.cursor/skills/gateway-competitor-sdlc/` into your Cursor skills path, or open this repo alongside TARGET_REPO and reference the skill when implementing work orders.

## License

Use internally for your gateway platform sustainment loop.
