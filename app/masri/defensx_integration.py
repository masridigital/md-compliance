"""
Masri Digital Compliance Platform — DefensX Browser Security Integration

Client for the DefensX Partner API.
Provides browser agent deployment status, web filtering policy compliance,
credential protection events, shadow AI detection, and cyber resilience scores.

Authentication: Bearer token from DefensX Partner Dashboard.

NOTE: DefensX does not publish a public API reference. Endpoint paths below
are based on the integration specification. They may need adjustment once
API access is confirmed with DefensX partner support.
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)


class DefensXIntegration:
    """
    DefensX browser security platform API client.

    Uses Partner API v1 — Bearer token authentication.
    Multi-tenant: single partner token accesses all customer tenants.

    Args:
        api_token: Partner API token (from DefensX Partner Dashboard → API Keys)
        base_url: API base URL (default: cloud.defensx.com)
    """

    BASE_URL = "https://cloud.defensx.com/api/partner/v1"

    def __init__(self, api_token: str, base_url: str = None):
        self.api_token = api_token
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        })
        self.session.timeout = 30

    def _get(self, path: str, params: dict = None) -> requests.Response:
        """Make an authenticated GET request to the DefensX API."""
        url = f"{self.base_url}{path}"
        resp = self.session.get(url, params=params)
        if not resp.ok:
            logger.error(
                "DefensX API GET %s returned %s: %s",
                path, resp.status_code, resp.text[:500],
            )
            raise RuntimeError(
                f"DefensX API error {resp.status_code}: {resp.reason}"
            )
        return resp

    # ── Connection Test ─────────────────────────────────────────────────

    def test_connection(self) -> dict:
        """Test API connectivity and return partner account status."""
        try:
            resp = self._get("/customers", params={"limit": 1})
            data = resp.json()
            total = data.get("total", len(data.get("customers", data.get("data", []))))
            return {
                "connected": True,
                "customer_count": total,
                "message": f"Connected — {total} customer(s) found",
            }
        except Exception as e:
            return {"connected": False, "error": str(e)}

    # ── Customer / Tenant Listing ───────────────────────────────────────

    def list_customers(self, page: int = 1, limit: int = 100) -> list:
        """List all managed customer tenants."""
        resp = self._get("/customers", params={"page": page, "limit": limit})
        data = resp.json()
        return data.get("customers", data.get("data", data if isinstance(data, list) else []))

    def get_customer(self, customer_id: str) -> dict:
        """Get detailed info for a specific customer."""
        return self._get(f"/customers/{customer_id}").json()

    # ── Agent Deployment ────────────────────────────────────────────────

    def get_agent_deployment_status(self, customer_id: str) -> dict:
        """
        Return agent deployment status per endpoint.
        Includes: total agents, active, inactive, version distribution.
        """
        return self._get(f"/customers/{customer_id}/agents").json()

    # ── Policy Compliance ───────────────────────────────────────────────

    def get_web_policy_compliance(self, customer_id: str) -> dict:
        """Return web filtering policy configuration and compliance status."""
        return self._get(f"/customers/{customer_id}/policies").json()

    # ── Resilience Assessment ───────────────────────────────────────────

    def get_cyber_resilience_assessment(self, customer_id: str) -> dict:
        """Return DefensX cyber resilience assessment score for a customer."""
        return self._get(f"/customers/{customer_id}/resilience-assessment").json()

    # ── User Activity ───────────────────────────────────────────────────

    def get_user_activity_summary(self, customer_id: str, days: int = 30) -> dict:
        """Summarize user activity: blocked URLs, credential attempts, file transfers."""
        return self._get(
            "/analytics/user-activity",
            params={"customer_id": customer_id, "days": days},
        ).json()

    # ── Security Logs ───────────────────────────────────────────────────

    def get_security_logs(
        self,
        customer_id: str,
        log_type: str,
        since: str = None,
        limit: int = 200,
    ) -> list:
        """
        Pull security logs for a customer.
        log_type: 'url_visits' | 'dns_queries' | 'credential_events' | 'file_transfers'
        """
        params = {"customer_id": customer_id, "type": log_type, "limit": limit}
        if since:
            params["since"] = since
        return self._get("/security/logs", params=params).json().get("logs", [])

    # ── Shadow AI Detection ─────────────────────────────────────────────

    def get_shadow_ai_usage(self, customer_id: str) -> dict:
        """Detect and report on Shadow AI / unauthorized AI tool usage."""
        return self._get(f"/customers/{customer_id}/shadow-ai").json()

    # ── Aggregate Collection ────────────────────────────────────────────

    def collect_all_data(self, customer_id: str) -> dict:
        """
        Single method to collect ALL compliance-relevant data.
        Called by auto-process pipeline.
        """
        result = {}
        for method, key, kwargs in [
            (self.get_agent_deployment_status, "agent_status", {"customer_id": customer_id}),
            (self.get_web_policy_compliance, "policy_compliance", {"customer_id": customer_id}),
            (self.get_cyber_resilience_assessment, "resilience_score", {"customer_id": customer_id}),
            (self.get_user_activity_summary, "user_activity", {"customer_id": customer_id}),
            (self.get_shadow_ai_usage, "shadow_ai", {"customer_id": customer_id}),
        ]:
            try:
                result[key] = method(**kwargs)
            except Exception as e:
                logger.warning("DefensX %s collection failed: %s", key, e)
                result[key] = {"error": str(e)}
        result["_collected_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return result
