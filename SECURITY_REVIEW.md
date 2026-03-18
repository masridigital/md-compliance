# Security Review Report - MD Compliance

**Date:** 2026-03-18
**Branch:** claude/security-review-U8PnZ
**Scope:** Full codebase review

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 2 |
| HIGH     | 3 |
| MEDIUM   | 10 |
| LOW      | 5 |

---

## Critical Findings

### 1. Hardcoded Default Secrets
**File:** `config.py` (lines 53, 72, 123)
**Severity:** CRITICAL

Weak, hardcoded default values for sensitive configuration:
- `SECRET_KEY = "change_secret_key"` — compromises session security if deployed as-is
- `DEFAULT_PASSWORD = "admin1234567"` — weak hardcoded default password
- `INTEGRATIONS_TOKEN = "changeme"` — placeholder secret exposed

**Fix:** Use strong randomly generated secrets from environment variables only. Never set insecure defaults.

---

### 2. Hardcoded Credentials in docker-compose.yml
**File:** `docker-compose.yml` (lines 30, 49–50)
**Severity:** CRITICAL

Default PostgreSQL credentials (`db1:db1`) and `SECRET_KEY = "change_secret_key"` hardcoded in compose file.

**Fix:** Remove all hardcoded credentials. Reference environment variables without defaults.

---

## High Findings

### 3. Path Traversal Vulnerability Risk
**File:** `app/main/views.py` (lines 19–25)
**Severity:** HIGH

The `/projects/<pid>/reports/<path:filename>` route uses `<path:filename>` (which allows slashes) without explicit path validation, potentially allowing `../../../etc/passwd` style traversal.

```python
# Current (vulnerable)
return send_from_directory(directory=UPLOAD_FOLDER, path=filename, as_attachment=True)

# Fix
import os
safe_name = os.path.basename(filename)
target = os.path.realpath(os.path.join(UPLOAD_FOLDER, safe_name))
if not target.startswith(os.path.realpath(UPLOAD_FOLDER)):
    abort(403)
```

---

### 4. Missing File Upload Validation
**File:** `app/models.py` (lines 1590–1620)
**Severity:** HIGH

`save_file()` does not validate uploaded file extensions against `UPLOAD_EXTENSIONS` config, allowing potentially dangerous file types.

**Fix:**
```python
allowed = current_app.config.get("UPLOAD_EXTENSIONS", [".csv", ".jpg", ".png", ".pdf"])
ext = os.path.splitext(file_name)[1].lower()
if ext not in allowed:
    abort(400, f"File type {ext} not allowed")
```

---

### 5. Incomplete API Authentication
**File:** `app/api_v1/` (throughout)
**Severity:** HIGH

Some API endpoints rely solely on `@login_required` with an optional token header fallback. No formal API key management for machine-to-machine access.

**Fix:** Implement proper API key/token management with separate tokens for programmatic access and enforce authentication on all API routes.

---

## Medium Findings

### 6. Open Redirect via Unvalidated `next` Parameter
**File:** `app/auth/views.py` (lines 25, 28, 53, 108, 160)
**Severity:** MEDIUM

```python
next_page = request.args.get("next")
return redirect(next_page or url_for("main.home"))  # Can redirect to external URL
```

**Fix:**
```python
from urllib.parse import urlparse
next_page = request.args.get("next")
if next_page:
    parsed = urlparse(next_page)
    if parsed.netloc:  # External URL — reject it
        next_page = None
return redirect(next_page or url_for("main.home"))
```

---

### 7. CSRF Disabled in Test Config
**File:** `config.py` (line 224)
**Severity:** MEDIUM

`WTF_CSRF_ENABLED = False` in `TestingConfig`. If testing config is accidentally used in production, CSRF protection is disabled.

**Fix:** Keep CSRF enabled in tests; use Flask-WTF testing utilities instead.

---

### 8. Database Error Details Exposed to Users
**File:** `app/__init__.py` (lines 207–222)
**Severity:** MEDIUM

```python
error = str(e.orig)  # Raw DB error exposed to user
```

**Fix:**
```python
if app.config.get("DEBUG"):
    error = str(e.orig)
else:
    error = "An internal error occurred"
```

---

### 9. Missing Security Headers
**File:** `app/__init__.py`
**Severity:** MEDIUM

No `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Content-Security-Policy`, or `Strict-Transport-Security` headers detected.

**Fix:**
```python
@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response
```

---

### 10. Outdated Dependencies
**File:** `requirements.txt`
**Severity:** MEDIUM

- `Flask==2.2.5` (2023)
- `Werkzeug==2.3.0` (2023)
- `Jinja2==3.0.3` (2021)
- `SQLAlchemy==1.3.20` (2019 — significantly outdated)

**Fix:** Update to current versions:
```
Flask>=3.0.0
Werkzeug>=3.0.0
SQLAlchemy>=2.0.0
Jinja2>=3.1.0
```

---

### 11. No Rate Limiting on Authentication Endpoints
**File:** Entire application
**Severity:** MEDIUM

No rate limiting detected on login, password reset, or registration endpoints — vulnerable to brute force attacks.

**Fix:** Implement Flask-Limiter:
```python
from flask_limiter import Limiter
limiter = Limiter(app, key_func=get_remote_address)
limiter.limit("5 per minute")(login_view)
```

---

### 12. Missing Request/Upload Size Limits
**File:** `app/__init__.py`
**Severity:** MEDIUM

No `MAX_CONTENT_LENGTH` configured — vulnerable to DoS via large uploads.

**Fix:**
```python
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
```

---

### 13. Insecure OAuth Multi-Tenant Endpoint
**File:** `app/__init__.py` (lines 72–82)
**Severity:** MEDIUM

Microsoft OAuth uses the `common` endpoint, which allows any Azure tenant to authenticate. If single-tenant is intended, this is a misconfiguration.

**Fix:** Use your specific tenant ID endpoint or add post-auth tenant validation if multi-tenant is intentional.

---

### 14. Insecure HTTP Default for Ollama
**File:** `app/masri/new_models.py` (line 196)
**Severity:** MEDIUM

```python
ollama_base_url = db.Column(db.String, default="http://localhost:11434")
```

Defaults to HTTP. Non-localhost connections over HTTP are vulnerable to MITM.

**Fix:** Default to HTTPS or warn/block when HTTP is used for non-localhost hosts.

---

### 15. Debug Print Statement in Auth Flow
**File:** `app/auth/views.py` (line 44)
**Severity:** MEDIUM

```python
print(current_app.is_email_configured)
```

Leaks internal application state to logs.

**Fix:** Remove the print statement or replace with `app.logger.debug(...)`.

---

## Low Findings

### 16. `random` Module Used Instead of `secrets`
**File:** `app/models.py` (line 297)
**Severity:** LOW

`random.randint(0, 101)` used for a risk display value. While not security-critical here, inconsistent randomness practices can be risky.

**Fix:** Use `secrets.randbelow(102)` for consistency, or document clearly that this value is non-security-sensitive.

---

### 17. JSON Parsing Without Schema Validation
**File:** `app/masri/llm_service.py` (line 418)
**Severity:** LOW

```python
parsed = json.loads(content)  # No schema validation on LLM response
```

Unexpected LLM response structure could cause downstream issues.

**Fix:** Validate parsed JSON against an expected schema using `jsonschema`.

---

### 18. `innerHTML` Usage in JavaScript
**File:** `app/static/js/field-transformers.js` (lines 49, 83, 221+)
**Severity:** LOW

`.innerHTML` assignments exist throughout client-side JS. Low risk when content is static, but dangerous if dynamic user data is inserted without sanitization.

**Fix:** Use `textContent` for plain text values; sanitize before using `innerHTML` with dynamic data.

---

### 19. SQL Injection — Low Risk (SQLAlchemy Usage)
**File:** `app/models.py` (throughout)
**Severity:** LOW

The codebase generally uses SQLAlchemy ORM which parameterizes queries. No raw string-concatenated SQL queries found during review.

**Recommendation:** Continue using ORM exclusively. Never use string concatenation for SQL queries.

---

### 20. Weak Example Password in `.env.example`
**File:** `.env.example` (line 37)
**Severity:** LOW

`DEFAULT_PASSWORD=admin1234567` shown as example.

**Fix:** Document password requirements explicitly and generate a strong random password in `.env`.

---

## Immediate Actions Required (Priority Order)

1. **Rotate all default secrets** — Generate strong random values for `SECRET_KEY`, `DEFAULT_PASSWORD`, `INTEGRATIONS_TOKEN`
2. **Update dependencies** — Especially SQLAlchemy 1.3 → 2.0+
3. **Add security headers** — Implement all standard HTTP security headers
4. **Implement rate limiting** — Protect authentication endpoints
5. **Add upload size limits** — Set `MAX_CONTENT_LENGTH`
6. **Validate file uploads** — Enforce strict extension checking in `save_file()`
7. **Fix open redirect** — Validate `next` parameter against netloc
8. **Fix path traversal** — Canonicalize and validate file paths in download endpoint
9. **Remove debug code** — Remove `print()` from auth flow
10. **Sanitize error messages** — Never expose raw DB errors outside DEBUG mode
