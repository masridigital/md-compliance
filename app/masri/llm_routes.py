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
    if not tenant_id:
        return jsonify({"success": False, "error": "tenant_id required"}), 400

    _validate_tenant_access(tenant_id)

    from app import db
    from app.models import Project, RiskRegister

    # Find projects for this tenant
    projects = db.session.execute(
        db.select(Project).filter_by(tenant_id=tenant_id)
    ).scalars().all()

    if not projects:
        return jsonify({"success": True, "controls_mapped": 0, "risks_added": 0,
                        "message": "No projects found for this tenant"})

    # Step 1: Compile integration data
    try:
        integration_data = _gather_integration_data(tenant_id)
    except Exception as e:
        return jsonify({"success": False, "error": f"Data compilation failed: {e}"}), 500

    if not integration_data or (not integration_data.get("telivy_scans") and not integration_data.get("entra_compliance") and not integration_data.get("risk_register")):
        return jsonify({"success": True, "controls_mapped": 0, "risks_added": 0,
                        "message": "No integration data found",
                        "debug_keys": list(integration_data.keys()) if integration_data else [],
                        "debug_note": integration_data.get("note", "")})

    # Step 2 + 3: For each project, map to controls and add risks
    total_mapped = 0
    total_risks = 0

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
            # Use LLM to intelligently map findings to controls
            try:
                import json
                messages = [
                    {
                        "role": "system",
                        "content": (
                            "You are a compliance automation engine. Given security scan data "
                            "and a list of compliance controls, do two things:\n"
                            "1. Map each finding to the most relevant control and suggest a status\n"
                            "2. List any findings that don't map to existing controls (these become risks)\n\n"
                            "Respond with JSON: {\"mappings\": [{\"project_control_id\": \"...\", "
                            "\"notes\": \"what the scan data shows for this control\"}], "
                            "\"risks\": [{\"title\": \"...\", \"description\": \"...\", \"severity\": \"high|medium|low\"}]}"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"## Integration Data\n{json.dumps(integration_data, indent=2, default=str)[:3000]}\n\n"
                            f"## Controls ({len(controls)})\n{json.dumps(controls[:20], indent=2)}"
                        ),
                    },
                ]

                result = LLMService.chat(
                    messages=messages,
                    tenant_id=tenant_id,
                    feature="auto_map",
                    temperature=0.1,
                    max_tokens=3000,
                )

                content = result["content"].strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

                try:
                    parsed = json.loads(content)
                except (json.JSONDecodeError, ValueError):
                    logger.warning("Auto-process LLM returned non-JSON: %s", content[:200])
                    parsed = {"mappings": [], "risks": []}

                # Apply control mappings (add notes)
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
                                total_mapped += 1
                    except Exception:
                        pass

                # Add risks to risk register
                for r in parsed.get("risks", []):
                    try:
                        title = r.get("title", "")
                        if title:
                            risk = RiskRegister(
                                title=title,
                                description=r.get("description", ""),
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
    })


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
            from app.masri.entra_integration import EntraClient
            creds = entra.get_credentials()
            client = EntraClient(
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
                        findings = client.get_scan_findings(scan_id)
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

    if not data:
        data["note"] = "No integration data available. Configure Entra ID or Telivy in Integrations."

    return data
