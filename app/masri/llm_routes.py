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
        return jsonify({"error": "LLM service request failed. Check provider configuration."}), 502
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
        return jsonify({"error": "LLM service request failed. Check provider configuration."}), 502
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
        return jsonify({"error": "LLM service request failed. Check provider configuration."}), 502
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
        return jsonify({"error": "LLM service request failed. Check provider configuration."}), 502
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
        return jsonify({"error": "LLM service request failed. Check provider configuration."}), 502
    except Exception as e:
        logger.exception("Auto-map failed")
        return jsonify({"error": "Auto-map failed. Check system logs for details."}), 500


# ===========================================================================
# Assist Gaps: Identify unmapped controls and suggest actions
# ===========================================================================

def _bg_assist_gaps(app, project_id, tenant_id):
    """Background worker for assist-gaps. Runs in thread, never blocks gunicorn."""
    import json
    with app.app_context():
        from app import db
        from app.models import Project, ConfigStore

        try:
            db.session.remove()
        except Exception:
            pass

        project = db.session.get(Project, project_id)
        if not project:
            return

        gap_controls = []
        for pc in project.controls.all():
            ctrl = pc.control
            if not ctrl:
                continue
            status = (pc.review_status or "").lower().strip()
            if status in ("complete", "ready for auditor"):
                continue
            evidence_count = 0
            try:
                evidence_count = pc.evidence.count() if hasattr(pc, 'evidence') else 0
            except Exception:
                pass
            gap_controls.append({
                "project_control_id": pc.id,
                "ref_code": ctrl.ref_code or "",
                "name": ctrl.name or "",
                "description": (ctrl.description or "")[:200],
                "category": ctrl.category or "",
                "review_status": pc.review_status or "infosec action",
                "has_evidence": evidence_count > 0,
                "notes": (pc.notes or "")[:200],
            })

        if not gap_controls:
            try:
                ConfigStore.upsert(f"assist_gaps_result_{project_id}", json.dumps({
                    "project_id": project_id,
                    "message": "All controls are complete! No gaps found.",
                    "total_gaps": 0,
                    "recommendations": [],
                }))
            except Exception:
                pass
            return

        try:
            from app.masri.llm_service import LLMService

            integration_context = ""
            try:
                raw = _gather_integration_data(tenant_id)
                integration_context = _compress_for_llm(raw) if raw else ""
            except Exception:
                pass

            fw_name = project.framework.name if project.framework else "Unknown"

            all_recommendations = []
            chunk_size = 10
            for i in range(0, len(gap_controls), chunk_size):
                chunk = gap_controls[i:i + chunk_size]
                ctrl_text = "\n".join([
                    f"- [{c['project_control_id']}] {c['ref_code']}: {c['name']}"
                    f" (status: {c['review_status']}, evidence: {'yes' if c['has_evidence'] else 'none'})"
                    + (f" | Notes: {c['notes'][:100]}" if c['notes'] else "")
                    for c in chunk
                ])

                messages = [
                    {
                        "role": "system",
                        "content": (
                            f"You are a compliance consultant specializing in {fw_name}. "
                            "You will receive controls that have gaps, along with security data from "
                            "Telivy vulnerability scans and/or Microsoft 365.\n\n"
                            "For EACH control, provide specific, actionable recommendations.\n"
                            "You MUST respond with ONLY a valid JSON array:\n"
                            '[{"project_control_id":"ID","priority":"high","recommendation":"specific action",'
                            '"evidence_suggestion":"specific source","estimated_effort":"quick",'
                            '"policy_needed":false,"template_suggestion":""}]\n\n'
                            "Rules: include ALL controls, priority=high|medium|low, "
                            "estimated_effort=quick|moderate|significant"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Framework: {fw_name}\n\n"
                            + (f"SCAN DATA:\n{integration_context}\n\n" if integration_context and integration_context != "No scan data available." else "")
                            + f"CONTROLS ({len(chunk)}):\n{ctrl_text}"
                        ),
                    },
                ]

                try:
                    result = LLMService.chat(
                        messages=messages, tenant_id=tenant_id,
                        feature="assist_gaps", temperature=0.3, max_tokens=4096,
                    )
                    content = result["content"].strip()
                    if content.startswith("```"):
                        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

                    parsed = None
                    try:
                        parsed = json.loads(content)
                    except (json.JSONDecodeError, ValueError):
                        bs = content.find("[")
                        be = content.rfind("]")
                        if bs >= 0 and be > bs:
                            try:
                                parsed = json.loads(content[bs:be + 1])
                            except Exception:
                                pass

                    if parsed and isinstance(parsed, list):
                        all_recommendations.extend(parsed)
                    elif parsed and isinstance(parsed, dict) and "recommendations" in parsed:
                        all_recommendations.extend(parsed["recommendations"])
                    else:
                        for c in chunk:
                            all_recommendations.append({
                                "project_control_id": c["project_control_id"],
                                "priority": "medium",
                                "recommendation": f"Review control {c['ref_code']} ({c['name']}) and gather required evidence.",
                                "evidence_suggestion": "Document current implementation status.",
                                "estimated_effort": "moderate",
                                "policy_needed": False, "template_suggestion": "",
                            })
                except Exception as e:
                    logger.warning("Assist-gaps chunk %d failed: %s", i, e)

            ConfigStore.upsert(f"assist_gaps_result_{project_id}", json.dumps({
                "project_id": project_id,
                "total_gaps": len(gap_controls),
                "recommendations": all_recommendations,
            }, default=str))

        except Exception as e:
            logger.exception("Assist gaps background failed for project %s", project_id)
            try:
                ConfigStore.upsert(f"assist_gaps_result_{project_id}", json.dumps({
                    "project_id": project_id,
                    "error": "Analysis failed. Check system logs.",
                    "total_gaps": len(gap_controls),
                    "recommendations": [],
                }))
            except Exception:
                pass

        try:
            db.session.remove()
        except Exception:
            pass


@llm_bp.route("/assist-gaps", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def assist_gaps():
    """POST /api/v1/llm/assist-gaps — kicks off background gap analysis."""
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

    _validate_tenant_access(project.tenant_id)

    import threading
    app = current_app._get_current_object()
    t = threading.Thread(
        target=_bg_assist_gaps,
        args=(app, project_id, project.tenant_id),
        daemon=True,
    )
    t.start()

    return jsonify({"success": True, "message": "Analysis started in background."})


@llm_bp.route("/assist-gaps-status/<string:project_id>", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def assist_gaps_status(project_id):
    """GET /api/v1/llm/assist-gaps-status/<project_id> — poll for results."""
    import json
    from app import db
    from app.models import Project, ConfigStore

    project = db.session.get(Project, project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404
    _validate_tenant_access(project.tenant_id)

    try:
        record = ConfigStore.find(f"assist_gaps_result_{project_id}")
        if record and record.value:
            return jsonify(json.loads(record.value))
    except Exception:
        pass
    return jsonify({"status": "processing"})


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
    _validate_tenant_access(tenant_id)

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
            # Return full finding objects with all details for expandable UI
            telivy["findings_list"] = raw["telivy_findings"].get("findings", [])[:50]
            telivy["findings"] = raw["telivy_findings"].get("count", 0)
        result["telivy"] = telivy

    # Microsoft Security data (from cached collect_all_security_data)
    import json as _json_local
    ms_cached = raw.get("microsoft") or {}
    if not ms_cached:
        # Try reading from ConfigStore cache
        try:
            from app.models import ConfigStore as _CS
            _rec = _CS.find(f"tenant_integration_data_{tenant_id}")
            if _rec and _rec.value:
                _cached = _json_local.loads(_rec.value)
                ms_cached = _cached.get("microsoft", {})
        except Exception:
            pass
    if ms_cached:
        microsoft = {}
        if ms_cached.get("secure_score"):
            ss = ms_cached["secure_score"]
            microsoft["secure_score"] = {
                "current": ss.get("current_score", 0),
                "max": ss.get("max_score", 0),
                "controls": ss.get("control_scores", [])[:15],
            }
        if ms_cached.get("security_alerts"):
            sa = ms_cached["security_alerts"]
            microsoft["alerts"] = {
                "count": sa.get("count", 0),
                "by_severity": sa.get("by_severity", {}),
                "items": sa.get("alerts", [])[:20],
            }
        if ms_cached.get("devices"):
            microsoft["devices"] = ms_cached["devices"]
        if ms_cached.get("risky_users"):
            microsoft["risky_users"] = ms_cached["risky_users"][:20]
        if ms_cached.get("risk_detections"):
            microsoft["risk_detections"] = ms_cached["risk_detections"][:20]
        if ms_cached.get("sign_in_summary"):
            microsoft["sign_ins"] = ms_cached["sign_in_summary"]
        if ms_cached.get("mfa"):
            mfa_list = ms_cached["mfa"]
            if isinstance(mfa_list, list):
                total = len(mfa_list)
                mfa_on = sum(1 for u in mfa_list if u.get("mfa_registered"))
                microsoft["mfa"] = {"enrolled": mfa_on, "total": total, "rate": f"{int(mfa_on/total*100)}%" if total else "N/A"}
        if ms_cached.get("compliance"):
            microsoft["compliance_score"] = ms_cached["compliance"].get("overall_score", "N/A")
        if microsoft:
            result["microsoft"] = microsoft

    if raw.get("risk_register"):
        result["risks"] = {
            "count": raw["risk_register"].get("count", 0),
            "items": raw["risk_register"].get("risks", [])[:30],
        }

    # Risk profiles (from cached computation)
    rp_cached = raw.get("risk_profiles")
    if not rp_cached:
        try:
            from app.models import ConfigStore as _CS2
            _rec2 = _CS2.find(f"tenant_integration_data_{tenant_id}")
            if _rec2 and _rec2.value:
                rp_cached = _json_local.loads(_rec2.value).get("risk_profiles")
        except Exception:
            pass
    if rp_cached:
        result["risk_profiles"] = {
            "summary": rp_cached.get("summary", {}),
            "users": rp_cached.get("users", [])[:30],
            "devices": rp_cached.get("devices", [])[:30],
        }

    # NinjaOne data (from ConfigStore cache)
    ninja_cached = {}
    try:
        from app.models import ConfigStore as _CS3
        _rec3 = _CS3.find(f"tenant_integration_data_{tenant_id}")
        if _rec3 and _rec3.value:
            ninja_cached = _json_local.loads(_rec3.value).get("ninjaone", {})
    except Exception:
        pass
    if ninja_cached:
        ninjaone = {}
        devices = ninja_cached.get("devices", [])
        if isinstance(devices, list):
            ninjaone["device_count"] = len(devices)
            ninjaone["devices"] = devices[:20]
        patches = ninja_cached.get("os_patches", [])
        if isinstance(patches, list):
            missing = [p for p in patches if isinstance(p, dict) and p.get("status") != "INSTALLED"]
            ninjaone["missing_patches"] = len(missing)
            ninjaone["patch_details"] = missing[:15]
        av = ninja_cached.get("antivirus_status", [])
        if isinstance(av, list):
            ninjaone["av_count"] = len(av)
            no_av = [a for a in av if isinstance(a, dict) and not a.get("productState")]
            ninjaone["unprotected_devices"] = len(no_av)
        threats = ninja_cached.get("antivirus_threats", [])
        if isinstance(threats, list):
            ninjaone["threat_count"] = len(threats)
            ninjaone["threats"] = threats[:10]
        alerts = ninja_cached.get("alerts", [])
        if isinstance(alerts, list):
            ninjaone["alert_count"] = len(alerts)
            ninjaone["alerts"] = alerts[:15]
        if ninjaone:
            result["ninjaone"] = ninjaone

    # DefensX data (from ConfigStore cache)
    dx_cached = {}
    try:
        if not _rec3:
            _rec3 = _CS3.find(f"tenant_integration_data_{tenant_id}")
        if _rec3 and _rec3.value:
            dx_cached = _json_local.loads(_rec3.value).get("defensx", {})
    except Exception:
        pass
    if dx_cached:
        defensx = {}
        agent = dx_cached.get("agent_status", {})
        if isinstance(agent, dict) and not agent.get("error"):
            defensx["agent_status"] = agent
        policy = dx_cached.get("policy_compliance", {})
        if isinstance(policy, dict) and not policy.get("error"):
            defensx["policy_compliance"] = policy
        resilience = dx_cached.get("resilience_score", {})
        if isinstance(resilience, dict) and not resilience.get("error"):
            defensx["resilience_score"] = resilience
        shadow_ai = dx_cached.get("shadow_ai", {})
        if isinstance(shadow_ai, dict) and not shadow_ai.get("error"):
            defensx["shadow_ai"] = shadow_ai
        if defensx:
            result["defensx"] = defensx

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
    _validate_tenant_access(tenant_id)
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
    # Handle both string and dict mapping formats
    matched = {}
    for k, v in mappings.items():
        if isinstance(v, str) and v == tenant_id:
            matched[k] = v
        elif isinstance(v, dict) and v.get("tenant_id") == tenant_id:
            matched[k] = v

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


def _update_job_status(tenant_id, stage, detail="", chunk_info=""):
    """Write current job stage to ConfigStore for frontend polling.

    Stages: collecting_telivy → collecting_microsoft → computing_risk_profiles
            → analyzing_phase1 → analyzing_phase2 → analyzing_cross_source
            → generating_evidence → syncing_progress → done
    """
    import json
    from app.models import ConfigStore
    try:
        status = {
            "status": "processing",
            "stage": stage,
            "detail": detail,
            "chunk_info": chunk_info,
        }
        ConfigStore.upsert(f"auto_process_status_{tenant_id}", json.dumps(status))
    except Exception:
        pass


def _bg_auto_process(app, tenant_id, scan_id, scan_type, run_mode="full"):
    """Background worker for auto-process. Runs in a thread, never blocks gunicorn.

    Args:
        run_mode: "telivy_only" | "microsoft_only" | "ninjaone_only" | "defensx_only" | "full" (default)
    """
    import json
    _VALID_MODES = {"telivy_only", "microsoft_only", "ninjaone_only", "defensx_only", "full"}
    if run_mode not in _VALID_MODES:
        run_mode = "full"

    with app.app_context():
        from app import db
        from app.models import Project, RiskRegister, ConfigStore, ProjectControl

        try:
            db.session.remove()
        except Exception:
            pass

        integration_data = {}
        telivy_raw = {}

        _only_mode = run_mode.endswith("_only")
        skip_telivy = _only_mode and run_mode != "telivy_only"
        skip_microsoft = _only_mode and run_mode != "microsoft_only"

        # Step 1: Pull data from Telivy
        if not skip_telivy:
            _update_job_status(tenant_id, "collecting_telivy", "Pulling Telivy scan data")
        if scan_id and not skip_telivy:
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
                logger.warning("Telivy data collection failed: %s", e)
                integration_data["telivy_error"] = "Data collection failed"

        # Pull Microsoft Security data (Entra + Defender + Devices + Secure Score)
        if not skip_microsoft:
            _update_job_status(tenant_id, "collecting_microsoft", "Pulling Microsoft 365 security data")
            try:
                from app.masri.new_models import SettingsEntra
                entra_cfg = db.session.execute(
                    db.select(SettingsEntra).filter_by(tenant_id=None)
                ).scalars().first()
                if entra_cfg and entra_cfg.is_fully_configured():
                    from app.masri.entra_integration import EntraIntegration
                    creds = entra_cfg.get_credentials()
                    ms_client = EntraIntegration(
                        tenant_id=creds["entra_tenant_id"],
                        client_id=creds["client_id"],
                        client_secret=creds["client_secret"],
                    )
                    ms_data = ms_client.collect_all_security_data()
                    if ms_data:
                        integration_data["microsoft"] = ms_data
            except Exception as e:
                logger.debug("Microsoft data collection skipped: %s", e)

        # Compute risk profiles from Microsoft data
        if integration_data.get("microsoft") and not skip_microsoft:
            _update_job_status(tenant_id, "computing_risk_profiles", "Computing user & device risk profiles")
            try:
                from app.masri.risk_profiles import compute_risk_profiles, generate_risk_narratives
                profiles = compute_risk_profiles(integration_data["microsoft"])
                if profiles:
                    profiles = generate_risk_narratives(profiles, tenant_id=tenant_id)
                    integration_data["risk_profiles"] = profiles
            except Exception as e:
                logger.debug("Risk profile computation skipped: %s", e)

        # Pull NinjaOne data (if configured and mapped to this tenant)
        skip_ninjaone = _only_mode and run_mode != "ninjaone_only"
        if not skip_ninjaone:
            _update_job_status(tenant_id, "collecting_ninjaone", "Pulling NinjaOne RMM data")
            try:
                from app.masri.new_models import SettingsStorage
                ninja_cfg = db.session.execute(
                    db.select(SettingsStorage).filter_by(provider="ninjaone")
                ).scalars().first()
                if ninja_cfg:
                    # Find the org_id mapped to this tenant
                    mapping_record = ConfigStore.find("ninjaone_org_mappings")
                    org_id = None
                    if mapping_record and mapping_record.value:
                        mappings = json.loads(mapping_record.value)
                        for oid, info in mappings.items():
                            if isinstance(info, dict) and info.get("tenant_id") == tenant_id:
                                org_id = oid
                                break
                    if org_id:
                        from app.masri.ninjaone_integration import NinjaOneIntegration
                        from app.masri.settings_service import decrypt_value
                        config = json.loads(decrypt_value(ninja_cfg.config_enc)) if ninja_cfg.config_enc else {}
                        if config.get("client_id") and config.get("client_secret"):
                            ninja_client = NinjaOneIntegration(
                                client_id=config["client_id"],
                                client_secret=config["client_secret"],
                                region=config.get("region", "us"),
                            )
                            ninja_data = ninja_client.collect_all_data(org_id=org_id)
                            if ninja_data:
                                integration_data["ninjaone"] = ninja_data
            except Exception as e:
                logger.debug("NinjaOne data collection skipped: %s", e)

        # Pull DefensX data (if configured and mapped to this tenant)
        skip_defensx = _only_mode and run_mode != "defensx_only"
        if not skip_defensx:
            _update_job_status(tenant_id, "collecting_defensx", "Pulling DefensX browser security data")
            try:
                from app.masri.new_models import SettingsStorage
                dx_cfg = db.session.execute(
                    db.select(SettingsStorage).filter_by(provider="defensx")
                ).scalars().first()
                if dx_cfg:
                    mapping_record = ConfigStore.find("defensx_customer_mappings")
                    customer_id = None
                    if mapping_record and mapping_record.value:
                        mappings = json.loads(mapping_record.value)
                        for cid, info in mappings.items():
                            if isinstance(info, dict) and info.get("tenant_id") == tenant_id:
                                customer_id = cid
                                break
                    if customer_id:
                        from app.masri.defensx_integration import DefensXIntegration
                        from app.masri.settings_service import decrypt_value
                        config = json.loads(decrypt_value(dx_cfg.config_enc)) if dx_cfg.config_enc else {}
                        if config.get("api_token"):
                            dx_client = DefensXIntegration(api_token=config["api_token"])
                            dx_data = dx_client.collect_all_data(customer_id=customer_id)
                            if dx_data:
                                integration_data["defensx"] = dx_data
            except Exception as e:
                logger.debug("DefensX data collection skipped: %s", e)

        # Store raw data at tenant level
        has_any_data = bool(integration_data.get("telivy") or integration_data.get("microsoft")
                           or integration_data.get("ninjaone") or integration_data.get("defensx"))
        has_data = has_any_data
        if has_data:
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
                if integration_data.get("microsoft"):
                    existing["microsoft"] = integration_data["microsoft"]
                if integration_data.get("risk_profiles"):
                    existing["risk_profiles"] = integration_data["risk_profiles"]
                if integration_data.get("ninjaone"):
                    existing["ninjaone"] = integration_data["ninjaone"]
                if integration_data.get("defensx"):
                    existing["defensx"] = integration_data["defensx"]
                existing["_updated"] = __import__("datetime").datetime.utcnow().isoformat()
                ConfigStore.upsert(f"tenant_integration_data_{tenant_id}", json.dumps(existing, default=str)[:35000000])
            except Exception:
                pass

        projects = db.session.execute(
            db.select(Project).filter_by(tenant_id=tenant_id)
        ).scalars().all()

        if not projects or not has_any_data:
            # Store result for polling
            try:
                ConfigStore.upsert(f"auto_process_result_{tenant_id}", json.dumps({
                    "success": has_any_data,
                    "controls_mapped": 0, "risks_added": 0,
                    "data_stored": has_any_data,
                    "message": "Scan data saved but this client has no compliance projects. Create a project (e.g. SOC 2 or FTC Safeguards) for this client first, then re-run." if has_any_data else "No scan data was pulled. Check your API key and scan mapping.",
                }, default=str))
            except Exception:
                pass
            try:
                db.session.remove()
            except Exception:
                pass
            return

        # Step 2+3: LLM analysis
        total_mapped = 0
        total_risks = 0

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
                    })
            if not controls:
                continue

            if llm_available:
                try:
                    fw_name = project.framework.name if project.framework else "Unknown"
                    has_telivy = bool(integration_data.get("telivy"))
                    has_microsoft = bool(integration_data.get("microsoft"))
                    has_profiles = bool(integration_data.get("risk_profiles"))

                    CHUNK_SIZE = 10
                    all_mappings = []
                    all_risks = []

                    # ── Phase 1: Telivy-only analysis ─────────────────────
                    if has_telivy:
                        _update_job_status(tenant_id, "analyzing_phase1", "Analyzing Telivy findings", f"0/{(len(controls) + CHUNK_SIZE - 1) // CHUNK_SIZE} chunks")
                        telivy_data = _compress_for_llm({"telivy": integration_data["telivy"]})
                        telivy_prompt = (
                            f"You are an external vulnerability analyst mapping Telivy scan findings to "
                            f"{fw_name} controls. You MUST respond with ONLY valid JSON.\n\n"
                            "TELIVY DATA INCLUDES: External vulnerability scan results — network exposure, "
                            "DNS security, email spoofing risk, SSL/TLS configuration, web application "
                            "vulnerabilities, typosquatting domains, breach data exposure.\n\n"
                            "For each control: check if Telivy findings provide evidence of compliance "
                            "or non-compliance. Reference specific finding names and severity levels.\n\n"
                            "MAPPING: compliant (scan confirms control met) | partial (some evidence) | "
                            "non_compliant (clear gap found)\n\n"
                            "RISK RULES:\n"
                            "- ONLY create risks for findings that ACTUALLY EXIST in the scan data above\n"
                            "- NEVER fabricate, invent, or assume findings not in the data\n"
                            "- NEVER paraphrase executive summaries as risk descriptions\n"
                            "- Each risk MUST reference specific items BY NAME from the data (IPs, domains, CVEs, finding names)\n"
                            "- If a finding has severity 'info' or 'low', do NOT create a risk for it\n"
                            "- If there are no real findings, return empty risks array []\n\n"
                            "JSON: {\"mappings\":[{\"project_control_id\":\"ID\",\"notes\":\"Telivy finding: [name] - [details]\","
                            "\"status\":\"compliant|partial|non_compliant\"}],"
                            "\"risks\":[{\"title\":\"Short risk name (no severity prefix)\","
                            "\"summary\":\"One sentence referencing specific finding names from the data\","
                            "\"description\":\"MUST include: 1) exact finding name from scan data, 2) affected IP/domain/port, 3) why this matters, 4) specific remediation steps\","
                            "\"evidence_data\":[{\"type\":\"finding|breach|vulnerability|config\",\"name\":\"exact item name from data\",\"detail\":\"exact details from data\"}],"
                            "\"severity\":\"critical|high|medium|low\"}]}"
                        )
                        all_mappings, all_risks = _run_chunked_llm(
                            LLMService, telivy_prompt, telivy_data, controls,
                            fw_name, "Telivy scan", tenant_id, CHUNK_SIZE,
                            all_mappings, all_risks, "auto_map",
                        )

                    # ── Phase 2: Microsoft-only analysis ──────────────────
                    if has_microsoft:
                        _update_job_status(tenant_id, "analyzing_phase2", "Analyzing Microsoft 365 findings", f"0/{(len(controls) + CHUNK_SIZE - 1) // CHUNK_SIZE} chunks")
                        ms_data = _compress_for_llm({"microsoft": integration_data["microsoft"],
                                                      "risk_profiles": integration_data.get("risk_profiles", {})})
                        ms_prompt = (
                            f"You are a Microsoft 365 security analyst mapping findings to "
                            f"{fw_name} controls. You MUST respond with ONLY valid JSON.\n\n"
                            "MICROSOFT DATA INCLUDES: Secure Score (overall posture + gap controls), "
                            "Defender security alerts, Intune device compliance (encryption, policy status), "
                            "MFA enrollment rates, Conditional Access policies, Identity Protection "
                            "(risky users, risk detections with IPs), sign-in activity (failures, anomalies), "
                            "SharePoint site inventory.\n\n"
                            "For each control:\n"
                            "- Check if Microsoft data provides evidence (Secure Score control, device policy, MFA rate)\n"
                            "- Reference SPECIFIC data: user names lacking MFA, device names non-compliant, "
                            "alert titles from Defender, Secure Score gap control names\n"
                            "- For identity controls: cite MFA percentage, risky user names, sign-in failure rates\n"
                            "- For device controls: cite compliance %, encryption %, specific non-compliant devices\n"
                            "- For access controls: cite Conditional Access policy count and status\n\n"
                            "MAPPING: compliant | partial | non_compliant\n\n"
                            "RISK RULES:\n"
                            "- ONLY create risks for issues that ACTUALLY EXIST in the data above\n"
                            "- NEVER fabricate users, devices, or findings not in the data\n"
                            "- Each risk MUST reference specific entities BY NAME from the data\n"
                            "- If MFA is 100%, do NOT create an MFA risk\n"
                            "- If all devices are compliant, do NOT create a device risk\n"
                            "- If there are no real issues, return empty risks array []\n\n"
                            "JSON: {\"mappings\":[{\"project_control_id\":\"ID\",\"notes\":\"Microsoft finding: [specific data point]\","
                            "\"status\":\"compliant|partial|non_compliant\"}],"
                            "\"risks\":[{\"title\":\"Short risk name (no severity prefix)\","
                            "\"summary\":\"One sentence referencing exact user/device/policy names from data\","
                            "\"description\":\"MUST include: 1) exact entity names from data, 2) what's wrong, 3) business impact, 4) remediation steps\","
                            "\"evidence_data\":[{\"type\":\"user|device|policy|alert\",\"name\":\"exact name from data\",\"detail\":\"exact finding from data\"}],"
                            "\"severity\":\"critical|high|medium|low\"}]}"
                        )
                        all_mappings, all_risks = _run_chunked_llm(
                            LLMService, ms_prompt, ms_data, controls,
                            fw_name, "Microsoft 365", tenant_id, CHUNK_SIZE,
                            all_mappings, all_risks, "auto_map",
                        )

                    # ── Phase 3: NinjaOne RMM analysis ────────────────────
                    has_ninjaone = bool(integration_data.get("ninjaone"))
                    if has_ninjaone:
                        _update_job_status(tenant_id, "analyzing_phase3", "Analyzing NinjaOne RMM data", f"0/{(len(controls) + CHUNK_SIZE - 1) // CHUNK_SIZE} chunks")
                        ninja_data = _compress_for_llm({"ninjaone": integration_data["ninjaone"]})
                        ninja_prompt = (
                            f"You are an endpoint security analyst mapping NinjaOne RMM findings to "
                            f"{fw_name} controls. You MUST respond with ONLY valid JSON.\n\n"
                            "NINJAONE DATA INCLUDES: Device inventory (OS, model, last sync), "
                            "OS patch compliance (missing patches, severity), antivirus status "
                            "(engine, definitions date, threats detected), disk encryption status, "
                            "device alerts and activities.\n\n"
                            "For each control:\n"
                            "- Check if NinjaOne data provides evidence of compliance or gaps\n"
                            "- Reference SPECIFIC devices by name: unpatched systems, missing AV, unencrypted drives\n"
                            "- For patch management: cite specific missing patches and their severity\n"
                            "- For endpoint protection: cite AV coverage %, devices without protection\n"
                            "- For asset management: cite stale/inactive devices (30+ days no sync)\n\n"
                            "MAPPING: compliant | partial | non_compliant\n\n"
                            "JSON: {\"mappings\":[{\"project_control_id\":\"ID\",\"notes\":\"NinjaOne finding: [specific data point]\","
                            "\"status\":\"compliant|partial|non_compliant\"}],"
                            "\"risks\":[{\"title\":\"Short risk name (no severity prefix)\",\"summary\":\"One sentence summary\",\"description\":\"Detailed explanation + remediation plan.\",\"evidence_data\":[{\"type\":\"device|patch|av\",\"name\":\"device or patch name\",\"detail\":\"specifics\"}],"
                            "\"severity\":\"critical|high|medium|low\"}]}"
                        )
                        all_mappings, all_risks = _run_chunked_llm(
                            LLMService, ninja_prompt, ninja_data, controls,
                            fw_name, "NinjaOne RMM", tenant_id, CHUNK_SIZE,
                            all_mappings, all_risks, "auto_map",
                        )

                    # ── Phase 4: DefensX browser security analysis ────────
                    has_defensx = bool(integration_data.get("defensx"))
                    if has_defensx:
                        _update_job_status(tenant_id, "analyzing_phase4", "Analyzing DefensX browser security data", f"0/{(len(controls) + CHUNK_SIZE - 1) // CHUNK_SIZE} chunks")
                        dx_data = _compress_for_llm({"defensx": integration_data["defensx"]})
                        dx_prompt = (
                            f"You are a browser security analyst mapping DefensX findings to "
                            f"{fw_name} controls. You MUST respond with ONLY valid JSON.\n\n"
                            "DEFENSX DATA INCLUDES: Browser agent deployment coverage, web policy "
                            "compliance (URL filtering, content categories), cyber resilience scores, "
                            "user browsing activity, shadow AI detection (unauthorized AI tool usage), "
                            "credential protection events, file transfer monitoring.\n\n"
                            "For each control:\n"
                            "- Check if DefensX data provides evidence of compliance or gaps\n"
                            "- For web filtering: cite policy compliance %, blocked categories\n"
                            "- For data protection: cite credential events, file transfer violations\n"
                            "- For shadow IT/AI: cite detected unauthorized tools and users\n"
                            "- For endpoint coverage: cite agent deployment % and unprotected users\n\n"
                            "MAPPING: compliant | partial | non_compliant\n\n"
                            "JSON: {\"mappings\":[{\"project_control_id\":\"ID\",\"notes\":\"DefensX finding: [specific data point]\","
                            "\"status\":\"compliant|partial|non_compliant\"}],"
                            "\"risks\":[{\"title\":\"Short risk name (no severity prefix)\",\"summary\":\"One sentence summary\",\"description\":\"Detailed explanation + remediation.\",\"evidence_data\":[{\"type\":\"shadow_ai|policy|credential\",\"name\":\"service or user\",\"detail\":\"specifics\"}],"
                            "\"severity\":\"critical|high|medium|low\"}]}"
                        )
                        all_mappings, all_risks = _run_chunked_llm(
                            LLMService, dx_prompt, dx_data, controls,
                            fw_name, "DefensX", tenant_id, CHUNK_SIZE,
                            all_mappings, all_risks, "auto_map",
                        )

                    # ── Phase 5: Cross-source analysis (if 2+ sources) ───
                    source_count = sum([has_telivy, has_microsoft, has_ninjaone, has_defensx])
                    if source_count >= 2:
                        _update_job_status(tenant_id, "analyzing_cross_source", "Cross-source correlation analysis")
                        combined_data = _compress_for_llm(integration_data)
                        # Build dynamic source list for cross-source prompt
                        sources = []
                        if has_telivy:
                            sources.append("Telivy (external vulnerability scan)")
                        if has_microsoft:
                            sources.append("Microsoft 365 (internal security posture)")
                        if has_ninjaone:
                            sources.append("NinjaOne RMM (endpoint management)")
                        if has_defensx:
                            sources.append("DefensX (browser security)")
                        source_list = ", ".join(sources)

                        cross_prompt = (
                            f"You are a compliance analyst performing CROSS-SOURCE analysis for "
                            f"{fw_name}. You MUST respond with ONLY valid JSON.\n\n"
                            f"You have data from MULTIPLE sources: {source_list}. "
                            "Focus ONLY on controls where correlating data across sources adds value:\n"
                            "- Email security: Telivy (SPF/DKIM) + Microsoft (Exchange rules)\n"
                            "- Authentication: breach data + MFA enrollment + browser credential events\n"
                            "- Encryption: SSL/TLS + device encryption + browser HTTPS enforcement\n"
                            "- Endpoint compliance: device compliance + patch status + AV coverage + browser agents\n"
                            "- Access control: open ports + Conditional Access + web filtering policies\n\n"
                            "ONLY map controls where cross-source correlation adds value beyond what "
                            "individual analyses already found. Reference data from MULTIPLE sources in notes.\n\n"
                            "JSON: {\"mappings\":[{\"project_control_id\":\"ID\","
                            "\"notes\":\"Cross-source: [Source A] shows [X] + [Source B] shows [Y] = [conclusion]\","
                            "\"status\":\"compliant|partial|non_compliant\"}],"
                            "\"risks\":[{\"title\":\"Short risk name (no severity prefix)\",\"summary\":\"One sentence cross-source summary\",\"description\":\"Correlated explanation + remediation.\",\"evidence_data\":[{\"type\":\"cross_source\",\"source\":\"integration name\",\"name\":\"entity\",\"detail\":\"specifics\"}],"
                            "\"severity\":\"critical|high|medium|low\"}]}"
                        )
                        # Only send controls that weren't already mapped as non_compliant
                        mapped_ids = {m.get("project_control_id") for m in all_mappings
                                      if m.get("status") == "non_compliant"}
                        unmapped = [c for c in controls if c["project_control_id"] not in mapped_ids]
                        if unmapped:
                            all_mappings, all_risks = _run_chunked_llm(
                                LLMService, cross_prompt, combined_data, unmapped,
                                fw_name, "Cross-source", tenant_id, CHUNK_SIZE,
                                all_mappings, all_risks, "auto_map",
                            )

                    _update_job_status(tenant_id, "generating_evidence", f"Applying {len(all_mappings)} mappings + generating evidence")
                    # Apply mappings
                    _STATUS_MAP = {
                        "compliant": "complete", "partial": "ready for auditor",
                        "non_compliant": "infosec action", "unknown": "infosec action",
                    }
                    _IMPL_MAP = {
                        "compliant": 100, "partial": 50, "non_compliant": 25,
                    }
                    from app.models import ProjectSubControl, ProjectEvidence, EvidenceAssociation
                    for m in all_mappings:
                        try:
                            pc_id = m.get("project_control_id")
                            notes = m.get("notes", "")
                            if pc_id and notes:
                                pc = db.session.get(ProjectControl, pc_id)
                                if pc:
                                    existing = pc.notes or ""
                                    pc.notes = f"{existing}\n\n[Auto-Mapped] {notes}".strip()
                                    llm_status = m.get("status", "").lower()
                                    new_status = _STATUS_MAP.get(llm_status)
                                    if new_status and pc.review_status in ("infosec action", "new", None, ""):
                                        pc.review_status = new_status
                                    # Update subcontrol progress
                                    impl_pct = _IMPL_MAP.get(llm_status, 0)
                                    if impl_pct > 0:
                                        for sc in pc.subcontrols.all():
                                            if sc.is_applicable and (sc.implemented or 0) < impl_pct:
                                                sc.implemented = impl_pct

                                    # Auto-generate evidence from the finding
                                    ctrl = pc.control
                                    ref_code = ctrl.ref_code if ctrl else pc_id
                                    ev_name = f"[Auto] {ref_code} - Integration Scan Evidence"
                                    # Check if evidence already exists for this control
                                    existing_ev = db.session.execute(
                                        db.select(ProjectEvidence).filter_by(
                                            name=ev_name, project_id=project.id)
                                    ).scalars().first()
                                    if not existing_ev:
                                        try:
                                            # Determine completeness — only mark complete if we have
                                            # concrete scan data. Otherwise mark as partial/draft.
                                            has_concrete_data = bool(notes and len(notes) > 50)
                                            is_compliant = llm_status == "compliant"

                                            if is_compliant and has_concrete_data:
                                                ev_status = "Complete — scan confirms compliance"
                                            elif has_concrete_data:
                                                ev_status = "Partial — scan data available, needs review"
                                            else:
                                                ev_status = "Draft — insufficient scan data"

                                            # Build exhibit references based on what evidence is needed
                                            ctrl_name = ctrl.name if ctrl else ref_code
                                            exhibits = []
                                            exhibits.append(f"Exhibit A: Integration scan report showing {ref_code} compliance status")
                                            if not is_compliant:
                                                exhibits.append(f"Exhibit B: Screenshot of current configuration or policy addressing this control")
                                                exhibits.append(f"Exhibit C: Remediation plan or change ticket documenting the fix")
                                            if "MFA" in (notes or "").upper() or "mfa" in (ctrl_name or "").lower():
                                                exhibits.append(f"Exhibit {'D' if not is_compliant else 'B'}: Screenshot of MFA enforcement policy (Source: Entra ID → Security → MFA)")
                                            if "encrypt" in (notes or "").lower() or "encrypt" in (ctrl_name or "").lower():
                                                exhibits.append(f"Exhibit {'D' if not is_compliant else 'B'}: Screenshot of encryption settings (Source: Device management or BitLocker status)")

                                            ev = ProjectEvidence(
                                                name=ev_name,
                                                description=(
                                                    f"Evidence Status: {ev_status}\n\n"
                                                    f"Control: {ref_code} — {ctrl_name}\n"
                                                    f"Compliance Status: {llm_status}\n"
                                                    f"Source: Integration Security Scan\n\n"
                                                    f"What the scan found:\n{notes}\n\n"
                                                    f"--- REQUIRED EXHIBITS ---\n" +
                                                    "\n".join(exhibits) +
                                                    f"\n\nUpload each exhibit as a supporting document. "
                                                    f"{'Review only — control appears compliant.' if is_compliant else 'This evidence is incomplete until all exhibits are uploaded.'}"
                                                ),
                                                content=notes,
                                                group="integration_scan",
                                                project_id=project.id,
                                                tenant_id=tenant_id,
                                            )
                                            db.session.add(ev)
                                            db.session.flush()  # Get ev.id
                                            # Link to all applicable subcontrols
                                            for sc in pc.subcontrols.all():
                                                if sc.is_applicable:
                                                    assoc = EvidenceAssociation(
                                                        control_id=sc.id,
                                                        evidence_id=ev.id,
                                                    )
                                                    db.session.add(assoc)
                                        except Exception:
                                            pass  # Duplicate name or other DB issue

                                    total_mapped += 1
                        except Exception:
                            pass

                    # Add risks
                    _SEV = {"critical": "critical", "high": "high", "medium": "moderate", "low": "low"}
                    for r in all_risks:
                        try:
                            title = r.get("title", "")
                            # Strip severity prefixes the LLM sometimes adds
                            import re as _re
                            title = _re.sub(r'^(Critical|High|Medium|Moderate|Low):\s*', '', title, flags=_re.IGNORECASE).strip()
                            if title:
                                th = RiskRegister._compute_title_hash(title, tenant_id)
                                dup = db.session.execute(
                                    db.select(RiskRegister).filter_by(title_hash=th, tenant_id=tenant_id)
                                ).scalars().first()
                                if dup:
                                    continue
                                risk = RiskRegister(
                                    title=title, title_hash=th,
                                    summary=r.get("summary", ""),
                                    description=r.get("description", ""),
                                    evidence_data=r.get("evidence_data", []),
                                    risk=_SEV.get(r.get("severity", "").lower(), "unknown"),
                                    tenant_id=tenant_id, project_id=project.id,
                                )
                                db.session.add(risk)
                                total_risks += 1
                        except Exception:
                            pass
                    _update_job_status(tenant_id, "syncing_progress", f"Syncing progress for {project.name if hasattr(project, 'name') else project.id}")
                    # Sync ALL subcontrol progress for this project
                    _sync_project_progress(db, project, ProjectControl, ProjectSubControl)
                    db.session.commit()

                    # Generate automated evidence from integration data
                    _update_job_status(tenant_id, "generating_evidence", f"Generating evidence for {project.name if hasattr(project, 'name') else project.id}")
                    try:
                        from app.masri.evidence_generators import generate_all_evidence
                        ev_count = generate_all_evidence(db, project, tenant_id)
                        if ev_count:
                            logger.info("Generated %d evidence records for project %s", ev_count, project.id)
                    except Exception as ev_err:
                        logger.warning("Evidence generation failed for project %s: %s", project.id, ev_err)
                except Exception as e:
                    logger.warning("LLM auto-process failed for project %s: %s", project.id, e)
            else:
                try:
                    if controls:
                        pc = db.session.get(ProjectControl, controls[0]["project_control_id"])
                        if pc:
                            pc.notes = (pc.notes or "") + f"\n\n[Integration Data]\n{json.dumps(integration_data, indent=2, default=str)[:500]}"
                            total_mapped += 1
                            db.session.commit()
                except Exception:
                    pass

        # Run drift check against baseline (non-fatal)
        try:
            from app.masri.continuous_monitor import check_drift
            record = ConfigStore.find(f"tenant_integration_data_{tenant_id}")
            if record and record.value:
                check_drift(tenant_id, json.loads(record.value))
        except Exception:
            pass

        # Store result for polling
        _update_job_status(tenant_id, "done", f"{total_mapped} controls, {total_risks} risks")
        try:
            msg = ""
            if not llm_available:
                msg = "LLM not configured. Add an AI provider in Settings → Integrations → AI/LLM Providers, then re-run."
            elif total_mapped == 0 and total_risks == 0:
                msg = f"LLM ran but produced no mappings. {len(projects)} project(s) with {sum(len(p.controls.all()) for p in projects)} controls checked."
            ConfigStore.upsert(f"auto_process_result_{tenant_id}", json.dumps({
                "success": total_mapped > 0 or total_risks > 0,
                "controls_mapped": total_mapped,
                "risks_added": total_risks,
                "projects_processed": len(projects),
                "llm_available": llm_available,
                "message": msg,
            }, default=str))
        except Exception:
            pass

        try:
            db.session.remove()
        except Exception:
            pass


@llm_bp.route("/auto-process", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def auto_process():
    """
    POST /api/v1/llm/auto-process

    Kicks off background processing. Returns immediately.
    Poll GET /api/v1/llm/auto-process-status/<tenant_id> for results.
    """
    data = request.get_json(silent=True) or {}
    tenant_id = data.get("tenant_id")
    scan_id = data.get("scan_id")
    scan_type = data.get("scan_type", "scan")
    run_mode = data.get("run_mode", "full")
    if scan_type not in ("scan", "assessment"):
        scan_type = "scan"
    if not tenant_id:
        return jsonify({"success": False, "error": "tenant_id required"}), 400

    _validate_tenant_access(tenant_id)

    import threading
    app = current_app._get_current_object()
    t = threading.Thread(
        target=_bg_auto_process,
        args=(app, tenant_id, scan_id, scan_type, run_mode),
        daemon=True,
    )
    t.start()

    return jsonify({
        "success": True,
        "message": "Processing started in background.",
        "controls_mapped": 0,
        "risks_added": 0,
        "data_stored": True,
    })


@llm_bp.route("/auto-process-status/<string:tenant_id>", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def auto_process_status(tenant_id):
    """GET /api/v1/llm/auto-process-status/<tenant_id> — poll for results."""
    _validate_tenant_access(tenant_id)
    import json
    from app.models import ConfigStore
    try:
        # Check for final result first
        record = ConfigStore.find(f"auto_process_result_{tenant_id}")
        if record and record.value:
            result = json.loads(record.value)
            # Merge in stage info if available
            stage_record = ConfigStore.find(f"auto_process_status_{tenant_id}")
            if stage_record and stage_record.value:
                stage_data = json.loads(stage_record.value)
                result["stage"] = stage_data.get("stage", "done")
                result["stage_detail"] = stage_data.get("detail", "")
                result["chunk_info"] = stage_data.get("chunk_info", "")
            return jsonify(result)
    except Exception:
        pass
    # No final result yet — check for in-progress stage
    try:
        stage_record = ConfigStore.find(f"auto_process_status_{tenant_id}")
        if stage_record and stage_record.value:
            return jsonify(json.loads(stage_record.value))
    except Exception:
        pass
    return jsonify({"status": "processing"})


@llm_bp.route("/refresh-microsoft/<string:tenant_id>", methods=["POST"])
@limiter.limit("3 per minute")
@login_required
def refresh_microsoft_data(tenant_id):
    """POST /api/v1/llm/refresh-microsoft/<tenant_id> — manually refresh Microsoft data.

    Pulls fresh data from all Microsoft Graph endpoints and stores in cache.
    Does NOT re-run LLM analysis — use auto-process for that.
    """
    _validate_tenant_access(tenant_id)

    import json
    from app import db
    from app.models import ConfigStore
    from app.masri.new_models import SettingsEntra

    entra_cfg = db.session.execute(
        db.select(SettingsEntra).filter_by(tenant_id=None)
    ).scalars().first()
    if not entra_cfg or not entra_cfg.is_fully_configured():
        return jsonify({"error": "Microsoft Entra ID not configured"}), 400

    from app.masri.entra_integration import EntraIntegration
    creds = entra_cfg.get_credentials()
    client = EntraIntegration(
        tenant_id=creds["entra_tenant_id"],
        client_id=creds["client_id"],
        client_secret=creds["client_secret"],
    )

    ms_data = client.collect_all_security_data()
    if not ms_data:
        return jsonify({"error": "No data returned from Microsoft"}), 502

    # Store in cache
    try:
        existing = {}
        record = ConfigStore.find(f"tenant_integration_data_{tenant_id}")
        if record and record.value:
            try:
                existing = json.loads(record.value)
            except Exception:
                pass
        existing["microsoft"] = ms_data
        existing["_updated"] = __import__("datetime").datetime.utcnow().isoformat()
        ConfigStore.upsert(f"tenant_integration_data_{tenant_id}", json.dumps(existing, default=str)[:35000000])
    except Exception as e:
        logger.exception("Failed to store Microsoft data for tenant %s", tenant_id)
        return jsonify({"error": "Failed to store data"}), 500

    return jsonify({
        "success": True,
        "message": "Microsoft data refreshed",
        "data_points": list(ms_data.keys()),
        "cached_at": existing.get("_updated"),
    })


def _run_chunked_llm(LLMService, system_prompt, data_summary, controls,
                      fw_name, source_label, tenant_id, chunk_size,
                      all_mappings, all_risks, feature):
    """Run chunked LLM analysis for a single data source.

    Sends controls in batches of chunk_size, accumulates mappings and risks.
    Uses prompt adapter layer to optimize prompts per model family.
    Returns updated (all_mappings, all_risks) lists.
    """
    import json
    from app.masri.prompt_adapters import get_adapter

    # Resolve the model being used for this feature and get the right adapter
    # (system prompt + temperature adapted automatically in LLMService.chat(),
    #  but chunk_size is adapted here since it controls batching logic)
    model_name = LLMService.get_feature_model(feature) or ""
    if not model_name:
        try:
            config = LLMService._get_config()
            model_name = config.get("model_name", "") if config else ""
        except Exception:
            model_name = ""
    adapter = get_adapter(model_name)
    adapted_chunk_size = adapter.adapt_chunk_size(chunk_size)
    adapted_max_tokens = adapter.adapt_max_tokens(3000)

    prev_summary = ""
    total_chunks = (len(controls) + adapted_chunk_size - 1) // adapted_chunk_size
    for chunk_idx in range(0, len(controls), adapted_chunk_size):
        chunk = controls[chunk_idx:chunk_idx + adapted_chunk_size]
        chunk_num = chunk_idx // adapted_chunk_size + 1
        chunk_label = f"{source_label} {chunk_num}/{total_chunks}"
        _update_job_status(tenant_id, f"analyzing_{source_label.lower().replace(' ', '_')}", f"Analyzing {source_label}", f"{chunk_num}/{total_chunks} chunks")
        ctrl_list = "\n".join([
            f"- [{c['project_control_id']}] {c['ref_code']}: {c['name']}"
            for c in chunk
        ])
        user_content = f"Framework: {fw_name}\nSource: {source_label}\n\n"
        if chunk_idx == 0:
            user_content += f"SECURITY DATA:\n{data_summary}\n\n"
        else:
            user_content += (
                f"(Data provided in batch 1. Previous: "
                f"{len(all_mappings)} mapped, {len(all_risks)} risks.)\n"
            )
            if prev_summary:
                user_content += f"Recent: {prev_summary}\n"
            user_content += "\n"
        user_content += f"CONTROLS ({chunk_label}):\n{ctrl_list}"
        user_content += f"\n\n{adapter.adapt_json_instruction()}"

        try:
            result = LLMService.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                tenant_id=tenant_id, feature=feature,
                temperature=0.2, max_tokens=adapted_max_tokens,
            )
            content = result["content"].strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            parsed = None
            try:
                parsed = json.loads(content)
            except (json.JSONDecodeError, ValueError):
                bs = content.find("{")
                be = content.rfind("}")
                if bs >= 0 and be > bs:
                    try:
                        parsed = json.loads(content[bs:be + 1])
                    except Exception:
                        pass
            if parsed:
                new_maps = parsed.get("mappings", [])
                new_risks = parsed.get("risks", [])
                all_mappings.extend(new_maps)
                all_risks.extend(new_risks)
                rt = [r.get("title", "") for r in new_risks]
                prev_summary = f"{len(new_maps)} mapped. Risks: {', '.join(rt[:3])}" if rt else ""
        except Exception as e:
            logger.warning("LLM chunk %s failed: %s", chunk_label, e)
            # Store the error so debug endpoint can show it
            try:
                from app.models import ConfigStore
                ConfigStore.upsert(f"llm_last_error_{tenant_id}", json.dumps({
                    "chunk": chunk_label,
                    "error": str(e)[:500],
                    "model": model_name,
                    "feature": feature,
                }, default=str))
            except Exception:
                pass

    return all_mappings, all_risks


def _build_evidence_description(ref_code, ctrl_name, status, is_compliant, has_data, finding_text):
    """Generate a natural-language evidence description instead of a rigid template."""
    import random

    finding_summary = finding_text[:400].strip() if finding_text else ""

    if is_compliant and has_data:
        openers = [
            f"An automated security scan assessed control {ref_code} ({ctrl_name}) and confirmed that the required security measures are in place.",
            f"Integration scan results for {ref_code} indicate that this control is being met. The scan verified that {ctrl_name.lower()[:80]}.",
            f"Based on the latest integration scan data, control {ref_code} appears to be fully addressed.",
        ]
        body = f"\n\nScan findings:\n{finding_summary}" if finding_summary else ""
        closer = "\n\nThis evidence was collected automatically and should be reviewed by the compliance team to confirm completeness."

    elif has_data:
        openers = [
            f"An integration scan identified findings relevant to control {ref_code} ({ctrl_name}). Review is needed to determine if remediation is required.",
            f"The automated scan flagged items related to {ref_code} that may require attention. Current status: {status}.",
            f"Scan data was collected for control {ref_code}. The findings below suggest this area needs further review.",
        ]
        body = f"\n\nKey findings from the scan:\n{finding_summary}"
        closer = "\n\nPlease review the findings above, attach supporting documentation (configuration screenshots, remediation tickets), and update the compliance status."

    else:
        openers = [
            f"Control {ref_code} ({ctrl_name}) was evaluated during the integration scan but no specific findings were recorded.",
            f"The automated scan did not produce detailed findings for control {ref_code}. Manual evidence collection may be needed.",
            f"Limited scan data is available for {ref_code}. This evidence record serves as a placeholder until more detailed documentation is gathered.",
        ]
        body = ""
        closer = "\n\nTo complete this evidence, upload relevant documentation such as policy documents, configuration exports, or audit screenshots."

    return random.choice(openers) + body + closer


def _sync_project_progress(db, project, ProjectControl, ProjectSubControl):
    """Sync subcontrol.implemented and backfill evidence for all mapped controls."""
    from app.models import ProjectEvidence, EvidenceAssociation
    _IMPL = {"complete": 100, "ready for auditor": 50, "infosec action": 0}
    try:
        for pc in project.controls.all():
            impl_pct = _IMPL.get(pc.review_status, 0)
            if impl_pct > 0:
                for sc in pc.subcontrols.all():
                    if sc.is_applicable and (sc.implemented or 0) < impl_pct:
                        sc.implemented = impl_pct

            # Backfill evidence for mapped controls that don't have auto-evidence yet
            if pc.notes and "[Auto-Mapped]" in (pc.notes or ""):
                ctrl = pc.control
                ref_code = ctrl.ref_code if ctrl else pc.id
                ev_name = f"[Auto] {ref_code} - Integration Scan Evidence"
                existing_ev = db.session.execute(
                    db.select(ProjectEvidence).filter_by(
                        name=ev_name, project_id=project.id)
                ).scalars().first()
                if not existing_ev:
                    try:
                        notes_parts = (pc.notes or "").split("[Auto-Mapped]")
                        finding_text = notes_parts[-1].strip() if len(notes_parts) > 1 else pc.notes or ""
                        status_label = pc.review_status or "infosec action"
                        has_data = bool(finding_text and len(finding_text) > 50)
                        is_compliant = status_label == "complete"

                        ctrl_obj = pc.control
                        ctrl_name = ctrl_obj.name if ctrl_obj else ref_code

                        # Build a natural-language description
                        desc = _build_evidence_description(
                            ref_code, ctrl_name, status_label,
                            is_compliant, has_data, finding_text
                        )

                        ev = ProjectEvidence(
                            name=ev_name,
                            description=desc,
                            content=finding_text[:1000],
                            group="integration_scan",
                            project_id=project.id,
                            tenant_id=project.tenant_id,
                        )
                        db.session.add(ev)
                        db.session.flush()
                        for sc in pc.subcontrols.all():
                            if sc.is_applicable:
                                db.session.add(EvidenceAssociation(
                                    control_id=sc.id, evidence_id=ev.id))
                    except Exception:
                        pass
    except Exception:
        pass


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

    # Microsoft Security data (from collect_all_security_data)
    ms = data.get("microsoft", {})
    if ms:
        # Secure Score
        ss = ms.get("secure_score", {})
        if ss and not ss.get("error"):
            lines.append(f"\nMICROSOFT SECURE SCORE: {ss.get('current_score', 0)}/{ss.get('max_score', 0)}")
            for cs in ss.get("control_scores", [])[:10]:
                if cs.get("score", 0) < cs.get("max_score", 1):
                    lines.append(f"  - {cs['name']}: {cs['score']}/{cs['max_score']}")

        # Security Alerts
        alerts = ms.get("security_alerts", {})
        if alerts and alerts.get("count"):
            by_sev = alerts.get("by_severity", {})
            lines.append(f"\nSECURITY ALERTS ({alerts['count']}): {by_sev.get('high', 0)} high, {by_sev.get('medium', 0)} medium, {by_sev.get('low', 0)} low")
            for a in alerts.get("alerts", [])[:10]:
                lines.append(f"  - [{a.get('severity', '?')}] {a.get('title', 'Alert')}: {a.get('description', '')[:120]}")

        # Device Compliance
        devices = ms.get("devices", {})
        if devices and devices.get("total_devices"):
            lines.append(f"\nDEVICE COMPLIANCE: {devices['compliant']}/{devices['total_devices']} compliant ({devices.get('compliance_rate', 0)}%), {devices.get('encrypted', 0)}/{devices['total_devices']} encrypted ({devices.get('encryption_rate', 0)}%)")
            for d in devices.get("non_compliant_devices", [])[:5]:
                lines.append(f"  - Non-compliant: {d.get('name', '?')} ({d.get('os', '?')}) user: {d.get('user', '?')}")
            for d in devices.get("unencrypted_devices", [])[:5]:
                lines.append(f"  - Unencrypted: {d.get('name', '?')} ({d.get('os', '?')}) user: {d.get('user', '?')}")

        # Risky Users
        risky = ms.get("risky_users", [])
        if risky:
            lines.append(f"\nRISKY USERS ({len(risky)}):")
            for u in risky[:10]:
                lines.append(f"  - {u.get('display_name', '?')} ({u.get('upn', '?')}): risk={u.get('risk_level', '?')}, state={u.get('risk_state', '?')}")

        # Risk Detections
        detections = ms.get("risk_detections", [])
        if detections:
            lines.append(f"\nRISK DETECTIONS ({len(detections)}):")
            for d in detections[:10]:
                lines.append(f"  - [{d.get('risk_level', '?')}] {d.get('risk_type', '?')}: user={d.get('user_display_name', '?')}, IP={d.get('ip_address', '?')}, location={d.get('location', '?')}")

        # MFA Status
        mfa = ms.get("mfa")
        if isinstance(mfa, list) and mfa:
            total = len(mfa)
            mfa_on = sum(1 for u in mfa if u.get("mfa_registered"))
            rate = int(mfa_on / total * 100) if total else 0
            lines.append(f"\nMFA STATUS: {mfa_on}/{total} users ({rate}%)")
            if rate < 100:
                no_mfa = [u.get("display_name", "?") for u in mfa if not u.get("mfa_registered")][:5]
                lines.append(f"  Users without MFA: {', '.join(no_mfa)}")

        # Sign-in Summary
        signins = ms.get("sign_in_summary", {})
        if signins and not signins.get("error"):
            lines.append(f"\nSIGN-IN ACTIVITY ({signins.get('days', 7)}d): {signins.get('total_signins', 0)} total, {signins.get('failed_signins', 0)} failed ({signins.get('failure_rate', 0)}%), {signins.get('risky_signins', 0)} risky")

        # Entra compliance (legacy format support)
        comp = ms.get("compliance", {})
        if comp:
            lines.append(f"\nENTRA COMPLIANCE SCORE: {comp.get('overall_score', 'N/A')}/100")
            for rec in comp.get("recommendations", [])[:5]:
                lines.append(f"  - {rec}")

    # Legacy Entra data format (from _gather_integration_data)
    entra = data.get("entra_compliance", {})
    if entra and not ms:
        lines.append(f"\nEntra ID Compliance Score: {entra.get('overall_score', 'N/A')}/100")
        for rec in entra.get("recommendations", [])[:5]:
            lines.append(f"- {rec}")

    # Risk profiles summary (if computed)
    rp = data.get("risk_profiles", {})
    if rp:
        summary = rp.get("summary", {})
        if summary.get("high_risk_users") or summary.get("high_risk_devices"):
            lines.append(f"\nRISK PROFILE SUMMARY:")
            lines.append(f"  Users: {summary.get('total_users', 0)} total, {summary.get('high_risk_users', 0)} high-risk (avg score: {summary.get('avg_user_score', 0)})")
            lines.append(f"  Devices: {summary.get('total_devices', 0)} total, {summary.get('high_risk_devices', 0)} high-risk (avg score: {summary.get('avg_device_score', 0)})")
            # Top 5 riskiest users
            for u in rp.get("users", [])[:5]:
                if u.get("score", 0) >= 50:
                    lines.append(f"  - HIGH RISK USER: {u.get('display_name', '?')} (score: {u['score']}) — {'; '.join(u.get('risk_factors', [])[:3])}")
            for d in rp.get("devices", [])[:5]:
                if d.get("score", 0) >= 50:
                    lines.append(f"  - HIGH RISK DEVICE: {d.get('name', '?')} (score: {d['score']}) — {'; '.join(d.get('risk_factors', [])[:3])}")

    # NinjaOne RMM data
    ninja = data.get("ninjaone", {})
    if ninja:
        devices = ninja.get("devices", [])
        if isinstance(devices, list) and devices:
            lines.append(f"\nNINJAONE DEVICES ({len(devices)}):")
            for d in devices[:15]:
                if isinstance(d, dict):
                    name = d.get("systemName", d.get("dnsName", "Unknown"))
                    os_name = d.get("os", {}).get("name", "Unknown") if isinstance(d.get("os"), dict) else d.get("os", "Unknown")
                    last_contact = d.get("lastContact", "Unknown")
                    lines.append(f"  - {name}: OS={os_name}, last_contact={last_contact}")

        patches = ninja.get("os_patches", [])
        if isinstance(patches, list) and patches:
            missing = [p for p in patches if isinstance(p, dict) and p.get("status") != "INSTALLED"]
            if missing:
                lines.append(f"\nMISSING OS PATCHES ({len(missing)}):")
                for p in missing[:10]:
                    lines.append(f"  - {p.get('name', '?')} severity={p.get('severity', '?')} device={p.get('deviceName', '?')}")

        av = ninja.get("antivirus_status", [])
        if isinstance(av, list) and av:
            lines.append(f"\nANTIVIRUS STATUS ({len(av)}):")
            no_av = [a for a in av if isinstance(a, dict) and not a.get("productState")]
            if no_av:
                lines.append(f"  Devices without AV: {len(no_av)}")
                for a in no_av[:5]:
                    lines.append(f"  - {a.get('deviceName', '?')}: no active antivirus")

        threats = ninja.get("antivirus_threats", [])
        if isinstance(threats, list) and threats:
            lines.append(f"\nAV THREATS DETECTED ({len(threats)}):")
            for t in threats[:10]:
                if isinstance(t, dict):
                    lines.append(f"  - {t.get('name', '?')} on {t.get('deviceName', '?')}: {t.get('status', '?')}")

        alerts = ninja.get("alerts", [])
        if isinstance(alerts, list) and alerts:
            lines.append(f"\nNINJAONE ALERTS ({len(alerts)}):")
            for a in alerts[:10]:
                if isinstance(a, dict):
                    lines.append(f"  - [{a.get('severity', '?')}] {a.get('message', a.get('subject', '?'))[:120]}")

    # DefensX browser security data
    dx = data.get("defensx", {})
    if dx:
        agent = dx.get("agent_status", {})
        if isinstance(agent, dict) and not agent.get("error"):
            total = agent.get("total_users", 0)
            protected = agent.get("protected_users", 0)
            rate = int(protected / total * 100) if total else 0
            lines.append(f"\nDEFENSX AGENT COVERAGE: {protected}/{total} users ({rate}%)")

        policy = dx.get("policy_compliance", {})
        if isinstance(policy, dict) and not policy.get("error"):
            lines.append(f"WEB POLICY COMPLIANCE: {policy.get('compliant_users', 0)}/{policy.get('total_users', 0)} compliant")
            violations = policy.get("violations", [])
            for v in violations[:5] if isinstance(violations, list) else []:
                if isinstance(v, dict):
                    lines.append(f"  - {v.get('user', '?')}: {v.get('category', '?')} ({v.get('count', 0)} events)")

        resilience = dx.get("resilience_score", {})
        if isinstance(resilience, dict) and not resilience.get("error"):
            lines.append(f"CYBER RESILIENCE SCORE: {resilience.get('score', 'N/A')}/100")

        shadow_ai = dx.get("shadow_ai", {})
        if isinstance(shadow_ai, dict) and not shadow_ai.get("error"):
            tools = shadow_ai.get("detected_tools", [])
            if isinstance(tools, list) and tools:
                lines.append(f"\nSHADOW AI DETECTED ({len(tools)}):")
                for t in tools[:5]:
                    if isinstance(t, dict):
                        lines.append(f"  - {t.get('tool_name', '?')}: {t.get('user_count', 0)} users, {t.get('usage_count', 0)} uses")

    # Existing risks (from risk register)
    risks = data.get("risk_register", {})
    if risks:
        lines.append(f"\nEXISTING RISKS ({risks.get('count', 0)}):")
        for r in risks.get("risks", [])[:5]:
            if isinstance(r, dict):
                lines.append(f"- [{r.get('risk', 'unknown')}] {r.get('title', '?')}: {r.get('description', '')[:80]}")

    result = "\n".join(lines)
    # Cap at 8000 chars — chunked calls keep total reasonable
    if len(result) > 8000:
        result = result[:8000] + "\n... (data truncated)"
    return result if result.strip() else "No scan data available."


def _gather_integration_data(tenant_id: str) -> dict:
    """Collect all available integration data for a tenant.

    CACHE-FIRST: Reads from ConfigStore (populated by auto-process and
    daily scheduler). Never calls external APIs directly — this prevents
    Microsoft Graph throttling on every page load.
    """
    import json
    data = {}

    # 1. Read cached integration data (Telivy + Microsoft)
    try:
        from app.models import ConfigStore
        record = ConfigStore.find(f"tenant_integration_data_{tenant_id}")
        if record and record.value:
            cached = json.loads(record.value)

            # Microsoft data
            if cached.get("microsoft"):
                data["microsoft"] = cached["microsoft"]

            # Telivy cached findings/scan
            if cached.get("telivy"):
                telivy_cached = cached["telivy"]
                if telivy_cached.get("findings"):
                    data["telivy_findings"] = {
                        "count": len(telivy_cached["findings"]),
                        "findings": telivy_cached["findings"][:20],
                    }
                if telivy_cached.get("scan"):
                    scan = telivy_cached["scan"]
                    details = scan.get("assessmentDetails", {})
                    data["telivy_scans"] = {
                        "count": 1,
                        "scans": [{"id": scan.get("id", ""), "org": details.get("organization_name", "Unknown"),
                                   "score": scan.get("securityScore"), "status": scan.get("scanStatus"),
                                   "type": "external_scan", "domain": details.get("domain_prim")}],
                    }
                if telivy_cached.get("assessment"):
                    assessment = telivy_cached["assessment"]
                    details = assessment.get("assessmentDetails", {})
                    if "telivy_scans" not in data:
                        data["telivy_scans"] = {
                            "count": 1,
                            "scans": [{"id": assessment.get("id", ""), "org": details.get("organization_name", "Unknown"),
                                       "score": assessment.get("securityScore"), "status": assessment.get("scanStatus"),
                                       "type": "risk_assessment", "domain": details.get("domain_prim")}],
                        }

            # Entra cached data (legacy format from old auto-process runs)
            if cached.get("entra"):
                entra_cached = cached["entra"]
                if entra_cached.get("compliance"):
                    data["entra_compliance"] = entra_cached["compliance"]
                if entra_cached.get("users"):
                    data["entra_users"] = entra_cached["users"]
                if entra_cached.get("mfa"):
                    data["entra_mfa"] = entra_cached["mfa"]

            data["_cached_at"] = cached.get("_updated")
    except Exception as e:
        logger.debug("ConfigStore cached data read failed: %s", e)

    # 2. Telivy: live API calls OK (no throttling) — enrich cached data with live findings
    try:
        from app.models import ConfigStore
        from app import db as _db

        # Get scan-to-tenant mappings
        mapping_record = ConfigStore.find("telivy_scan_mappings")
        if mapping_record and mapping_record.value:
            all_mappings = json.loads(mapping_record.value)
            mapped_items = []
            mapped_ids = set()
            for item_id, mapping in all_mappings.items():
                if isinstance(mapping, str):
                    mapped_tid = mapping
                    item_data = {"id": item_id, "org": item_id, "type": "unknown"}
                elif isinstance(mapping, dict):
                    mapped_tid = mapping.get("tenant_id", "")
                    item_data = {
                        "id": item_id, "org": mapping.get("org", item_id),
                        "score": mapping.get("score"), "status": mapping.get("status"),
                        "type": mapping.get("type", "unknown"), "domain": mapping.get("domain"),
                    }
                else:
                    continue
                if mapped_tid == tenant_id:
                    mapped_items.append(item_data)
                    mapped_ids.add(item_id)
            if mapped_items and "telivy_scans" not in data:
                data["telivy_scans"] = {"count": len(mapped_items), "scans": mapped_items}

            # Fetch live findings from Telivy API (OK — no throttling)
            if mapped_ids and "telivy_findings" not in data:
                try:
                    from flask import current_app
                    api_key = None
                    try:
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
                        all_findings = []
                        for scan_id in list(mapped_ids)[:3]:
                            try:
                                findings = client.get_external_scan_findings(scan_id)
                                if findings and isinstance(findings, list):
                                    all_findings.extend(findings[:15])
                            except Exception:
                                pass
                        if all_findings:
                            data["telivy_findings"] = {
                                "count": len(all_findings),
                                "findings": all_findings[:50],
                            }
                except Exception:
                    pass
    except Exception:
        pass

    # 3. Risk register (always live from DB — no external API)
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
        data["note"] = "No integration data available. Map a scan or configure Microsoft Entra ID in Integrations."

    return data
