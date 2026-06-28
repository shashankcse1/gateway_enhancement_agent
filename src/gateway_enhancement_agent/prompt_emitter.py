"""Emit Cursor IDE work orders for implementation in TARGET_REPO."""

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

- [ ] Security Architect — authz, least privilege, threat boundaries
- [ ] Audit Architect — allow/deny audit evidence on mutations
- [ ] CISO — blast radius and residual risk
- [ ] Security Engineer — abuse-case tests for changed surfaces

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
    return f"""# Agent Work Order — Cycle {cycle_id:04d}

> Open this file in Cursor with **TARGET_REPO** as workspace root, or paste into Agent chat.

## Task

Implement the highest-priority gateway gap for cycle {cycle_id:04d}:

**{gap.title}** (`{gap.gap_id}`)

## Context

- Target repo: `{repo}`
- Design brief: `artifacts/cycle-{cycle_id:04d}/design_brief.md`
- Gap matrix: `artifacts/cycle-{cycle_id:04d}/gap_matrix.json`

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
