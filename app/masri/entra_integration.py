"""
Masri Digital Compliance Platform — Microsoft Entra ID (Azure AD) Integration

Provides ``EntraIntegration`` class for interacting with Microsoft Graph API:
  - User listing and profile retrieval
  - MFA status checking
  - Compliance posture assessment via directory policies

Requires ``msal`` library and a registered Azure AD app with appropriate
Graph API permissions (User.Read.All, Policy.Read.All, etc.).
"""

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


class EntraIntegration:
    """
    Microsoft Entra ID / Azure AD integration via MSAL and Graph API.

    Args:
        tenant_id: Azure AD tenant ID (directory ID)
        client_id: Registered app (client) ID
        client_secret: App client secret
    """

    GRAPH_BASE = "https://graph.microsoft.com/v1.0"
    AUTHORITY_BASE = "https://login.microsoftonline.com"

    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self._msal_app = None
        self._access_token = None
        self._token_expires_at = 0

    def _get_access_token(self) -> str:
        """Acquire an access token using client credentials flow (cached)."""
        import time

        # Return cached token if still valid (with 60s buffer)
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        try:
            import msal
        except ImportError:
            raise RuntimeError(
                "msal library is required for Entra ID integration. "
                "Install with: pip install msal"
            )

        # Reuse MSAL app across calls
        if not self._msal_app:
            authority = f"{self.AUTHORITY_BASE}/{self.tenant_id}"
            self._msal_app = msal.ConfidentialClientApplication(
                self.client_id,
                authority=authority,
                client_credential=self.client_secret,
            )

        scopes = ["https://graph.microsoft.com/.default"]
        result = self._msal_app.acquire_token_for_client(scopes=scopes)

        if "access_token" not in result:
            error = result.get("error_description", result.get("error", "Unknown"))
            raise RuntimeError(f"Failed to acquire token: {error}")

        self._access_token = result["access_token"]
        self._token_expires_at = time.time() + result.get("expires_in", 3600)
        return self._access_token

    def _graph_request(self, endpoint: str, method: str = "GET", **kwargs) -> dict:
        """Make an authenticated request to the Microsoft Graph API."""
        import requests

        token = self._get_access_token()
        url = f"{self.GRAPH_BASE}{endpoint}"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        resp = requests.request(
            method, url, headers=headers, timeout=30, **kwargs
        )

        if resp.status_code == 204:
            return {}

        if not resp.ok:
            logger.error(
                "Graph API %s %s returned %s: %s",
                method, endpoint, resp.status_code, resp.text[:500],
            )
            raise RuntimeError(
                f"Graph API error {resp.status_code}: {resp.reason}"
            )

        return resp.json()

    def test_connection(self) -> dict:
        """
        Test the Graph API connection by fetching the organization profile.

        Returns:
            dict with org display name and verified domains
        """
        data = self._graph_request("/organization")
        orgs = data.get("value", [])
        if not orgs:
            return {"connected": True, "organization": None}

        org = orgs[0]
        return {
            "connected": True,
            "organization": {
                "display_name": org.get("displayName"),
                "id": org.get("id"),
                "verified_domains": [
                    d.get("name") for d in org.get("verifiedDomains", [])
                ],
            },
        }

    def list_users(self, limit: int = 100) -> list:
        """
        List users from Azure AD directory.

        Args:
            limit: Maximum number of users to return

        Returns:
            list of user dicts with id, displayName, mail, accountEnabled
        """
        endpoint = f"/users?$top={limit}&$select=id,displayName,mail,userPrincipalName,accountEnabled,createdDateTime"
        data = self._graph_request(endpoint)
        users = data.get("value", [])

        return [
            {
                "id": u.get("id"),
                "display_name": u.get("displayName"),
                "email": u.get("mail") or u.get("userPrincipalName"),
                "account_enabled": u.get("accountEnabled"),
                "created": u.get("createdDateTime"),
            }
            for u in users
        ]

    def get_mfa_status(self) -> list:
        """
        Check MFA registration status for all users.

        Uses the authentication methods registration endpoint to determine
        which users have registered MFA methods.

        Returns:
            list of dicts with user_id, display_name, mfa_registered, methods
        """
        # Get user registration details (requires Reports.Read.All or
        # AuditLog.Read.All permission)
        try:
            data = self._graph_request(
                "/reports/authenticationMethods/userRegistrationDetails"
            )
            registrations = data.get("value", [])
        except RuntimeError:
            # Fall back to per-user check if report endpoint unavailable
            logger.warning("MFA report endpoint unavailable, falling back to user list")
            users = self.list_users()
            return [
                {
                    "user_id": u["id"],
                    "display_name": u["display_name"],
                    "mfa_registered": None,
                    "methods": [],
                }
                for u in users
            ]

        results = []
        for reg in registrations:
            methods = reg.get("methodsRegistered", [])
            results.append({
                "user_id": reg.get("id"),
                "display_name": reg.get("userDisplayName"),
                "mfa_registered": len(methods) > 1,  # password + at least one other
                "methods": methods,
                "is_admin": reg.get("isAdmin", False),
            })

        return results

    def list_csp_clients(self) -> list:
        """
        List CSP/partner managed tenants via delegated admin relationships.

        Requires: DelegatedAdminRelationship.Read.All or Contract.Read.All

        Returns:
            list of dicts with customer_id, display_name, domain
        """
        clients = []

        # Try delegated admin relationships first (GDAP)
        try:
            data = self._graph_request("/tenantRelationships/delegatedAdminRelationships?$top=100")
            for rel in data.get("value", []):
                customer = rel.get("customer", {})
                clients.append({
                    "customer_tenant_id": customer.get("tenantId"),
                    "display_name": customer.get("displayName") or rel.get("displayName", "Unknown"),
                    "domain": customer.get("tenantId"),  # May not have domain
                    "status": rel.get("status"),
                    "source": "gdap",
                })
        except Exception as e:
            logger.debug("GDAP relationships not available: %s", e)

        # Also try contracts endpoint (legacy CSP)
        try:
            data = self._graph_request("/contracts?$top=100")
            existing_ids = {c["customer_tenant_id"] for c in clients}
            for contract in data.get("value", []):
                cid = contract.get("customerId")
                if cid and cid not in existing_ids:
                    clients.append({
                        "customer_tenant_id": cid,
                        "display_name": contract.get("displayName", "Unknown"),
                        "domain": contract.get("defaultDomainName", ""),
                        "status": "active",
                        "source": "contract",
                    })
        except Exception as e:
            logger.debug("Contracts endpoint not available: %s", e)

        return clients

    def assess_compliance(self) -> dict:
        """
        Perform a basic compliance posture assessment based on Entra ID
        configuration.

        Checks:
        - MFA adoption rate
        - Disabled/stale accounts
        - Conditional access policies (if accessible)

        Returns:
            dict with overall_score, findings, recommendations
        """
        findings = []
        recommendations = []
        score = 100

        # --- MFA check ---
        try:
            mfa_status = self.get_mfa_status()
            total_users = len(mfa_status)
            mfa_enabled = sum(1 for u in mfa_status if u.get("mfa_registered"))
            mfa_rate = (mfa_enabled / total_users * 100) if total_users > 0 else 0

            findings.append({
                "category": "MFA",
                "total_users": total_users,
                "mfa_enabled": mfa_enabled,
                "mfa_rate": round(mfa_rate, 1),
            })

            if mfa_rate < 100:
                penalty = min(30, int((100 - mfa_rate) * 0.3))
                score -= penalty
                recommendations.append(
                    f"Enable MFA for all users. Current rate: {mfa_rate:.0f}% "
                    f"({total_users - mfa_enabled} users without MFA)"
                )
        except Exception as e:
            logger.warning("MFA assessment failed: %s", e)
            findings.append({"category": "MFA", "error": str(e)})

        # --- Stale accounts check ---
        try:
            users = self.list_users(limit=999)
            disabled_count = sum(1 for u in users if not u.get("account_enabled"))

            findings.append({
                "category": "Account hygiene",
                "total_users": len(users),
                "disabled_accounts": disabled_count,
            })

            if disabled_count > 0:
                recommendations.append(
                    f"Review {disabled_count} disabled accounts for removal"
                )
        except Exception as e:
            logger.warning("Account hygiene check failed: %s", e)
            findings.append({"category": "Account hygiene", "error": str(e)})

        # --- Conditional access policies ---
        try:
            policies = self._graph_request(
                "/identity/conditionalAccess/policies"
            )
            policy_list = policies.get("value", [])
            active_policies = [
                p for p in policy_list if p.get("state") == "enabled"
            ]

            findings.append({
                "category": "Conditional Access",
                "total_policies": len(policy_list),
                "active_policies": len(active_policies),
            })

            if len(active_policies) == 0:
                score -= 20
                recommendations.append(
                    "No active Conditional Access policies found. "
                    "Configure policies for MFA, device compliance, and location-based access."
                )
        except Exception as e:
            logger.warning("Conditional Access check failed: %s", e)
            findings.append({"category": "Conditional Access", "error": str(e)})

        return {
            "overall_score": max(0, score),
            "assessed_at": datetime.utcnow().isoformat(),
            "findings": findings,
            "recommendations": recommendations,
        }

    # ─── Microsoft Security / Defender ────────────────────────────────

    def get_secure_score(self):
        """
        Get Microsoft Secure Score — overall security posture score.

        Returns:
            dict with current_score, max_score, average_comparative_score,
            and control_scores list.
        """
        try:
            data = self._graph_request("/security/secureScores?$top=1")
            scores = data.get("value", [])
            if not scores:
                return {"current_score": 0, "max_score": 0, "control_scores": []}

            latest = scores[0]
            return {
                "current_score": latest.get("currentScore", 0),
                "max_score": latest.get("maxScore", 0),
                "average_comparative_score": latest.get("averageComparativeScores", []),
                "enabled_services": latest.get("enabledServices", []),
                "control_scores": [
                    {
                        "name": cs.get("controlName"),
                        "score": cs.get("score"),
                        "max_score": cs.get("maxScore"),
                        "description": cs.get("description", ""),
                    }
                    for cs in latest.get("controlScores", [])
                ],
            }
        except Exception as e:
            logger.warning("Secure Score fetch failed: %s", e)
            return {"error": str(e)}

    def get_security_alerts(self, top=50):
        """
        Get recent security alerts from Microsoft Defender.

        Returns:
            list of alert dicts with severity, title, status, category.
        """
        try:
            data = self._graph_request(
                f"/security/alerts_v2?$top={top}&$orderby=createdDateTime desc"
            )
            alerts = data.get("value", [])
            return [
                {
                    "id": a.get("id"),
                    "title": a.get("title"),
                    "severity": a.get("severity"),
                    "status": a.get("status"),
                    "category": a.get("category"),
                    "description": a.get("description", "")[:300],
                    "created": a.get("createdDateTime"),
                    "source": a.get("detectionSource"),
                    "assigned_to": a.get("assignedTo"),
                }
                for a in alerts
            ]
        except Exception as e:
            logger.warning("Security alerts fetch failed: %s", e)
            return []

    def get_security_incidents(self, top=20):
        """
        Get recent security incidents.

        Returns:
            list of incident dicts with severity, status, alert count.
        """
        try:
            data = self._graph_request(
                f"/security/incidents?$top={top}&$orderby=createdDateTime desc"
            )
            incidents = data.get("value", [])
            return [
                {
                    "id": i.get("id"),
                    "display_name": i.get("displayName"),
                    "severity": i.get("severity"),
                    "status": i.get("status"),
                    "created": i.get("createdDateTime"),
                    "last_update": i.get("lastUpdateDateTime"),
                    "assigned_to": i.get("assignedTo"),
                }
                for i in incidents
            ]
        except Exception as e:
            logger.warning("Security incidents fetch failed: %s", e)
            return []

    # ─── Device Compliance (Intune) ───────────────────────────────────

    def get_managed_devices(self, top=100):
        """
        Get managed device inventory with compliance status.

        Returns:
            list of device dicts with name, OS, compliance, encryption status.
        """
        try:
            data = self._graph_request(
                f"/deviceManagement/managedDevices?$top={top}"
                "&$select=id,deviceName,operatingSystem,osVersion,"
                "complianceState,isEncrypted,lastSyncDateTime,"
                "userPrincipalName,model,manufacturer"
            )
            devices = data.get("value", [])
            return [
                {
                    "id": d.get("id"),
                    "name": d.get("deviceName"),
                    "os": d.get("operatingSystem"),
                    "os_version": d.get("osVersion"),
                    "compliance": d.get("complianceState"),
                    "encrypted": d.get("isEncrypted"),
                    "last_sync": d.get("lastSyncDateTime"),
                    "user": d.get("userPrincipalName"),
                    "model": d.get("model"),
                    "manufacturer": d.get("manufacturer"),
                }
                for d in devices
            ]
        except Exception as e:
            logger.warning("Managed devices fetch failed: %s", e)
            return []

    def get_device_compliance_summary(self):
        """
        Summarize device compliance across the tenant.

        Returns:
            dict with total, compliant, non_compliant, unknown counts.
        """
        devices = self.get_managed_devices(top=500)
        total = len(devices)
        compliant = sum(1 for d in devices if d.get("compliance") == "compliant")
        non_compliant = sum(1 for d in devices if d.get("compliance") == "noncompliant")
        encrypted = sum(1 for d in devices if d.get("encrypted"))
        return {
            "total_devices": total,
            "compliant": compliant,
            "non_compliant": non_compliant,
            "unknown": total - compliant - non_compliant,
            "encrypted": encrypted,
            "unencrypted": total - encrypted,
            "compliance_rate": round(compliant / total * 100, 1) if total else 0,
            "encryption_rate": round(encrypted / total * 100, 1) if total else 0,
            "non_compliant_devices": [
                d for d in devices if d.get("compliance") != "compliant"
            ][:20],
            "unencrypted_devices": [
                d for d in devices if not d.get("encrypted")
            ][:20],
        }

    # ─── Sign-in Risk / Identity Protection ───────────────────────────

    def get_risky_users(self, top=50):
        """
        Get users flagged as risky by Identity Protection.

        Returns:
            list of risky user dicts.
        """
        try:
            data = self._graph_request(
                f"/identityProtection/riskyUsers?$top={top}"
                "&$filter=riskState ne 'remediated'"
            )
            return [
                {
                    "id": u.get("id"),
                    "display_name": u.get("userDisplayName"),
                    "upn": u.get("userPrincipalName"),
                    "risk_level": u.get("riskLevel"),
                    "risk_state": u.get("riskState"),
                    "risk_detail": u.get("riskDetail"),
                    "last_updated": u.get("riskLastUpdatedDateTime"),
                }
                for u in data.get("value", [])
            ]
        except Exception as e:
            logger.warning("Risky users fetch failed: %s", e)
            return []

    def get_risk_detections(self, top=50):
        """
        Get recent risk detection events.

        Returns:
            list of risk detection dicts.
        """
        try:
            data = self._graph_request(
                f"/identityProtection/riskDetections?$top={top}"
                "&$orderby=detectedDateTime desc"
            )
            return [
                {
                    "id": d.get("id"),
                    "risk_type": d.get("riskEventType"),
                    "risk_level": d.get("riskLevel"),
                    "risk_state": d.get("riskState"),
                    "user_display_name": d.get("userDisplayName"),
                    "user_principal_name": d.get("userPrincipalName"),
                    "detected": d.get("detectedDateTime"),
                    "ip_address": d.get("ipAddress"),
                    "location": d.get("location", {}).get("city"),
                    "source": d.get("source"),
                }
                for d in data.get("value", [])
            ]
        except Exception as e:
            logger.warning("Risk detections fetch failed: %s", e)
            return []

    # ─── SharePoint / OneDrive Governance ─────────────────────────────

    def get_sharepoint_sites(self, top=50):
        """
        List SharePoint sites for data governance review.

        Returns:
            list of site dicts with name, URL, last modified.
        """
        try:
            data = self._graph_request(
                f"/sites?search=*&$top={top}"
                "&$select=id,displayName,webUrl,lastModifiedDateTime,createdDateTime"
            )
            return [
                {
                    "id": s.get("id"),
                    "name": s.get("displayName"),
                    "url": s.get("webUrl"),
                    "last_modified": s.get("lastModifiedDateTime"),
                    "created": s.get("createdDateTime"),
                }
                for s in data.get("value", [])
            ]
        except Exception as e:
            logger.warning("SharePoint sites fetch failed: %s", e)
            return []

    # ─── Audit Logs ───────────────────────────────────────────────────

    def get_sign_in_summary(self, days=7):
        """
        Get sign-in activity summary for the last N days.

        Returns:
            dict with total_signins, failed, risky, locations.
        """
        try:
            from_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
            data = self._graph_request(
                f"/auditLogs/signIns?$top=500"
                f"&$filter=createdDateTime ge {from_date}"
                "&$select=id,status,userDisplayName,ipAddress,"
                "location,riskLevelDuringSignIn,appDisplayName"
            )
            sign_ins = data.get("value", [])
            total = len(sign_ins)
            failed = sum(1 for s in sign_ins if s.get("status", {}).get("errorCode", 0) != 0)
            risky = sum(1 for s in sign_ins if s.get("riskLevelDuringSignIn") not in (None, "none", "hidden"))

            # Unique locations
            locations = set()
            for s in sign_ins:
                loc = s.get("location", {})
                city = loc.get("city")
                country = loc.get("countryOrRegion")
                if city or country:
                    locations.add(f"{city or '?'}, {country or '?'}")

            return {
                "total_signins": total,
                "failed_signins": failed,
                "risky_signins": risky,
                "unique_locations": list(locations)[:20],
                "days": days,
                "failure_rate": round(failed / total * 100, 1) if total else 0,
            }
        except Exception as e:
            logger.warning("Sign-in summary failed: %s", e)
            return {"error": str(e)}

    # ─── CISA SCUBA Baselines (Entra ID) ──────────────────────────────

    def assess_cisa_scuba(self) -> dict:
        """
        Assess Microsoft Entra ID against CISA SCUBA Baselines.
        Checks key configurations to evaluate alignment with CISA SCUBA.
        
        Returns:
            dict with scuba_score, max_score, assessed_at, findings.
        """
        findings = []
        score = 100
        max_score = 100

        def add_finding(control_id, title, status, description, penalty=0):
            nonlocal score
            findings.append({
                "control_id": control_id,
                "title": title,
                "status": status,
                "description": description
            })
            if status in ["fail", "warning"]:
                score -= penalty

        # 1. Identity Security Defaults or Conditional Access
        try:
            sec_defaults = self._graph_request("/policies/identitySecurityDefaultsEnforcementPolicy")
            ca_policies_data = self._graph_request("/identity/conditionalAccess/policies")
            ca_policies = ca_policies_data.get("value", [])
            active_ca = [p for p in ca_policies if p.get("state") == "enabled"]
            
            is_sec_defaults_enabled = sec_defaults.get("isEnabled", False)
            
            if is_sec_defaults_enabled:
                add_finding("MS.AAD.1", "Phishing-resistant MFA", "warning", "Security Defaults is enabled. This enforces MFA but may not explicitly require phishing-resistant MFA like FIDO2.", 0)
                add_finding("MS.AAD.2", "Block Legacy Authentication", "pass", "Security Defaults is enabled, which natively blocks legacy authentication.", 0)
            elif active_ca:
                legacy_blocked = False
                for p in active_ca:
                    cond = p.get("conditions", {})
                    apps = cond.get("clientAppTypes", [])
                    if "exchangeActiveSync" in apps or "other" in apps:
                        grant = p.get("grantControls", {})
                        if grant.get("operator") in ["OR", "AND"]:
                            if "block" in grant.get("builtInControls", []):
                                legacy_blocked = True
                
                if legacy_blocked:
                    add_finding("MS.AAD.2", "Block Legacy Authentication", "pass", "Legacy authentication is explicitly blocked via Conditional Access.", 0)
                else:
                    add_finding("MS.AAD.2", "Block Legacy Authentication", "fail", "Legacy authentication is not explicitly blocked via Conditional Access.", 15)
            else:
                add_finding("MS.AAD.1.2", "MFA/Security Defaults", "fail", "Neither Security Defaults nor proactive Conditional Access policies are enabled.", 20)
                
        except Exception as e:
            logger.warning("CISA CA/Security Defaults check failed: %s", e)

        # 2. Authorization Policies (User Consent & Guest Settings)
        try:
            # We get the default authorization policy which is generally item 'authorizationPolicy'
            auth_policy = self._graph_request("/policies/authorizationPolicy/authorizationPolicy")
        except Exception:
            try:
                # Fallback if first request fails
                auth_policy = self._graph_request("/policies/authorizationPolicy")
            except Exception as e:
                logger.warning("CISA Authorization Policy check failed: %s", e)
                auth_policy = {}

        if auth_policy:
            consent_setting = auth_policy.get("defaultUserRolePermissions", {}).get("permissionGrantPoliciesAssigned", [])
            if consent_setting and "ManagePermissionGrantsForSelf.microsoft-user-default-legacy" in consent_setting:
                add_finding("MS.AAD.4", "Restrict User Consent", "fail", "Users can consent to third-party applications accessing company data on their behalf.", 10)
            else:
                add_finding("MS.AAD.4", "Restrict User Consent", "pass", "User consent to third-party applications is restricted.", 0)

            guest_invite = auth_policy.get("allowInvitesFrom", "")
            if guest_invite == "everyone":
                add_finding("MS.AAD.5", "Restrict Guest Invitations", "warning", "Guest invitations are allowed from everyone.", 5)
            else:
                add_finding("MS.AAD.5", "Restrict Guest Invitations", "pass", f"Guest invitations restricted to: {guest_invite}.", 0)

        # 3. Authentication Methods Policy (FIDO2)
        try:
            auth_methods = self._graph_request("/policies/authenticationMethodsPolicy")
            # In Microsoft Graph, we might need to query the actual methods individually
            fido2_enabled = False
            
            try:
                # Try specific method query
                fido_res = self._graph_request("/policies/authenticationMethodsPolicy/authenticationMethodConfigurations/Fido2")
                if fido_res.get("state") == "enabled":
                    fido2_enabled = True
            except Exception:
                pass

            if fido2_enabled:
                add_finding("MS.AAD.3.1", "Phishing Resistant MFA Methods", "pass", "FIDO2 security keys are enabled as an authentication method.", 0)
            else:
                add_finding("MS.AAD.3.1", "Phishing Resistant MFA Methods", "warning", "FIDO2 security keys (phishing-resistant MFA) are not explicitly enabled.", 5)

        except Exception as e:
            logger.warning("CISA Authentication Methods Policy check failed: %s", e)

        return {
            "scuba_score": max(0, score),
            "max_score": max_score,
            "assessed_at": datetime.utcnow().isoformat(),
            "findings": findings
        }

    def collect_all_security_data(self):
        """
        Collect ALL available Microsoft security data in one call.
        Used by the auto-process pipeline.

        Returns:
            dict with SCUBA-aligned security data categories.

        Output is structured to match the CISA SCUBA framework product groupings:
            MS.AAD  — Entra ID / Azure AD (identity, MFA, Conditional Access)
            MS.Defender — Microsoft Defender (alerts, incidents, Secure Score)
            MS.Intune   — Device Management (compliance, encryption)
            MS.Purview  — Information Protection (DLP, sensitivity labels)
            MS.SharePoint — SharePoint / OneDrive governance
        """
        result = {}

        # ── MS.AAD — Entra ID / Identity ──────────────────────────────
        ms_aad = {}
        try:
            users = self.list_users()
            ms_aad["users"] = {"count": len(users), "sample": users[:5]}
        except Exception:
            pass

        try:
            mfa = self.get_mfa_status()
            ms_aad["mfa"] = mfa
        except Exception:
            pass

        try:
            scuba = self.assess_cisa_scuba()
            ms_aad["scuba_baseline"] = scuba
        except Exception:
            pass

        try:
            compliance = self.assess_compliance()
            ms_aad["compliance"] = compliance
        except Exception:
            pass

        try:
            risky = self.get_risky_users(top=20)
            if risky:
                ms_aad["risky_users"] = risky
        except Exception:
            pass

        try:
            risk_detections = self.get_risk_detections(top=20)
            if risk_detections:
                ms_aad["risk_detections"] = risk_detections
        except Exception:
            pass

        try:
            signins = self.get_sign_in_summary(days=7)
            if not signins.get("error"):
                ms_aad["sign_in_summary"] = signins
        except Exception:
            pass

        if ms_aad:
            result["ms_aad"] = ms_aad

        # ── MS.Defender — Microsoft Defender & Secure Score ───────────
        ms_defender = {}
        try:
            score = self.get_secure_score()
            if not score.get("error"):
                ms_defender["secure_score"] = score
        except Exception:
            pass

        try:
            alerts = self.get_security_alerts(top=30)
            if alerts:
                ms_defender["security_alerts"] = {
                    "count": len(alerts),
                    "alerts": alerts,
                    "by_severity": {
                        "high": sum(1 for a in alerts if a.get("severity") == "high"),
                        "medium": sum(1 for a in alerts if a.get("severity") == "medium"),
                        "low": sum(1 for a in alerts if a.get("severity") == "low"),
                    },
                }
        except Exception:
            pass

        try:
            incidents = self.get_security_incidents(top=10)
            if incidents:
                ms_defender["security_incidents"] = incidents
        except Exception:
            pass

        if ms_defender:
            result["ms_defender"] = ms_defender

        # ── MS.Intune — Device Management & Compliance ────────────────
        ms_intune = {}
        try:
            devices = self.get_device_compliance_summary()
            if devices.get("total_devices"):
                ms_intune["device_compliance"] = devices
        except Exception:
            pass

        if ms_intune:
            result["ms_intune"] = ms_intune

        # ── MS.Purview — Information Protection ───────────────────────
        try:
            purview = self.assess_purview()
            if purview and not purview.get("error"):
                result["ms_purview"] = purview
        except Exception:
            pass

        # ── MS.SharePoint — Collaboration & DLP ───────────────────────
        ms_sharepoint = {}
        try:
            sites = self.get_sharepoint_sites(top=20)
            if sites:
                ms_sharepoint["sites"] = sites
        except Exception:
            pass

        if ms_sharepoint:
            result["ms_sharepoint"] = ms_sharepoint

        # ── Flat aliases for backwards compatibility with evidence_generators ──
        # Keep top-level keys that existing code in evidence_generators.py / llm_routes.py expects
        if result.get("ms_aad", {}).get("mfa"):
            result["mfa"] = result["ms_aad"]["mfa"]
        if result.get("ms_aad", {}).get("compliance"):
            result["compliance"] = result["ms_aad"]["compliance"]
        if result.get("ms_aad", {}).get("scuba_baseline"):
            result["scuba_baseline"] = result["ms_aad"]["scuba_baseline"]
        if result.get("ms_defender", {}).get("secure_score"):
            result["secure_score"] = result["ms_defender"]["secure_score"]
        if result.get("ms_defender", {}).get("security_alerts"):
            result["security_alerts"] = result["ms_defender"]["security_alerts"]
        if result.get("ms_intune", {}).get("device_compliance"):
            result["devices"] = result["ms_intune"]["device_compliance"]
        if result.get("ms_aad", {}).get("risky_users"):
            result["risky_users"] = result["ms_aad"]["risky_users"]
        if result.get("ms_aad", {}).get("risk_detections"):
            result["risk_detections"] = result["ms_aad"]["risk_detections"]
        if result.get("ms_aad", {}).get("sign_in_summary"):
            result["sign_in_summary"] = result["ms_aad"]["sign_in_summary"]
        if result.get("ms_sharepoint", {}).get("sites"):
            result["sharepoint_sites"] = result["ms_sharepoint"]["sites"]
        if result.get("ms_aad", {}).get("users"):
            result["users"] = result["ms_aad"]["users"]

        return result

    # ─── Microsoft Purview — Information Protection ───────────────────

    def assess_purview(self) -> dict:
        """
        Assess Microsoft Purview / Information Protection configuration.

        Maps to CISA SCUBA MS.Purview baselines:
          - DLP policies (data loss prevention)
          - Sensitivity labels (information classification)
          - Audit log settings
          - Communication compliance (insider risk)

        Returns:
            dict with scuba_product, findings, purview_score, max_score, assessed_at
        """
        findings = []
        score = 100
        max_score = 100

        def add_finding(control_id, title, status, description, penalty=0):
            nonlocal score
            findings.append({
                "control_id": control_id,
                "title": title,
                "status": status,
                "description": description,
                "scuba_product": "MS.Purview",
            })
            if status in ["fail", "warning"]:
                score -= penalty

        # 1. Sensitivity Labels (MS.Purview.1.x)
        try:
            labels_data = self._graph_request("/security/informationProtection/sensitivityLabels")
            labels = labels_data.get("value", [])
            if labels:
                add_finding(
                    "MS.Purview.1.1",
                    "Sensitivity Labels Configured",
                    "pass",
                    f"{len(labels)} sensitivity label(s) are configured in Purview Information Protection.",
                )
                # Check for auto-labeling policies
                auto_labels = [l for l in labels if l.get("autoLabeling")]
                if auto_labels:
                    add_finding(
                        "MS.Purview.1.2",
                        "Auto-Labeling Policies",
                        "pass",
                        f"{len(auto_labels)} label(s) have auto-labeling configured.",
                    )
                else:
                    add_finding(
                        "MS.Purview.1.2",
                        "Auto-Labeling Policies",
                        "warning",
                        "No auto-labeling policies found. Manual classification increases risk of data mishandling.",
                        5,
                    )
            else:
                add_finding(
                    "MS.Purview.1.1",
                    "Sensitivity Labels Configured",
                    "fail",
                    "No sensitivity labels are configured. Data classification and protection cannot be enforced.",
                    20,
                )
        except Exception as e:
            logger.debug("Purview sensitivity labels check failed: %s", e)
            add_finding(
                "MS.Purview.1.1",
                "Sensitivity Labels Configured",
                "unknown",
                f"Could not retrieve sensitivity labels. Requires InformationProtectionPolicy.Read permission. Error: {str(e)[:100]}",
            )

        # 2. DLP Policies (MS.Purview.2.x)
        try:
            dlp_data = self._graph_request("/security/dataLossPreventionPolicies")
            dlp_policies = dlp_data.get("value", [])
            enabled_dlp = [p for p in dlp_policies if p.get("status") == "enabled"]

            if enabled_dlp:
                add_finding(
                    "MS.Purview.2.1",
                    "DLP Policies Active",
                    "pass",
                    f"{len(enabled_dlp)} of {len(dlp_policies)} DLP policy/policies are enabled.",
                )
            elif dlp_policies:
                add_finding(
                    "MS.Purview.2.1",
                    "DLP Policies Active",
                    "fail",
                    f"{len(dlp_policies)} DLP policies found but none are enabled. Data exfiltration protection is not enforced.",
                    15,
                )
            else:
                add_finding(
                    "MS.Purview.2.1",
                    "DLP Policies Active",
                    "fail",
                    "No Data Loss Prevention (DLP) policies are configured. Sensitive data may be exfiltrated without detection.",
                    20,
                )
        except Exception as e:
            logger.debug("Purview DLP policy check failed: %s", e)
            add_finding(
                "MS.Purview.2.1",
                "DLP Policies Active",
                "unknown",
                f"Could not retrieve DLP policies. May require Compliance Center permissions. Error: {str(e)[:100]}",
            )

        # 3. Audit Log (MS.Purview.3.x — SCUBA requires audit logging enabled)
        try:
            # Query audit log settings via organization-level admin controls
            # Graph doesn't expose the Unified Audit Log toggle directly,
            # but we can probe the auditLogs endpoint to test if it's accessible
            audit_probe = self._graph_request("/auditLogs/directoryAudits?$top=1")
            add_finding(
                "MS.Purview.3.1",
                "Unified Audit Log Enabled",
                "pass",
                "Audit logs are accessible. Unified Audit Log appears to be enabled for this tenant.",
            )
        except Exception as e:
            if "403" in str(e) or "Forbidden" in str(e):
                add_finding(
                    "MS.Purview.3.1",
                    "Unified Audit Log Enabled",
                    "warning",
                    "Audit log access was denied by Graph API permissions. Verify AuditLog.Read.All is granted.",
                    5,
                )
            else:
                add_finding(
                    "MS.Purview.3.1",
                    "Unified Audit Log Enabled",
                    "fail",
                    f"Could not access audit logs. Unified Audit Log may be disabled. Error: {str(e)[:100]}",
                    15,
                )

        # 4. Insider Risk Management / Communication Compliance  (MS.Purview.4.x)
        # These are policy-center only APIs — attempt a discovery call
        try:
            insider_data = self._graph_request("/security/cases/ediscoveryCases?$top=1")
            add_finding(
                "MS.Purview.4.1",
                "eDiscovery / Insider Risk Access",
                "pass",
                "Purview eDiscovery endpoint is accessible. Insider risk capabilities are reachable.",
            )
        except Exception as e:
            add_finding(
                "MS.Purview.4.1",
                "eDiscovery / Insider Risk Access",
                "unknown",
                f"Could not access Purview eDiscovery endpoint. eDiscovery.Read.All or higher may be required. Error: {str(e)[:100]}",
            )

        return {
            "scuba_product": "MS.Purview",
            "purview_score": max(0, score),
            "max_score": max_score,
            "assessed_at": datetime.utcnow().isoformat(),
            "findings": findings,
        }
