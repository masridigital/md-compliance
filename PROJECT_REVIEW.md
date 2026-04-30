# Product Review & Recommendations (April 30, 2026)

## What is working well
- Strong breadth of compliance functionality (frameworks, evidence, risks, reports, and integrations).
- Good modular separation in `app/services`, `app/masri`, and `app/api_v1`.
- Existing security baseline includes CSRF protection, rate limiting, and secret-key validation.
- Automated tests exist for several critical surfaces (encryption, settings API, Entra routes, models).

## Key issues observed
1. **Test fragility across database backends**
   - SQLAlchemy engine options were globally applied in a way that can break SQLite test runs.
   - This causes `pytest` collection failures in environments that default to SQLite.

2. **Architecture/documentation drift risk**
   - README claims `app/models.py` monolith, but code uses `app/models/*.py` split modules.
   - Drift makes onboarding and troubleshooting harder.

3. **Startup path complexity in app factory**
   - `create_app` and startup helpers in `app/__init__.py` perform many side-effectful operations.
   - A failure-is-nonfatal strategy helps uptime, but hidden startup errors can become silent reliability issues.

4. **Potential operations risk in auto-DDL at runtime**
   - `_ensure_db_columns` mutates schema at boot time.
   - Useful for emergency compatibility, but can diverge from Alembic migration history and complicate rollback.

## High-impact recommendations

### 1) Reliability & Testing
- Keep backend-specific DB config strictly scoped by dialect/environment.
- Add CI matrix for `testing` with PostgreSQL and SQLite to catch regressions.
- Add `pytest.ini` with explicit test paths and naming patterns to avoid accidental collection of utility scripts.

### 2) Security hardening
- Add CSP and stricter security headers (including HSTS in prod behind TLS).
- Add secret scanning and dependency vulnerability scanning in CI.
- Add audit logging for sensitive setting changes (LLM providers, storage credentials, auth config).

### 3) Product quality and UX
- Add a health dashboard for integration freshness, last successful sync, queue depth, and error rates.
- Add per-control evidence confidence and freshness badges in UI.
- Add “explainability” breadcrumbs for AI mapping decisions (source finding → control mapping rationale).

### 4) Performance & operations
- Instrument critical endpoints with request timing and DB query count telemetry.
- Move long-running background jobs to Celery workers consistently (if not already fully migrated).
- Add retry/backoff + circuit breaker patterns for external integrations.

### 5) Data governance
- Add configurable data retention and purge policies by tenant.
- Add export package containing evidence/provenance trail for audits.
- Add immutable event timeline for risk/evidence/control status changes.

## Suggested 90-day roadmap
- **Weeks 1–2:** Stabilize test config + CI matrix + explicit pytest collection rules.
- **Weeks 3–4:** Observability (metrics/logging/error budgets) and integration health dashboard.
- **Weeks 5–8:** AI explainability + evidence freshness UX improvements.
- **Weeks 9–12:** Governance features (retention, audit trail exports, immutable timelines).
