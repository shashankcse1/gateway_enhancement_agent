---
name: gateway-competitor-sdlc
description: >-
  Runs the local gateway competitor-gap SDLC loop against an external TARGET_REPO.
  Use when implementing agent_work_order.md from gateway-enhancement-agent artifacts,
  enhancing AI gateway Python code, closing parity gaps, or completing governance sync
  after a competitor analysis cycle.
---

# Gateway Competitor SDLC

## When to use

The user is implementing a work order from `gateway-enhancement-agent/artifacts/cycle-*/agent_work_order.md` in a **separate** gateway platform repo.

## Rules

1. Work in **TARGET_REPO** only — do not add orchestrator code to the gateway repo.
2. Read `backend/AGENTS.md` before any backend change.
3. Close one gap per cycle: backend + tests + governance docs (+ UI if inventory marks Partial/Gap).
4. Preserve security contract: roles, prod dual-approval, deny-path audit.
5. After implementation, user runs `gateway-agent validate` from the enhancement agent project.

## Implementation checklist

- [ ] Read design brief and gap matrix for the active cycle
- [ ] Implement minimal correct slice in gateway repo
- [ ] Update API inventory and coverage map if endpoints/UI changed
- [ ] Run focused pytest then `gateway-agent validate`
- [ ] Complete doc_sync_checklist.md items

## Validation (from enhancement agent project)

```bash
cd /path/to/gateway-enhancement-agent
TARGET_REPO=/path/to/gateway-platform gateway-agent validate
```
