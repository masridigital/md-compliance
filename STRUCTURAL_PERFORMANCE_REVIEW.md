# Structural + Performance Review (Blunt Assessment)

Date: 2026-04-14
Reviewer: GPT-5.3-Codex

## Bottom line (harsh but fair)

This codebase ships a lot of features, but the internal structure is **overgrown and fragile**.
It currently behaves like a fast-moving prototype that never got the cleanup pass.

If you keep adding features without refactoring, delivery speed will appear high short-term but reliability and debugging costs will spike hard.

---

## Measured structural signals (not opinions)

Repository scan results:

- Python files: **68**
- Python LOC: **30,512**
- Flask route handlers: **372**
- `except Exception` occurrences: **348**
- Wildcard imports (`import *`): **5**

Largest hotspots:

- `app/models.py`: **5,162 lines**, 48 classes, 305 defs
- `app/masri/llm_routes.py`: **2,325 lines**
- `app/masri/settings_routes.py`: **2,170 lines**, 81 defs
- `app/api_v1/views.py`: **1,433 lines**, 95 defs
- `app/masri/mcp_server.py`: **1,184 lines**

This is textbook “god-file” architecture and it is the primary reason maintainability is degrading.

---

## Structural issues and how to fix them

## 1) God files / no bounded contexts

### Problem
Core modules mix transport, business logic, DB writes, validation, and response shaping in the same files.

### Why this hurts
- High change-collision risk (many contributors touch same files)
- Hard to test single behaviors in isolation
- Slow code review and high regressions

### Fix
- Split by bounded context with explicit layers:
  - `routes/` (HTTP only)
  - `services/` (business logic)
  - `repositories/` (query + persistence)
  - `schemas/` (input/output contracts)
- Start with these files first:
  1. `app/masri/settings_routes.py`
  2. `app/masri/llm_routes.py`
  3. `app/api_v1/views.py`
  4. `app/models.py` (extract domain services + query objects)

---

## 2) Exception handling strategy is masking defects

### Problem
`except Exception` is used everywhere, frequently with generic fallbacks.

### Why this hurts
- Real faults are hidden
- You lose root-cause visibility in production
- Security-sensitive flows may silently degrade

### Fix
- Define exception taxonomy (`DomainError`, `IntegrationError`, `AuthError`, `ValidationError`).
- Catch only expected exceptions at boundaries.
- Route handlers map known exceptions to HTTP responses; unknown exceptions should be logged and surfaced as 500 with trace IDs.

---

## 3) Route handlers are doing too much work

### Problem
Many handlers contain orchestration + business rules + DB access + integration calls in one place.

### Why this hurts
- Request latency grows unpredictably
- Impossible to reason about side effects
- Poor reuse across APIs/scheduler/jobs

### Fix
- Move logic into service layer:
  - `SettingsService`, `LLMService`, `RiskService`, `EvidenceService`, `IntegrationSyncService`
- Keep handlers thin: parse -> authorize -> call service -> serialize.

---

## 4) Data/model layer is oversized and tightly coupled to Flask globals

### Problem
`models.py` is huge and includes many cross-domain behaviors, app globals, email logic, file logic.

### Why this hurts
- ORM objects carry side effects and integration concerns
- Increased DB/session coupling and hidden I/O

### Fix
- Keep models mostly state + invariants.
- Move side effects (email, files, external APIs, heavy computed workflows) into domain services.
- Introduce query modules for read patterns (`queries/project_queries.py`, etc.).

---

## 5) Wildcard imports and namespace leakage

### Problem
`from app.models import *` appears in API/auth/utils and tooling.

### Why this hurts
- Hidden dependencies (sometimes relying on names pulled in indirectly)
- Breaks static analysis precision

### Fix
- Replace with explicit imports or `import app.models as models`.
- Enforce lint rule to block new wildcard imports.

---

## 6) Startup path is overloaded and risky

### Problem
App bootstrap does too much: optional tasks, mutable DB schema checks, auth/session policy, etc.

### Why this hurts
- Hard startup debugging
- Non-deterministic boot behavior across environments

### Fix
- Startup should only validate dependencies/config and initialize extensions.
- Move schema changes strictly to migrations.
- Background warmups should be separate jobs with health checks.

---

## 7) Test architecture is not reliable enough for rapid iteration

### Problem
Pytest can be broken by non-test scripts and DB config mismatches.

### Why this hurts
- CI signal cannot be trusted
- Developers become afraid to refactor

### Fix
- Force pytest discovery to `tests/` only.
- Separate test config from runtime config completely.
- Add smoke tests for app factory, migrations, and auth/session paths.

---

## 8) Performance risks that likely affect load time / responsiveness

### Problem areas
- Heavy request handlers (LLM/integration orchestration in request context)
- Potential N+1 query patterns from mixed ORM access patterns
- Very large template/pages and route modules
- High per-request overhead from scattered checks

### Likely symptoms
- Slow page loads on data-heavy views
- API p95 latency spikes during integration/LLM operations
- Worker starvation under burst traffic

### Fixes (practical)
1. **Push all long-running LLM/integration work to async jobs** (Celery/Redis) and return job IDs.
2. **Instrument query counts and latency** per endpoint (OpenTelemetry or SQLAlchemy event hooks).
3. **Add caching** for expensive read endpoints (tenant/project summaries).
4. **Use eager loading** (`selectinload/joinedload`) for known relational fetches.
5. **Paginate aggressively** on list endpoints and UI tables.
6. **Set response compression and cache headers** for static/template payloads.

---

## 9) Concrete re-organization blueprint

Target layout:

```text
app/
  api/
    routes/
      auth.py
      tenants.py
      projects.py
      controls.py
      evidence.py
      settings.py
      integrations.py
    schemas/
    presenters/
  domain/
    services/
      llm_service.py
      settings_service.py
      risk_service.py
      evidence_service.py
      integration_sync_service.py
    policies/
    exceptions.py
  data/
    models/
    repositories/
    queries/
  workers/
    tasks/
  web/
    templates/
    static/
```

This gives you clear ownership boundaries and lowers accidental coupling.

---

## 10) 30-day hard reset plan (if you want this codebase to scale)

### Week 1 — Stabilize
- Fix migration/runtime blockers and pytest discovery/config.
- Remove startup DDL mutation.
- Add baseline telemetry (request time, query count, exception rate).

### Week 2 — Split hot route files
- Extract services from `settings_routes`, `llm_routes`, `api_v1/views`.
- Add contract tests around extracted services.

### Week 3 — Model/domain cleanup
- Move side effects out of models.
- Introduce repositories/query objects for heavy reads.

### Week 4 — Performance pass
- Add async boundaries for long-running jobs.
- Apply eager loading + pagination + selective caching.
- Run before/after benchmarks and lock SLOs.

---

## 11) “Harsh feedback” summary for Claude-generated code

- Too many giant files: fast to generate, expensive to maintain.
- Too many broad exception blocks: problems are hidden, not solved.
- Too many fat handlers: HTTP layer became business layer.
- Too much implicit magic (`import *`, side-effect imports): hard to reason about correctness.

None of this means the product is bad. It means the code now needs an explicit architecture phase before adding more surface area.

---

## 12) Commands used for this structural assessment

```bash
python -m pytest -q
ruff check .
python - <<'PY'
# metrics: file counts, route counts, exception counts, star imports, hotspots
PY
sed -n '1,220p' run.sh
sed -n '1,220p' Dockerfile
sed -n '1,220p' docker-compose.yml
```
