"""
Masri Digital Compliance Platform — Telivy API Routes

Blueprint: telivy_bp at url_prefix /api/v1/telivy

Endpoints
─────────
Settings (platform-admin only):
  GET  /api/v1/telivy/config          — Get current Telivy config
  PUT  /api/v1/telivy/config          — Save / update API key + settings
  POST /api/v1/telivy/test            — Test connection to Telivy API

Risk Assessments:
  GET  /api/v1/telivy/risk-assessments          — List all risk assessments
  GET  /api/v1/telivy/risk-assessments/<id>     — Get single assessment
  POST /api/v1/telivy/risk-assessments          — Create a new assessment
  GET  /api/v1/telivy/risk-assessments/<id>/devices   — List assessment devices
  POST /api/v1/telivy/risk-assessments/<id>/sync      — Sync CSRA to a project

External Scans:
  GET  /api/v1/telivy/external-scans            — List all external scans
  GET  /api/v1/telivy/external-scans/<id>       — Get single scan
  POST /api/v1/telivy/external-scans            — Create a new external scan
  GET  /api/v1/telivy/external-scans/<id>/findings       — Get findings
  GET  /api/v1/telivy/external-scans/<id>/breach-data    — Get breach data
  POST /api/v1/telivy/external-scans/<id>/sync           — Sync scan to project

Utility:
  GET  /api/v1/telivy/supported-frameworks      — List mappable frameworks
"""

import logging
import json
from datetime import datetime

from flask import Blueprint, jsonify, request, abort
from flask_login import current_user
from app.utils.decorators import login_required
from app.utils.authorizer import Authorizer
from app import db, limiter
from app.masri.schemas import validate_payload, TelivyConfigSchema, TelivySyncSchema, TelivyCreateAssessmentSchema

logger = logging.getLogger(__name__)

telivy_bp = Blueprint("telivy_bp", __name__, url_prefix="/api/v1/telivy")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_platform_admin():
    """Abort 403 if current user is not a platform superuser."""
    Authorizer(current_user).can_user_manage_platform()


def _get_client():
    """Build a TelivyIntegration from stored settings. Raises RuntimeError if not configured."""
    from app.masri.settings_service import SettingsService
    from app.masri.telivy_integration import TelivyIntegration

    config = SettingsService.get_telivy_config()
    if not config or not config.get("api_key"):
        raise RuntimeError("Telivy is not configured. Add an API key in Settings → Telivy.")
    if not config.get("enabled"):
        raise RuntimeError("Telivy integration is disabled. Enable it in Settings → Telivy.")

    return TelivyIntegration(api_key=config["api_key"])


def _json_err(message: str, status: int):
    return jsonify({"error": message}), status


# ---------------------------------------------------------------------------
# Config / Settings
# ---------------------------------------------------------------------------

@telivy_bp.route("/config", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def get_config():
    """GET /api/v1/telivy/config — Return current Telivy settings (key masked)."""
    _require_platform_admin()
    from app.masri.settings_service import SettingsService
    cfg = SettingsService.get_telivy_config()
    if cfg is None:
        return jsonify({"enabled": False, "has_api_key": False})
    return jsonify(cfg)


@telivy_bp.route("/config", methods=["PUT"])
@limiter.limit("10 per minute")
@login_required
def update_config():
    """PUT /api/v1/telivy/config — Save API key and enable/disable integration."""
    _require_platform_admin()
    data, err = validate_payload(TelivyConfigSchema, request.get_json(silent=True))
    if err:
        return err
    try:
        from app.masri.settings_service import SettingsService
        result = SettingsService.update_telivy_config(data)
        return jsonify(result)
    except ValueError as e:
        return _json_err(str(e), 400)


@telivy_bp.route("/test", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def test_connection():
    """POST /api/v1/telivy/test — Verify API key by calling Telivy agent-versions endpoint."""
    _require_platform_admin()
    try:
        client = _get_client()
        result = client.test_connection()
        return jsonify(result)
    except RuntimeError as e:
        return _json_err(str(e), 400)
    except Exception:
        logger.exception("Telivy connection test failed")
        return _json_err("Connection test failed", 500)


# ---------------------------------------------------------------------------
# Risk Assessments — read-through
# ---------------------------------------------------------------------------

@telivy_bp.route("/risk-assessments", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def list_risk_assessments():
    """GET /api/v1/telivy/risk-assessments — Proxy list from Telivy."""
    try:
        client = _get_client()
        params = {
            "search":      request.args.get("search"),
            "sort_by":     request.args.get("sortBy", "createdAt"),
            "sort_order":  request.args.get("sortOrder", "DESC"),
            "limit":       request.args.get("limit", 100, type=int),
            "offset":      request.args.get("offset", type=int),
        }
        result = client.list_risk_assessments(**{k: v for k, v in params.items() if v is not None})
        return jsonify(result)
    except RuntimeError as e:
        return _json_err(str(e), 502)
    except Exception:
        logger.exception("list_risk_assessments failed")
        return _json_err("Failed to fetch risk assessments", 500)


@telivy_bp.route("/risk-assessments/<string:assessment_id>", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def get_risk_assessment(assessment_id):
    """GET /api/v1/telivy/risk-assessments/<id>"""
    try:
        client = _get_client()
        return jsonify(client.get_risk_assessment(assessment_id))
    except RuntimeError as e:
        return _json_err(str(e), 502)
    except Exception:
        logger.exception("get_risk_assessment failed")
        return _json_err("Failed to fetch assessment", 500)


@telivy_bp.route("/risk-assessments", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def create_risk_assessment():
    """POST /api/v1/telivy/risk-assessments — Create a new Telivy risk assessment."""
    data, err = validate_payload(TelivyCreateAssessmentSchema, request.get_json(silent=True))
    if err:
        return err
    try:
        client = _get_client()
        result = client.create_risk_assessment(
            organization_name=data["organizationName"],
            domain=data["domain"],
            **{k: v for k, v in data.items() if k not in ("organizationName", "domain") and v is not None},
        )
        return jsonify(result), 201
    except RuntimeError as e:
        return _json_err(str(e), 502)
    except Exception:
        logger.exception("create_risk_assessment failed")
        return _json_err("Failed to create assessment", 500)


@telivy_bp.route("/risk-assessments/<string:assessment_id>/devices", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def get_risk_assessment_devices(assessment_id):
    """GET /api/v1/telivy/risk-assessments/<id>/devices"""
    try:
        client = _get_client()
        return jsonify(client.get_risk_assessment_devices(assessment_id))
    except RuntimeError as e:
        return _json_err(str(e), 502)
    except Exception:
        logger.exception("get_risk_assessment_devices failed")
        return _json_err("Failed to fetch devices", 500)


# ---------------------------------------------------------------------------
# External Scans — read-through
# ---------------------------------------------------------------------------

@telivy_bp.route("/external-scans", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def list_external_scans():
    """GET /api/v1/telivy/external-scans"""
    try:
        client = _get_client()
        params = {
            "search":     request.args.get("search"),
            "sort_by":    request.args.get("sortBy", "createdAt"),
            "sort_order": request.args.get("sortOrder", "DESC"),
            "limit":      request.args.get("limit", 100, type=int),
            "offset":     request.args.get("offset", type=int),
        }
        result = client.list_external_scans(**{k: v for k, v in params.items() if v is not None})
        return jsonify(result)
    except RuntimeError as e:
        return _json_err(str(e), 502)
    except Exception:
        logger.exception("list_external_scans failed")
        return _json_err("Failed to fetch external scans", 500)


@telivy_bp.route("/external-scans/<string:scan_id>", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def get_external_scan(scan_id):
    """GET /api/v1/telivy/external-scans/<id>"""
    try:
        client = _get_client()
        return jsonify(client.get_external_scan(scan_id))
    except RuntimeError as e:
        return _json_err(str(e), 502)
    except Exception:
        logger.exception("get_external_scan failed")
        return _json_err("Failed to fetch external scan", 500)


@telivy_bp.route("/external-scans", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def create_external_scan():
    """POST /api/v1/telivy/external-scans"""
    data, err = validate_payload(TelivyCreateAssessmentSchema, request.get_json(silent=True))
    if err:
        return err
    try:
        client = _get_client()
        result = client.create_external_scan(
            organization_name=data["organizationName"],
            domain=data["domain"],
        )
        return jsonify(result), 201
    except RuntimeError as e:
        return _json_err(str(e), 502)
    except Exception:
        logger.exception("create_external_scan failed")
        return _json_err("Failed to create external scan", 500)


@telivy_bp.route("/external-scans/<string:scan_id>/findings", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def get_external_scan_findings(scan_id):
    """GET /api/v1/telivy/external-scans/<id>/findings"""
    try:
        client = _get_client()
        return jsonify(client.get_external_scan_findings(scan_id))
    except RuntimeError as e:
        return _json_err(str(e), 502)
    except Exception:
        logger.exception("get_external_scan_findings failed")
        return _json_err("Failed to fetch findings", 500)


@telivy_bp.route("/external-scans/<string:scan_id>/breach-data", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def get_breach_data(scan_id):
    """GET /api/v1/telivy/external-scans/<id>/breach-data"""
    try:
        client = _get_client()
        return jsonify(client.get_breach_data(scan_id))
    except RuntimeError as e:
        return _json_err(str(e), 502)
    except Exception:
        logger.exception("get_breach_data failed")
        return _json_err("Failed to fetch breach data", 500)


# ---------------------------------------------------------------------------
# Sync — the core compliance mapping operation
# ---------------------------------------------------------------------------

@telivy_bp.route("/risk-assessments/<string:assessment_id>/sync", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def sync_risk_assessment(assessment_id):
    """
    POST /api/v1/telivy/risk-assessments/<id>/sync

    Pulls a Telivy risk assessment and maps it into a compliance project.

    Request body:
      {
        "project_id":       "<project UUID>",    required
        "tenant_id":        "<tenant UUID>",      required
        "framework":        "nist_csf",           required — must match project framework name
        "create_evidence":  true,                 optional (default true)
        "create_risks":     true,                 optional (default true) — create RiskRegister entries
        "dry_run":          false                 optional — return preview without writing
      }

    Response:
      {
        "synced":    true,
        "dry_run":   false,
        "controls_updated":  12,
        "evidence_created":  1,
        "risks_created":     4,
        "preview":   { ... }   (only present when dry_run=true)
      }
    """
    data, err = validate_payload(TelivySyncSchema, request.get_json(silent=True))
    if err:
        return err

    project_id    = data["project_id"]
    tenant_id     = data["tenant_id"]
    framework     = data["framework"]
    create_ev     = data.get("create_evidence", True)
    create_risks  = data.get("create_risks", True)
    dry_run       = data.get("dry_run", False)

    # Authorization — user must have access to the project
    Authorizer(current_user).can_user_access_project(project_id)

    try:
        client = _get_client()
        bundle = client.get_csra_bundle(assessment_id)
    except RuntimeError as e:
        return _json_err(str(e), 502)
    except Exception:
        logger.exception("Failed to fetch Telivy CSRA bundle %s", assessment_id)
        return _json_err("Failed to fetch Telivy data", 500)

    try:
        result = _apply_csra_sync(
            bundle=bundle,
            project_id=project_id,
            tenant_id=tenant_id,
            framework=framework,
            create_evidence=create_ev,
            create_risks=create_risks,
            dry_run=dry_run,
            source_type="risk_assessment",
        )
        return jsonify(result)
    except Exception:
        logger.exception("CSRA sync failed for assessment %s → project %s", assessment_id, project_id)
        return _json_err("Sync failed — see server logs", 500)


@telivy_bp.route("/external-scans/<string:scan_id>/sync", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def sync_external_scan(scan_id):
    """
    POST /api/v1/telivy/external-scans/<id>/sync

    Same contract as risk-assessment sync but uses external scan bundle
    (SecurityGradesDTO instead of ExecutiveSummaryDTO).
    """
    data, err = validate_payload(TelivySyncSchema, request.get_json(silent=True))
    if err:
        return err

    project_id   = data["project_id"]
    tenant_id    = data["tenant_id"]
    framework    = data["framework"]
    create_ev    = data.get("create_evidence", True)
    create_risks = data.get("create_risks", True)
    dry_run      = data.get("dry_run", False)

    Authorizer(current_user).can_user_access_project(project_id)

    try:
        client = _get_client()
        bundle = client.get_external_scan_bundle(scan_id)
    except RuntimeError as e:
        return _json_err(str(e), 502)
    except Exception:
        logger.exception("Failed to fetch Telivy external scan bundle %s", scan_id)
        return _json_err("Failed to fetch Telivy data", 500)

    try:
        result = _apply_csra_sync(
            bundle=bundle,
            project_id=project_id,
            tenant_id=tenant_id,
            framework=framework,
            create_evidence=create_ev,
            create_risks=create_risks,
            dry_run=dry_run,
            source_type="external_scan",
        )
        return jsonify(result)
    except Exception:
        logger.exception("External scan sync failed %s → project %s", scan_id, project_id)
        return _json_err("Sync failed — see server logs", 500)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

@telivy_bp.route("/supported-frameworks", methods=["GET"])
@login_required
def supported_frameworks():
    """GET /api/v1/telivy/supported-frameworks — List frameworks supported by the mapper."""
    from app.masri.telivy_mapping import supported_frameworks as _sf
    return jsonify({"frameworks": _sf()})


# ---------------------------------------------------------------------------
# Core sync logic
# ---------------------------------------------------------------------------

def _apply_csra_sync(
    bundle: dict,
    project_id: str,
    tenant_id: str,
    framework: str,
    create_evidence: bool,
    create_risks: bool,
    dry_run: bool,
    source_type: str,
) -> dict:
    """
    Map Telivy data onto a compliance project.

    Writes:
      1. ProjectSubControl.implemented updated for each matched control
      2. ProjectEvidence record (one per sync run) linking to matched subcontrols
      3. RiskRegister entries for high/critical severity findings

    Returns a summary dict.
    """
    from app.masri import telivy_mapping as tm
    from app import models

    # ── 1. Build category mappings from the bundle ──────────────────────────
    if source_type == "risk_assessment":
        exec_summary = bundle.get("executive_summary", {})
        category_mappings = tm.map_executive_summary(exec_summary, framework)
        findings_raw = bundle.get("findings", [])
    else:
        grades = bundle.get("grades", {})
        category_mappings = tm.map_grades(grades, framework)
        findings_raw = bundle.get("findings", [])

    finding_mappings = tm.map_findings_to_controls(findings_raw, framework)

    # ── 2. Collect all ref_codes we need to match ───────────────────────────
    all_ref_codes = set()
    for m in category_mappings:
        all_ref_codes.update(m["ref_codes"])
    for m in finding_mappings:
        all_ref_codes.update(m["ref_codes"])

    if not all_ref_codes:
        return {
            "synced": not dry_run,
            "dry_run": dry_run,
            "controls_updated": 0,
            "evidence_created": 0,
            "risks_created": 0,
            "warning": f"No controls mapped for framework '{framework}'. "
                       f"Check that this framework name matches the project's framework.",
        }

    # ── 3. Resolve project controls from the DB ─────────────────────────────
    # Find ProjectSubControl rows whose parent Control.ref_code is in our set
    matched_subcontrols = (
        db.session.execute(
            db.select(models.ProjectSubControl)
            .join(models.ProjectControl, models.ProjectSubControl.project_control_id == models.ProjectControl.id)
            .join(models.Control, models.ProjectControl.control_id == models.Control.id)
            .where(
                models.ProjectSubControl.project_id == project_id,
                models.Control.ref_code.in_(list(all_ref_codes)),
            )
        )
        .scalars()
        .all()
    )

    # Build ref_code → [subcontrols] index
    from collections import defaultdict
    ref_to_subs: dict[str, list] = defaultdict(list)
    for sub in matched_subcontrols:
        ref_code = sub.p_control.control.ref_code
        ref_to_subs[ref_code].append(sub)

    controls_updated = 0
    subcontrol_ids_for_evidence = []

    if not dry_run:
        # ── 4a. Apply category-level grades ────────────────────────────────
        for mapping in category_mappings:
            impl_value = mapping["implemented"]
            if impl_value is None:
                continue
            for ref_code in mapping["ref_codes"]:
                for sub in ref_to_subs.get(ref_code, []):
                    sub.implemented = impl_value
                    subcontrol_ids_for_evidence.append(sub.id)
                    controls_updated += 1

        # ── 4b. Finding-level overrides (higher severity wins) ─────────────
        # Findings are often more severe — only downgrade if current is higher
        for mapping in finding_mappings:
            finding_impl = _severity_to_implemented(mapping["severity"])
            for ref_code in mapping["ref_codes"]:
                for sub in ref_to_subs.get(ref_code, []):
                    if sub.implemented > finding_impl:
                        sub.implemented = finding_impl
                        if sub.id not in subcontrol_ids_for_evidence:
                            subcontrol_ids_for_evidence.append(sub.id)
                            controls_updated += 1

        db.session.flush()

        # ── 5. Create evidence ──────────────────────────────────────────────
        evidence_created = 0
        if create_evidence and subcontrol_ids_for_evidence:
            evidence_content = tm.build_evidence_content(
                assessment_type=source_type,
                assessment_id=bundle.get("assessment_id") or bundle.get("scan_id", ""),
                organization=bundle.get("organization", ""),
                domain=bundle.get("domain", ""),
                category_mappings=category_mappings,
                finding_mappings=finding_mappings,
            )
            ev_name = (
                f"Telivy CSRA — {bundle.get('organization', 'Unknown')} "
                f"({datetime.utcnow().strftime('%Y-%m-%d')})"
            )
            evidence = models.ProjectEvidence(
                name=ev_name[:255],
                description=f"Automatically imported from Telivy {source_type.replace('_', ' ')}.",
                content=evidence_content,
                group="telivy",
                project_id=project_id,
                tenant_id=tenant_id,
                owner_id=current_user.id,
            )
            db.session.add(evidence)
            db.session.flush()

            # Associate evidence with matched subcontrols
            for sub_id in set(subcontrol_ids_for_evidence):
                models.EvidenceAssociation.add(sub_id, evidence.id)

            evidence_created = 1

        # ── 6. Create risks ─────────────────────────────────────────────────
        risks_created = 0
        if create_risks:
            for mapping in finding_mappings:
                if mapping["severity"] not in ("high", "medium"):
                    continue
                risk_title = f"[Telivy] {mapping['name']}"
                # Avoid duplicates within the same tenant
                existing = db.session.execute(
                    db.select(models.RiskRegister).where(
                        models.RiskRegister.tenant_id == tenant_id,
                        models.RiskRegister.title == risk_title,
                    )
                ).scalars().first()
                if existing:
                    continue

                risk = models.RiskRegister(
                    title=risk_title[:255],
                    description=mapping.get("description", "") or f"Telivy finding: {mapping['slug']}",
                    remediation=mapping.get("recommendation", ""),
                    risk=mapping["risk_level"],
                    status="new",
                    tenant_id=tenant_id,
                    project_id=project_id,
                )
                db.session.add(risk)
                risks_created += 1

        db.session.commit()

    else:
        # dry_run — compute preview only, no writes
        evidence_created = 0
        risks_created = sum(
            1 for m in finding_mappings if m["severity"] in ("high", "medium")
        )

    return {
        "synced":           not dry_run,
        "dry_run":          dry_run,
        "controls_updated": controls_updated if not dry_run else len(matched_subcontrols),
        "evidence_created": evidence_created,
        "risks_created":    risks_created,
        "preview": {
            "category_mappings":  len(category_mappings),
            "finding_mappings":   len(finding_mappings),
            "matched_ref_codes":  sorted(all_ref_codes),
            "matched_subcontrols": len(matched_subcontrols),
        } if dry_run else None,
    }


def _severity_to_implemented(severity: str) -> int:
    """High severity finding → low implementation score."""
    return {"high": 0, "medium": 1, "low": 2, "info": 2}.get(severity, 1)
