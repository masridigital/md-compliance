# Security Policy

## Reporting Vulnerabilities

Please report security vulnerabilities to **security@masridigital.com**.

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We will acknowledge receipt within 24 hours and provide a timeline for resolution.

## Security Measures

- All credentials encrypted at rest using Fernet (PBKDF2-HMAC-SHA256, 260K iterations)
- Tenant-level authorization enforced on all data endpoints
- Rate limiting: 2000 requests/day, 500/hour per IP
- API keys, tokens, passwords redacted from application logs
- HTTPS enforced via Let's Encrypt with HSTS headers
- Session management with server boot stamp + 30-minute inactivity timeout
- TOTP 2FA support for non-SSO accounts
- Content Security Policy headers on all responses
- No raw exception details exposed to clients

## Responsible Disclosure

We follow responsible disclosure practices. Please do not publicly disclose vulnerabilities until we have had an opportunity to address them.

---

*Masri Digital LLC — [masridigital.com](https://masridigital.com)*
