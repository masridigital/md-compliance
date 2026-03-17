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

logger = logging.getLogger(__name__)

llm_bp = Blueprint("llm_bp", __name__, url_prefix="/api/v1/llm")


def _require_llm():
    """Abort 403 if LLM is not enabled."""
    if not current_app.config.get("LLM_ENABLED"):
        abort(403, description="LLM features are not enabled")


@llm_bp.route("/control-assist", methods=["POST"])
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

    data = request.get_json(silent=True)
    if not data:
        abort(400, description="Request body must be valid JSON")

    control_description = data.get("control_description", "")
    evidence_text = data.get("evidence_text", "")
    tenant_id = data.get("tenant_id")

    if not control_description:
        return jsonify({"error": "control_description is required"}), 400
    if not evidence_text:
        return jsonify({"error": "evidence_text is required"}), 400

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

    data = request.get_json(silent=True)
    if not data:
        abort(400, description="Request body must be valid JSON")

    framework = data.get("framework", "")
    control_ref = data.get("control_ref", "")
    current_state = data.get("current_state", "")
    tenant_id = data.get("tenant_id")

    if not framework or not control_ref:
        return jsonify({"error": "framework and control_ref are required"}), 400

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

    data = request.get_json(silent=True)
    if not data:
        abort(400, description="Request body must be valid JSON")

    risk_description = data.get("risk_description", "")
    context = data.get("context", "")
    tenant_id = data.get("tenant_id")

    if not risk_description:
        return jsonify({"error": "risk_description is required"}), 400

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
            temperature=0.1,
            max_tokens=800,
        )

        content = result["content"].strip()
        # Handle markdown code blocks
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, IndexError):
            parsed = {
                "severity": "unknown",
                "explanation": content,
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

    data = request.get_json(silent=True)
    if not data:
        abort(400, description="Request body must be valid JSON")

    evidence_text = data.get("evidence_text", "")
    control_context = data.get("control_context", "")
    tenant_id = data.get("tenant_id")

    if not evidence_text:
        return jsonify({"error": "evidence_text is required"}), 400

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
@login_required
def llm_usage():
    """
    GET /api/v1/llm/usage?tenant_id=<id>

    Returns token usage and call statistics for the tenant.
    """
    tenant_id = request.args.get("tenant_id")
    if not tenant_id:
        return jsonify({"error": "tenant_id query parameter is required"}), 400

    try:
        from app.masri.llm_service import LLMService

        usage = LLMService.get_usage(tenant_id)
        return jsonify({"tenant_id": tenant_id, "usage": usage})
    except Exception as e:
        logger.exception("Usage fetch failed")
        return jsonify({"error": "Failed to retrieve usage stats"}), 500
