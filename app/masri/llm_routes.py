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
        # Get controls with their current status — find gaps
        # ProjectControl.VALID_REVIEW_STATUS = ["infosec action", "ready for auditor", "complete"]
        # Default is "infosec action". Gaps = anything NOT complete.
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
            return jsonify({
                "project_id": project_id,
                "message": "All controls are complete! No gaps found.",
                "gaps": [],
            })

        from app.masri.llm_service import LLMService
        import json

        # Gather integration data for context
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
                        "You will receive controls that have gaps. "
                        "For EACH control, provide a specific recommendation.\n\n"
                        "You MUST respond with ONLY a valid JSON array — no markdown, no text:\n"
                        '[{"project_control_id":"ID","priority":"high","recommendation":"Do X",'
                        '"evidence_suggestion":"Collect Y","estimated_effort":"quick",'
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

            result = LLMService.chat(
                messages=messages, tenant_id=tenant_id,
                feature="auto_map", temperature=0.3, max_tokens=4096,
            )

            content = result["content"].strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            parsed = None
            try:
                parsed = json.loads(content)
            except (json.JSONDecodeError, ValueError):
                # Try brace extraction
                brace_start = content.find("[")
                brace_end = content.rfind("]")
                if brace_start >= 0 and brace_end > brace_start:
                    try:
                        parsed = json.loads(content[brace_start:brace_end + 1])
                    except Exception:
                        pass

            if parsed and isinstance(parsed, list):
                all_recommendations.extend(parsed)
            elif parsed and isinstance(parsed, dict) and "recommendations" in parsed:
                all_recommendations.extend(parsed["recommendations"])
            else:
                logger.warning("LLM assist-gaps: parse failed chunk %d: %s", i, content[:200])
                for c in chunk:
                    all_recommendations.append({
                        "project_control_id": c["project_control_id"],
                        "priority": "medium",
                        "recommendation": f"Review control {c['ref_code']} ({c['name']}) and gather required evidence.",
                        "evidence_suggestion": "Document current implementation status.",
                        "estimated_effort": "moderate",
                        "policy_needed": False, "template_suggestion": "",
                    })

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
            # Return full finding objects with all details for expandable UI
            telivy["findings_list"] = raw["telivy_findings"].get("findings", [])[:50]
            telivy["findings"] = raw["telivy_findings"].get("count", 0)
        result["telivy"] = telivy

    if raw.get("risk_register"):
        result["risks"] = {
            "count": raw["risk_register"].get("count", 0),
            "items": raw["risk_register"].get("risks", [])[:30],
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


def _bg_auto_process(app, tenant_id, scan_id, scan_type):
    """Background worker for auto-process. Runs in a thread, never blocks gunicorn."""
    import json
    with app.app_context():
        from app import db
        from app.models import Project, RiskRegister, ConfigStore, ProjectControl

        try:
            db.session.remove()
        except Exception:
            pass

        integration_data = {}
        telivy_raw = {}

        # Step 1: Pull data from Telivy
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

        # Store raw data at tenant level
        if integration_data.get("telivy"):
            try:
                existing = {}
                record = ConfigStore.find(f"tenant_integration_data_{tenant_id}")
                if record and record.value:
                    try:
                        existing = json.loads(record.value)
                    except Exception:
                        pass
                existing["telivy"] = integration_data["telivy"]
                existing["_updated"] = __import__("datetime").datetime.utcnow().isoformat()
                ConfigStore.upsert(f"tenant_integration_data_{tenant_id}", json.dumps(existing, default=str)[:50000])
            except Exception:
                pass

        projects = db.session.execute(
            db.select(Project).filter_by(tenant_id=tenant_id)
        ).scalars().all()

        if not projects or not integration_data.get("telivy"):
            # Store result for polling
            try:
                ConfigStore.upsert(f"auto_process_result_{tenant_id}", json.dumps({
                    "success": bool(integration_data.get("telivy")),
                    "controls_mapped": 0, "risks_added": 0,
                    "data_stored": bool(integration_data.get("telivy")),
                    "message": "Data saved (no projects)." if integration_data.get("telivy") else "No data pulled.",
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
                    data_summary = _compress_for_llm(integration_data)
                    fw_name = project.framework.name if project.framework else "Unknown"

                    CHUNK_SIZE = 10
                    all_mappings = []
                    all_risks = []
                    prev_summary = ""

                    system_prompt = (
                        "You are an expert compliance analyst reviewing security scan results against "
                        f"the {fw_name} framework. You MUST respond with ONLY valid JSON — no markdown, "
                        "no explanation, no text before or after.\n\n"
                        "Your tasks:\n"
                        "1. MAP each scan finding to the most relevant compliance control in this batch\n"
                        "2. CREATE detailed risk entries for findings that represent security gaps\n\n"
                        "IMPORTANT:\n"
                        "- Include specific details: affected hostnames, IPs, users, endpoints\n"
                        "- Explain WHY each finding is a risk and recommend remediation\n"
                        "- Only create risks for findings NOT already covered in previous batches\n\n"
                        "JSON format:\n"
                        '{"mappings":[{"project_control_id":"ID","notes":"finding details",'
                        '"status":"compliant|partial|non_compliant"}],'
                        '"risks":[{"title":"risk","description":"details + remediation",'
                        '"severity":"critical|high|medium|low"}]}'
                    )

                    for chunk_idx in range(0, len(controls), CHUNK_SIZE):
                        chunk = controls[chunk_idx:chunk_idx + CHUNK_SIZE]
                        chunk_label = f"Batch {chunk_idx // CHUNK_SIZE + 1}/{(len(controls) + CHUNK_SIZE - 1) // CHUNK_SIZE}"
                        ctrl_list = "\n".join([
                            f"- [{c['project_control_id']}] {c['ref_code']}: {c['name']}"
                            for c in chunk
                        ])
                        user_content = f"Framework: {fw_name}\n\n"
                        if chunk_idx == 0:
                            user_content += f"SCAN RESULTS:\n{data_summary}\n\n"
                        else:
                            user_content += f"(Scan data provided in batch 1. Previous: {len(all_mappings)} mapped, {len(all_risks)} risks.)\n\n"
                            if prev_summary:
                                user_content += f"PREVIOUS:\n{prev_summary}\n\n"
                        user_content += f"CONTROLS ({chunk_label}):\n{ctrl_list}"

                        try:
                            result = LLMService.chat(
                                messages=[
                                    {"role": "system", "content": system_prompt},
                                    {"role": "user", "content": user_content},
                                ],
                                tenant_id=tenant_id, feature="auto_map",
                                temperature=0.2, max_tokens=3000,
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
                                all_mappings.extend(parsed.get("mappings", []))
                                all_risks.extend(parsed.get("risks", []))
                                rt = [r.get("title", "") for r in parsed.get("risks", [])]
                                prev_summary = f"Mapped {len(parsed.get('mappings', []))} controls. Risks: {', '.join(rt[:5])}" if rt else ""
                        except Exception as e:
                            logger.warning("Auto-process chunk %d failed: %s", chunk_idx, e)

                    # Apply mappings
                    _STATUS_MAP = {
                        "compliant": "complete", "partial": "ready for auditor",
                        "non_compliant": "infosec action", "unknown": "infosec action",
                    }
                    _IMPL_MAP = {
                        "compliant": 100, "partial": 50, "non_compliant": 25,
                    }
                    from app.models import ProjectSubControl
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
                                    # Update subcontrol progress for the progress bar
                                    impl_pct = _IMPL_MAP.get(llm_status, 0)
                                    if impl_pct > 0:
                                        for sc in pc.subcontrols.all():
                                            if sc.is_applicable and (sc.implemented or 0) < impl_pct:
                                                sc.implemented = impl_pct
                                    total_mapped += 1
                        except Exception:
                            pass

                    # Add risks
                    _SEV = {"critical": "critical", "high": "high", "medium": "moderate", "low": "low"}
                    for r in all_risks:
                        try:
                            title = r.get("title", "")
                            if title:
                                th = RiskRegister._compute_title_hash(title, tenant_id)
                                dup = db.session.execute(
                                    db.select(RiskRegister).filter_by(title_hash=th, tenant_id=tenant_id)
                                ).scalars().first()
                                if dup:
                                    continue
                                risk = RiskRegister(
                                    title=title, title_hash=th,
                                    description=r.get("description", ""),
                                    risk=_SEV.get(r.get("severity", "").lower(), "unknown"),
                                    tenant_id=tenant_id, project_id=project.id,
                                )
                                db.session.add(risk)
                                total_risks += 1
                        except Exception:
                            pass
                    db.session.commit()
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

        # Store result for polling
        try:
            ConfigStore.upsert(f"auto_process_result_{tenant_id}", json.dumps({
                "success": total_mapped > 0 or total_risks > 0,
                "controls_mapped": total_mapped,
                "risks_added": total_risks,
                "projects_processed": len(projects),
                "llm_available": llm_available,
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
    if not tenant_id:
        return jsonify({"success": False, "error": "tenant_id required"}), 400

    try:
        _validate_tenant_access(tenant_id)
    except Exception:
        pass

    import threading
    app = current_app._get_current_object()
    t = threading.Thread(
        target=_bg_auto_process,
        args=(app, tenant_id, scan_id, scan_type),
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
    from app.models import ConfigStore
    try:
        record = ConfigStore.find(f"auto_process_result_{tenant_id}")
        if record and record.value:
            return jsonify(_json.loads(record.value))
    except Exception:
        pass
    return jsonify({"status": "processing"})


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

    # Entra data
    entra = data.get("entra_compliance", {})
    if entra:
        lines.append(f"\nEntra ID Compliance Score: {entra.get('overall_score', 'N/A')}/100")
        for rec in entra.get("recommendations", [])[:5]:
            lines.append(f"- {rec}")

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
    import json
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
                        "scans": [{"id": scan.get("id", ""), "org": details.get("organization_name", "Unknown"),
                                   "score": scan.get("securityScore"), "status": scan.get("scanStatus"),
                                   "type": "external_scan", "domain": details.get("domain_prim")}],
                    }
                if "telivy_scans" not in data and telivy_cached.get("assessment"):
                    assessment = telivy_cached["assessment"]
                    details = assessment.get("assessmentDetails", {})
                    data["telivy_scans"] = {
                        "count": 1,
                        "scans": [{"id": assessment.get("id", ""), "org": details.get("organization_name", "Unknown"),
                                   "score": assessment.get("securityScore"), "status": assessment.get("scanStatus"),
                                   "type": "risk_assessment", "domain": details.get("domain_prim")}],
                    }
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
