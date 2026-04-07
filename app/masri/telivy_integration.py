"""
Masri Digital Compliance Platform — Telivy Security Integration

Client for the Telivy Security API (https://api-v1.telivy.com).
Provides external vulnerability scanning, risk assessments, breach
data, and downloadable security reports.

Authentication: API key via x-api-key header.
All credentials are stored Fernet-encrypted in SettingsTelivy.
"""

import logging
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

TELIVY_BASE_URL = "https://api-v1.telivy.com"


class TelivyIntegration:
    """
    Telivy Security API client.

    Args:
        api_key: Telivy API key (from portal.telivy.com → Account → Integrations)
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = TELIVY_BASE_URL

    def _headers(self) -> dict:
        return {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs):
        """Make an authenticated request to the Telivy API."""
        url = f"{self.base_url}{path}"
        resp = requests.request(
            method, url, headers=self._headers(), timeout=30, **kwargs
        )

        if not resp.ok:
            logger.error(
                "Telivy API %s %s returned %s: %s",
                method, path, resp.status_code, resp.text[:500],
            )
            raise RuntimeError(
                f"Telivy API error {resp.status_code}: {resp.reason}"
            )

        # Report downloads return binary
        if resp.headers.get("content-type", "").startswith("application/octet-stream"):
            return resp.content

        if resp.status_code == 204:
            return {}

        return resp.json()

    # ─── Connection Test ──────────────────────────────────────────────

    def test_connection(self) -> dict:
        """Test the API connection and count external scans + risk assessments."""
        ext_data = self._request("GET", "/api/v1/security/external-scans", params={"limit": 1})
        ext_count = ext_data.get("total", 0)
        assess_count = 0
        try:
            assess_data = self._request("GET", "/api/v1/security/risk-assessments", params={"limit": 1})
            assess_count = assess_data.get("total", 0)
        except Exception:
            pass
        return {
            "connected": True,
            "external_scans": ext_count,
            "risk_assessments": assess_count,
            "total_scans": ext_count + assess_count,
        }

    # ─── External Scans ──────────────────────────────────────────────

    def list_external_scans(self, search: str = None, limit: int = 100, offset: int = 0) -> dict:
        """List all external scan assessments."""
        params = {"limit": limit, "offset": offset, "assessmentSortBy": "createdAt", "sortOrder": "DESC"}
        if search:
            params["search"] = search
        return self._request("GET", "/api/v1/security/external-scans", params=params)

    def create_external_scan(self, organization_name: str, domain: str,
                              client_category: str = None, client_status: str = None) -> dict:
        """Create a new external scan assessment."""
        payload = {"organizationName": organization_name, "domain": domain}
        if client_category:
            payload["clientCategory"] = client_category
        if client_status:
            payload["clientStatus"] = client_status
        return self._request("POST", "/api/v1/security/external-scans", json=payload)

    def get_external_scan(self, scan_id: str) -> dict:
        """Get an external scan by ID."""
        return self._request("GET", f"/api/v1/security/external-scans/{scan_id}")

    def get_external_scan_findings(self, scan_id: str) -> list:
        """Get findings for an external scan."""
        return self._request("GET", f"/api/v1/security/external-scans/{scan_id}/findings")

    def get_external_scan_finding_details(self, scan_id: str, slug: str) -> list:
        """Get detailed findings for a specific finding slug."""
        return self._request("GET", f"/api/v1/security/external-scans/{scan_id}/findings/{slug}")

    def get_breach_data(self, scan_id: str) -> list:
        """Get breach data for an external scan."""
        return self._request("GET", f"/api/v1/security/external-scans/{scan_id}/breach-data")

    def download_external_scan_report(self, scan_id: str, detailed: bool = False,
                                        fmt: str = "pdf") -> bytes:
        """Download external scan report as PDF or DOCX."""
        params = {"detailed": str(detailed).lower(), "format": fmt}
        return self._request("GET", f"/api/v1/security/external-scans/{scan_id}/report", params=params)

    def rescan_external(self, scan_id: str, reason: str = "") -> dict:
        """Trigger a rescan for all devices in an external scan."""
        return self._request("POST", f"/api/v1/security/external-scans/{scan_id}/rescan-all",
                             json={"reason": reason})

    # ─── Risk Assessments ─────────────────────────────────────────────

    def list_risk_assessments(self, search: str = None, limit: int = 100, offset: int = 0) -> dict:
        """List all risk assessments."""
        params = {"limit": limit, "offset": offset, "assessmentSortBy": "createdAt", "sortOrder": "DESC"}
        if search:
            params["search"] = search
        return self._request("GET", "/api/v1/security/risk-assessments", params=params)

    def create_risk_assessment(self, organization_name: str, domain: str,
                                country: str = "US", is_light_scan: bool = True,
                                client_category: str = None, client_status: str = None) -> dict:
        """Create a new risk assessment."""
        payload = {
            "organizationName": organization_name,
            "domain": domain,
            "country": country,
            "isLightScan": is_light_scan,
        }
        if client_category:
            payload["clientCategory"] = client_category
        if client_status:
            payload["clientStatus"] = client_status
        return self._request("POST", "/api/v1/security/risk-assessments", json=payload)

    def get_risk_assessment(self, assessment_id: str) -> dict:
        """Get a risk assessment by ID."""
        return self._request("GET", f"/api/v1/security/risk-assessments/{assessment_id}")

    def get_risk_assessment_devices(self, assessment_id: str) -> list:
        """Get all devices for a risk assessment."""
        return self._request("GET", f"/api/v1/security/risk-assessments/{assessment_id}/devices")

    def get_scan_status(self, assessment_id: str) -> dict:
        """Get scan completion status for all devices."""
        return self._request("GET", f"/api/v1/security/risk-assessments/{assessment_id}/scan-status")

    def download_risk_assessment_report(self, assessment_id: str,
                                         report_type: str = "telivy_complete_report_pdf") -> bytes:
        """Download risk assessment report."""
        return self._request("GET", f"/api/v1/security/risk-assessments/{assessment_id}/report",
                             params={"reportType": report_type})

    def update_monitoring(self, assessment_id: str, frequency: str = None) -> dict:
        """Update monitoring settings. frequency: QUARTERLY, MONTHLY, WEEKLY, or None to disable."""
        return self._request("PATCH", f"/api/v1/security/risk-assessments/{assessment_id}/monitoring-settings",
                             json={"monitoringFrequency": frequency})

    def convert_to_risk_assessment(self, assessment_id: str) -> dict:
        """Convert an external scan to a full risk assessment."""
        return self._request("POST", f"/api/v1/security/risk-assessments/{assessment_id}/convert-to-risk-assessment")

    # ─── Risk Progress ────────────────────────────────────────────────

    def get_risk_progress(self, assessment_id: str, current_timestamp: str,
                           compare_timestamp: str = None) -> dict:
        """Get risk progress report comparing two scan timestamps."""
        params = {"currentTimestampGroup": current_timestamp}
        if compare_timestamp:
            params["compareWithTimestampGroup"] = compare_timestamp
        return self._request("GET", f"/api/v1/security/{assessment_id}/risk", params=params)

    # ─── Findings ─────────────────────────────────────────────────────

    def get_finding_details(self, slug: str) -> dict:
        """Get finding details by slug (e.g. TYPO_SQUATTING, PERSONAL_EMAILS)."""
        return self._request("GET", f"/api/v1/security/findings/{slug}")

    # ─── Agent Versions ───────────────────────────────────────────────

    def get_agent_versions(self) -> dict:
        """Get latest Telivy agent versions (Windows/Mac)."""
        return self._request("GET", "/api/v1/security/agent-versions")
