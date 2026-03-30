"""
Masri Digital Compliance Platform — MCP Server Blueprint

Model Context Protocol (MCP) server exposing compliance tools via a
JSON-over-HTTP API.  Authentication uses bearer tokens backed by
MCPAPIKey records.  Each tool is registered as a discoverable definition
with JSON-Schema-style parameter metadata.

Blueprint: ``mcp`` at url_prefix ``/mcp/v1``
"""

import json
import logging
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, jsonify, request, abort

logger = logging.getLogger(__name__)

mcp_bp = Blueprint("mcp", __name__, url_prefix="/mcp/v1")


# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------

def _error_response(code: int, message: str):
    """Return a JSON error response in the standard MCP envelope."""
    return jsonify({"error": {"code": code, "message": message}}), code


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def _authenticate():
    """
    Validate the ``Authorization: Bearer <key>`` header.

    Returns the ``MCPAPIKey`` record on success.  Aborts with 401 on
    any authentication failure.
    """
    from app.masri.new_models import MCPAPIKey

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        abort(401, description="Missing or malformed Authorization header")

    raw_key = auth_header[7:].strip()
    if not raw_key:
        abort(401, description="API key is empty")

    key_record = MCPAPIKey.validate(raw_key)
    if key_record is None:
        abort(401, description="Invalid or expired API key")

    # MCPAPIKey.validate() already checks ``enabled`` and ``expires_at``,
    # but we perform an explicit guard here so the intent is clear to
    # future readers and covers any edge-case drift.
    if not key_record.enabled:
        abort(401, description="API key is disabled")

    if key_record.expires_at and datetime.utcnow() > key_record.expires_at:
        abort(401, description="API key has expired")

    return key_record


def _require_auth(f):
    """Decorator that authenticates and injects ``api_key`` into kwargs."""

    @wraps(f)
    def decorated(*args, **kwargs):
        key_record = _authenticate()
        kwargs["api_key"] = key_record
        return f(*args, **kwargs)

    return decorated


# ---------------------------------------------------------------------------
# Rate-limiting placeholder
# ---------------------------------------------------------------------------

# In-memory sliding-window counters keyed by API-key id.
# A production deployment would use Redis or a similar store.
_rate_counters: dict = {}  # key_id -> list[float]


def _check_rate_limit(key_record):
    """
    Enforce per-key rate limiting if a ``rate_limit`` value is configured
    in the key's scopes metadata.

    The rate limit is expected as an integer (requests per minute) stored
    in ``scopes_json`` under the key ``"rate_limit"``, or as a top-level
    attribute if the model is extended in the future.
    """
    import time

    # Attempt to read a per-key rate limit from scopes metadata.
    rate_limit = None
    scopes = key_record.get_scopes()
    if isinstance(scopes, dict):
        rate_limit = scopes.get("rate_limit")
    if rate_limit is None:
        return  # No limit configured — allow the request.

    try:
        rate_limit = int(rate_limit)
    except (TypeError, ValueError):
        return

    now = time.time()
    window = 60.0  # 1-minute sliding window
    key_id = key_record.id

    timestamps = _rate_counters.get(key_id, [])
    timestamps = [t for t in timestamps if t > now - window]
    if len(timestamps) >= rate_limit:
        abort(429, description="Rate limit exceeded")

    timestamps.append(now)
    _rate_counters[key_id] = timestamps


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": "list_frameworks",
        "description": "List compliance frameworks available to a tenant.",
        "parameters": {
            "type": "object",
            "properties": {
                "tenant_id": {
                    "type": "string",
                    "description": "ID of the tenant whose frameworks to list.",
                },
            },
            "required": ["tenant_id"],
        },
    },
    {
        "name": "get_compliance_status",
        "description": (
            "Return a compliance summary for a project, including overall "
            "completion percentage, control counts, and status."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "ID of the project.",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "list_controls",
        "description": "List the controls associated with a project.",
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "ID of the project.",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "assess_control",
        "description": (
            "Use an LLM to assess a control against provided evidence text. "
            "Returns a status (compliant / partial / non_compliant / unknown), "
            "confidence score, explanation, and recommendations."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "control_id": {
                    "type": "string",
                    "description": "ID of the control to assess.",
                },
                "evidence_text": {
                    "type": "string",
                    "description": "Evidence text to evaluate against the control.",
                },
            },
            "required": ["control_id", "evidence_text"],
        },
    },
    {
        "name": "list_risks",
        "description": "Return the risk register entries for a tenant.",
        "parameters": {
            "type": "object",
            "properties": {
                "tenant_id": {
                    "type": "string",
                    "description": "ID of the tenant.",
                },
            },
            "required": ["tenant_id"],
        },
    },
    {
        "name": "get_due_dates",
        "description": (
            "Return upcoming due dates for a tenant within a specified "
            "look-ahead window."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tenant_id": {
                    "type": "string",
                    "description": "ID of the tenant.",
                },
                "days_ahead": {
                    "type": "integer",
                    "description": (
                        "Number of days to look ahead (default 30)."
                    ),
                    "default": 30,
                },
            },
            "required": ["tenant_id"],
        },
    },
    {
        "name": "generate_gap_narrative",
        "description": (
            "Use the configured LLM provider to generate a gap analysis "
            "narrative for a compliance control. Returns gap description, "
            "risk impact, and remediation steps."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "framework": {
                    "type": "string",
                    "description": "Compliance framework name (e.g. SOC2, NIST 800-53).",
                },
                "control_ref": {
                    "type": "string",
                    "description": "Control reference identifier.",
                },
                "current_state": {
                    "type": "string",
                    "description": "Description of the current implementation state.",
                },
                "tenant_id": {
                    "type": "string",
                    "description": "Tenant ID for usage tracking (optional).",
                },
            },
            "required": ["framework", "control_ref"],
        },
    },
    {
        "name": "score_risk",
        "description": (
            "Use the configured LLM provider to evaluate a risk description "
            "and return a structured risk score with likelihood (1-5), "
            "impact (1-5), severity, explanation, and mitigations."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "risk_description": {
                    "type": "string",
                    "description": "Description of the risk to evaluate.",
                },
                "context": {
                    "type": "string",
                    "description": "Organizational or environmental context (optional).",
                },
                "tenant_id": {
                    "type": "string",
                    "description": "Tenant ID for usage tracking (optional).",
                },
            },
            "required": ["risk_description"],
        },
    },
    {
        "name": "interpret_evidence",
        "description": (
            "Use the configured LLM provider to analyze evidence text and "
            "extract compliance-relevant findings, including evidence "
            "strength (strong/moderate/weak) and identified gaps."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "evidence_text": {
                    "type": "string",
                    "description": "The evidence text to analyze.",
                },
                "control_context": {
                    "type": "string",
                    "description": "Control or compliance context to evaluate against (optional).",
                },
                "tenant_id": {
                    "type": "string",
                    "description": "Tenant ID for usage tracking (optional).",
                },
            },
            "required": ["evidence_text"],
        },
    },
    {
        "name": "generate_policy",
        "description": (
            "Use the configured LLM provider to generate a policy draft "
            "for a compliance control. Returns Markdown-formatted policy "
            "with Purpose, Scope, Policy Statement, Responsibilities, "
            "and Review Schedule sections."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "framework": {
                    "type": "string",
                    "description": "Compliance framework name.",
                },
                "control_ref": {
                    "type": "string",
                    "description": "Control reference identifier.",
                },
                "organisation_context": {
                    "type": "string",
                    "description": "Organisation name or context for tailored policy (optional).",
                },
                "tenant_id": {
                    "type": "string",
                    "description": "Tenant ID for usage tracking (optional).",
                },
            },
            "required": ["framework", "control_ref"],
        },
    },
    {
        "name": "summarize_text",
        "description": (
            "Use the configured LLM provider to summarize a block of text. "
            "Useful for condensing long evidence documents, policy texts, "
            "or audit findings."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to summarize.",
                },
                "max_length": {
                    "type": "integer",
                    "description": "Maximum summary length in words (default 300).",
                    "default": 300,
                },
                "tenant_id": {
                    "type": "string",
                    "description": "Tenant ID for usage tracking (optional).",
                },
            },
            "required": ["text"],
        },
    },
]

# Index for O(1) lookup by name.
_TOOL_INDEX = {t["name"]: t for t in TOOL_DEFINITIONS}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _tool_list_frameworks(params: dict, api_key) -> dict:
    from app import db
    from app.models import Framework, Tenant

    tenant_id = params.get("tenant_id")
    if not tenant_id:
        return _missing_param("tenant_id")

    tenant = db.session.get(Tenant, tenant_id)
    if tenant is None:
        return {"error": {"code": 404, "message": "Tenant not found"}}

    # Scope check: if the API key is tenant-scoped, it must match.
    if api_key.tenant_id and api_key.tenant_id != tenant_id:
        return {"error": {"code": 403, "message": "Access denied for this tenant"}}

    frameworks = db.session.execute(db.select(Framework).filter_by(tenant_id=tenant_id)).scalars().all()
    return {
        "tenant_id": tenant_id,
        "frameworks": [fw.as_dict() for fw in frameworks],
    }


def _tool_get_compliance_status(params: dict, api_key) -> dict:
    from app import db
    from app.models import Project

    project_id = params.get("project_id")
    if not project_id:
        return _missing_param("project_id")

    project = db.session.get(Project, project_id)
    if project is None:
        return {"error": {"code": 404, "message": "Project not found"}}

    if api_key.tenant_id and api_key.tenant_id != project.tenant_id:
        return {"error": {"code": 403, "message": "Access denied for this project"}}

    data = project.as_dict(with_summary=True, exclude_timely=True)
    return {
        "project_id": project_id,
        "name": data.get("name"),
        "framework": data.get("framework"),
        "status": data.get("status", "unknown"),
        "completion_progress": data.get("completion_progress", 0),
        "total_controls": data.get("total_controls", 0),
        "total_policies": data.get("total_policies", 0),
    }


def _tool_list_controls(params: dict, api_key) -> dict:
    from app import db
    from app.models import Project, ProjectControl

    project_id = params.get("project_id")
    if not project_id:
        return _missing_param("project_id")

    project = db.session.get(Project, project_id)
    if project is None:
        return {"error": {"code": 404, "message": "Project not found"}}

    if api_key.tenant_id and api_key.tenant_id != project.tenant_id:
        return {"error": {"code": 403, "message": "Access denied for this project"}}

    controls = project.controls.all()
    result = []
    for pc in controls:
        ctrl = pc.control
        result.append({
            "project_control_id": pc.id,
            "control_id": ctrl.id if ctrl else None,
            "name": ctrl.name if ctrl else None,
            "ref_code": ctrl.ref_code if ctrl else None,
            "category": ctrl.category if ctrl else None,
            "review_status": pc.review_status,
        })

    return {
        "project_id": project_id,
        "controls": result,
    }


def _tool_assess_control(params: dict, api_key) -> dict:
    from app import db
    from app.models import Control
    from app.masri.llm_service import LLMService

    control_id = params.get("control_id")
    evidence_text = params.get("evidence_text")

    if not control_id:
        return _missing_param("control_id")
    if not evidence_text:
        return _missing_param("evidence_text")

    control = db.session.get(Control, control_id)
    if control is None:
        return {"error": {"code": 404, "message": "Control not found"}}

    if api_key.tenant_id and api_key.tenant_id != control.tenant_id:
        return {"error": {"code": 403, "message": "Access denied for this control"}}

    # Determine tenant_id for LLM budget tracking.
    tenant_id = api_key.tenant_id or control.tenant_id

    if not LLMService.is_enabled():
        return {"error": {"code": 503, "message": "LLM service is not configured"}}

    try:
        assessment = LLMService.assess_control(
            control_description=control.description or control.name,
            evidence_text=evidence_text,
            tenant_id=tenant_id,
        )
    except RuntimeError as exc:
        logger.error("LLM assess_control failed: %s", exc)
        return {"error": {"code": 502, "message": str(exc)}}

    return {
        "control_id": control_id,
        "assessment": assessment,
    }


def _tool_list_risks(params: dict, api_key) -> dict:
    from app import db
    from app.models import RiskRegister, Tenant

    tenant_id = params.get("tenant_id")
    if not tenant_id:
        return _missing_param("tenant_id")

    tenant = db.session.get(Tenant, tenant_id)
    if tenant is None:
        return {"error": {"code": 404, "message": "Tenant not found"}}

    if api_key.tenant_id and api_key.tenant_id != tenant_id:
        return {"error": {"code": 403, "message": "Access denied for this tenant"}}

    risks = db.session.execute(db.select(RiskRegister).filter_by(tenant_id=tenant_id)).scalars().all()
    return {
        "tenant_id": tenant_id,
        "risks": [r.as_dict() for r in risks],
    }


def _tool_get_due_dates(params: dict, api_key) -> dict:
    from app import db
    from app.masri.new_models import DueDate

    tenant_id = params.get("tenant_id")
    if not tenant_id:
        return _missing_param("tenant_id")

    if api_key.tenant_id and api_key.tenant_id != tenant_id:
        return {"error": {"code": 403, "message": "Access denied for this tenant"}}

    days_ahead = params.get("days_ahead", 30)
    try:
        days_ahead = int(days_ahead)
    except (TypeError, ValueError):
        days_ahead = 30

    cutoff = datetime.utcnow() + timedelta(days=days_ahead)
    due_dates = (
        db.session.execute(
            db.select(DueDate)
            .filter_by(tenant_id=tenant_id)
            .filter(DueDate.due_date <= cutoff)
            .filter(DueDate.status.in_(["pending", "overdue"]))
            .order_by(DueDate.due_date.asc())
        ).scalars().all()
    )
    return {
        "tenant_id": tenant_id,
        "days_ahead": days_ahead,
        "due_dates": [dd.as_dict() for dd in due_dates],
    }


def _missing_param(name: str) -> dict:
    return {"error": {"code": 400, "message": f"Missing required parameter: {name}"}}


def _require_llm():
    """Return LLMService if enabled, or an error dict."""
    from app.masri.llm_service import LLMService
    if not LLMService.is_enabled():
        return None, {"error": {"code": 503, "message": "LLM is not configured. Configure an LLM provider in Settings > Integrations first."}}
    return LLMService, None


def _tool_generate_gap_narrative(params: dict, api_key) -> dict:
    LLMService, err = _require_llm()
    if err:
        return err

    framework = params.get("framework")
    control_ref = params.get("control_ref")
    if not framework:
        return _missing_param("framework")
    if not control_ref:
        return _missing_param("control_ref")

    current_state = params.get("current_state", "Not assessed")
    tenant_id = params.get("tenant_id") or api_key.tenant_id

    try:
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
                    f"Current state: {current_state}"
                ),
            },
        ]
        result = LLMService.chat(messages=messages, tenant_id=tenant_id, temperature=0.3, max_tokens=1500)
        return {
            "narrative": result["content"],
            "tokens_used": result["usage"]["total_tokens"],
            "model": result.get("model"),
            "provider": result.get("provider"),
        }
    except RuntimeError as exc:
        return {"error": {"code": 502, "message": str(exc)}}


def _tool_score_risk(params: dict, api_key) -> dict:
    import json as _json
    LLMService, err = _require_llm()
    if err:
        return err

    risk_description = params.get("risk_description")
    if not risk_description:
        return _missing_param("risk_description")

    context = params.get("context", "General organization")
    tenant_id = params.get("tenant_id") or api_key.tenant_id

    try:
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
                "content": f"Risk: {risk_description}\nContext: {context}",
            },
        ]
        result = LLMService.chat(messages=messages, tenant_id=tenant_id, temperature=0.1, max_tokens=800)
        content = result["content"].strip()

        # Handle markdown code blocks
        if content.startswith("```"):
            parts = content.split("\n", 1)
            content = parts[1].rsplit("```", 1)[0].strip() if len(parts) > 1 else content

        try:
            parsed = _json.loads(content)
        except (_json.JSONDecodeError, ValueError):
            parsed = {
                "likelihood": 0, "impact": 0, "overall_score": 0,
                "severity": "unknown",
                "explanation": content, "mitigations": [],
            }

        return {
            "risk_score": parsed,
            "tokens_used": result["usage"]["total_tokens"],
            "model": result.get("model"),
            "provider": result.get("provider"),
        }
    except RuntimeError as exc:
        return {"error": {"code": 502, "message": str(exc)}}


def _tool_interpret_evidence(params: dict, api_key) -> dict:
    LLMService, err = _require_llm()
    if err:
        return err

    evidence_text = params.get("evidence_text")
    if not evidence_text:
        return _missing_param("evidence_text")

    control_context = params.get("control_context", "General compliance")
    tenant_id = params.get("tenant_id") or api_key.tenant_id

    try:
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
                    f"Control context: {control_context}"
                ),
            },
        ]
        result = LLMService.chat(messages=messages, tenant_id=tenant_id, temperature=0.2, max_tokens=1200)
        return {
            "interpretation": result["content"],
            "tokens_used": result["usage"]["total_tokens"],
            "model": result.get("model"),
            "provider": result.get("provider"),
        }
    except RuntimeError as exc:
        return {"error": {"code": 502, "message": str(exc)}}


def _tool_generate_policy(params: dict, api_key) -> dict:
    LLMService, err = _require_llm()
    if err:
        return err

    framework = params.get("framework")
    control_ref = params.get("control_ref")
    if not framework:
        return _missing_param("framework")
    if not control_ref:
        return _missing_param("control_ref")

    organisation_context = params.get("organisation_context", "General")
    tenant_id = params.get("tenant_id") or api_key.tenant_id

    try:
        policy = LLMService.generate_policy_draft(
            framework=framework,
            control_ref=control_ref,
            organisation_context=organisation_context,
            tenant_id=tenant_id,
        )
        return {
            "policy_markdown": policy,
            "model": "configured",
            "provider": "configured",
        }
    except RuntimeError as exc:
        return {"error": {"code": 502, "message": str(exc)}}


def _tool_summarize_text(params: dict, api_key) -> dict:
    LLMService, err = _require_llm()
    if err:
        return err

    text = params.get("text")
    if not text:
        return _missing_param("text")

    max_length = params.get("max_length", 300)
    tenant_id = params.get("tenant_id") or api_key.tenant_id

    try:
        summary = LLMService.summarise(text=text, tenant_id=tenant_id, max_length=max_length)
        return {
            "summary": summary,
            "model": "configured",
            "provider": "configured",
        }
    except RuntimeError as exc:
        return {"error": {"code": 502, "message": str(exc)}}


# Dispatch table mapping tool names to handler functions.
_TOOL_HANDLERS = {
    "list_frameworks": _tool_list_frameworks,
    "get_compliance_status": _tool_get_compliance_status,
    "list_controls": _tool_list_controls,
    "assess_control": _tool_assess_control,
    "list_risks": _tool_list_risks,
    "get_due_dates": _tool_get_due_dates,
    "generate_gap_narrative": _tool_generate_gap_narrative,
    "score_risk": _tool_score_risk,
    "interpret_evidence": _tool_interpret_evidence,
    "generate_policy": _tool_generate_policy,
    "summarize_text": _tool_summarize_text,
}


# ---------------------------------------------------------------------------
# Scope enforcement
# ---------------------------------------------------------------------------

def _check_scope(api_key, tool_name: str) -> bool:
    """
    Return ``True`` if the API key is allowed to invoke ``tool_name``.

    Keys with ``scopes_json`` set to ``null`` (or an absent list) have
    access to all tools.  Otherwise the tool name must appear in the
    scopes list.
    """
    scopes = api_key.get_scopes()
    if scopes is None:
        return True
    if isinstance(scopes, list) and tool_name in scopes:
        return True
    # If scopes is a dict, check for a "tools" key containing a list.
    if isinstance(scopes, dict):
        tools_list = scopes.get("tools")
        if tools_list is None:
            return True
        if isinstance(tools_list, list) and tool_name in tools_list:
            return True
    return False


# ---------------------------------------------------------------------------
# Error handlers for the blueprint
# ---------------------------------------------------------------------------

@mcp_bp.errorhandler(400)
def _handle_400(exc):
    return _error_response(400, str(exc.description) if hasattr(exc, "description") else "Bad request")


@mcp_bp.errorhandler(401)
def _handle_401(exc):
    return _error_response(401, str(exc.description) if hasattr(exc, "description") else "Unauthorized")


@mcp_bp.errorhandler(403)
def _handle_403(exc):
    return _error_response(403, str(exc.description) if hasattr(exc, "description") else "Forbidden")


@mcp_bp.errorhandler(404)
def _handle_404(exc):
    return _error_response(404, str(exc.description) if hasattr(exc, "description") else "Not found")


@mcp_bp.errorhandler(429)
def _handle_429(exc):
    return _error_response(429, str(exc.description) if hasattr(exc, "description") else "Rate limit exceeded")


@mcp_bp.errorhandler(500)
def _handle_500(exc):
    return _error_response(500, "Internal server error")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@mcp_bp.route("/docs", methods=["GET"])
def public_docs():
    """
    GET /mcp/v1/docs — Public API documentation endpoint.

    Returns the full MCP tool catalogue with parameter schemas,
    authentication requirements, and usage examples.
    No authentication required.
    """
    return jsonify({
        "name": "Masri Digital Compliance MCP Server",
        "version": "1.0",
        "description": (
            "Model Context Protocol server exposing compliance management tools. "
            "Supports framework listing, compliance status, control assessment "
            "(with LLM), risk register access, and due date tracking."
        ),
        "authentication": {
            "type": "bearer",
            "header": "Authorization: Bearer <api_key>",
            "description": (
                "Generate API keys from Settings > API Keys. "
                "Include the key in the Authorization header for all /tools endpoints."
            ),
        },
        "base_url": "/mcp/v1",
        "endpoints": {
            "GET /mcp/v1/docs": "This documentation endpoint (no auth required)",
            "GET /mcp/v1/tools": "List available tools (auth required, scope-filtered)",
            "POST /mcp/v1/tools/<tool_name>": "Execute a tool (auth required)",
        },
        "tools": TOOL_DEFINITIONS,
        "rate_limiting": "Configurable per API key via scopes.rate_limit (requests per minute)",
    })


@mcp_bp.route("/tools", methods=["GET"])
def list_tools():
    """
    Tool discovery endpoint.

    Returns the catalogue of available tools with their JSON-Schema
    parameter definitions.  Authentication is required so that scoped
    keys only see tools they are permitted to call.
    """
    api_key = _authenticate()
    _check_rate_limit(api_key)

    # Filter the tool list according to the key's scopes.
    visible = []
    for tool_def in TOOL_DEFINITIONS:
        if _check_scope(api_key, tool_def["name"]):
            visible.append(tool_def)

    return jsonify({"tools": visible})


@mcp_bp.route("/tools/<string:tool_name>", methods=["POST"])
def execute_tool(tool_name: str):
    """
    Tool execution endpoint.

    Dispatches to the named tool handler with the JSON body as
    parameters.  The response envelope is:

    .. code-block:: json

        {"result": { ... tool-specific payload ... }}

    or on error:

    .. code-block:: json

        {"error": {"code": <int>, "message": "<string>"}}
    """
    api_key = _authenticate()
    _check_rate_limit(api_key)

    # --- validate tool name ---
    if tool_name not in _TOOL_HANDLERS:
        return _error_response(404, f"Unknown tool: {tool_name}")

    # --- scope check ---
    if not _check_scope(api_key, tool_name):
        return _error_response(
            403, f"API key does not have permission to invoke '{tool_name}'"
        )

    # --- parse body ---
    params = request.get_json(silent=True) or {}
    if not isinstance(params, dict):
        return _error_response(400, "Request body must be a JSON object")

    # --- log the call ---
    logger.info(
        "MCP tool=%s key=%s tenant=%s",
        tool_name,
        api_key.key_prefix,
        api_key.tenant_id,
    )

    # --- execute ---
    try:
        result = _TOOL_HANDLERS[tool_name](params, api_key)
    except Exception:
        logger.exception("Unhandled error in MCP tool %s", tool_name)
        return _error_response(500, "Internal server error while executing tool")

    # If the handler returned an error dict, translate it to an HTTP response.
    if isinstance(result, dict) and "error" in result:
        err = result["error"]
        return _error_response(err.get("code", 500), err.get("message", "Unknown error"))

    return jsonify({"result": result})
