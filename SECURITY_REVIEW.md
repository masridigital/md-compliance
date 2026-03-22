# Security Review Report — MD Compliance

**Date:** 2026-03-22
**Branch:** claude/upgrade-python-dockerfile-iCh9A
**Scope:** Full codebase review (post-build-fix)
**Reviewer:** Claude (Sonnet 4.6)

---

## Executive Summary

The codebase has a solid security baseline. Many findings from the prior review
(2026-03-18) have already been addressed. This review reflects the current state
after the Python / dependency upgrade and covers new findings as well as
confirming items that have been resolved.

| Severity | Count |
|----------|-------|
| CRITICAL | 0     |
| HIGH     | 1     |
| MEDIUM   | 5     |
| LOW      | 4     |

---

## Previously Reported — Now Fixed

The following issues from the 2026-03-18 review are confirmed resolved:

| # | Issue | Where Fixed |
|---|-------|------------|
| 1 | Hardcoded DB credentials in `docker-compose.yml` | `.env.example` now uses `CHANGE_ME_*` placeholders; compose references env vars |
| 2 | No security headers (CSP, HSTS, X-Frame-Options, etc.) | `configure_security_headers()` in `app/__init__.py` (line 295) adds full header set |
| 3 | No rate limiting on auth/reset endpoints | Flask-Limiter applied on `post_login`, `reset_password_request`, `post_register` |
| 4 | Path traversal in `/projects/<pid>/reports/<path:filename>` | `os.path.basename()` + `os.path.realpath()` guard added (`app/main/views.py` lines 28–31) |
| 5 | No file upload extension validation in `save_file()` | Allowlist check added (`app/models.py` lines 1615–1624) |
| 6 | Open redirect via `?next=` parameter | `_safe_next()` validates `netloc == ""` (`app/auth/views.py` lines 20–24) |
| 7 | Raw DB error details exposed to users | `handle_db_exceptions` conditionally redacts error in non-DEBUG mode (`app/__init__.py` lines 237–243) |
| 8 | No `MAX_CONTENT_LENGTH` (DoS via large upload) | Set to 16 MB in `config.py` line 94 |
| 9 | Weak `SECRET_KEY` default shipped to production | `ProductionConfig` raises `RuntimeError` if key is missing or matches the insecure default |
| 10 | Debug `print(data)` in vendor risk update route | Removed from `app/api_v1/vendors.py` (this review) |

---

## High Findings

### H-1: Dead Code Shadows Active Security Header Configuration

**File:** `app/__init__.py` — lines 49–63 vs lines 295–317
**Severity:** HIGH

`configure_security_headers` is defined **twice** in the same module. In Python,
the second definition replaces the first before `create_app` is ever called.
The first definition (lines 49–63) is therefore **dead code** — it is never
executed. However, it contains a critically different behaviour:

- **First definition (dead):** Sets `X-Frame-Options: SAMEORIGIN` and applies
  HSTS only when `SCHEME == "https"` (scheme-aware).
- **Second definition (active):** Sets `X-Frame-Options: DENY`, includes a
  full CSP, and applies HSTS whenever `DEBUG` is falsy — regardless of whether
  HTTPS is actually in use.

Additionally, `create_app` calls `configure_security_headers(app)` on both
line 37 and line 38, registering the `after_request` handler **twice**. This
causes every response to execute the header-setting function twice (redundant
but not harmful by itself).

The real risk: the dead first definition's scheme-aware HSTS logic never runs,
so a deployment running HTTP behind a proxy that has not set SCHEME correctly
will emit an HSTS header (`max-age=31536000`) on a non-TLS connection, which
will make the site unreachable over HTTP for up to a year for any browser that
cached it.

**Fix:**
1. Remove the first `configure_security_headers` definition entirely (lines 49–63).
2. Remove the duplicate call on line 38 so it is called exactly once on line 37.
3. In the remaining function, gate HSTS on `SCHEME == "https"` as the original
   intent was:

```python
if app.config.get("SCHEME") == "https":
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
```

---

## Medium Findings

### M-1: CSP Allows `unsafe-inline` for Scripts and Styles

**File:** `app/__init__.py` — line 302–311
**Severity:** MEDIUM

```python
"script-src 'self' 'unsafe-inline'; "
"style-src 'self' 'unsafe-inline'; "
```

`'unsafe-inline'` permits inline `<script>` and `<style>` blocks, which
significantly weakens XSS protection. Any reflected or stored XSS that injects
an inline script will bypass this CSP.

**Fix:** Replace inline scripts/styles with external files and use a nonce or
hash-based CSP. Minimum: remove `'unsafe-inline'` from `script-src`. A nonce
approach with Flask-Talisman is the cleanest path.

---

### M-2: MCP Rate Limiter Uses In-Memory Store (Not Safe for Multi-Worker/Restart)

**File:** `app/masri/mcp_server.py` — lines 88–125
**Severity:** MEDIUM

The per-key rate limiter stores timestamps in a module-level dict:

```python
_rate_counters: dict = {}  # key_id -> list[float]
```

This is noted in a comment but not mitigated. In a multi-worker Gunicorn
deployment (the default in docker-compose sets `GUNICORN_WORKERS=2`) each
worker has its own memory space, so each worker enforces limits independently.
A client can make `rate_limit × num_workers` requests per minute before being
blocked. On restart all limits reset.

**Fix:** Use the Flask-Limiter instance (which uses in-memory storage by default
but can be backed by Redis) instead of the custom counter:

```python
from app import limiter
# Apply @limiter.limit(...) to the route decorators instead.
```

Or configure `RATELIMIT_STORAGE_URI=redis://...` for the Flask-Limiter
instance and reuse it throughout.

---

### M-3: Microsoft OAuth Uses `/common` Endpoint (Any Azure Tenant Can Authenticate)

**File:** `app/__init__.py` — lines 96–106
**Severity:** MEDIUM

The Microsoft OAuth registration uses the `common` endpoint:

```python
authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
access_token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
```

This allows users from **any** Azure AD tenant to initiate authentication.
Unless multi-tenant access is intentional, this is a misconfiguration.

**Fix:** If single-tenant, replace `common` with `{ENTRA_TENANT_ID}`:

```python
authorize_url=f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize",
access_token_url=f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
```

If multi-tenant is intentional, add a post-authentication check that validates
the `tid` claim in the token matches an allowlisted tenant.

---

### M-4: Default Admin Credentials Documented in README

**File:** `README.md` — Quick Start › Log in table
**Severity:** MEDIUM

The README documents default login credentials:

```
Email:    admin@example.com
Password: admin1234567
```

If a user runs `docker compose up -d` without setting `DEFAULT_PASSWORD` in
their `.env`, they may end up with a live instance accessible with these known
defaults. Even with a "change immediately" warning, this is a meaningful risk
for public-facing deployments.

**Fix:** Remove the hardcoded example password from the README table. Instead
instruct users to check `.env` for the `DEFAULT_PASSWORD` they set, or generate
a random default in the `setup.sh` wizard:

```bash
DEFAULT_PASSWORD=$(python3 -c "import secrets, string; print(''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(16)))")
```

---

### M-5: Ollama Integration Defaults to HTTP (MITM Risk for Non-Localhost)

**File:** `app/masri/new_models.py` — `SettingsLLM.ollama_base_url`
**Severity:** MEDIUM

The default Ollama base URL is `http://localhost:11434`. When administrators
configure a remote Ollama instance (e.g. a GPU server on the network), they
are likely to type an HTTP URL, exposing LLM prompts and responses — which
contain client compliance data — to network interception.

**Fix:** Add a validation that warns or blocks HTTP URLs for non-localhost hosts
at the settings layer. Example check in `SettingsService.update_llm_config()`:

```python
if provider == "ollama":
    url = data.get("ollama_base_url", "")
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Ollama must be configured with HTTPS for non-localhost hosts")
```

---

## Low Findings

### L-1: `innerHTML` Assignments in Client-Side JavaScript

**File:** `app/static/js/field-transformers.js` — lines 49, 83, 221+
**File:** `app/static/js/common.js` — various
**Severity:** LOW

Multiple `.innerHTML` assignments exist in the front-end JavaScript. When
content is sourced from static data this is benign, but if any of these paths
are updated to include user-controlled input the risk escalates to stored XSS.

**Fix:** Audit each `.innerHTML` usage. Replace with `.textContent` where the
value is plain text. Where HTML rendering is genuinely needed, sanitize with
DOMPurify before assignment.

---

### L-2: Non-Cryptographic `random` Module in Risk Display

**File:** `app/models.py`
**Severity:** LOW

`random.randint()` is used to produce a display value for risk scoring. This is
non-security-critical, but mixing `random` and `secrets` throughout a security
platform creates an inconsistency that is worth flagging to avoid future
developers reusing the pattern in a sensitive context.

**Fix:** Use `secrets.randbelow(n)` for consistency. Document clearly in a
comment that the value is non-sensitive.

---

### L-3: `WTF_CSRF_ENABLED` Not Set in `TestingConfig` (Falls Back to Base Default)

**File:** `config.py` — `TestingConfig`
**Severity:** LOW

`TestingConfig` sets `WTF_CSRF_ENABLED = True`, which is correct. However the
base `Config` class does not set this key at all, meaning any test that runs
without a CSRF token will fail. This is the right security posture, but it
should be explicitly documented to avoid future developers disabling CSRF in
tests to make them pass.

**Recommendation:** Add a comment in `TestingConfig` noting that CSRF is
intentionally kept on and that Flask-WTF provides `WTFCSRFTest` mixin for
proper CSRF-aware testing.

---

### L-4: Session Cookie `REMEMBER_COOKIE_SECURE = False` in Base Config

**File:** `config.py` — line 63
**Severity:** LOW

```python
REMEMBER_COOKIE_SECURE = False  # overridden in ProductionConfig
```

This is correctly overridden in `ProductionConfig`. However, if a developer
accidentally runs the app via a non-standard config name that resolves to the
base `Config` rather than `ProductionConfig`, the remember-me cookie will be
sent over HTTP.

**Recommendation:** Default `REMEMBER_COOKIE_SECURE = True` in the base `Config`
and only set it to `False` explicitly in `DevelopmentConfig`/`TestingConfig`
where HTTP is expected.

---

## Summary of Recommended Actions (Priority Order)

| Priority | Action | File |
|----------|--------|------|
| 1 | Remove duplicate `configure_security_headers` definition and registration; fix scheme-aware HSTS | `app/__init__.py` |
| 2 | Tighten CSP — remove `unsafe-inline` from `script-src` | `app/__init__.py` |
| 3 | Replace in-memory MCP rate limiter with Flask-Limiter | `app/masri/mcp_server.py` |
| 4 | Lock Microsoft OAuth to specific tenant or validate `tid` claim | `app/__init__.py` |
| 5 | Remove hardcoded default credentials from README | `README.md` |
| 6 | Validate Ollama URL scheme before saving non-localhost HTTP | `app/masri/settings_service.py` |
| 7 | Audit and sanitize `.innerHTML` usage in JS | `app/static/js/` |
| 8 | Default `REMEMBER_COOKIE_SECURE = True` in base Config | `config.py` |

---

## Build & Dependency Fixes Applied (This Session)

The following build-blocking issues were fixed as part of this review:

| Fix | File | Detail |
|-----|------|--------|
| Python 3.9 → 3.11 | `Dockerfile` | Both `builder` and `app` stages upgraded; faster pip resolver, supported until Oct 2027 |
| Pinned Google Cloud stack | `requirements.txt` | `google-cloud-storage==2.18.2`, `google-cloud-logging==3.11.3`, `protobuf==5.26.1`, `proto-plus==1.24.0`, `grpcio==1.62.1`, `google-api-core==2.19.0`, `googleapis-common-protos==1.63.0` — eliminates 20+ minute pip backtracking |
| Added upper bounds to all `>=` deps | `requirements.txt` | e.g. `Flask>=2.3.3,<3.0`, `SQLAlchemy>=2.0.0,<3.0`, `openai>=1.30.0,<2.0` — reproducible builds |
| `.env` setup instructions | `README.md` | Quick Start now explicitly instructs `cp .env.example .env` before `docker compose up` |
| Removed `print(data)` debug statement | `app/api_v1/vendors.py` | Prevented request payload from leaking to application logs |
