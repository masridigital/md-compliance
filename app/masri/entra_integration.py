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
from datetime import datetime

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
        self._token_cache = None

    def _get_access_token(self) -> str:
        """Acquire an access token using client credentials flow."""
        try:
            import msal
        except ImportError:
            raise RuntimeError(
                "msal library is required for Entra ID integration. "
                "Install with: pip install msal"
            )

        authority = f"{self.AUTHORITY_BASE}/{self.tenant_id}"
        app = msal.ConfidentialClientApplication(
            self.client_id,
            authority=authority,
            client_credential=self.client_secret,
        )

        scopes = ["https://graph.microsoft.com/.default"]
        result = app.acquire_token_for_client(scopes=scopes)

        if "access_token" not in result:
            error = result.get("error_description", result.get("error", "Unknown"))
            raise RuntimeError(f"Failed to acquire token: {error}")

        return result["access_token"]

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
