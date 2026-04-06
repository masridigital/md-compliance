# MD Compliance — Integration Reference

> Integration methodology, current integration specs, and coming-soon integration plans.

---

## Integration Methodology (Template for ALL Integrations)

When adding any new integration, follow this exact methodology. Each integration goes through the same pipeline stages.

### Stage 1: Data Collection Layer
Every integration MUST have:
- **Client class** (`app/masri/{name}_integration.py`): API client with `_request()` helper, auth, timeouts (30s default)
- **Routes blueprint** (`app/masri/{name}_routes.py`): Flask endpoints for test, list, get, download
- **Credential storage**: Encrypted via `SettingsStorage` or dedicated model (e.g., `SettingsEntra`)
- **Credential chain**: DB → raw SQL fallback → env var (3-tier fallback)
- **collect_all_data() method**: Single method that gathers ALL data from the integration in one call
- **Cache-first reads**: Page loads NEVER call external APIs. Data refreshed only during:
  - Auto-process (Re-run button)
  - Manual refresh endpoint
  - Daily scheduler (every 24 hours)

### Stage 2: Data Storage
All integration data stored in `ConfigStore("tenant_integration_data_{tenant_id}")` as JSON:
```json
{
  "telivy": { ... raw Telivy data ... },
  "microsoft": { ... raw Microsoft data ... },
  "risk_profiles": { ... computed risk profiles ... },
  "_updated": "2026-03-31T12:00:00"
}
```
- Each integration owns its own key in the JSON (e.g., `"telivy"`, `"microsoft"`)
- New integrations add their own key — never overwrite others
- Cap: 35MB per tenant (allows full device inventories, detailed findings, risk profiles)

### Stage 3: LLM Analysis Pipeline (Multi-Phase)
Each integration gets its OWN LLM analysis phase with a strategically crafted prompt. Then a cross-source phase combines overlapping data.

**Pattern for each integration's LLM phase:**
1. Compress raw data into LLM-friendly text via `_compress_for_llm()`
2. Craft a system prompt that is SPECIFIC to that data source
3. Run chunked analysis: 10 controls per LLM call via `_run_chunked_llm()`
4. Context passing: batch 1 gets full data, subsequent batches get summary of previous findings

**Multi-phase execution order in `_bg_auto_process`:**
```
Phase 1: Integration A only (e.g., Telivy — external vulns)
Phase 2: Integration B only (e.g., Microsoft — internal security)
Phase N: Integration N only (each future integration gets its own phase)
Cross:   Combined analysis (only for controls where multiple sources have relevant data)
```

### Stage 4: Control Mapping + Evidence + Risks
After LLM returns JSON `{mappings, risks}`:
1. **Control mapping**: Update `ProjectControl.review_status` + `notes` with `[Auto-Mapped]` prefix
2. **Subcontrol progress**: Update `ProjectSubControl.implemented` (compliant=100%, partial=50%, non_compliant=25%)
3. **Evidence generation**: Create `ProjectEvidence` with three tiers: Complete / Partial / Draft
4. **Risk creation**: Create `RiskRegister` entries with `title_hash` dedup + `project_id`
5. **Progress sync**: `_sync_project_progress()` backfills all subcontrols + evidence

### Stage 5: Risk Profile Computation
After all integration data is collected:
1. `compute_risk_profiles(microsoft_data)` generates per-user and per-device scores
2. `generate_risk_narratives(profiles)` uses Tier 4 LLM for high-risk items (score >= 50)
3. Stored in ConfigStore alongside integration data

### Stage 6: UI Display
Each integration appears as a card on the project integrations tab:
- Summary stats row (4 boxes with key metrics)
- Clickable header to expand/collapse
- Expandable detail items with severity badges
- All data read from ConfigStore cache — no live API calls

### Adding a New Integration Checklist
When adding integration "X":
- [ ] Create `app/masri/x_integration.py` with API client class
- [ ] Create `app/masri/x_routes.py` with Flask blueprint
- [ ] Add credential storage (model or ConfigStore)
- [ ] Add `collect_all_data()` method
- [ ] Add data pull to `_bg_auto_process()` under key `"x"`
- [ ] Add `_compress_for_llm()` section for "x" data
- [ ] Add LLM Phase N with source-specific system prompt
- [ ] Update cross-source phase to include "x" correlations
- [ ] Add risk profile contributions (if applicable)
- [ ] Add UI card to `view_project.html` integrations tab
- [ ] Add settings tile to `integrations.html`
- [ ] Add to daily scheduler refresh
- [ ] Update docs with integration-specific notes
- [ ] Add required permissions/setup guide to the settings tile

---

## Current Integrations

### Integration 1: Telivy (External Vulnerability Scanning)
- **Client**: `TelivyIntegration` in `telivy_integration.py` (NOT `TelivyClient`)
- **Auth**: API key via `x-api-key` header
- **Credential chain**: DB `SettingsStorage` → raw SQL fallback → env var `TELIVY_API_KEY`
- **Data collected**: External scans, findings, risk assessments, breach data
- **Key methods**: `get_external_scan_findings(scan_id)` (NOT `get_scan_findings`), `list_external_scans()`, `get_risk_assessment()`
- **Scan mappings**: `ConfigStore("telivy_scan_mappings")` — two formats: string `{scan_id: tenant_id}` and dict `{scan_id: {tenant_id, type, org, ...}}`
- **Reports**: `?inline=true` serves PDF inline for in-app viewer
- **LLM prompt focus**: External vulnerabilities — network exposure, DNS, email spoofing, SSL/TLS, web app flaws, typosquatting, breach data

### Integration 2: Microsoft 365 (Entra ID + Defender + Intune)
- **Client**: `EntraIntegration` in `entra_integration.py` (NOT `EntraClient`)
- **Auth**: MSAL client credentials flow (OAuth 2.0)
- **Credential storage**: `SettingsEntra` model with `entra_tenant_id_enc`, `entra_client_id_enc`, `entra_client_secret_enc`
- **Platform-level**: `tenant_id=None` means platform-wide config
- **Single collection method**: `collect_all_security_data()` pulls everything
- **Data collected**:
  - Users + MFA enrollment status
  - Secure Score (overall + gap controls)
  - Defender security alerts + incidents
  - Intune managed devices (compliance, encryption)
  - Identity Protection risky users + risk detections
  - Sign-in activity (failures, anomalies, locations)
  - Conditional Access policies
  - SharePoint sites
- **Cache-first**: Page loads NEVER call Graph API — prevents throttling
- **LLM prompt focus**: Internal security posture — Secure Score gaps, Defender alerts, device compliance/encryption, MFA gaps, risky users by name, sign-in anomalies

#### Microsoft Graph API Permissions Required
Register an Azure AD App with these **Application** permissions:

| Endpoint | Permission | Used For |
|----------|-----------|----------|
| `/users` | `User.Read.All` | User inventory, account status |
| `/reports/authenticationMethods/userRegistrationDetails` | `UserAuthenticationMethod.Read.All` | MFA enrollment |
| `/identity/conditionalAccess/policies` | `Policy.Read.All` | Conditional Access audit |
| `/security/alerts_v2` | `SecurityAlert.Read.All` | Defender alerts |
| `/security/secureScores` | `SecurityEvents.Read.All` | Secure Score |
| `/security/incidents` | `SecurityIncident.Read.All` | Security incidents |
| `/deviceManagement/managedDevices` | `DeviceManagementManagedDevices.Read.All` | Intune devices |
| `/identityProtection/riskyUsers` | `IdentityRiskEvent.Read.All` | Risky users |
| `/identityProtection/riskDetections` | `IdentityRiskEvent.Read.All` | Risk events |
| `/auditLogs/signIns` | `AuditLog.Read.All` | Sign-in logs |
| `/sites` | `Sites.Read.All` | SharePoint sites |
| `/organization` | `Organization.Read.All` | Org profile |

### Integration 3: NinjaOne RMM (Endpoint Management)
- **Client**: `NinjaOneIntegration` in `ninjaone_integration.py`
- **Auth**: OAuth2 Client Credentials (client_id + client_secret, scope: `monitoring`)
- **Token endpoint**: `{instance_url}/oauth/token` (NOT under `/v2/`)
- **Region-specific base URLs**: US (`app.ninjarmm.com`), EU (`eu.ninjarmm.com`), AP (`app.ninjarmm.com.au`), CA (`ca.ninjarmm.com`)
- **API prefix**: `/v2/`
- **Credential storage**: `SettingsStorage` with `provider="ninjaone"`, encrypted config containing `client_id`, `client_secret`, `region`
- **Credential chain**: DB SettingsStorage → env vars `NINJAONE_CLIENT_ID` / `NINJAONE_CLIENT_SECRET` / `NINJAONE_REGION`
- **Org mappings**: `ConfigStore("ninjaone_org_mappings")` — JSON: `{org_id: {tenant_id, org_name}}`
- **Multi-tenant**: Single MSP-level OAuth app sees all client organizations. Devices scoped via `organizationId`.
- **Data collected**: devices (detailed), OS patches, software patches, AV status, AV threats, alerts, activities, organizations
- **Key bulk endpoints**: `/v2/queries/os-patches`, `/v2/queries/antivirus-status` (prefer over per-device calls)
- **Pagination**: Cursor-based (`pageSize` + `after` params), safety cap 5000
- **LLM prompt focus**: Endpoint compliance — patch status, AV coverage, encryption enforcement, stale devices, OS currency

### Integration 4: DefensX (Browser Security)
- **Client**: `DefensXIntegration` in `defensx_integration.py`
- **Auth**: Bearer token (`Authorization: Bearer {api_token}`)
- **Base URL**: `https://cloud.defensx.com/api/partner/v1`
- **NOTE**: DefensX does not publish a public API reference. Endpoint paths are per integration spec — may need adjustment once API access is confirmed with DefensX partner support.
- **Credential storage**: `SettingsStorage` with `provider="defensx"`, encrypted config containing `api_token`
- **Credential chain**: DB SettingsStorage → env var `DEFENSX_API_TOKEN`
- **Customer mappings**: `ConfigStore("defensx_customer_mappings")` — JSON: `{customer_id: {tenant_id, customer_name}}`
- **Multi-tenant**: Single partner token accesses all customer tenants
- **Data collected**: agent deployment status, web policy compliance, cyber resilience scores, user activity, shadow AI detection, security logs (URL visits, DNS queries, credential events, file transfers)
- **LLM prompt focus**: Browser-layer controls — web filtering, credential protection, shadow AI, DLP

### Coming Soon Integrations (Tiles Only — No Backend)
- **Blackpoint Cyber** (`ti-shield-bolt`): MDR/SOC detections, endpoint inventory, vulnerability scanning, dark web monitoring, NIST-aligned security posture rating. CompassOne HTTP Export API.
- **Keeper Security** (`ti-lock`): Password health audits, 2FA enrollment, BreachWatch dark web monitoring, PAM session logs. Admin REST API + MSP Account Management API.
- **SentinelOne** (`ti-sword`): EDR agent coverage, threat detection/mitigation, policy enforcement, endpoint compliance. Management Console REST API v2.1 with `ApiToken` auth.
