# Gateway Enhancement Agent — Usage Guide

Operator and developer guide for running the local competitor-gap SDLC agent on macOS. For architecture, data planes, and gap scoring rules, see **[DESIGN.md](DESIGN.md)**.

## Overview

The **gateway-enhancement-agent** is a standalone Python project that:

1. Reads your gateway platform checkout (`TARGET_REPO`) — routes, tests, governance inventory.
2. Compares it against local competitor capability profiles (`config/competitors.json`).
3. Prioritizes gaps and emits SDLC artifacts (gap matrix, design brief, work order).
4. Optionally validates changes via agent self-tests and gateway repo gates.

Everything runs **locally**. There is no cloud API, no network fetch for competitor data, and no code embedded inside the gateway repo.

### Prerequisites

| Requirement | Notes |
|-------------|-------|
| **macOS** | LaunchAgent scheduling is documented for Mac; CLI works on any OS with Python 3.9+. |
| **Python 3.9+** | Declared in `pyproject.toml` (`requires-python = ">=3.9"`). |
| **Gateway checkout** | A local clone of your AI gateway platform with `backend/`, governance docs, and tests. |
| **`TARGET_REPO`** | Absolute path to that checkout, quoted if it contains spaces. |
| **Node.js** | Required only for gateway validation gate `frontend_syntax` (`node --check app.js`). |
| **Cursor (optional)** | Used to implement `agent_work_order.md` in the gateway repo. |

Typical layout:

```
/Users/sk/Desktop/untitled folder/
├── gateway-enhancement-agent/     ← this project (orchestrator)
└── new design/                    ← TARGET_REPO (gateway platform)
```

---

## First-time setup

### 1. Clone or open the agent project

```bash
cd "/Users/sk/Desktop/untitled folder/gateway-enhancement-agent"
```

### 2. Create `.env`

Copy the example and set your gateway path:

```bash
cp .env.example .env
```

Edit `.env`:

```bash
# Quote paths that contain spaces.
TARGET_REPO="/Users/sk/Desktop/untitled folder/new design"

# Optional — loop interval in seconds (default 3600 = 1 hour)
LOOP_INTERVAL_SECONDS=3600

# Optional — stop after N cycles in a loop session (0 = unlimited)
MAX_CYCLES=0
```

The CLI loads `.env` from the project root automatically (`gateway_enhancement_agent/cli.py`). Shell scripts (`make login-install`, daemon scripts) also source `.env` when present.

### 3. Install the package

```bash
make install
```

This runs `python3 -m pip install --user -e ".[dev]"`, which installs the `gateway-agent` console script and pytest dev dependency.

Alternatively:

```bash
python3 -m pip install --user -e ".[dev]"
```

Verify:

```bash
gateway-agent status
```

You should see your `TARGET_REPO` path and `Cycles completed: 0` (or higher if you have run cycles before).

### 4. Sanity check

```bash
gateway-agent discover
gateway-agent analyze
```

If `discover` reports zero routes or gaps, confirm `TARGET_REPO` points at the correct checkout and that `backend/app/routers/gateway.py` and `backend/docs/governance/api-inventory-and-ui-map.md` exist.

---

## CLI commands

All commands are available as `gateway-agent <command>` or `python3 -m gateway_enhancement_agent <command>`. Every command requires a valid `TARGET_REPO` (from `.env` or environment).

### `status`

Show target repo path and loop state (cycle count, last cycle status).

```bash
gateway-agent status
```

Example output:

```
Target repo: /Users/sk/Desktop/untitled folder/new design
Cycles completed: 10
Last cycle: #10 status=completed phase=done
```

### `discover`

Print a read-only inventory snapshot: gateway route count, Partial/Gap endpoint count, test files, competitor profile count.

```bash
gateway-agent discover
```

Use this first when troubleshooting stale or empty analysis.

### `analyze`

Build and print the prioritized gap matrix (markdown). Shows the current top gap.

```bash
gateway-agent analyze
```

Does not write cycle artifacts; use `run` for a full SDLC cycle with persisted outputs.

### `coverage`

Print the competitor capability coverage matrix — which capabilities from `config/competitors.json` appear covered by inventory routes.

```bash
gateway-agent coverage
```

### `backlog`

Print the persistent enhancement backlog across all cycles (open, scheduled, closed, deferred items).

```bash
gateway-agent backlog
```

Backlog data lives in `.runtime/backlog.json` (or Application Support when scheduled — see [Artifacts and backlog locations](#artifacts-and-backlog-locations)).

### `run`

Run one full SDLC cycle: discover → analyze → design → implement → validate → document → release prep.

```bash
gateway-agent run
```

On success, artifacts are written to `artifacts/cycle-XXXX/` (four-digit cycle id). The command prints the active gap and path to the work order:

```
Cycle 11 finished: status=completed
Artifacts: artifacts/cycle-0011/
Active gap: inv-042 — open agent_work_order.md in Cursor
```

Skip validation (not recommended for pre-merge checks):

```bash
gateway-agent run --skip-validation
```

In **background mode** (`AGENT_BACKGROUND_MODE=1`), the loop runner forces `--skip-validation` automatically.

### `validate`

Run **agent self-tests** then **TARGET_REPO validation gates**. Exits non-zero if any required gate fails.

```bash
gateway-agent validate
```

Or via Makefile:

```bash
make validate
```

Run this in the **foreground** after implementing a work order in the gateway repo. Background LaunchAgent cycles intentionally skip gateway pytest.

### `self-test`

Run only the agent's own unit tests (same gate as the first tier of `validate`).

```bash
gateway-agent self-test
```

Equivalent to:

```bash
make self-test
# or: python3 -m pytest -q tests
```

### `loop`

Run SDLC cycles continuously, sleeping between cycles.

```bash
gateway-agent loop --interval 3600
```

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--interval` | `LOOP_INTERVAL_SECONDS` or `3600` | Seconds between cycles |
| `--max-cycles` | `MAX_CYCLES` or `0` | Stop after N cycles (`0` = unlimited) |
| `--skip-validation` | off | Skip validation every cycle |

Example — three cycles, five minutes apart:

```bash
gateway-agent loop --interval 300 --max-cycles 3
```

When `AGENT_BACKGROUND_MODE=1` is set (LaunchAgent install), validation is always skipped.

### `sync-mirror`

Copy governance docs, `backend/AGENTS.md`, and `backend/app/routers/gateway.py` from `TARGET_REPO` into the local mirror directory.

```bash
gateway-agent sync-mirror
```

Default mirror path: `<project_root>/target-mirror/`. Override with `TARGET_REPO_MIRROR`.

Run after gateway governance or route changes so background reads stay current. `make login-install` performs an initial mirror sync automatically.

### `design`

Print the architecture document to stdout.

```bash
gateway-agent design
```

Same content as `docs/DESIGN.md`.

---

## Makefile targets

Run all Make targets from the agent project root:

```bash
cd "/Users/sk/Desktop/untitled folder/gateway-enhancement-agent"
```

| Target | Command | Purpose |
|--------|---------|---------|
| `install` | `pip install -e ".[dev]"` | Install `gateway-agent` CLI |
| `discover` | `gateway-agent discover` | Inventory snapshot |
| `analyze` | `gateway-agent analyze` | Gap matrix (stdout only) |
| `coverage` | `gateway-agent coverage` | Capability coverage matrix |
| `backlog` | `gateway-agent backlog` | Persistent backlog report |
| `run` | `gateway-agent run` | One full SDLC cycle |
| `run-full` | `test` + `validate` + `run` | Self-test, validate, then cycle |
| `validate` | `gateway-agent validate` | Agent + gateway gates |
| `self-test` / `test` | `pytest -q tests` | Agent unit tests only |
| `sync-mirror` | `gateway-agent sync-mirror` | Refresh governance mirror |
| `design-doc` | `gateway-agent design` | Print DESIGN.md |
| `loop` | `gateway-agent loop` | Continuous cycles (uses `.env` interval) |
| `status` | `gateway-agent status` | Cycle state |
| `login-install` | `scripts/install_login_agent.sh` | Install LaunchAgent (recommended) |
| `login-uninstall` | `scripts/uninstall_login_agent.sh` | Remove LaunchAgent |
| `agent-status` | `scripts/agent_status.sh` | LaunchAgent + daemon + agent state |
| `ensure-running` | `scripts/ensure_running.sh` | Start LaunchAgent or daemon if idle |
| `daemon-start` | `scripts/start_daemon.sh` | Background loop without launchd |
| `daemon-stop` | `scripts/stop_daemon.sh` | Stop daemon by PID file |
| `daemon-status` | Check daemon PID + launchd | Quick process check |

**Note:** `make run` sets `TARGET_REPO` from `GATEWAY_REPO` in the Makefile default (`/Users/sk/Desktop/untitled folder/new design`). Override for one-shot runs:

```bash
make run GATEWAY_REPO="/path/to/your/gateway"
```

---

## macOS LaunchAgent scheduling

The recommended way to run hourly gap detection and work-order generation is **`make login-install`**, which registers a user LaunchAgent that starts at login and stays alive.

### What `login-install` does

1. Reads `.env` for `TARGET_REPO` and `LOOP_INTERVAL_SECONDS`.
2. Installs the Python package to user site-packages.
3. Creates a space-free symlink: `~/.gateway-enhancement-agent-src` → your checkout.
4. Copies config to Application Support and syncs the governance mirror.
5. Writes `~/Library/Application Support/gateway-enhancement-agent/run_loop.sh` with environment:
   - `AGENT_DATA_DIR` → Application Support
   - `AGENT_SOURCE_ROOT` → symlink
   - `TARGET_REPO_MIRROR` → `<Support>/target-mirror`
   - `AGENT_BACKGROUND_MODE=1` (skips gateway validation)
6. Installs `~/Library/LaunchAgents/com.gateway.enhancement-agent.plist` with `RunAtLoad` and `KeepAlive`.

### Install

```bash
cd "/Users/sk/Desktop/untitled folder/gateway-enhancement-agent"
make login-install
```

### Check status

```bash
make agent-status
```

Logs:

- `~/Library/Application Support/gateway-enhancement-agent/.runtime/launchd.out.log`
- `~/Library/Application Support/gateway-enhancement-agent/.runtime/launchd.err.log`

### Uninstall

```bash
make login-uninstall
```

This stops the agent and removes the plist. Application Support data is **not** deleted automatically.

### Application Support paths

| Path | Contents |
|------|----------|
| `~/Library/Application Support/gateway-enhancement-agent/` | Writable data root (`AGENT_DATA_DIR`) |
| `.../artifacts/cycle-XXXX/` | Cycle artifacts when scheduled |
| `.../.runtime/state.json` | Cycle counter and history |
| `.../.runtime/backlog.json` | Persistent backlog |
| `.../target-mirror/` | Governance mirror for background reads |
| `.../config/` | Installed copy of `competitors.json`, validation configs |
| `.../run_loop.sh` | LaunchAgent entry script |
| `~/.gateway-enhancement-agent-src` | Symlink to source checkout (no spaces in path) |

After editing `config/competitors.json` in your checkout, re-run `make login-install` or copy updated files to Application Support config manually.

### Alternative: dev daemon (no launchd)

For a single session without login persistence:

```bash
make daemon-start    # background loop, logs to .runtime/daemon.log
make daemon-status
make daemon-stop
```

The dev daemon uses the project checkout for data (`.runtime/`, `artifacts/`) unless you set `AGENT_DATA_DIR`.

---

## Foreground vs background modes

| Aspect | Foreground | Background |
|--------|------------|------------|
| **Typical trigger** | `gateway-agent run`, `make validate` | `make login-install`, `AGENT_BACKGROUND_MODE=1` |
| **Validation** | Full: agent pytest + TARGET_REPO gates | Skipped (`loop_runner` sets `skip_validation=True`) |
| **Mirror** | Optional | Required for reliable governance reads |
| **Data directory** | Project `.runtime/` and `artifacts/` | Application Support |
| **Use case** | Pre-merge validation, manual cycles | Hourly gap detection + work orders |

### Environment variables

| Variable | Purpose |
|----------|---------|
| `AGENT_BACKGROUND_MODE=1` | Loop and scheduled runs skip TARGET_REPO validation |
| `AGENT_SKIP_TARGET_VALIDATION=1` | Run agent self-tests only during `run` (not gateway gates) |
| `AGENT_DATA_DIR` | Writable root for state and artifacts |
| `AGENT_SOURCE_ROOT` | Read-only code location (symlink for launchd) |
| `AGENT_CONFIG_DIR` | Config JSON location (Application Support when installed) |
| `TARGET_REPO_MIRROR` | Mirror path for governance/gateway.py reads |

### When validation runs

- **`gateway-agent run`** (foreground, default): runs combined validation unless `--skip-validation` or `AGENT_SKIP_TARGET_VALIDATION=1`.
- **`gateway-agent loop`**: validates each cycle unless `--skip-validation` or `AGENT_BACKGROUND_MODE=1`.
- **`gateway-agent validate`**: always runs both tiers; use after implementing a work order.

Background mode exists because launchd cannot reliably execute long pytest suites against repos on Desktop paths (macOS privacy permissions). The intended workflow is: background generates work orders → you implement in Cursor → foreground `make validate`.

---

## Governance mirror

Background processes read governance files from **`TARGET_REPO_MIRROR`** when direct reads of `TARGET_REPO` fail (common for Desktop paths under launchd).

### Sync manually

```bash
cd "/Users/sk/Desktop/untitled folder/gateway-enhancement-agent"
gateway-agent sync-mirror
# or: make sync-mirror
```

Copied files:

- `backend/docs/governance/*.md`
- `backend/AGENTS.md`
- `backend/app/routers/gateway.py`

### When to sync

- After updating API inventory or governance docs in the gateway repo.
- After adding or changing routes in `gateway.py`.
- Before relying on background cycle output for prioritization.

If analysis looks stale (old gap counts, missing endpoints), sync the mirror first:

```bash
make sync-mirror
gateway-agent discover
```

---

## Artifacts and backlog locations

### Per-cycle artifacts

Each `gateway-agent run` (or loop iteration) writes to:

```
artifacts/cycle-XXXX/
├── inventory_snapshot.json
├── competitor_snapshot.json
├── gap_matrix.json
├── gap_report.md
├── capability_coverage.json
├── capability_coverage.md
├── backlog.md
├── design_brief.md
├── agent_work_order.md      ← paste into Cursor Agent
├── validation_report.json   ← foreground runs only
├── validation_report.md
├── doc_sync_checklist.md
├── release_decision_draft.md
└── cycle_summary.json
```

When scheduled via LaunchAgent, the same structure appears under:

```
~/Library/Application Support/gateway-enhancement-agent/artifacts/cycle-XXXX/
```

### Persistent state

| File | Location | Purpose |
|------|----------|---------|
| `state.json` | `.runtime/` or Application Support `.runtime/` | Cycle count, last cycle metadata |
| `backlog.json` | same `.runtime/` | Cross-cycle gap backlog |
| `daemon.pid` | project `.runtime/` | Dev daemon PID (not used by LaunchAgent) |

### Implementing a work order

1. Open `artifacts/cycle-XXXX/agent_work_order.md` (or the Application Support path).
2. Switch Cursor workspace to **TARGET_REPO** (the gateway platform).
3. Follow the work order; read `backend/AGENTS.md` first.
4. Return to the agent project and run `make validate`.

See also `.cursor/skills/gateway-competitor-sdlc/SKILL.md` in this repo for Cursor Agent rules.

---

## Validation gates

Validation is two-tiered. Both tiers must pass for `gateway-agent validate` and for a foreground `run` cycle to succeed.

### Tier 1 — Agent self-tests

Defined in `config/agent_self_tests.json`:

| Gate | Command |
|------|---------|
| `agent_unit_tests` | `python3 -m pytest -q tests` (in agent project, 300s timeout) |

### Tier 2 — TARGET_REPO gates

Defined in `config/validation_gates.json`. Commands run with `cwd` relative to `TARGET_REPO`:

| Gate | Directory | Command |
|------|-----------|---------|
| `frontend_syntax` | `frontend/` | `node --check app.js` |
| `security_smoke` | `frontend/` | `bash scripts/security_smoke.sh` |
| `control_coverage` | `backend/` | `python3 scripts/check_control_coverage.py` |
| `gateway_pytest` | `backend/` | Focused pytest on gateway test modules (600s timeout) |

Add or adjust gates by editing the JSON files. After `login-install`, the Application Support copy is used unless you set `AGENT_CONFIG_DIR` back to the checkout.

### Reading validation output

```bash
gateway-agent validate
```

Failures include stderr tails in the markdown report. Per-cycle reports are also saved as `artifacts/cycle-XXXX/validation_report.md`.

---

## Configuration reference

### `.env` (project root)

```bash
TARGET_REPO="/Users/sk/Desktop/untitled folder/new design"
LOOP_INTERVAL_SECONDS=3600
MAX_CYCLES=0
```

Always quote `TARGET_REPO` when the path contains spaces.

### `config/competitors.json`

Local competitor capability profiles — no network fetch. Each competitor has `capabilities` with `route_hints` used for gap boosting. Edit here to add competitors or reprioritize parity targets.

### `config/validation_gates.json` / `config/agent_self_tests.json`

Subprocess gate definitions for the gateway repo and this agent, respectively.

---

## Troubleshooting

### `TARGET_REPO is not set`

Create `.env` from `.env.example` or export the variable:

```bash
export TARGET_REPO="/Users/sk/Desktop/untitled folder/new design"
```

### Paths with spaces break silently

Use quotes in `.env`:

```bash
TARGET_REPO="/Users/sk/Desktop/untitled folder/new design"
```

Unquoted values truncate at the first space.

### `ModuleNotFoundError: gateway_enhancement_agent`

Install the package in editable mode:

```bash
cd "/Users/sk/Desktop/untitled folder/gateway-enhancement-agent"
make install
```

For LaunchAgent, re-run `make login-install` to refresh the Application Support pylibs install.

### Desktop folder permission errors (launchd)

macOS may block launchd from reading repos on Desktop/Documents. Symptoms: zero routes, empty inventory, mirror fallback errors.

Mitigations:

1. Use **`make login-install`** — it sets `AGENT_SOURCE_ROOT` via `~/.gateway-enhancement-agent-src` and mirrors governance files.
2. Run **`make sync-mirror`** after gateway doc changes.
3. Run **`make validate`** in Terminal (foreground) for pytest — not from LaunchAgent.

### Stale gap analysis / wrong top gap

Governance mirror is out of date. Sync and re-run:

```bash
make sync-mirror
gateway-agent discover
gateway-agent run
```

### LaunchAgent not running

```bash
make agent-status
make ensure-running
```

Inspect logs at `~/Library/Application Support/gateway-enhancement-agent/.runtime/launchd.err.log`.

### Cycle `status=failed` with validation errors

Expected when gateway gates fail. Fix the gateway repo, then:

```bash
make validate
```

Re-run a cycle when ready:

```bash
gateway-agent run
```

### `gateway-agent: command not found`

Ensure user Python bin is on `PATH`:

```bash
export PATH="${HOME}/Library/Python/3.9/bin:${PATH}"
```

Or use the module form:

```bash
python3 -m gateway_enhancement_agent status
```

---

## Workflow examples

### One-shot analysis (no artifacts)

Quick check without starting a numbered cycle:

```bash
cd "/Users/sk/Desktop/untitled folder/gateway-enhancement-agent"
gateway-agent discover
gateway-agent analyze
gateway-agent coverage
gateway-agent backlog
```

### Full SDLC cycle (manual)

```bash
cd "/Users/sk/Desktop/untitled folder/gateway-enhancement-agent"
make sync-mirror
gateway-agent run
```

Open the printed `artifacts/cycle-XXXX/agent_work_order.md` in Cursor with TARGET_REPO as workspace. After implementation:

```bash
make validate
```

Complete items in `artifacts/cycle-XXXX/doc_sync_checklist.md`.

### Full pipeline with tests first

```bash
make run-full
```

Runs agent self-tests, combined validation, then one SDLC cycle.

### Scheduled hourly operation

One-time setup:

```bash
cd "/Users/sk/Desktop/untitled folder/gateway-enhancement-agent"
cp .env.example .env
# edit TARGET_REPO and LOOP_INTERVAL_SECONDS
make login-install
```

Ongoing operator routine:

1. Agent runs hourly in background; new work orders appear under Application Support `artifacts/`.
2. After gateway governance edits: `make sync-mirror`.
3. When implementing a gap: use latest `agent_work_order.md` in Cursor → `make validate` in foreground.
4. Check health: `make agent-status`.

To change interval, update `LOOP_INTERVAL_SECONDS` in `.env` and re-run `make login-install`.

### Short dev loop (three cycles, validation on)

```bash
gateway-agent loop --interval 120 --max-cycles 3
```

Do **not** set `AGENT_BACKGROUND_MODE` if you want validation each cycle (slower, requires gateway repo access from Terminal).

---

## Related documentation

- **[DESIGN.md](DESIGN.md)** — Architecture, runtime modes, gap prioritization, backlog lifecycle.
- **[README.md](../README.md)** — Project summary and quick start.
- **`.cursor/skills/gateway-competitor-sdlc/SKILL.md`** — Cursor Agent checklist for implementing work orders.
