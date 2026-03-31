"""
Masri Digital Compliance Platform — LLM API Routes

Exposes LLM-powered compliance assistance endpoints:
  - POST /api/v1/llm/control-assist     — Control assessment assistance
  - POST /api/v1/llm/gap-narrative      — Gap analysis narrative generation
  - POST /api/v1/llm/risk-score         — Risk scoring with explanation
  - POST /api/v1/llm/interpret-evidence  — Evidence interpretation
  - GET  /api/v1/llm/usage              — Token/call usage stats

Blueprint: ``llm_bp`` at url_prefix ``/api/v1/llm``
"""

import logging

from flask import Blueprint, jsonify, request, abort, current_app
from flask_login import current_user
from app.utils.decorators import login_required
from app.utils.authorizer import Authorizer
from app import limiter
from app.masri.schemas import (
    validate_payload,
    ControlAssistSchema,
    GapNarrativeSchema,
    RiskScoreSchema,
    InterpretEvidenceSchema,
)

logger = logging.getLogger(__name__)

def _validate_tenant_access(tenant_id):
    """Abort 403 if current_user does not have access to tenant_id."""
    if tenant_id:
        Authorizer(current_user).can_user_access_tenant(tenant_id)

llm_bp = Blueprint("llm_bp", __name__, url_prefix="/api/v1/llm")


def _require_llm():
    """Abort 403 if LLM is not enabled and not configured."""
    # Check env/config flag first
    if current_app.config.get("LLM_ENABLED"):
        return
    # Also check if there's an active LLM config in the database
    try:
        from app.masri.llm_service import LLMService
        if LLMService.is_enabled():
            return
    except Exception:
        pass
    abort(403, description="LLM features are not enabled. Configure an AI provider in Integrations.")


@llm_bp.route("/control-assist", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def control_assist():
    """
    POST /api/v1/llm/control-assist

    Request body:
        {
            "control_description": <str>,
            "evidence_text": <str>,
            "tenant_id": <str, optional>
        }

    Returns LLM assessment of a control against evidence.
    """
    _require_llm()

    data, err = validate_payload(ControlAssistSchema, request.get_json(silent=True))
    if err:
        return err

    control_description = data.get("control_description", "")
    evidence_text = data.get("evidence_text", "")
    tenant_id = data.get("tenant_id")

    _validate_tenant_access(tenant_id)

    try:
        from app.masri.llm_service import LLMService

        result = LLMService.assess_control(
            control_description=control_description,
            evidence_text=evidence_text,
            tenant_id=tenant_id,
        )
        return jsonify({"assessment": result})
    except RuntimeError as e:
        logger.warning("Control assist failed: %s", e)
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        logger.exception("Control assist unexpected error")
        return jsonify({"error": "Internal error during assessment"}), 500


@llm_bp.route("/gap-narrative", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def gap_narrative():
    """
    POST /api/v1/llm/gap-narrative

    Request body:
        {
            "framework": <str>,
            "control_ref": <str>,
            "current_state": <str>,
            "tenant_id": <str, optional>
        }

    Generates a gap analysis narrative for a compliance control.
    """
    _require_llm()

    data, err = validate_payload(GapNarrativeSchema, request.get_json(silent=True))
    if err:
        return err

    framework = data.get("framework", "")
    control_ref = data.get("control_ref", "")
    current_state = data.get("current_state", "")
    tenant_id = data.get("tenant_id")

    _validate_tenant_access(tenant_id)

    try:
        from app.masri.llm_service import LLMService

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a compliance gap analyst. Write a clear, professional "
                    "gap analysis narrative that identifies the gap between the "
                    "current state and the control requirement. Include: "
                    "Gap Description, Risk Impact, and Remediation Steps."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Framework: {framework}\n"
                    f"Control: {control_ref}\n"
                    f"Current state: {current_state or 'Not assessed'}"
                ),
            },
        ]

        result = LLMService.chat(
            messages=messages,
            tenant_id=tenant_id,
            feature="gap_narrative",
            temperature=0.3,
            max_tokens=1500,
        )

        return jsonify({
            "narrative": result["content"],
            "tokens_used": result["usage"]["total_tokens"],
        })
    except RuntimeError as e:
        logger.warning("Gap narrative failed: %s", e)
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        logger.exception("Gap narrative unexpected error")
        return jsonify({"error": "Internal error during generation"}), 500


@llm_bp.route("/risk-score", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def risk_score():
    """
    POST /api/v1/llm/risk-score

    Request body:
        {
            "risk_description": <str>,
            "context": <str, optional>,
            "tenant_id": <str, optional>
        }

    Returns an LLM-generated risk score with explanation.
    """
    _require_llm()

    data, err = validate_payload(RiskScoreSchema, request.get_json(silent=True))
    if err:
        return err

    risk_description = data.get("risk_description", "")
    context = data.get("context", "")
    tenant_id = data.get("tenant_id")

    _validate_tenant_access(tenant_id)

    try:
        from app.masri.llm_service import LLMService
        import json

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a risk assessment specialist. Evaluate the described "
                    "risk and respond with valid JSON: "
                    '{"likelihood": <1-5>, "impact": <1-5>, "overall_score": <1-25>, '
                    '"severity": "low|medium|high|critical", '
                    '"explanation": "<brief explanation>", '
                    '"mitigations": ["<suggested mitigations>"]}'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Risk: {risk_description}\n"
                    f"Context: {context or 'General organization'}"
                ),
            },
        ]

        result = LLMService.chat(
            messages=messages,
            tenant_id=tenant_id,
            feature="risk_score",
            temperature=0.1,
            max_tokens=800,
        )

        content = result["content"].strip()
        # Handle markdown code blocks
        if content.startswith("```"):
            parts = content.split("\n", 1)
            content = parts[1].rsplit("```", 1)[0].strip() if len(parts) > 1 else content

        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            parsed = None

        # Validate parsed structure matches expected schema; fall back to safe defaults
        _valid_severities = {"low", "medium", "high", "critical", "unknown"}
        if (
            not isinstance(parsed, dict)
            or parsed.get("severity") not in _valid_severities
            or not isinstance(parsed.get("likelihood"), int)
            or not isinstance(parsed.get("impact"), int)
        ):
            parsed = {
                "likelihood": 0,
                "impact": 0,
                "overall_score": 0,
                "severity": "unknown",
                "explanation": "Risk score could not be determined.",
                "mitigations": [],
            }

        return jsonify({
            "risk_score": parsed,
            "tokens_used": result["usage"]["total_tokens"],
        })
    except RuntimeError as e:
        logger.warning("Risk score failed: %s", e)
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        logger.exception("Risk score unexpected error")
        return jsonify({"error": "Internal error during scoring"}), 500


@llm_bp.route("/interpret-evidence", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def interpret_evidence():
    """
    POST /api/v1/llm/interpret-evidence

    Request body:
        {
            "evidence_text": <str>,
            "control_context": <str, optional>,
            "tenant_id": <str, optional>
        }

    Interprets uploaded evidence text and extracts compliance-relevant findings.
    """
    _require_llm()

    data, err = validate_payload(InterpretEvidenceSchema, request.get_json(silent=True))
    if err:
        return err

    evidence_text = data.get("evidence_text", "")
    control_context = data.get("control_context", "")
    tenant_id = data.get("tenant_id")

    _validate_tenant_access(tenant_id)

    try:
        from app.masri.llm_service import LLMService

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a compliance evidence analyst. Analyze the provided "
                    "evidence and extract key findings relevant to compliance. "
                    "Summarise what the evidence demonstrates, any gaps, and "
                    "the strength of the evidence (strong/moderate/weak)."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Evidence:\n{evidence_text}\n\n"
                    f"Control context: {control_context or 'General compliance'}"
                ),
            },
        ]

        result = LLMService.chat(
            messages=messages,
            tenant_id=tenant_id,
            feature="evidence_interpret",
            temperature=0.2,
            max_tokens=1200,
        )

        return jsonify({
            "interpretation": result["content"],
            "tokens_used": result["usage"]["total_tokens"],
        })
    except RuntimeError as e:
        logger.warning("Interpret evidence failed: %s", e)
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        logger.exception("Interpret evidence unexpected error")
        return jsonify({"error": "Internal error during interpretation"}), 500


@llm_bp.route("/usage", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def llm_usage():
    """
    GET /api/v1/llm/usage?tenant_id=<id>

    Returns token usage and call statistics for the tenant.
    """
    tenant_id = request.args.get("tenant_id")
    if not tenant_id:
        return jsonify({"error": "tenant_id query parameter is required"}), 400

    _validate_tenant_access(tenant_id)

    try:
        from app.masri.llm_service import LLMService

        usage = LLMService.get_usage(tenant_id)
        return jsonify({"tenant_id": tenant_id, "usage": usage})
    except Exception as e:
        logger.exception("Usage fetch failed")
        return jsonify({"error": "Failed to retrieve usage stats"}), 500


# ===========================================================================
# Auto-Map: Pull integration data and map to controls
# ===========================================================================

@llm_bp.route("/auto-map", methods=["POST"])
@limiter.limit("3 per minute")
@login_required
def auto_map():
    """
    POST /api/v1/llm/auto-map

    Pulls data from all configured integrations (Entra ID, Telivy, etc.)
    for the given project, then uses the LLM to map findings to controls
    and auto-populate evidence/notes.

    Body: { "project_id": "<str>" }

    Returns a list of mappings: control_id, suggested_status, evidence_summary, source.
    """
    _require_llm()
    data = request.get_json(silent=True) or {}
    project_id = data.get("project_id")
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    from app import db
    from app.models import Project

    project = db.session.get(Project, project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    tenant_id = project.tenant_id
    _validate_tenant_access(tenant_id)

    try:
        # 1. Gather all integration data
        integration_data = _gather_integration_data(tenant_id)

        # 2. Get all controls for this project
        controls = []
        for pc in project.controls.all():
            ctrl = pc.control
            if ctrl:
                controls.append({
                    "project_control_id": pc.id,
                    "ref_code": ctrl.ref_code or "",
                    "name": ctrl.name or "",
                    "description": ctrl.description or "",
                    "category": ctrl.category or "",
                    "review_status": pc.review_status or "not started",
                })

        if not controls:
            return jsonify({"error": "Project has no controls", "mappings": []}), 200

        # 3. Send to LLM for mapping
        from app.masri.llm_service import LLMService
        import json

        # Chunk controls to avoid token limits (max ~20 at a time)
        all_mappings = []
        chunk_size = 15
        for i in range(0, len(controls), chunk_size):
            chunk = controls[i:i + chunk_size]
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a compliance automation engine. Given integration data from "
                        "security tools (Entra ID, vulnerability scanners, etc.) and a list of "
                        "compliance controls, map each finding to the most relevant control.\n\n"
                        "Respond with a JSON array of objects:\n"
                        '[{"project_control_id": "...", "suggested_status": "compliant|partial|non_compliant|not_started", '
                        '"evidence_summary": "brief description of what the integration data shows for this control", '
                        '"confidence": 0-100, "source": "entra|telivy|manual", '
                        '"auto_notes": "detailed notes to add to this control"}]\n\n'
                        "Only include controls where you found relevant evidence. "
                        "Be conservative — mark as partial unless evidence is conclusive."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"## Integration Data\n{json.dumps(integration_data, indent=2, default=str)}\n\n"
                        f"## Controls to Map\n{json.dumps(chunk, indent=2)}"
                    ),
                },
            ]

            result = LLMService.chat(
                messages=messages,
                tenant_id=tenant_id,
                feature="auto_map",
                temperature=0.1,
                max_tokens=4000,
            )

            content = result["content"].strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            try:
                parsed = json.loads(content)
                if isinstance(parsed, list):
                    all_mappings.extend(parsed)
            except (json.JSONDecodeError, ValueError):
                logger.warning("LLM auto-map returned non-JSON for chunk %d", i)

        return jsonify({
            "project_id": project_id,
            "mappings": all_mappings,
            "integration_sources": list(integration_data.keys()),
            "total_controls": len(controls),
            "mapped_controls": len(all_mappings),
        })

    except RuntimeError as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        logger.exception("Auto-map failed")
        return jsonify({"error": "Auto-map failed: " + str(e)}), 500


# ===========================================================================
# Assist Gaps: Identify unmapped controls and suggest actions
# ===========================================================================

@llm_bp.route("/assist-gaps", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def assist_gaps():
    """
    POST /api/v1/llm/assist-gaps

    Analyzes a project's controls, identifies gaps (unmapped, missing evidence,
    not started), and provides actionable recommendations for each.

    Body: { "project_id": "<str>" }
    """
    _require_llm()
    data = request.get_json(silent=True) or {}
    project_id = data.get("project_id")
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    from app import db
    from app.models import Project

    project = db.session.get(Project, project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    tenant_id = project.tenant_id
    _validate_tenant_access(tenant_id)

    try:
        # Get controls with their current status
        gap_controls = []
        for pc in project.controls.all():
            ctrl = pc.control
            if ctrl and pc.review_status in ("not started", "not_started", "in progress", "in_progress", None, ""):
                evidence_count = 0
                try:
                    evidence_count = pc.evidence.count() if hasattr(pc, 'evidence') else 0
                except Exception:
                    pass
                gap_controls.append({
                    "project_control_id": pc.id,
                    "ref_code": ctrl.ref_code or "",
                    "name": ctrl.name or "",
                    "description": ctrl.description or "",
                    "category": ctrl.category or "",
                    "review_status": pc.review_status or "not started",
                    "has_evidence": evidence_count > 0,
                    "notes": pc.notes or "",
                })

        if not gap_controls:
            return jsonify({
                "project_id": project_id,
                "message": "All controls are complete! No gaps found.",
                "gaps": [],
            })

        from app.masri.llm_service import LLMService
        import json

        # Send gaps to LLM for recommendations
        all_recommendations = []
        chunk_size = 10
        for i in range(0, len(gap_controls), chunk_size):
            chunk = gap_controls[i:i + chunk_size]
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a compliance consultant. Given a list of compliance controls "
                        "that have gaps (missing evidence, not started, or in progress), provide "
                        "specific, actionable recommendations for each.\n\n"
                        "Respond with a JSON array:\n"
                        '[{"project_control_id": "...", "priority": "high|medium|low", '
                        '"recommendation": "specific action to take", '
                        '"evidence_suggestion": "what evidence to collect", '
                        '"estimated_effort": "quick|moderate|significant", '
                        '"policy_needed": true/false, '
                        '"template_suggestion": "suggested policy/procedure template name if applicable"}]\n\n'
                        "Be specific and practical. Prioritize high-risk items."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Framework: {project.framework.name if project.framework else 'Unknown'}\n"
                        f"## Controls with Gaps\n{json.dumps(chunk, indent=2)}"
                    ),
                },
            ]

            result = LLMService.chat(
                messages=messages,
                tenant_id=tenant_id,
                feature="auto_map",
                temperature=0.2,
                max_tokens=4000,
            )

            content = result["content"].strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            try:
                parsed = json.loads(content)
                if isinstance(parsed, list):
                    all_recommendations.extend(parsed)
            except (json.JSONDecodeError, ValueError):
                logger.warning("LLM assist-gaps returned non-JSON for chunk %d", i)

        return jsonify({
            "project_id": project_id,
            "total_gaps": len(gap_controls),
            "recommendations": all_recommendations,
        })

    except RuntimeError as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        logger.exception("Assist gaps failed")
        return jsonify({"error": "Assist gaps failed: " + str(e)}), 500


@llm_bp.route("/integration-data/<string:project_id>", methods=["GET"])
@limiter.limit("10 per minute")
@login_required
def get_integration_data(project_id):
    """GET /api/v1/llm/integration-data/<project_id> — get live integration data for display."""
    from app import db
    from app.models import Project

    project = db.session.get(Project, project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    tenant_id = project.tenant_id
    try:
        _validate_tenant_access(tenant_id)
    except Exception:
        pass

    try:
        raw = _gather_integration_data(tenant_id)
    except Exception as e:
        logger.exception("Failed to gather integration data for tenant %s", tenant_id)
        raw = {"_error": str(e)}

    # Format for display
    result = {}
    if raw.get("entra_users") or raw.get("entra_mfa") or raw.get("entra_compliance"):
        entra = {}
        if raw.get("entra_users"):
            entra["users"] = raw["entra_users"].get("count", 0)
            entra["user_list"] = raw["entra_users"].get("sample", [])[:10]
        if raw.get("entra_mfa"):
            mfa_list = raw["entra_mfa"]
            if isinstance(mfa_list, list):
                total = len(mfa_list)
                mfa_on = sum(1 for u in mfa_list if u.get("mfa_registered"))
                entra["mfa_rate"] = f"{int(mfa_on/total*100)}%" if total else "N/A"
                entra["mfa_details"] = mfa_list[:10]
            elif isinstance(mfa_list, dict):
                entra["mfa_rate"] = mfa_list.get("mfa_rate", "N/A")
        if raw.get("entra_compliance"):
            entra["score"] = raw["entra_compliance"].get("overall_score", "N/A")
            entra["recommendations"] = raw["entra_compliance"].get("recommendations", [])
            entra["findings"] = raw["entra_compliance"].get("findings", [])
        result["entra"] = entra

    if raw.get("telivy_scans") or raw.get("telivy_findings"):
        telivy = {}
        if raw.get("telivy_scans"):
            telivy["scans"] = raw["telivy_scans"].get("count", 0)
            telivy["scan_details"] = [
                {"id": s.get("id"), "org": s.get("org"), "score": s.get("score"), "status": s.get("status")}
                for s in raw["telivy_scans"].get("scans", [])
            ]
        if raw.get("telivy_findings"):
            telivy["findings_list"] = raw["telivy_findings"].get("findings", [])[:20]
            telivy["findings"] = raw["telivy_findings"].get("count", 0)
        result["telivy"] = telivy

    if raw.get("risk_register"):
        result["risks"] = {
            "count": raw["risk_register"].get("count", 0),
            "items": raw["risk_register"].get("risks", [])[:10],
        }

    if raw.get("_cached_at"):
        result["_cached_at"] = raw["_cached_at"]

    return jsonify(result)


@llm_bp.route("/integration-debug/<string:project_id>", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def debug_integration_mapping(project_id):
    """GET /api/v1/llm/integration-debug/<project_id> — debug mapping info."""
    from app import db
    from app.models import Project, ConfigStore
    import json as _json

    project = db.session.get(Project, project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    tenant_id = project.tenant_id
    tenant_name = project.tenant.name if project.tenant else "unknown"

    # Get all mappings
    mappings = {}
    try:
        record = ConfigStore.find("telivy_scan_mappings")
        if record and record.value:
            mappings = _json.loads(record.value)
    except Exception as e:
        mappings = {"_error": str(e)}

    # Find which IDs map to this tenant
    matched = {k: v for k, v in mappings.items() if v == tenant_id}

    # Check Telivy API key
    has_telivy_key = False
    try:
        result = db.session.execute(
            db.text("SELECT config_enc FROM settings_storage WHERE provider = 'telivy' LIMIT 1")
        ).scalar()
        has_telivy_key = bool(result)
    except Exception:
        pass

    return jsonify({
        "project_id": project_id,
        "tenant_id": tenant_id,
        "tenant_name": tenant_name,
        "all_mappings": mappings,
        "matched_for_tenant": matched,
        "has_telivy_api_key": has_telivy_key,
    })


@llm_bp.route("/auto-process", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def auto_process():
    """
    POST /api/v1/llm/auto-process

    Automatically triggered when a scan/assessment is mapped to a client.
    Steps:
      1. Compile integration data for the tenant
      2. Map findings to project controls via LLM
      3. Add unmatched findings to the risk register
    """
    data = request.get_json(silent=True) or {}
    tenant_id = data.get("tenant_id")
    scan_id = data.get("scan_id")
    scan_type = data.get("scan_type", "scan")
    if not tenant_id:
        return jsonify({"success": False, "error": "tenant_id required"}), 400

    try:
        _validate_tenant_access(tenant_id)
    except Exception:
        pass

    from app import db
    from app.models import Project, RiskRegister, ConfigStore
    import json

    # Step 1: Pull data from Telivy
    integration_data = {}
    telivy_raw = {}

    if scan_id:
        try:
            from app.masri.telivy_routes import _get_telivy_client
            client = _get_telivy_client()

            if scan_type == "scan":
                try:
                    findings = client.get_external_scan_findings(scan_id)
                    if findings:
                        telivy_raw["findings"] = findings[:30] if isinstance(findings, list) else []
                except Exception:
                    pass
                try:
                    scan_detail = client.get_external_scan(scan_id)
                    if scan_detail:
                        telivy_raw["scan"] = scan_detail
                except Exception:
                    pass
            elif scan_type == "assessment":
                try:
                    assessment = client.get_risk_assessment(scan_id)
                    if assessment:
                        telivy_raw["assessment"] = assessment
                except Exception:
                    pass

            if telivy_raw:
                integration_data["telivy"] = telivy_raw
        except Exception as e:
            integration_data["telivy_error"] = str(e)

    # Also pull Entra ID data if configured
    try:
        from app.masri.new_models import SettingsEntra
        entra_cfg = db.session.execute(
            db.select(SettingsEntra).filter_by(tenant_id=None)
        ).scalars().first()
        if entra_cfg and entra_cfg.is_fully_configured():
            from app.masri.entra_integration import EntraIntegration
            creds = entra_cfg.get_credentials()
            entra_client = EntraIntegration(
                tenant_id=creds["entra_tenant_id"],
                client_id=creds["client_id"],
                client_secret=creds["client_secret"],
            )
            entra_raw = {}
            try:
                users = entra_client.list_users()
                entra_raw["users"] = {"count": len(users), "sample": users[:5]}
            except Exception:
                pass
            try:
                mfa = entra_client.get_mfa_status()
                entra_raw["mfa"] = mfa
            except Exception:
                pass
            try:
                compliance = entra_client.assess_compliance()
                entra_raw["compliance"] = compliance
            except Exception:
                pass
            if entra_raw:
                integration_data["entra"] = entra_raw
    except Exception as e:
        logger.debug("Entra data collection in auto-process skipped: %s", e)

    # Store raw data at TENANT level so projects can use it later
    has_any_data = bool(integration_data.get("telivy") or integration_data.get("entra"))
    if has_any_data:
        try:
            existing = {}
            record = ConfigStore.find(f"tenant_integration_data_{tenant_id}")
            if record and record.value:
                try:
                    existing = json.loads(record.value)
                except Exception:
                    pass
            if integration_data.get("telivy"):
                existing["telivy"] = integration_data["telivy"]
            if integration_data.get("entra"):
                existing["entra"] = integration_data["entra"]
            existing["_updated"] = __import__("datetime").datetime.utcnow().isoformat()
            ConfigStore.upsert(f"tenant_integration_data_{tenant_id}", json.dumps(existing, default=str)[:50000])
        except Exception:
            pass

    # Find projects — OK if none exist (data already stored at tenant level)
    projects = db.session.execute(
        db.select(Project).filter_by(tenant_id=tenant_id)
    ).scalars().all()

    if not projects:
        return jsonify({
            "success": has_any_data, "controls_mapped": 0, "risks_added": 0,
            "data_stored": has_any_data,
            "message": "Data saved to client." if has_any_data else "No data pulled.",
            "data_sources": list(integration_data.keys()),
        })

    if not integration_data:
        return jsonify({"success": False, "controls_mapped": 0, "risks_added": 0,
                        "message": "No integration data available.",
                        "data_sources": []})

    # Step 2 + 3: For each project, map to controls and add risks
    total_mapped = 0
    total_risks = 0
    llm_debug = None

    # Check if LLM is available for intelligent mapping
    llm_available = False
    try:
        from app.masri.llm_service import LLMService
        llm_available = LLMService.is_enabled()
    except Exception:
        pass

    for project in projects:
        controls = []
        for pc in project.controls.all():
            ctrl = pc.control
            if ctrl:
                controls.append({
                    "project_control_id": pc.id,
                    "ref_code": ctrl.ref_code or "",
                    "name": ctrl.name or "",
                    "description": ctrl.description or "",
                    "review_status": pc.review_status or "not started",
                })

        if not controls:
            continue

        if llm_available:
            try:
                # Compress integration data into a concise summary for the LLM
                data_summary = _compress_for_llm(integration_data)

                fw_name = project.framework.name if project.framework else "Unknown"

                # Build a clean list of controls with just what the LLM needs
                ctrl_list = "\n".join([
                    f"- [{c['project_control_id']}] {c['ref_code']}: {c['name']}"
                    for c in controls[:30]
                ])

                messages = [
                    {
                        "role": "system",
                        "content": (
                            "You are a compliance analyst. You will receive security scan results "
                            "and a list of compliance controls. You MUST respond with ONLY valid JSON.\n\n"
                            "Analyze the scan data and:\n"
                            "1. Map relevant findings to controls using the project_control_id\n"
                            "2. Create risk entries for findings that don't match any control\n\n"
                            "JSON format (NO other text before or after):\n"
                            '{"mappings":[{"project_control_id":"ID","notes":"what was found","status":"compliant|partial|non_compliant"}],'
                            '"risks":[{"title":"risk name","description":"details","severity":"critical|high|medium|low"}]}'
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Framework: {fw_name}\n\n"
                            f"SCAN RESULTS:\n{data_summary}\n\n"
                            f"CONTROLS:\n{ctrl_list}"
                        ),
                    },
                ]

                result = LLMService.chat(
                    messages=messages,
                    tenant_id=tenant_id,
                    feature="auto_map",
                    temperature=0.2,
                    max_tokens=4096,
                )

                content = result["content"].strip()

                # Strip markdown code blocks
                if content.startswith("```"):
                    parts = content.split("\n", 1)
                    content = parts[1] if len(parts) > 1 else content
                    content = content.rsplit("```", 1)[0].strip()

                # Try to find JSON in the response even if there's extra text
                llm_debug = {"raw_length": len(content), "preview": content[:300]}
                parsed = None
                try:
                    parsed = json.loads(content)
                except (json.JSONDecodeError, ValueError):
                    # Find the outermost JSON object using brace matching
                    brace_start = content.find("{")
                    if brace_start >= 0:
                        depth = 0
                        in_string = False
                        escape_next = False
                        for i in range(brace_start, len(content)):
                            ch = content[i]
                            if escape_next:
                                escape_next = False
                                continue
                            if ch == "\\":
                                escape_next = True
                                continue
                            if ch == '"' and not escape_next:
                                in_string = not in_string
                                continue
                            if in_string:
                                continue
                            if ch == "{":
                                depth += 1
                            elif ch == "}":
                                depth -= 1
                                if depth == 0:
                                    try:
                                        parsed = json.loads(content[brace_start:i+1])
                                    except Exception:
                                        pass
                                    break

                if parsed is None:
                    logger.warning("Auto-process: could not parse LLM response: %s", content[:300])
                    llm_debug["parse_error"] = True
                    parsed = {"mappings": [], "risks": []}
                else:
                    llm_debug["parsed_mappings"] = len(parsed.get("mappings", []))
                    llm_debug["parsed_risks"] = len(parsed.get("risks", []))

                # Apply control mappings (add notes + update status)
                _STATUS_MAP = {
                    "compliant": "complete",
                    "partial": "pending_review",
                    "non_compliant": "info_required",
                    "unknown": "new",
                }
                for m in parsed.get("mappings", []):
                    try:
                        pc_id = m.get("project_control_id")
                        notes = m.get("notes", "")
                        if pc_id and notes:
                            from app.models import ProjectControl
                            pc = db.session.get(ProjectControl, pc_id)
                            if pc:
                                existing = pc.notes or ""
                                pc.notes = f"{existing}\n\n[Auto-Mapped] {notes}".strip()
                                # Update review status based on LLM assessment
                                llm_status = m.get("status", "").lower()
                                new_status = _STATUS_MAP.get(llm_status)
                                if new_status and pc.review_status in ("new", None):
                                    pc.review_status = new_status
                                total_mapped += 1
                    except Exception:
                        pass

                # Add risks to risk register
                _SEVERITY_MAP = {"critical": "critical", "high": "high", "medium": "moderate", "low": "low"}
                for r in parsed.get("risks", []):
                    try:
                        title = r.get("title", "")
                        if title:
                            # Check for duplicate by title_hash
                            title_hash = RiskRegister._compute_title_hash(title, tenant_id)
                            existing_risk = db.session.execute(
                                db.select(RiskRegister).filter_by(title_hash=title_hash, tenant_id=tenant_id)
                            ).scalars().first()
                            if existing_risk:
                                continue  # Skip duplicates
                            severity = _SEVERITY_MAP.get(r.get("severity", "").lower(), "unknown")
                            risk = RiskRegister(
                                title=title,
                                title_hash=title_hash,
                                description=r.get("description", ""),
                                risk=severity,
                                tenant_id=tenant_id,
                            )
                            db.session.add(risk)
                            total_risks += 1
                    except Exception:
                        pass

                db.session.commit()
            except Exception as e:
                logger.warning("LLM auto-process failed for project %s: %s", project.id, e)
        else:
            # No LLM — just add raw data as notes to the first control
            try:
                if controls and integration_data:
                    import json
                    from app.models import ProjectControl
                    pc = db.session.get(ProjectControl, controls[0]["project_control_id"])
                    if pc:
                        pc.notes = (pc.notes or "") + f"\n\n[Integration Data]\n{json.dumps(integration_data, indent=2, default=str)[:500]}"
                        total_mapped += 1
                        db.session.commit()
            except Exception:
                pass

    return jsonify({
        "success": total_mapped > 0 or total_risks > 0,
        "controls_mapped": total_mapped,
        "risks_added": total_risks,
        "projects_processed": len(projects),
        "llm_available": llm_available,
        "data_sources": list(integration_data.keys()) if integration_data else [],
        "llm_debug": llm_debug,
    })


def _compress_for_llm(data: dict) -> str:
    """Compress integration data into a concise text summary for the LLM.

    Instead of dumping raw JSON (which wastes tokens), extract the key
    findings and present them as readable bullet points.
    """
    lines = []

    # Telivy scan data
    telivy = data.get("telivy", {})
    if telivy:
        scan = telivy.get("scan", {})
        assessment = telivy.get("assessment", {})
        findings = telivy.get("findings", [])

        if scan:
            details = scan.get("assessmentDetails", {})
            lines.append(f"Organization: {details.get('organization_name', 'Unknown')}")
            lines.append(f"Domain: {details.get('domain_prim', 'Unknown')}")
            lines.append(f"Security Score: {scan.get('securityScore', 'N/A')}")
            lines.append(f"Scan Status: {scan.get('scanStatus', 'Unknown')}")

        if assessment:
            details = assessment.get("assessmentDetails", {})
            lines.append(f"Organization: {details.get('organization_name', 'Unknown')}")
            lines.append(f"Domain: {details.get('domain_prim', 'Unknown')}")
            lines.append(f"Assessment Status: {assessment.get('scanStatus', 'Unknown')}")
            # Extract executive summary scores
            exec_sum = assessment.get("executiveSummary", {})
            if exec_sum:
                for category, scores in exec_sum.items():
                    if isinstance(scores, dict) and scores.get("securityScore"):
                        lines.append(f"  {category}: Score {scores['securityScore']}")

        if findings:
            lines.append(f"\nFindings ({len(findings)}):")
            for f in findings[:20]:
                if isinstance(f, dict):
                    name = f.get("name", f.get("slug", f.get("title", "Unknown")))
                    severity = f.get("severity", f.get("riskLevel", ""))
                    desc = f.get("description", f.get("details", ""))[:150]
                    lines.append(f"- [{severity}] {name}: {desc}")
                elif isinstance(f, str):
                    lines.append(f"- {f[:150]}")

    # Entra data — handle both auto-process format (data["entra"]["compliance"])
    # and _gather_integration_data format (data["entra_compliance"])
    entra = data.get("entra_compliance", {})
    entra_container = data.get("entra", {})
    if not entra and isinstance(entra_container, dict):
        entra = entra_container.get("compliance", {})
    if entra:
        lines.append(f"\nEntra ID Compliance Score: {entra.get('overall_score', 'N/A')}/100")
        for rec in entra.get("recommendations", [])[:5]:
            lines.append(f"- {rec}")
    # Include MFA data if available
    mfa_data = entra_container.get("mfa") if isinstance(entra_container, dict) else None
    if isinstance(mfa_data, list) and mfa_data:
        total = len(mfa_data)
        mfa_on = sum(1 for u in mfa_data if u.get("mfa_registered"))
        lines.append(f"\nMFA Status: {mfa_on}/{total} users have MFA enabled ({int(mfa_on/total*100) if total else 0}%)")
    # Include user count
    users_data = entra_container.get("users") if isinstance(entra_container, dict) else None
    if isinstance(users_data, dict) and users_data.get("count"):
        lines.append(f"Total Entra Users: {users_data['count']}")

    # Risk register
    risks = data.get("risk_register", {})
    if risks:
        lines.append(f"\nExisting Risks ({risks.get('count', 0)}):")
        for r in risks.get("risks", [])[:5]:
            if isinstance(r, dict):
                lines.append(f"- {r.get('title', 'Unknown')}: {r.get('description', '')[:100]}")

    result = "\n".join(lines)
    # Hard cap at 4000 chars to stay within token limits
    if len(result) > 4000:
        result = result[:4000] + "\n... (data truncated)"
    return result if result.strip() else "No scan data available."


def _gather_integration_data(tenant_id: str) -> dict:
    """Collect all available integration data for a tenant."""
    data = {}

    # Entra ID
    try:
        from app.masri.settings_service import SettingsService
        from app.masri.new_models import SettingsEntra
        from app import db

        entra = db.session.execute(
            db.select(SettingsEntra).filter_by(tenant_id=None)
        ).scalars().first()
        if entra and entra.is_fully_configured():
            from app.masri.entra_integration import EntraIntegration
            creds = entra.get_credentials()
            client = EntraIntegration(
                tenant_id=creds["entra_tenant_id"],
                client_id=creds["client_id"],
                client_secret=creds["client_secret"],
            )
            try:
                users = client.list_users()
                data["entra_users"] = {"count": len(users), "sample": users[:5] if users else []}
            except Exception:
                pass
            try:
                mfa = client.get_mfa_status()
                data["entra_mfa"] = mfa
            except Exception:
                pass
            try:
                assessment = client.assess_compliance()
                data["entra_compliance"] = assessment
            except Exception:
                pass
    except Exception as e:
        logger.debug("Entra data collection skipped: %s", e)

    # Telivy scans — get API key from DB or env, filter by tenant mapping
    try:
        from flask import current_app

        # Get Telivy API key — use same method as telivy_routes._get_telivy_client()
        api_key = None
        try:
            from app import db as _db
            result = _db.session.execute(
                _db.text("SELECT config_enc FROM settings_storage WHERE provider = 'telivy' LIMIT 1")
            ).scalar()
            if result:
                from app.masri.settings_service import decrypt_value
                config = json.loads(decrypt_value(result))
                api_key = config.get("api_key")
        except Exception:
            pass
        if not api_key:
            api_key = current_app.config.get("TELIVY_API_KEY")

        if api_key:
            from app.masri.telivy_integration import TelivyIntegration
            client = TelivyIntegration(api_key=api_key)

            # Get scan-to-tenant mappings from DB — includes stored data
            mapped_items = []
            mapped_ids = set()
            try:
                from app.models import ConfigStore
                import json as _json
                mapping_record = ConfigStore.find("telivy_scan_mappings")
                if mapping_record and mapping_record.value:
                    all_mappings = _json.loads(mapping_record.value)
                    for item_id, mapping in all_mappings.items():
                        # Handle both old format (string) and new format (dict)
                        if isinstance(mapping, str):
                            mapped_tid = mapping
                            item_data = {"id": item_id, "org": item_id, "type": "unknown"}
                        elif isinstance(mapping, dict):
                            mapped_tid = mapping.get("tenant_id", "")
                            item_data = {
                                "id": item_id,
                                "org": mapping.get("org", item_id),
                                "score": mapping.get("score"),
                                "status": mapping.get("status"),
                                "type": mapping.get("type", "unknown"),
                                "domain": mapping.get("domain"),
                            }
                        else:
                            continue
                        if mapped_tid == tenant_id:
                            mapped_items.append(item_data)
                            mapped_ids.add(item_id)
            except Exception:
                pass

            # Use stored mapping data directly (no API call needed for basic display)
            if mapped_items:
                data["telivy_scans"] = {
                    "count": len(mapped_items),
                    "scans": mapped_items,
                }

            # Also try to fetch live findings from Telivy API for richer data
            if mapped_ids and api_key:
                all_findings = []
                for scan_id in list(mapped_ids)[:3]:
                    try:
                        findings = client.get_external_scan_findings(scan_id)
                        if findings:
                            all_findings.extend(findings[:10] if isinstance(findings, list) else [])
                    except Exception:
                        pass
                if all_findings:
                    data["telivy_findings"] = {
                        "count": len(all_findings),
                        "findings": all_findings[:20],
                    }
    except Exception as e:
        logger.debug("Telivy data collection skipped: %s", e)

    # Risk register
    try:
        from app import db
        from app.models import RiskRegister

        risks = db.session.execute(
            db.select(RiskRegister).filter_by(tenant_id=tenant_id)
        ).scalars().all()
        if risks:
            data["risk_register"] = {
                "count": len(risks),
                "risks": [r.as_dict() for r in risks[:10]],
            }
    except Exception as e:
        logger.debug("Risk data collection skipped: %s", e)

    # Merge in cached tenant-level data from ConfigStore (stored by auto-process)
    try:
        from app.models import ConfigStore
        record = ConfigStore.find(f"tenant_integration_data_{tenant_id}")
        if record and record.value:
            cached = json.loads(record.value)
            # If we didn't get live findings, use cached telivy data
            if "telivy_findings" not in data and cached.get("telivy"):
                telivy_cached = cached["telivy"]
                if telivy_cached.get("findings"):
                    data["telivy_findings"] = {
                        "count": len(telivy_cached["findings"]),
                        "findings": telivy_cached["findings"][:20],
                    }
                if "telivy_scans" not in data and telivy_cached.get("scan"):
                    scan = telivy_cached["scan"]
                    details = scan.get("assessmentDetails", {})
                    data["telivy_scans"] = {
                        "count": 1,
                        "scans": [{
                            "id": scan.get("id", ""),
                            "org": details.get("organization_name", "Unknown"),
                            "score": scan.get("securityScore"),
                            "status": scan.get("scanStatus"),
                            "type": "external_scan",
                            "domain": details.get("domain_prim"),
                        }],
                    }
                if "telivy_scans" not in data and telivy_cached.get("assessment"):
                    assessment = telivy_cached["assessment"]
                    details = assessment.get("assessmentDetails", {})
                    data["telivy_scans"] = {
                        "count": 1,
                        "scans": [{
                            "id": assessment.get("id", ""),
                            "org": details.get("organization_name", "Unknown"),
                            "score": assessment.get("securityScore"),
                            "status": assessment.get("scanStatus"),
                            "type": "risk_assessment",
                            "domain": details.get("domain_prim"),
                        }],
                    }
            # Entra cached data
            if "entra_compliance" not in data and cached.get("entra"):
                entra_cached = cached["entra"]
                if entra_cached.get("compliance"):
                    data["entra_compliance"] = entra_cached["compliance"]
                if "entra_users" not in data and entra_cached.get("users"):
                    data["entra_users"] = entra_cached["users"]
                if "entra_mfa" not in data and entra_cached.get("mfa"):
                    data["entra_mfa"] = entra_cached["mfa"]
            data["_cached_at"] = cached.get("_updated")
    except Exception as e:
        logger.debug("ConfigStore cached data read failed: %s", e)

    if not data:
        data["note"] = "No integration data available. Configure Entra ID or Telivy in Integrations."

    return data
