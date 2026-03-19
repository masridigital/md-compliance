"""
Masri Digital Compliance Platform — Telivy API Integration

Wraps the Telivy Security API (https://api-v1.telivy.com) for MSPs.

Authentication: x-api-key header (obtain from Telivy Portal → Account → Integrations)
Base URL: https://api-v1.telivy.com

Supported resources:
  - Risk Assessments  (/api/v1/security/risk-assessments)
  - External Scans    (/api/v1/security/external-scans)
  - Findings & Breach Data
  - Risk Progress Reports
"""

import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

_BASE_URL = "https://api-v1.telivy.com"
_TIMEOUT = 30  # seconds


def _build_session(api_key: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({"x-api-key": api_key, "Content-Type": "application/json"})
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


class TelivyIntegration:
    """
    Client for the Telivy Security API.

    Usage:
        client = TelivyIntegration(api_key="your-key")
        assessments = client.list_risk_assessments()
    """

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("api_key is required")
        self._session = _build_session(api_key)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{_BASE_URL}{path}"
        try:
            resp = self._session.get(url, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            logger.warning("Telivy GET %s → %s", path, e.response.status_code)
            raise RuntimeError(f"Telivy API error {e.response.status_code}: {e.response.text[:200]}") from e
        except requests.RequestException as e:
            logger.exception("Telivy GET %s failed", path)
            raise RuntimeError(f"Telivy request failed: {e}") from e

    def _post(self, path: str, body: dict = None) -> dict:
        url = f"{_BASE_URL}{path}"
        try:
            resp = self._session.post(url, json=body or {}, timeout=_TIMEOUT)
            resp.raise_for_status()
            return resp.json() if resp.content else {}
        except requests.HTTPError as e:
            raise RuntimeError(f"Telivy API error {e.response.status_code}: {e.response.text[:200]}") from e
        except requests.RequestException as e:
            raise RuntimeError(f"Telivy request failed: {e}") from e

    def _put(self, path: str, body: dict = None) -> dict:
        url = f"{_BASE_URL}{path}"
        try:
            resp = self._session.put(url, json=body or {}, timeout=_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            raise RuntimeError(f"Telivy API error {e.response.status_code}: {e.response.text[:200]}") from e
        except requests.RequestException as e:
            raise RuntimeError(f"Telivy request failed: {e}") from e

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------

    def test_connection(self) -> dict:
        """
        Verify credentials and connectivity by fetching agent versions.
        Returns {"connected": True, "windows": "...", "mac": "..."}.
        """
        result = self._get("/api/v1/security/agent-versions")
        return {"connected": True, **result}

    # ------------------------------------------------------------------
    # Risk Assessments
    # ------------------------------------------------------------------

    def list_risk_assessments(
        self,
        search: str = None,
        scan_status: list = None,
        sort_by: str = "createdAt",
        sort_order: str = "DESC",
        offset: int = None,
        limit: int = 100,
    ) -> dict:
        """
        GET /api/v1/security/risk-assessments
        Returns {message, assessments: [...], total}.
        """
        params = {"assessmentSortBy": sort_by, "sortOrder": sort_order, "limit": limit}
        if search:
            params["search"] = search
        if scan_status:
            params["scanStatus"] = scan_status
        if offset is not None:
            params["offset"] = offset
        return self._get("/api/v1/security/risk-assessments", params=params)

    def get_risk_assessment(self, assessment_id: str) -> dict:
        """GET /api/v1/security/risk-assessments/{id}"""
        return self._get(f"/api/v1/security/risk-assessments/{assessment_id}")

    def create_risk_assessment(self, organization_name: str, domain: str, **kwargs) -> dict:
        """POST /api/v1/security/risk-assessments"""
        body = {"organizationName": organization_name, "domain": domain, **kwargs}
        return self._post("/api/v1/security/risk-assessments", body)

    def get_risk_assessment_devices(self, assessment_id: str) -> list:
        """GET /api/v1/security/risk-assessments/{id}/devices"""
        return self._get(f"/api/v1/security/risk-assessments/{assessment_id}/devices")

    def get_risk_progress(
        self,
        assessment_id: str,
        current_timestamp_group: str,
        compare_with_timestamp_group: str = None,
    ) -> dict:
        """
        GET /api/v1/security/{id}/risk
        Returns findings progress report: {scans, report: {new, resolved, regressed, open}}.
        """
        params = {"currentTimestampGroup": current_timestamp_group}
        if compare_with_timestamp_group:
            params["compareWithTimestampGroup"] = compare_with_timestamp_group
        return self._get(f"/api/v1/security/{assessment_id}/risk", params=params)

    # ------------------------------------------------------------------
    # External Scans
    # ------------------------------------------------------------------

    def list_external_scans(
        self,
        search: str = None,
        sort_by: str = "createdAt",
        sort_order: str = "DESC",
        offset: int = None,
        limit: int = 100,
    ) -> dict:
        """
        GET /api/v1/security/external-scans
        Returns {message, assessments: [...], total}.
        """
        params = {"assessmentSortBy": sort_by, "sortOrder": sort_order, "limit": limit}
        if search:
            params["search"] = search
        if offset is not None:
            params["offset"] = offset
        return self._get("/api/v1/security/external-scans", params=params)

    def get_external_scan(self, scan_id: str) -> dict:
        """GET /api/v1/security/external-scans/{id}"""
        return self._get(f"/api/v1/security/external-scans/{scan_id}")

    def get_external_scan_findings(self, scan_id: str) -> list:
        """
        GET /api/v1/security/external-scans/{id}/findings
        Returns list of SecurityFindingDTO.
        """
        return self._get(f"/api/v1/security/external-scans/{scan_id}/findings")

    def get_external_scan_finding_detail(self, scan_id: str, slug: str) -> list:
        """
        GET /api/v1/security/external-scans/{id}/findings/{slug}
        Returns list of SecurityFindingDetailDTO.
        """
        return self._get(f"/api/v1/security/external-scans/{scan_id}/findings/{slug}")

    def get_breach_data(self, scan_id: str) -> list:
        """
        GET /api/v1/security/external-scans/{id}/breach-data
        Returns list of BreachDataDTO.
        """
        return self._get(f"/api/v1/security/external-scans/{scan_id}/breach-data")

    def create_external_scan(self, organization_name: str, domain: str, **kwargs) -> dict:
        """POST /api/v1/security/external-scans"""
        body = {"organizationName": organization_name, "domain": domain, **kwargs}
        return self._post("/api/v1/security/external-scans", body)

    # ------------------------------------------------------------------
    # Global finding catalogue
    # ------------------------------------------------------------------

    def get_finding_by_slug(self, slug: str) -> dict:
        """
        GET /api/v1/security/findings/{slug}
        Returns SecurityFindingDTO (name, description, risk, recommendation, severity).
        """
        return self._get(f"/api/v1/security/findings/{slug}")

    # ------------------------------------------------------------------
    # Convenience: full CSRA data bundle
    # ------------------------------------------------------------------

    def get_csra_bundle(self, assessment_id: str) -> dict:
        """
        Fetch a complete CSRA data bundle for a risk assessment:
          - assessment metadata + executive summary + grades
          - all device targets
          - findings from associated external scan (if available)

        Returns a normalised dict ready for the mapping layer.
        """
        assessment = self.get_risk_assessment(assessment_id)

        bundle = {
            "assessment_id": assessment_id,
            "assessment": assessment,
            "executive_summary": assessment.get("executiveSummary", {}),
            "scan_status": assessment.get("scanStatus"),
            "organization": assessment.get("assessmentDetails", {}).get("organization_name"),
            "domain": assessment.get("assessmentDetails", {}).get("domain_prim"),
            "devices": [],
            "findings": [],
            "breach_data": [],
        }

        # Devices
        try:
            bundle["devices"] = self.get_risk_assessment_devices(assessment_id)
        except RuntimeError as e:
            logger.warning("Could not fetch devices for %s: %s", assessment_id, e)

        return bundle

    def get_external_scan_bundle(self, scan_id: str) -> dict:
        """
        Fetch a complete data bundle for an external scan:
          - scan metadata + security grades
          - all findings (with slug, severity, scanType)
          - breach data

        Returns a normalised dict ready for the mapping layer.
        """
        scan = self.get_external_scan(scan_id)
        findings = []
        breach_data = []

        try:
            findings = self.get_external_scan_findings(scan_id)
        except RuntimeError as e:
            logger.warning("Could not fetch findings for scan %s: %s", scan_id, e)

        try:
            breach_data = self.get_breach_data(scan_id)
        except RuntimeError as e:
            logger.warning("Could not fetch breach data for scan %s: %s", scan_id, e)

        return {
            "scan_id": scan_id,
            "scan": scan,
            "grades": scan.get("grades", {}),
            "security_score": scan.get("securityScore"),
            "organization": scan.get("assessmentDetails", {}).get("organization_name"),
            "domain": scan.get("assessmentDetails", {}).get("domain_prim"),
            "findings": findings if isinstance(findings, list) else [],
            "breach_data": breach_data if isinstance(breach_data, list) else [],
        }
