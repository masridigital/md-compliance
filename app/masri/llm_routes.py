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
            # "complete" and "ready for auditor" are done — everything else is a gap
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

        # Also gather integration data to give the LLM context about actual findings
        integration_context = ""
        try:
            raw = _gather_integration_data(tenant_id)
            integration_context = _compress_for_llm(raw) if raw else ""
        except Exception:
            pass

        fw_name = project.framework.name if project.framework else "Unknown"

        # Send gaps to LLM for recommendations
        all_recommendations = []
        chunk_size = 10
        for i in range(0, len(gap_controls), chunk_size):
            chunk = gap_controls[i:i + chunk_size]

            # Build a concise control list instead of dumping full JSON
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
                        "You are a compliance consultant specializing in " + fw_name + ". "
                        "You will receive a list of compliance controls that have gaps "
                        "(missing evidence, incomplete review, or no action taken yet).\n\n"
                        "For EACH control in the list, provide a specific, actionable recommendation.\n\n"
                        "You MUST respond with ONLY a valid JSON array — no markdown, no explanation, "
                        "no text before or after the JSON. Example format:\n"
                        '[{"project_control_id":"ID","priority":"high","recommendation":"Do X",'
                        '"evidence_suggestion":"Collect Y","estimated_effort":"quick",'
                        '"policy_needed":false,"template_suggestion":""}]\n\n'
                        "Rules:\n"
                        "- Include ALL controls from the input, not just some\n"
                        "- priority: high (security/data-critical), medium (operational), low (administrative)\n"
                        "- recommendation: 1-2 sentences, specific action to take NOW\n"
                        "- evidence_suggestion: specific document/screenshot/config to collect\n"
                        "- estimated_effort: quick (<1hr), moderate (1-4hr), significant (>4hr)\n"
                        "- policy_needed: true if a written policy/procedure document is required\n"
                        "- template_suggestion: suggested policy template name, or empty string"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Framework: {fw_name}\n\n"
                        + (f"INTEGRATION SCAN DATA (for context):\n{integration_context}\n\n" if integration_context and integration_context != "No scan data available." else "")
                        + f"CONTROLS NEEDING ACTION ({len(chunk)}):\n{ctrl_text}"
                    ),
                },
            ]

            result = LLMService.chat(
                messages=messages,
                tenant_id=tenant_id,
                feature="auto_map",
                temperature=0.3,
                max_tokens=4096,
            )

            content = result["content"].strip()

            # Use the robust JSON extractor
            parsed = _extract_json(content)
            if parsed is not None:
                if isinstance(parsed, list):
                    all_recommendations.extend(parsed)
                elif isinstance(parsed, dict) and "recommendations" in parsed:
                    all_recommendations.extend(parsed["recommendations"])
                elif isinstance(parsed, dict):
                    # Single recommendation wrapped in object
                    all_recommendations.append(parsed)
            else:
                logger.warning("LLM assist-gaps: could not parse JSON for chunk %d: %s", i, content[:200])
                # Provide fallback recommendations for this chunk
                for c in chunk:
                    all_recommendations.append({
                        "project_control_id": c["project_control_id"],
                        "priority": "medium",
                        "recommendation": f"Review control {c['ref_code']} ({c['name']}) and gather required evidence.",
                        "evidence_suggestion": "Document current implementation status and any existing controls.",
                        "estimated_effort": "moderate",
                        "policy_needed": False,
                        "template_suggestion": "",
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

    # Find which IDs map to this tenant — handle both string and dict formats
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


# ---------------------------------------------------------------------------
# Background processing infrastructure
# ---------------------------------------------------------------------------

import threading
import json as _json
from datetime import datetime as _dt

# In-memory store for active processing jobs — survives page navigation
_active_jobs = {}  # tenant_id -> {"status": ..., "log": [...], "result": {...}}
_jobs_lock = threading.Lock()


def _log_step(tenant_id: str, step: str, detail: str = "", level: str = "info"):
    """Append a timestamped log entry for a processing job."""
    with _jobs_lock:
        job = _active_jobs.get(tenant_id, {})
        job.setdefault("log", []).append({
            "ts": _dt.utcnow().isoformat(),
            "step": step,
            "detail": detail[:500],
            "level": level,
        })
        _active_jobs[tenant_id] = job
    # Also persist to ConfigStore for durability across restarts
    try:
        from app.models import ConfigStore
        ConfigStore.upsert(
            f"process_log_{tenant_id}",
            _json.dumps(job, default=str)[:100000],
        )
    except Exception:
        pass


def _extract_json(content: str):
    """Extract JSON from LLM response using brace-matching."""
    # Strip markdown code blocks
    if content.startswith("```"):
        parts = content.split("\n", 1)
        content = parts[1] if len(parts) > 1 else content
        content = content.rsplit("```", 1)[0].strip()

    try:
        return _json.loads(content)
    except (ValueError, _json.JSONDecodeError):
        pass

    # Brace-matching extraction
    brace_start = content.find("{")
    if brace_start < 0:
        return None
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
        if ch == '"':
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
                    return _json.loads(content[brace_start:i + 1])
                except Exception:
                    return None
    return None


def _run_auto_process(app, tenant_id, scan_id, scan_type):
    """Background worker: pull data, analyze with LLM, map controls, add risks."""
    with app.app_context():
        from app import db
        from app.models import Project, RiskRegister, ConfigStore, ProjectControl
        # Remove any stale session state from previous requests
        try:
            db.session.remove()
        except Exception:
            pass

        with _jobs_lock:
            _active_jobs[tenant_id] = {
                "status": "running",
                "started": _dt.utcnow().isoformat(),
                "log": [],
                "result": {},
            }

        integration_data = {}

        # ── Step 1: Pull Telivy data ──────────────────────────────────
        _log_step(tenant_id, "telivy_pull", f"Pulling scan data for {scan_id} (type={scan_type})")
        telivy_raw = {}
        if scan_id:
            try:
                from app.masri.telivy_routes import _get_telivy_client
                client = _get_telivy_client()

                if scan_type == "scan":
                    try:
                        scan_detail = client.get_external_scan(scan_id)
                        if scan_detail:
                            telivy_raw["scan"] = scan_detail
                            details = scan_detail.get("assessmentDetails", {})
                            _log_step(tenant_id, "telivy_scan",
                                      f"Scan: {details.get('organization_name', 'Unknown')} | "
                                      f"Score: {scan_detail.get('securityScore', 'N/A')} | "
                                      f"Status: {scan_detail.get('scanStatus', 'Unknown')}")
                    except Exception as e:
                        _log_step(tenant_id, "telivy_scan", f"Failed: {e}", "warning")

                    try:
                        findings = client.get_external_scan_findings(scan_id)
                        if findings and isinstance(findings, list):
                            telivy_raw["findings"] = findings[:50]
                            _log_step(tenant_id, "telivy_findings",
                                      f"Retrieved {len(findings)} findings (keeping top 50)")
                            # Log individual findings for live view
                            for f in findings[:10]:
                                if isinstance(f, dict):
                                    name = f.get("name", f.get("slug", ""))
                                    sev = f.get("severity", f.get("riskLevel", ""))
                                    _log_step(tenant_id, "finding",
                                              f"[{sev}] {name}", "data")
                    except Exception as e:
                        _log_step(tenant_id, "telivy_findings", f"Failed: {e}", "warning")

                elif scan_type == "assessment":
                    try:
                        assessment = client.get_risk_assessment(scan_id)
                        if assessment:
                            telivy_raw["assessment"] = assessment
                            details = assessment.get("assessmentDetails", {})
                            _log_step(tenant_id, "telivy_assessment",
                                      f"Assessment: {details.get('organization_name', 'Unknown')}")
                            # Log exec summary scores
                            exec_sum = assessment.get("executiveSummary", {})
                            if exec_sum:
                                for cat, scores in exec_sum.items():
                                    if isinstance(scores, dict) and scores.get("securityScore"):
                                        _log_step(tenant_id, "assessment_score",
                                                  f"{cat}: {scores['securityScore']}", "data")
                    except Exception as e:
                        _log_step(tenant_id, "telivy_assessment", f"Failed: {e}", "warning")

                if telivy_raw:
                    integration_data["telivy"] = telivy_raw
                    _log_step(tenant_id, "telivy_done",
                              f"Telivy data collected: {list(telivy_raw.keys())}")
                else:
                    _log_step(tenant_id, "telivy_done", "No Telivy data retrieved", "warning")
            except Exception as e:
                _log_step(tenant_id, "telivy_error", str(e), "error")

        # ── Step 2: Pull Entra ID data ────────────────────────────────
        _log_step(tenant_id, "entra_pull", "Checking Entra ID configuration...")
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
                    _log_step(tenant_id, "entra_users", f"Found {len(users)} users")
                except Exception as e:
                    _log_step(tenant_id, "entra_users", f"Failed: {e}", "warning")
                try:
                    mfa = entra_client.get_mfa_status()
                    entra_raw["mfa"] = mfa
                    if isinstance(mfa, list):
                        mfa_on = sum(1 for u in mfa if u.get("mfa_registered"))
                        _log_step(tenant_id, "entra_mfa", f"MFA: {mfa_on}/{len(mfa)} users enrolled")
                except Exception as e:
                    _log_step(tenant_id, "entra_mfa", f"Failed: {e}", "warning")
                try:
                    compliance = entra_client.assess_compliance()
                    entra_raw["compliance"] = compliance
                    _log_step(tenant_id, "entra_compliance",
                              f"Score: {compliance.get('overall_score', 'N/A')}/100")
                except Exception as e:
                    _log_step(tenant_id, "entra_compliance", f"Failed: {e}", "warning")
                if entra_raw:
                    integration_data["entra"] = entra_raw
            else:
                _log_step(tenant_id, "entra_skip", "Entra ID not configured", "info")
        except Exception as e:
            _log_step(tenant_id, "entra_error", str(e), "warning")

        # ── Step 3: Store raw data ────────────────────────────────────
        has_any_data = bool(integration_data.get("telivy") or integration_data.get("entra"))
        if has_any_data:
            _log_step(tenant_id, "store_data", "Saving integration data to client record...")
            try:
                existing = {}
                record = ConfigStore.find(f"tenant_integration_data_{tenant_id}")
                if record and record.value:
                    try:
                        existing = _json.loads(record.value)
                    except Exception:
                        pass
                if integration_data.get("telivy"):
                    existing["telivy"] = integration_data["telivy"]
                if integration_data.get("entra"):
                    existing["entra"] = integration_data["entra"]
                existing["_updated"] = _dt.utcnow().isoformat()
                ConfigStore.upsert(
                    f"tenant_integration_data_{tenant_id}",
                    _json.dumps(existing, default=str)[:100000],
                )
                _log_step(tenant_id, "store_done", "Data saved to client ConfigStore")
            except Exception as e:
                _log_step(tenant_id, "store_error", str(e), "error")

        # ── Step 4: Find projects ─────────────────────────────────────
        projects = db.session.execute(
            db.select(Project).filter_by(tenant_id=tenant_id)
        ).scalars().all()

        if not projects:
            _log_step(tenant_id, "no_projects",
                      "No projects found for this client — data stored at tenant level", "info")
            with _jobs_lock:
                _active_jobs[tenant_id]["status"] = "done"
                _active_jobs[tenant_id]["result"] = {
                    "controls_mapped": 0, "risks_added": 0,
                    "data_stored": has_any_data, "projects": 0,
                }
            _log_step(tenant_id, "complete", "Processing complete (data stored, no projects to map)")
            return

        if not integration_data:
            _log_step(tenant_id, "no_data", "No integration data to analyze", "error")
            with _jobs_lock:
                _active_jobs[tenant_id]["status"] = "failed"
                _active_jobs[tenant_id]["result"] = {"error": "No data pulled"}
            return

        # ── Step 5: LLM analysis per project ──────────────────────────
        total_mapped = 0
        total_risks = 0

        llm_available = False
        try:
            from app.masri.llm_service import LLMService
            llm_available = LLMService.is_enabled()
        except Exception:
            pass

        if not llm_available:
            _log_step(tenant_id, "llm_skip", "LLM not configured — storing raw data only", "warning")

        # ProjectControl VALID_REVIEW_STATUS = ["infosec action", "ready for auditor", "complete"]
        _STATUS_MAP = {
            "compliant": "complete",
            "partial": "ready for auditor",
            "non_compliant": "infosec action",
            "unknown": "infosec action",
        }
        _SEVERITY_MAP = {
            "critical": "critical", "high": "high",
            "medium": "moderate", "low": "low",
        }

        for project in projects:
            fw_name = project.framework.name if project.framework else "Unknown"
            _log_step(tenant_id, "project_start",
                      f"Processing project: {project.name} ({fw_name})")

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
                _log_step(tenant_id, "project_skip",
                          f"No controls in {project.name} — skipping", "warning")
                continue

            _log_step(tenant_id, "controls_loaded",
                      f"Found {len(controls)} controls in {fw_name}")

            if llm_available:
                try:
                    # Build structured data chunks for LLM
                    data_summary = _compress_for_llm(integration_data)
                    _log_step(tenant_id, "llm_prepare",
                              f"Prepared {len(data_summary)} chars of data for LLM analysis")

                    # Send controls in chunks if >30 to handle large frameworks
                    chunk_size = 25
                    for chunk_idx in range(0, len(controls), chunk_size):
                        chunk = controls[chunk_idx:chunk_idx + chunk_size]
                        chunk_label = f"controls {chunk_idx + 1}-{chunk_idx + len(chunk)}" if len(controls) > chunk_size else "all controls"

                        ctrl_list = "\n".join([
                            f"- [{c['project_control_id']}] {c['ref_code']}: {c['name']}"
                            for c in chunk
                        ])

                        _log_step(tenant_id, "llm_call",
                                  f"Sending {chunk_label} to LLM for mapping...")

                        messages = [
                            {
                                "role": "system",
                                "content": (
                                    "You are an expert compliance analyst reviewing security scan results against "
                                    f"the {fw_name} framework. You MUST respond with ONLY valid JSON — no markdown, "
                                    "no explanation, no text before or after.\n\n"
                                    "Your tasks:\n"
                                    "1. MAP each scan finding to the most relevant compliance control\n"
                                    "2. CREATE detailed risk entries for ALL findings that represent security gaps\n\n"
                                    "IMPORTANT for risk entries:\n"
                                    "- Create a risk for EVERY significant security finding (unencrypted devices, "
                                    "missing MFA, open ports, weak configs, expired certs, vulnerable software, etc.)\n"
                                    "- Include specific details: affected hostnames, IP addresses, user accounts, "
                                    "device names, endpoint URLs, port numbers — whatever was in the scan\n"
                                    "- Explain WHY this is a risk and what could happen if not remediated\n"
                                    "- Be thorough — it's better to create too many risks than too few\n\n"
                                    "JSON format:\n"
                                    '{"mappings":[{"project_control_id":"ID","notes":"detailed finding with affected '
                                    'assets/users/endpoints","status":"compliant|partial|non_compliant"}],'
                                    '"risks":[{"title":"specific risk name","description":"Detailed description '
                                    'including: what was found, which specific assets/users/endpoints are affected, '
                                    'why this is dangerous, and recommended remediation steps",'
                                    '"severity":"critical|high|medium|low"}]}'
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
                        _log_step(tenant_id, "llm_response",
                                  f"LLM responded ({len(content)} chars, model: {result.get('model', 'unknown')})")

                        parsed = _extract_json(content)

                        if parsed is None:
                            _log_step(tenant_id, "llm_parse_fail",
                                      f"Could not parse LLM JSON: {content[:200]}", "error")
                            continue

                        mappings = parsed.get("mappings", [])
                        risks = parsed.get("risks", [])
                        _log_step(tenant_id, "llm_parsed",
                                  f"Parsed {len(mappings)} control mappings, {len(risks)} risks")

                        # Apply mappings
                        for m in mappings:
                            try:
                                pc_id = m.get("project_control_id")
                                notes = m.get("notes", "")
                                if pc_id and notes:
                                    pc = db.session.get(ProjectControl, pc_id)
                                    if pc:
                                        existing_notes = pc.notes or ""
                                        pc.notes = f"{existing_notes}\n\n[Auto-Mapped] {notes}".strip()
                                        llm_status = m.get("status", "").lower()
                                        new_status = _STATUS_MAP.get(llm_status)
                                        if new_status and pc.review_status in ("infosec action", "new", None, ""):
                                            pc.review_status = new_status
                                        total_mapped += 1
                                        _log_step(tenant_id, "mapped",
                                                  f"Mapped: {pc_id} → {llm_status}", "data")
                            except Exception:
                                pass

                        # Add risks
                        for r in risks:
                            try:
                                title = r.get("title", "")
                                if title:
                                    title_hash = RiskRegister._compute_title_hash(title, tenant_id)
                                    existing_risk = db.session.execute(
                                        db.select(RiskRegister).filter_by(
                                            title_hash=title_hash, tenant_id=tenant_id)
                                    ).scalars().first()
                                    if existing_risk:
                                        continue
                                    severity = _SEVERITY_MAP.get(
                                        r.get("severity", "").lower(), "unknown")
                                    risk_obj = RiskRegister(
                                        title=title,
                                        title_hash=title_hash,
                                        description=r.get("description", ""),
                                        risk=severity,
                                        tenant_id=tenant_id,
                                    )
                                    db.session.add(risk_obj)
                                    total_risks += 1
                                    _log_step(tenant_id, "risk_added",
                                              f"Risk: [{severity}] {title[:80]}", "data")
                            except Exception:
                                pass

                        db.session.commit()

                except Exception as e:
                    _log_step(tenant_id, "llm_error",
                              f"LLM processing failed for {project.name}: {e}", "error")
                    logger.warning("LLM auto-process failed for project %s: %s", project.id, e)
            else:
                # No LLM — attach raw data to first control
                try:
                    if controls:
                        pc = db.session.get(ProjectControl, controls[0]["project_control_id"])
                        if pc:
                            pc.notes = (pc.notes or "") + f"\n\n[Integration Data]\n{_json.dumps(integration_data, indent=2, default=str)[:500]}"
                            total_mapped += 1
                            db.session.commit()
                except Exception:
                    pass

        # ── Done ──────────────────────────────────────────────────────
        _log_step(tenant_id, "complete",
                  f"Processing complete: {total_mapped} controls mapped, {total_risks} risks added")

        with _jobs_lock:
            _active_jobs[tenant_id]["status"] = "done"
            _active_jobs[tenant_id]["result"] = {
                "controls_mapped": total_mapped,
                "risks_added": total_risks,
                "projects": len(projects),
                "data_sources": list(integration_data.keys()),
            }

        # Persist final state
        try:
            ConfigStore.upsert(
                f"process_log_{tenant_id}",
                _json.dumps(_active_jobs.get(tenant_id, {}), default=str)[:100000],
            )
        except Exception:
            pass
        finally:
            # Clean up session to prevent leaking into other threads
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

    Kicks off background processing for a tenant. Returns immediately.
    Poll GET /api/v1/llm/process-status/<tenant_id> for progress.
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

    # Check if already running
    with _jobs_lock:
        existing = _active_jobs.get(tenant_id, {})
        if existing.get("status") == "running":
            return jsonify({
                "success": True,
                "already_running": True,
                "message": "Processing is already in progress for this client.",
            })

    # Launch in background thread
    app = current_app._get_current_object()
    t = threading.Thread(
        target=_run_auto_process,
        args=(app, tenant_id, scan_id, scan_type),
        daemon=True,
        name=f"auto-process-{tenant_id}",
    )
    t.start()

    return jsonify({
        "success": True,
        "message": "Processing started in background.",
        "status_url": f"/api/v1/llm/process-status/{tenant_id}",
    })


@llm_bp.route("/process-status/<string:tenant_id>", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def process_status(tenant_id):
    """
    GET /api/v1/llm/process-status/<tenant_id>

    Returns current processing status + live log for the frontend.
    Supports ?since=<iso_timestamp> to only return new log entries.
    """
    try:
        _validate_tenant_access(tenant_id)
    except Exception:
        pass

    since = request.args.get("since")

    # Check in-memory first (most current)
    with _jobs_lock:
        job = _active_jobs.get(tenant_id)

    # Fall back to ConfigStore (persisted across restarts)
    if not job:
        try:
            from app.models import ConfigStore
            record = ConfigStore.find(f"process_log_{tenant_id}")
            if record and record.value:
                job = _json.loads(record.value)
        except Exception:
            pass

    if not job:
        return jsonify({"status": "idle", "log": [], "result": {}})

    log = job.get("log", [])

    # Filter by timestamp if requested
    if since:
        log = [entry for entry in log if entry.get("ts", "") > since]

    return jsonify({
        "status": job.get("status", "idle"),
        "started": job.get("started"),
        "log": log,
        "result": job.get("result", {}),
        "total_log_entries": len(job.get("log", [])),
    })


def _compress_for_llm(data: dict) -> str:
    """Compress integration data into a structured, LLM-friendly summary.

    Groups Telivy findings by severity and extracts compliance-relevant details
    (category, CVE, remediation hints). Entra data is formatted as posture signals.
    """
    sections = []

    # ── Telivy scan/assessment data ───────────────────────────────────
    telivy = data.get("telivy", {})
    if telivy:
        scan = telivy.get("scan", {})
        assessment = telivy.get("assessment", {})
        findings = telivy.get("findings", [])

        # Org overview
        details = (scan or assessment or {}).get("assessmentDetails", {})
        if details:
            sections.append(
                f"ORGANIZATION: {details.get('organization_name', 'Unknown')} "
                f"({details.get('domain_prim', 'Unknown')})"
            )

        if scan:
            sections.append(f"Security Score: {scan.get('securityScore', 'N/A')}")

        if assessment:
            exec_sum = assessment.get("executiveSummary", {})
            if exec_sum:
                scores = []
                for cat, val in exec_sum.items():
                    if isinstance(val, dict) and val.get("securityScore"):
                        scores.append(f"{cat}={val['securityScore']}")
                if scores:
                    sections.append(f"Assessment Scores: {', '.join(scores)}")

        # Findings grouped by severity for cleaner LLM analysis
        if findings:
            by_severity = {"critical": [], "high": [], "medium": [], "low": [], "info": [], "other": []}
            for f in findings:
                if not isinstance(f, dict):
                    continue
                sev = (f.get("severity") or f.get("riskLevel") or "other").lower()
                bucket = sev if sev in by_severity else "other"
                name = f.get("name") or f.get("slug") or f.get("title") or "Unknown"
                desc = (f.get("description") or f.get("details") or "")[:120]
                category = f.get("category") or f.get("type") or ""
                cve = f.get("cve") or f.get("cveId") or ""
                remediation = (f.get("remediation") or f.get("recommendation") or "")[:100]
                entry = name
                if category:
                    entry = f"[{category}] {entry}"
                if desc:
                    entry += f": {desc}"
                if cve:
                    entry += f" (CVE: {cve})"
                if remediation:
                    entry += f" | Fix: {remediation}"
                by_severity[bucket].append(entry)

            total = sum(len(v) for v in by_severity.values())
            sections.append(f"\nSECURITY FINDINGS ({total} total):")

            for sev in ["critical", "high", "medium", "low", "info"]:
                items = by_severity[sev]
                if items:
                    sections.append(f"\n[{sev.upper()}] ({len(items)}):")
                    for item in items[:15]:
                        sections.append(f"  - {item}")
                    if len(items) > 15:
                        sections.append(f"  ... and {len(items) - 15} more {sev} findings")

    # ── Entra ID posture signals ──────────────────────────────────────
    entra = data.get("entra_compliance") or {}
    entra_container = data.get("entra", {})
    if not entra and isinstance(entra_container, dict):
        entra = entra_container.get("compliance", {})

    if entra or entra_container:
        sections.append("\nIDENTITY & ACCESS (Entra ID):")
        if entra:
            sections.append(f"  Compliance Score: {entra.get('overall_score', 'N/A')}/100")
            for finding in entra.get("findings", []):
                if isinstance(finding, dict):
                    cat = finding.get("category", "")
                    sections.append(f"  - {cat}: {_json.dumps({k: v for k, v in finding.items() if k != 'category'}, default=str)[:120]}")
            for rec in entra.get("recommendations", [])[:5]:
                sections.append(f"  Recommendation: {rec}")

        mfa_data = entra_container.get("mfa") if isinstance(entra_container, dict) else None
        if isinstance(mfa_data, list) and mfa_data:
            total = len(mfa_data)
            mfa_on = sum(1 for u in mfa_data if u.get("mfa_registered"))
            rate = int(mfa_on / total * 100) if total else 0
            sections.append(f"  MFA: {mfa_on}/{total} users ({rate}%)")
            if rate < 100:
                no_mfa = [u.get("display_name", "?") for u in mfa_data if not u.get("mfa_registered")][:5]
                sections.append(f"  Users without MFA: {', '.join(no_mfa)}")

        users_data = entra_container.get("users") if isinstance(entra_container, dict) else None
        if isinstance(users_data, dict) and users_data.get("count"):
            sections.append(f"  Total Users: {users_data['count']}")

    # ── Existing risks ────────────────────────────────────────────────
    risks = data.get("risk_register", {})
    if risks and risks.get("count"):
        sections.append(f"\nEXISTING RISKS ({risks['count']}):")
        for r in risks.get("risks", [])[:5]:
            if isinstance(r, dict):
                sections.append(f"  - [{r.get('risk', 'unknown')}] {r.get('title', 'Unknown')}: {r.get('description', '')[:80]}")

    result = "\n".join(sections)
    # Hard cap to stay within token limits
    if len(result) > 8000:
        result = result[:8000] + "\n... (data truncated)"
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
