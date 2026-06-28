"""Emit implementation briefs and work orders for local LLM execution in TARGET_REPO."""

from __future__ import annotations

from pathlib import Path

from gateway_enhancement_agent.config import target_repo
from gateway_enhancement_agent.gap_analyzer import GapItem


def build_design_brief(gap: GapItem, cycle_id: int) -> str:
    repo = target_repo()
    comp_line = ", ".join(gap.competitor_ids) if gap.competitor_ids else "N/A"
    caps_line = ", ".join(gap.related_capabilities) if gap.related_capabilities else "N/A"
    return f"""# Design Brief — Cycle {cycle_id:04d}

## Gap

- **ID:** `{gap.gap_id}`
- **Title:** {gap.title}
- **Score:** {gap.score} (lower = higher priority)
- **Source:** {gap.source}
- **Route:** {gap.route or 'N/A'}
- **Coverage:** {gap.coverage or 'N/A'}
- **Competitors:** {comp_line}
- **Related capabilities:** {caps_line}
- **Rationale:** {gap.rationale}

## Target repository

`{repo}`

## Role-lens checklist (from backend/AGENTS.md)

- [ ] **Security Architect** — authz, least privilege, threat boundaries, token lifecycle
- [ ] **Audit Architect** — mutation audit, deny-path evidence, traceability
- [ ] **CISO** — blast radius, residual risk, go/no-go
- [ ] **AWS Engineer** — IAM least privilege, STS boundaries, secret posture
- [ ] **Cloud Engineer** — deployability, rollback, observability, rate limits
- [ ] **AI Architect** — model routing, fallback strategy, responsible-AI controls
- [ ] **Frontend UI Expert** — accessibility, operator UX, error paths
- [ ] **Security Engineer Expert** — abuse-case tests, input validation, hardening

## Component-driven architecture

- Extend the **owning component** first (see `config/components.json` in the agent repo).
- Keep changes within component path boundaries; avoid cross-component drive-by edits.
- UI: use existing console partials; backend: router + focused service module + tests in one slice.

## Microservices guidance

- **Default:** enhance the gateway monolith until `components.json` `microservice_triggers` apply.
- **Extract only when:** independent scaling, blast-radius isolation, or stable API boundary is documented in governance.
- **Never extract without:** observability, rollback, dual-approval parity, and API inventory entry for the new service contract.

## Constraints (mandatory)

1. Read `backend/AGENTS.md` in the target repo before coding.
2. Align with governance docs under `backend/docs/governance/`.
3. Implement backend contract + tests + UI (if API inventory marks Partial/Gap) in one slice.
4. Preserve security: role gates, prod dual-approval, deny-path audit.
5. No cloud service dependencies for the enhancement itself.

## Acceptance criteria

1. Gap closed or explicitly documented as deferred with governance update.
2. Focused pytest for touched modules passes.
3. API inventory / coverage map updated when UI or endpoint behavior changes.
4. Residual risk register updated when auth/routing/privileged actions change.

## Suggested touch surfaces

- `backend/app/routers/gateway.py` and related services
- `backend/tests/test_gateway_*.py`
- `frontend/views/routing-gateway.html` and `frontend/app.js` (if operator UI needed)
"""


def build_agent_work_order(gap: GapItem, cycle_id: int) -> str:
    repo = target_repo()
    return f"""# Implementation Work Order — Cycle {cycle_id:04d}

> The SDLC pipeline applies this via **local Ollama** (CPU/GPU on this Mac). No cloud or IDE dependency.

## Task

Implement the highest-priority gateway gap for cycle {cycle_id:04d}:

**{gap.title}** (`{gap.gap_id}`)

## Context

- Target repo: `{repo}`
- Design brief: `artifacts/cycle-{cycle_id:04d}/design_brief.md`
- Gap matrix: `artifacts/cycle-{cycle_id:04d}/gap_matrix.json`
- Implementation report: `artifacts/cycle-{cycle_id:04d}/implementation_report.md`

## Instructions

1. Read `backend/AGENTS.md` and relevant governance docs.
2. Implement the minimal correct slice (backend + tests + docs; UI if inventory requires).
3. Run validation gates from the enhancement agent project:
   ```bash
   cd "{Path(__file__).resolve().parents[2].parent}"
   TARGET_REPO="{repo}" gateway-agent validate
   ```
4. Do not commit secrets, `.runtime/`, or `artifacts/`.

## Definition of done

- [ ] Gap addressed or formally deferred in governance docs
- [ ] Tests added/updated for changed behavior
- [ ] Governance inventory synced
- [ ] `gateway-agent validate` passes required gates
"""


def build_implementation_report(gap: GapItem, cycle_id: int, result) -> str:
    repo = target_repo()
    if not result.attempted:
        status = f"Skipped — {result.skipped_reason or 'not configured'}"
    elif result.succeeded:
        status = f"Applied via local model `{result.model}`"
    else:
        status = f"Failed — {result.error or result.skipped_reason or 'no files written'}"
    files = "\n".join(f"- `{f}`" for f in result.files_written) or "- _(none)_"
    mode = getattr(result, "implementation_mode", "single")
    parallel_lines = ""
    if mode == "parallel":
        parallel_lines = (
            f"\n## Parallel subagents\n\n"
            f"- Mode: **parallel**\n"
            f"- Workers run: **{getattr(result, 'subagents_run', 0)}**\n"
            f"- Workers succeeded: **{getattr(result, 'subagents_succeeded', 0)}**\n"
            f"- Synthesizer merge: **{'yes' if getattr(result, 'synthesizer_used', False) else 'no'}**\n"
            f"- Artifacts: `artifacts/cycle-{cycle_id:04d}/subagents/`, `parallel_merge.md`\n"
        )
    return f"""# Local Implementation Report — Cycle {cycle_id:04d}

## Gap

**{gap.title}** (`{gap.gap_id}`)

## Status

{status}

## Target repository

`{repo}`

## Files written

{files}
{parallel_lines}
## Next steps

1. Review diffs in TARGET_REPO before merge.
2. Run `gateway-agent validate` in foreground.
3. Update governance docs per `doc_sync_checklist.md`.
"""


def build_doc_sync_checklist(gap: GapItem) -> str:
    return f"""# Documentation Sync Checklist

Active gap: **{gap.title}** (`{gap.gap_id}`)

Update in target repo when behavior or UI changes:

- [ ] `backend/docs/governance/api-inventory-and-ui-map.md`
- [ ] `backend/docs/governance/ui-api-design-coverage-map.md`
- [ ] `backend/docs/governance/documentation-source-of-truth.md`
- [ ] `backend/docs/security/residual-and-accepted-risk-register.md` (if privileged/auth changes)
- [ ] `frontend/README.md` (if operator surface changes)
- [ ] Focused impact analysis doc (if new parity slice)
"""


def build_release_draft(gap: GapItem, cycle_id: int, validation_passed: bool) -> str:
    status = "PASS" if validation_passed else "FAIL — do not release"
    return f"""# Release Decision Draft — Cycle {cycle_id:04d}

## Scope

{gap.title} (`{gap.gap_id}`)

## Validation posture

**{status}**

## Role-lens sign-off (complete before merge)

- [ ] Security Architect
- [ ] Audit Architect
- [ ] CISO
- [ ] AWS Engineer
- [ ] Cloud Engineer
- [ ] AI Architect
- [ ] Frontend UI Expert
- [ ] Security Engineer Expert

## Test evidence

Attach `artifacts/cycle-{cycle_id:04d}/validation_report.json`.

## Residual risk

Document any accepted risk with expiry in the target repo risk register.
"""
