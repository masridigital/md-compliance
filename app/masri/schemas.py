"""
Masri Digital Compliance Platform — Masri Module Marshmallow Schemas

Defines validation schemas for all JSON payloads accepted by
the masri blueprint endpoints (LLM, WISP, Notifications, Settings).
"""

from flask import jsonify
from marshmallow import Schema, fields, validate, ValidationError, EXCLUDE, INCLUDE


# ---------------------------------------------------------------------------
# Helper (mirrors api_v1 version for independence)
# ---------------------------------------------------------------------------

def validate_payload(schema_class, data):
    """Validate a JSON payload against a marshmallow schema.

    Returns:
        (data, None) on success — data is the deserialized dict.
        (None, response) on failure — response is a Flask (json, 422) tuple.
    """
    schema = schema_class()
    try:
        result = schema.load(data or {})
        return result, None
    except ValidationError as err:
        return None, (jsonify({"error": "Validation failed", "details": err.messages}), 422)


# ===========================================================================
# llm_routes.py schemas
# ===========================================================================

class ControlAssistSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    control_description = fields.Str(required=True, validate=validate.Length(min=1))
    evidence_text = fields.Str(required=True, validate=validate.Length(min=1))
    tenant_id = fields.Str(load_default=None)


class GapNarrativeSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    framework = fields.Str(required=True, validate=validate.Length(min=1))
    control_ref = fields.Str(required=True, validate=validate.Length(min=1))
    current_state = fields.Str(load_default="")
    tenant_id = fields.Str(load_default=None)


class RiskScoreSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    risk_description = fields.Str(required=True, validate=validate.Length(min=1))
    context = fields.Str(load_default="")
    tenant_id = fields.Str(load_default=None)


class InterpretEvidenceSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    evidence_text = fields.Str(required=True, validate=validate.Length(min=1))
    control_context = fields.Str(load_default="")
    tenant_id = fields.Str(load_default=None)


# ===========================================================================
# wisp_routes.py schemas
# ===========================================================================

class WISPAssistSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    step = fields.Int(load_default=None)
    step_name = fields.Str(load_default="")
    data = fields.Dict(load_default={})
    tenant_id = fields.Str(load_default=None)


class WISPGenerateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    wizard_data = fields.Dict(required=True)
    tenant_id = fields.Str(load_default=None)
    format = fields.Str(load_default="html", validate=validate.OneOf(["html", "pdf"]))


class WISPSignSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    signature_data = fields.Str(required=True, validate=validate.Length(min=1))


class WISPLLMGenerateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    sections = fields.List(fields.Str(), load_default=None)


# ===========================================================================
# notification_routes.py schemas
# ===========================================================================

class TestTeamsSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    tenant_id = fields.Str(required=True, validate=validate.Length(min=1))
    webhook_url = fields.Str(load_default=None)


class TestEmailSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    tenant_id = fields.Str(required=True, validate=validate.Length(min=1))
    recipient = fields.Email(required=True)


class SendNotificationSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    tenant_id = fields.Str(required=True, validate=validate.Length(min=1))
    channel = fields.Str(required=True, validate=validate.OneOf(["teams", "email", "slack", "sms"]))
    subject = fields.Str(load_default="Notification")
    body = fields.Str(load_default="")
    recipient = fields.Str(load_default=None)
    card_type = fields.Str(load_default="general")


class CheckRemindersSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    tenant_id = fields.Str(required=True, validate=validate.Length(min=1))


# ===========================================================================
# settings_routes.py schemas
# ===========================================================================

class PlatformSettingsUpdateSchema(Schema):
    """Dynamic platform settings — fields vary."""
    class Meta:
        unknown = INCLUDE
    # TODO: tighten once PlatformSettings model fields are documented


class TenantBrandingUpdateSchema(Schema):
    """Dynamic tenant branding — fields vary."""
    class Meta:
        unknown = INCLUDE
    # TODO: tighten once TenantBranding model fields are documented


class LLMConfigUpdateSchema(Schema):
    """Dynamic LLM config — fields vary."""
    class Meta:
        unknown = INCLUDE
    # TODO: tighten once SettingsLLM model fields are documented


class StorageProviderUpdateSchema(Schema):
    """Dynamic storage config — fields vary."""
    class Meta:
        unknown = INCLUDE
    # TODO: tighten once SettingsStorage model fields are documented


class SSOConfigUpdateSchema(Schema):
    """Dynamic SSO config — fields vary."""
    class Meta:
        unknown = INCLUDE
    # TODO: tighten once SettingsSSO model fields are documented


class NotificationChannelUpdateSchema(Schema):
    """Dynamic notification channel config — fields vary."""
    class Meta:
        unknown = EXCLUDE
    tenant_id = fields.Str(load_default=None)


class MCPKeyCreateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    name = fields.Str(required=True, validate=validate.Length(min=1, max=255))
    tenant_id = fields.Str(load_default=None)
    scopes = fields.Raw(load_default=None)
    expires_at = fields.Str(load_default=None)
