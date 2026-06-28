# Architecture Best Practices Review

This document records how the Gateway Enhancement Agent aligns with **security**, **cloud engineering**, **CISO**, **agentic**, **parallelism**, **component-driven**, and **microservices** practices.

Related: [DESIGN.md](DESIGN.md) · [DISCLAIMER.md](DISCLAIMER.md)

---

## Executive summary

| Lens | Status | Mechanism |
|------|--------|-----------|
| Security / Security Engineer | ✅ Enforced | Guardrails, review subagent, validation gates, path allowlists |
| Audit Architect | ✅ Enforced | Review subagent, AGENTS.md contract, governance checklist |
| CISO | ✅ Enforced | Review subagent, risk register path hints, autonomous rollback |
| Cloud Engineer | ✅ Enforced | Review subagent, deploy/observability focus, LaunchAgent ops |
| AWS Engineer | ⚠️ Optional | Via target repo gates; enable in `role_lenses.json` when AWS-heavy |
| AI Architect | ✅ Enforced | Local Ollama only, synthesizer merge, no cloud LLM dependency |
| Agentic best practices | ✅ Enforced | Phased SDLC, artifacts, idempotent backlog, guardrailed autonomy |
| Parallelism | ✅ Enforced | Implement + review worker pools, synthesizer merge |
| Component-driven | ✅ Enforced | `components.json` ownership map per worker |
| Microservices | ✅ Guided | Extract only on documented triggers; default monolith slice |

---

## 1. Agentic best practices

### Observed patterns (aligned)

| Practice | Implementation |
|----------|----------------|
| **Explicit phases** | discover → analyze → design → implement → validate → merge → document → release_prep |
| **Artifact trail** | Every cycle writes JSON + markdown under `artifacts/cycle-XXXX/` |
| **Idempotent backlog** | `backlog.json` tracks open → scheduled → closed without duplicate work |
| **Guardrailed autonomy** | Auto-merge only after validation + guardrails + role-lens reviews |
| **Rollback on failure** | Git restore when validation or BLOCKER reviews fail |
| **Human override** | `PARALLEL_IMPLEMENT=0`, `AGENT_FULLY_AUTONOMOUS=0`, `make validate` |
| **Observability** | `parallel_summary.json`, `role_lens_reviews.md`, weekly email, cycle state |

### Anti-patterns avoided

- Unbounded tool use (path allowlists, no shell execution from LLM output)
- Silent merge without validation
- Secret material in artifacts (content pattern scan)
- Single monolithic prompt for unrelated concerns (parallel workers)

---

## 2. Parallelism architecture

```
Phase A — Implement (parallel)
  backend_contract │ backend_tests │ frontend_ui │ governance_docs
                   └───────┬───────┘
                           ▼
                  Synthesizer merge
                           ▼
Phase B — Security guardrails (deterministic)
                           ▼
Phase C — Role-lens review (parallel, read-only)
  security_architect │ audit_architect │ ciso_lens │ cloud_engineer
                           ▼
Phase D — Apply patches (if no BLOCKER)
                           ▼
Phase E — Validate + autonomous git merge
```

**Concurrency model:** `ThreadPoolExecutor` for I/O-bound Ollama HTTP. On single-GPU Macs, Ollama may queue requests — workers still improve **separation of concerns** and review quality.

**Merge strategy:** Non-overlapping files union; conflicts → synthesizer LLM; fallback → component priority order.

Configure: `config/parallel_workers.json`, `PARALLEL_MAX_WORKERS`.

---

## 3. Component-driven architecture

Components are defined in `config/components.json`:

| Component | Owns | Microservice candidate |
|-----------|------|------------------------|
| `gateway-router` | `gateway.py`, services | No (core monolith) |
| `gateway-authz-audit` | middleware, audit, security docs | No (cross-cutting) |
| `gateway-operator-ui` | frontend views, app.js | No |
| `gateway-governance` | governance markdown | No |
| `gateway-validation` | tests, scripts | No |
| `gateway-orchestration` | orchestration router + UI | **Yes** (when triggers met) |

Each implement worker declares `"component": "..."` so prompts stay within ownership boundaries.

**Rule:** One SDLC cycle = one component slice + governance sync, not repo-wide refactors.

---

## 4. Microservices — when required

### Default: monolith enhancement

The agent patches `TARGET_REPO` in-place. This matches the current gateway platform (single deployable unit with router + operator UI).

### Extract a microservice only when ALL apply

From `components.json` → `microservice_triggers`:

1. Independent scaling (CPU/GPU/memory) with a **stable API boundary**
2. CISO-mandated blast-radius isolation
3. Team ownership split with API inventory contract
4. Regulatory audit domain separation

### Before extraction, agent must produce

- API inventory entry for the new service
- Observability + rollback plan (Cloud Engineer review APPROVE)
- Dual-approval / authz parity (Security Architect APPROVE)
- Residual risk register update (CISO APPROVE)

### Anti-patterns (blocked by design)

- Splitting synchronous operator CRUD without caching strategy
- Network hop without governance doc
- Extraction before contract is marked stable in inventory

The **cloud_engineer** review subagent explicitly checks microservice necessity against these triggers.

---

## 5. Security architecture

### Deterministic guardrails (`security_guardrails.py`)

- Blocked paths: `.env`, `.pem`, `secrets/`, credentials
- Blocked content: AWS keys, private keys, inline passwords
- Max file size cap
- Warnings on privileged paths (`gateway.py`, risk register)

### Role-lens review gate

Review workers output `APPROVE` or `BLOCKER`. Any `BLOCKER` prevents patch apply.

Mandatory lenses (see `config/role_lenses.json`):

- security_architect
- audit_architect
- ciso_lens
- security_engineer (via backend_tests worker)

### Target repo gates (`validation_gates.json`)

- Frontend syntax + security smoke
- Control coverage
- Gateway pytest subset

### Autonomous git (`autonomous.json`)

- Excludes `.env`, `.runtime/`, `artifacts/` from commits
- Rollback on validation failure
- Feature branch `agent/cycle-XXXX` → merge target branch

---

## 6. CISO lens

| Control | Agent behavior |
|---------|----------------|
| Blast radius | One gap per cycle; single component scope |
| Residual risk | `residual-and-accepted-risk-register.md` in governance worker path hints |
| Go/no-go | CISO review subagent verdict in `role_lens_reviews.md` |
| Accepted risk | Must be documented before deferring gap (backlog `deferred` status) |
| Autonomous merge | Blocked on BLOCKER reviews or validation failure |

Weekly email to operator provides trend visibility (open gaps, merge count, failures).

---

## 7. Cloud engineering lens

| Concern | Agent behavior |
|---------|----------------|
| **Deployability** | cloud_engineer review subagent; no change to CI without validation gates passing |
| **Rollback** | `rollback_on_validation_failure` in git automation |
| **Observability** | Artifacts + logs in Application Support; weekly summary email |
| **Scheduling** | LaunchAgent with KeepAlive; separate weekly email plist |
| **Secrets** | SMTP via env only; never committed; guardrails scan patches |
| **Local runtime** | Ollama on Mac Metal GPU; no cloud inference dependency for agent itself |
| **Mirror** | Governance mirror for launchd-safe reads from Desktop paths |

Email is the only routine outbound network call (operator-configured SMTP).

---

## 8. Configuration reference

| File | Purpose |
|------|---------|
| `config/parallel_workers.json` | Implement + review workers, components, stages |
| `config/components.json` | Component boundaries + microservice triggers |
| `config/role_lenses.json` | Mandatory role lenses from AGENTS.md |
| `config/security_guardrails.json` | Pre-apply patch scanning |
| `config/autonomous.json` | Git merge + push policy |
| `config/validation_gates.json` | Target repo quality gates |

Environment overrides: `PARALLEL_IMPLEMENT`, `AGENT_FULLY_AUTONOMOUS`, `AGENT_AUTO_PUSH`, `WEEKLY_EMAIL_*`, `SMTP_*`.

---

## 9. Gaps and recommended next steps

| Gap | Recommendation |
|-----|----------------|
| AWS-specific worker not default | Enable `aws_engineer` review worker when IAM/STS changes are frequent |
| Ollama GPU queue | Acceptable on Mac; optional second machine for worker parallelism |
| Full pytest in background launchd | Intentionally skipped; autonomous mode runs validate before merge |
| Cross-repo microservice codegen | Out of scope until service contract exists in governance |

---

## 10. Verification checklist

Before marking an agent enhancement complete:

- [ ] All mandatory role-lens review subagents ran (or documented skip)
- [ ] `parallel_summary.json` shows `guardrail_passed: true`
- [ ] No `review_blockers` in summary
- [ ] `make validate` passes in foreground after cycle
- [ ] Component ownership respected (no files outside worker component paths)
- [ ] Governance docs updated when inventory behavior changed
- [ ] Microservice extraction not proposed unless triggers in `components.json` met
