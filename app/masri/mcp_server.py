"""
Masri Digital Compliance Platform — MCP Server Blueprint

Model Context Protocol (MCP) server exposing compliance tools via a
JSON-over-HTTP API.  Authentication uses bearer tokens backed by
MCPAPIKey records.  Each tool is registered as a discoverable definition
with JSON-Schema-style parameter metadata.

Blueprint: ``mcp`` at url_prefix ``/mcp``
"""

import json
import logging
import hashlib
import secrets
import time
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, jsonify, request, abort
from app import limiter

logger = logging.getLogger(__name__)

mcp_bp = Blueprint("mcp", __name__, url_prefix="/mcp")


# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------

def _error_response(code: int, message: str):
    """Return a JSON error response in the standard MCP envelope."""
    return jsonify({"error": {"code": code, "message": message}}), code


# NOTE: _authenticate and _require_auth are defined below alongside the
# OAuth 2.0 token store, after the tool implementations section.


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
# OAuth 2.0 — In-memory access token store
# ---------------------------------------------------------------------------

# Maps access_token_hash -> { "key_record_id": str, "expires": float }
_oauth_tokens: dict = {}


def _issue_oauth_token(key_record) -> tuple:
    """Issue a short-lived OAuth access token for an authenticated API key.

    Returns (access_token, expires_in_seconds).
    """
    access_token = f"mcp_at_{secrets.token_urlsafe(48)}"
    token_hash = hashlib.sha256(access_token.encode()).hexdigest()
    expires_in = 3600  # 1 hour
    _oauth_tokens[token_hash] = {
        "key_record_id": key_record.id,
        "expires": time.time() + expires_in,
    }
    # Prune expired tokens (keep store small)
    now = time.time()
    expired = [h for h, v in _oauth_tokens.items() if v["expires"] < now]
    for h in expired:
        _oauth_tokens.pop(h, None)

    return access_token, expires_in


def _validate_oauth_token(token: str):
    """Validate an OAuth access token. Returns the MCPAPIKey record or None."""
    from app.masri.new_models import MCPAPIKey
    from app import db

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    entry = _oauth_tokens.get(token_hash)
    if not entry:
        return None
    if entry["expires"] < time.time():
        _oauth_tokens.pop(token_hash, None)
        return None
    return db.session.get(MCPAPIKey, entry["key_record_id"])


# ---------------------------------------------------------------------------
# Updated authentication — supports both API keys and OAuth tokens
# ---------------------------------------------------------------------------

def _authenticate():
    """
    Validate the ``Authorization: Bearer <token>`` header.

    Accepts either:
      1. A raw MCP API key (``mcp_...``)
      2. An OAuth access token (``mcp_at_...``) issued by POST /mcp/token

    Returns the ``MCPAPIKey`` record on success. Aborts 401 on failure.
    """
    from app.masri.new_models import MCPAPIKey

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        abort(401, description="Missing or malformed Authorization header. Use OAuth: POST /mcp/token with client_credentials grant, or pass an API key directly.")

    token = auth_header[7:].strip()
    if not token:
        abort(401, description="Bearer token is empty")

    # Try OAuth access token first
    if token.startswith("mcp_at_"):
        key_record = _validate_oauth_token(token)
        if key_record is None:
            abort(401, description="Invalid or expired OAuth access token. Request a new one via POST /mcp/token.")
        return key_record

    # Fall back to raw API key
    key_record = MCPAPIKey.validate(token)
    if key_record is None:
        abort(401, description="Invalid or expired API key")

    if not key_record.enabled:
        abort(401, description="API key is disabled")

    if key_record.expires_at and datetime.utcnow() > key_record.expires_at:
        abort(401, description="API key has expired")

    return key_record


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@mcp_bp.route("/.well-known/oauth-authorization-server", methods=["GET"])
def oauth_metadata():
    """
    OAuth 2.0 Authorization Server Metadata (RFC 8414).

    LLM clients and MCP-compatible tools discover the token endpoint
    and supported grant types from this well-known URL.
    """
    base = request.host_url.rstrip("/") + "/mcp"
    return jsonify({
        "issuer": base,
        "token_endpoint": base + "/token",
        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
        "grant_types_supported": ["client_credentials"],
        "scopes_supported": ["mcp:tools", "mcp:read", "mcp:write"],
        "response_types_supported": [],
        "service_documentation": base + "/docs",
    })


@mcp_bp.route("/token", methods=["POST"])
@limiter.limit("10 per minute")
def oauth_token():
    """
    OAuth 2.0 Token Endpoint — Client Credentials Grant.

    Accepts:
      - ``grant_type=client_credentials`` (required)
      - ``client_id`` — the MCP API key prefix (first 8 chars) or full key
      - ``client_secret`` — the full MCP API key

    Supports both form-encoded body and HTTP Basic auth.

    Returns:
        { "access_token": "...", "token_type": "Bearer", "expires_in": 3600 }
    """
    from app.masri.new_models import MCPAPIKey

    # Accept form-encoded or JSON
    if request.content_type and "json" in request.content_type:
        data = request.get_json(silent=True) or {}
    else:
        data = request.form.to_dict()

    grant_type = data.get("grant_type", "")
    if grant_type != "client_credentials":
        return jsonify({
            "error": "unsupported_grant_type",
            "error_description": "Only client_credentials grant is supported."
        }), 400

    # Extract client credentials — prefer body, fall back to Basic auth
    client_id = data.get("client_id", "")
    client_secret = data.get("client_secret", "")

    if not client_id and not client_secret:
        # Try HTTP Basic auth (username=client_id, password=client_secret)
        auth = request.authorization
        if auth:
            client_id = auth.username or ""
            client_secret = auth.password or ""

    if not client_id and not client_secret:
        return jsonify({
            "error": "invalid_client",
            "error_description": "client_id and client_secret are required. Generate credentials in Integrations > MCP Server."
        }), 401

    # Validate: look up by client_id first, then verify client_secret
    key_record = None
    if client_id and client_secret:
        # Standard OAuth: validate client_id matches, then verify secret hash
        key_record = MCPAPIKey.find_by_client_id(client_id)
        if key_record:
            # Verify the secret matches
            expected_hash = hashlib.sha256(client_secret.encode()).hexdigest()
            if key_record.key_hash != expected_hash:
                key_record = None
    elif client_secret:
        # Legacy: secret-only auth (backward compat)
        key_record = MCPAPIKey.validate(client_secret)

    if key_record is None:
        return jsonify({
            "error": "invalid_client",
            "error_description": "Invalid credentials. Check your client_id and client_secret."
        }), 401

    if not key_record.enabled:
        return jsonify({
            "error": "invalid_client",
            "error_description": "Credential is disabled."
        }), 401

    if key_record.expires_at and datetime.utcnow() > key_record.expires_at:
        return jsonify({
            "error": "invalid_client",
            "error_description": "Credential has expired."
        }), 401

    # Issue access token
    access_token, expires_in = _issue_oauth_token(key_record)

    # Update last_used_at
    from app import db
    key_record.last_used_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "scope": "mcp:tools mcp:read mcp:write",
    })


@mcp_bp.route("/docs", methods=["GET"])
def public_docs():
    """
    GET /mcp/docs — Public API documentation endpoint.

    Returns the full MCP tool catalogue with parameter schemas,
    authentication requirements, and usage examples.
    No authentication required.
    """
    base = request.host_url.rstrip("/") + "/mcp"
    return jsonify({
        "name": "Masri Digital Compliance MCP Server",
        "version": "1.0",
        "description": (
            "Model Context Protocol server exposing compliance management tools. "
            "Supports framework listing, compliance status, control assessment "
            "(with LLM), risk register access, and due date tracking."
        ),
        "authentication": {
            "type": "oauth2",
            "flows": {
                "client_credentials": {
                    "token_url": base + "/token",
                    "description": (
                        "Use your MCP API key as the client_secret in a standard "
                        "OAuth 2.0 client_credentials grant. The client_id can be "
                        "any value (or the key prefix). A short-lived access token "
                        "is returned for use as a Bearer token."
                    ),
                },
            },
            "discovery_url": base + "/.well-known/oauth-authorization-server",
            "legacy_api_key": (
                "You can also pass the raw MCP API key directly as a Bearer token "
                "without going through the OAuth flow."
            ),
        },
        "base_url": base,
        "endpoints": {
            "GET  /.well-known/oauth-authorization-server": "OAuth 2.0 server metadata (RFC 8414)",
            "POST /token": "OAuth 2.0 token endpoint (client_credentials grant)",
            "GET  /docs": "This documentation (no auth required)",
            "GET  /tools": "List available tools (auth required)",
            "POST /tools/<tool_name>": "Execute a tool (auth required)",
        },
        "quick_start": {
            "step_1": "Generate an API key in Integrations > MCP Server",
            "step_2": "POST /mcp/token with grant_type=client_credentials&client_secret=YOUR_KEY",
            "step_3": "Use the returned access_token as: Authorization: Bearer <access_token>",
            "step_4": "GET /mcp/tools to discover available tools",
            "step_5": "POST /mcp/tools/<name> with JSON params to execute",
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
