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

    def collect_all_security_data(self):
        """
        Collect ALL available Microsoft security data in one call.
        Used by the auto-process pipeline.

        Returns:
            dict with all security data categories.
        """
        result = {}

        # Existing Entra data
        try:
            users = self.list_users()
            result["users"] = {"count": len(users), "sample": users[:5]}
        except Exception:
            pass

        try:
            mfa = self.get_mfa_status()
            result["mfa"] = mfa
        except Exception:
            pass

        try:
            compliance = self.assess_compliance()
            result["compliance"] = compliance
        except Exception:
            pass

        # New Microsoft Security data
        try:
            score = self.get_secure_score()
            if not score.get("error"):
                result["secure_score"] = score
        except Exception:
            pass

        try:
            alerts = self.get_security_alerts(top=30)
            if alerts:
                result["security_alerts"] = {
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
            devices = self.get_device_compliance_summary()
            if devices.get("total_devices"):
                result["devices"] = devices
        except Exception:
            pass

        try:
            risky = self.get_risky_users(top=20)
            if risky:
                result["risky_users"] = risky
        except Exception:
            pass

        try:
            risk_detections = self.get_risk_detections(top=20)
            if risk_detections:
                result["risk_detections"] = risk_detections
        except Exception:
            pass

        try:
            signins = self.get_sign_in_summary(days=7)
            if not signins.get("error"):
                result["sign_in_summary"] = signins
        except Exception:
            pass

        try:
            sites = self.get_sharepoint_sites(top=20)
            if sites:
                result["sharepoint_sites"] = sites
        except Exception:
            pass

        return result
