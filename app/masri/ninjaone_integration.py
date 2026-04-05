"""
Masri Digital Compliance Platform — NinjaOne RMM Integration

Client for the NinjaOne API v2 (formerly NinjaRMM).
Provides endpoint inventory, patch compliance, antivirus status,
disk encryption, alerts, and activity logs.

Authentication: OAuth2 Client Credentials (client_id + client_secret).
Region-specific base URLs: US, EU, Asia-Pacific, Canada.
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)

# Region-specific base URLs
NINJAONE_REGIONS = {
    "us": "https://app.ninjarmm.com",
    "eu": "https://eu.ninjarmm.com",
    "ap": "https://app.ninjarmm.com.au",
    "ca": "https://ca.ninjarmm.com",
}


class NinjaOneIntegration:
    """
    NinjaOne RMM API client.

    Uses OAuth2 Client Credentials flow for machine-to-machine access.
    A single set of MSP-level credentials accesses all client organizations.

    Args:
        client_id: OAuth app client ID (from NinjaOne Administration → Apps)
        client_secret: OAuth app client secret
        instance_url: Region-specific base URL (default: US)
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        instance_url: str = "https://app.ninjarmm.com",
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.instance_url = instance_url.rstrip("/")
        self.api_base = f"{self.instance_url}/v2"
        self._access_token = None
        self._token_expires_at = 0

    # ── Authentication ──────────────────────────────────────────────────

    def _get_access_token(self) -> str:
        """Acquire an access token using OAuth2 client credentials flow."""
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        token_url = f"{self.instance_url}/oauth/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "monitoring",
        }
        resp = requests.post(token_url, data=data, timeout=30)
        resp.raise_for_status()
        token_data = resp.json()
        self._access_token = token_data["access_token"]
        self._token_expires_at = time.time() + token_data.get("expires_in", 3600)
        return self._access_token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, params: dict = None) -> requests.Response:
        """Make an authenticated request to the NinjaOne API."""
        url = f"{self.api_base}{path}"
        resp = requests.request(
            method, url, headers=self._headers(), params=params, timeout=30,
        )
        if not resp.ok:
            logger.error(
                "NinjaOne API %s %s returned %s: %s",
                method, path, resp.status_code, resp.text[:500],
            )
            raise RuntimeError(
                f"NinjaOne API error {resp.status_code}: {resp.reason}"
            )
        return resp

    def _paginate(self, path: str, params: dict = None, page_size: int = 200, cap: int = 5000) -> list:
        """Cursor-based pagination. Returns all results up to cap."""
        params = dict(params or {})
        params["pageSize"] = page_size
        results = []
        while True:
            resp = self._request("GET", path, params=params)
            page = resp.json()
            if isinstance(page, list):
                results.extend(page)
            else:
                results.extend(page.get("results", page.get("data", [])))
            if len(results) >= cap:
                break
            # NinjaOne uses `after` param with last item's ID
            if isinstance(page, list) and len(page) < page_size:
                break
            if isinstance(page, list) and page:
                params["after"] = page[-1].get("id")
            else:
                break
        return results[:cap]

    # ── Connection Test ─────────────────────────────────────────────────

    def test_connection(self) -> dict:
        """Test API connectivity by fetching organization list."""
        try:
            orgs = self.list_organizations()
            return {
                "connected": True,
                "organization_count": len(orgs),
                "message": f"Connected — {len(orgs)} organization(s) found",
            }
        except Exception as e:
            return {"connected": False, "error": str(e)}

    # ── Organizations (MSP Client Tenants) ──────────────────────────────

    def list_organizations(self) -> list:
        """List all client organizations under this MSP account."""
        resp = self._request("GET", "/organizations")
        return resp.json() if isinstance(resp.json(), list) else resp.json().get("results", [])

    # ── Device Inventory ────────────────────────────────────────────────

    def get_devices_detailed(self, org_id: str = None) -> list:
        """Return all endpoints with detailed info (OS, hardware, disks)."""
        params = {}
        if org_id:
            params["df"] = f"org = {org_id}"
        return self._paginate("/devices-detailed", params=params)

    # ── Patch Management ────────────────────────────────────────────────

    def get_os_patches(self) -> list:
        """Query pending OS patches across all devices."""
        return self._paginate("/queries/os-patches")

    def get_software_patches(self) -> list:
        """Query pending software patches across all devices."""
        return self._paginate("/queries/software-patches")

    # ── Antivirus / Security Status ─────────────────────────────────────

    def get_antivirus_status(self) -> list:
        """Query AV status across all devices."""
        return self._paginate("/queries/antivirus-status")

    def get_antivirus_threats(self) -> list:
        """Query detected AV threats across all devices."""
        return self._paginate("/queries/antivirus-threats")

    # ── Alerts ──────────────────────────────────────────────────────────

    def get_alerts(self, severity: str = None) -> list:
        """Get active alerts. Optional severity filter: NONE, MINOR, MAJOR, CRITICAL."""
        params = {}
        if severity:
            params["severity"] = severity
        return self._paginate("/alerts", params=params)

    # ── Activity Logs ───────────────────────────────────────────────────

    def get_activities(self, days: int = 30) -> list:
        """Get recent activity log entries."""
        from datetime import datetime, timedelta, timezone
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        params = {"after": since}
        return self._paginate("/activities", params=params, cap=2000)

    # ── Aggregate Collection ────────────────────────────────────────────

    def collect_all_data(self, org_id: str = None) -> dict:
        """
        Single method to collect ALL compliance-relevant data.
        Called by auto-process pipeline.
        Follows the collect_all_data() pattern from EntraIntegration.
        """
        result = {}
        for method, key, kwargs in [
            (self.get_devices_detailed, "devices", {"org_id": org_id}),
            (self.get_os_patches, "os_patches", {}),
            (self.get_software_patches, "software_patches", {}),
            (self.get_antivirus_status, "antivirus_status", {}),
            (self.get_antivirus_threats, "antivirus_threats", {}),
            (self.get_alerts, "alerts", {}),
        ]:
            try:
                result[key] = method(**kwargs)
            except Exception as e:
                logger.warning("NinjaOne %s collection failed: %s", key, e)
                result[key] = {"error": str(e)}
        result["_collected_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return result
