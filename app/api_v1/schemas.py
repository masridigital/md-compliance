"""
Masri Digital Compliance Platform — API v1 Marshmallow Schemas

Defines validation schemas for all JSON payloads accepted by
the api_v1 blueprint endpoints.
"""

from flask import jsonify
from marshmallow import Schema, fields, validate, ValidationError, EXCLUDE, INCLUDE


# ---------------------------------------------------------------------------
# Helper
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
# base.py schemas
# ===========================================================================

class UserExistSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    email = fields.Email(required=True)


class AdminUserCreateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    email = fields.Email(required=True)


class UserUpdateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    username = fields.Str(load_default=None, validate=validate.Length(max=255))
    email = fields.Email(load_default=None)
    first_name = fields.Str(load_default=None, validate=validate.Length(max=255))
    last_name = fields.Str(load_default=None, validate=validate.Length(max=255))
    license = fields.Str(load_default=None)
    trial_days = fields.Int(load_default=None)
    is_active = fields.Bool(load_default=None)
    super = fields.Bool(load_default=None)
    can_user_create_tenant = fields.Bool(load_default=None)
    tenant_limit = fields.Int(load_default=None)
    email_confirmed = fields.Bool(load_default=None)


class VerifyConfirmationSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    code = fields.Str(required=True, validate=validate.Length(min=1))


class PasswordChangeSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    password = fields.Str(required=True, validate=validate.Length(min=8, max=128))
    password2 = fields.Str(required=True, validate=validate.Length(min=8, max=128))


class TenantUpdateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    contact_email = fields.Email(load_default=None)
    magic_link_login = fields.Bool(load_default=None)
    approved_domains = fields.Raw(load_default=None)  # str or list
    license = fields.Str(load_default=None)
    storage_cap = fields.Raw(load_default=None)
    user_cap = fields.Int(load_default=None)
    project_cap = fields.Int(load_default=None)


class TenantCreateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    name = fields.Str(required=True, validate=validate.Length(min=1, max=255))
    contact_email = fields.Email(load_default=None)
    approved_domains = fields.Raw(load_default=None)


class UserInTenantUpdateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    username = fields.Str(load_default=None, validate=validate.Length(max=255))
    email = fields.Email(load_default=None)
    first_name = fields.Str(load_default=None, validate=validate.Length(max=255))
    last_name = fields.Str(load_default=None, validate=validate.Length(max=255))
    license = fields.Str(load_default=None)
    trial_days = fields.Int(load_default=None)
    roles = fields.List(fields.Str(), load_default=None)


class AddUserToTenantSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    email = fields.Email(required=True)
    roles = fields.List(fields.Str(), load_default=[])


class AIChatSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    messages = fields.List(fields.Dict(), load_default=[])


# ===========================================================================
# views.py schemas
# ===========================================================================

class DataFieldSchema(Schema):
    """Generic schema for endpoints that accept {data: <str>}."""
    class Meta:
        unknown = EXCLUDE
    data = fields.Str(required=True)


class CommentSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    data = fields.Str(required=True, validate=validate.Length(min=1))


class MemberSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    id = fields.Str(required=True)
    access_level = fields.Str(load_default=None)


class AddMembersSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    members = fields.List(fields.Nested(MemberSchema), required=True)


class AccessLevelSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    access_level = fields.Str(required=True)


class ControlCreateSchema(Schema):
    """Catch-all for control creation — payload forwarded to model."""
    class Meta:
        unknown = INCLUDE
    # TODO: tighten once Control.create() payload is documented
    name = fields.Str(load_default=None)
    ref_code = fields.Str(load_default=None)
    description = fields.Str(load_default=None)


class TenantPolicyCreateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    name = fields.Str(required=True, validate=validate.Length(min=1, max=255))
    description = fields.Str(load_default=None)
    code = fields.Str(load_default=None)


class ProjectUpdateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    name = fields.Str(load_default=None, validate=validate.Length(max=255))
    description = fields.Str(load_default=None)


class PolicyUpdateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    name = fields.Str(required=True)
    ref_code = fields.Str(required=True)
    description = fields.Str(required=True)
    template = fields.Str(required=True)
    content = fields.Str(required=True)


class ProjectCreateSchema(Schema):
    """Catch-all for project creation — payload forwarded to project_creation()."""
    class Meta:
        unknown = INCLUDE
    # TODO: tighten once project_creation() payload is documented
    name = fields.Str(load_default=None)
    framework_id = fields.Str(load_default=None)


class ProjectSettingsSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    name = fields.Str(load_default=None, validate=validate.Length(max=255))
    description = fields.Str(load_default=None)
    auditor_enabled = fields.Bool(load_default=None)
    can_auditor_read_scratchpad = fields.Bool(load_default=None)
    can_auditor_write_scratchpad = fields.Bool(load_default=None)
    can_auditor_read_comments = fields.Bool(load_default=None)
    can_auditor_write_comments = fields.Bool(load_default=None)
    policies_require_cc = fields.Bool(load_default=None)


class RiskCreateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    title = fields.Str(load_default=None, validate=validate.Length(max=500))
    description = fields.Str(load_default=None)
    status = fields.Str(load_default=None)
    risk = fields.Str(load_default=None)
    priority = fields.Str(load_default=None)


class PolicyVersionCreateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    content = fields.Str(load_default="")


class PolicyVersionUpdateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    content = fields.Str(load_default=None)
    status = fields.Str(load_default=None)
    publish = fields.Bool(load_default=None)


class ProjectPolicyUpdateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    name = fields.Str(load_default=None, validate=validate.Length(max=255))
    description = fields.Str(load_default=None)
    reviewer = fields.Str(load_default=None)


class ProjectPolicyCreateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    name = fields.Str(load_default=None, validate=validate.Length(max=255))
    description = fields.Str(load_default=None)
    template = fields.Str(load_default=None)


class ReviewStatusSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    # Note: field name uses hyphen in the payload
    review_status = fields.Str(data_key="review-status", required=True)


class SubcontrolUpdateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    applicable = fields.Bool(load_default=None)
    implemented = fields.Bool(load_default=None)
    notes = fields.Str(load_default=None)
    context = fields.Str(load_default=None)
    evidence = fields.Raw(load_default=None)
    owner_id = fields.Str(data_key="owner-id", load_default=None)


class ApplicabilitySchema(Schema):
    class Meta:
        unknown = EXCLUDE
    applicable = fields.Bool(required=True)


class EvidenceAssociationSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    evidence = fields.Raw(required=True)


class TagsSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    tags = fields.List(fields.Str(), required=True)


class RiskCommentSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    message = fields.Str(required=True, validate=validate.Length(min=1))


class AssigneeSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    assignee_id = fields.Str(data_key="assignee-id", load_default=None)


class FeedbackSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    title = fields.Str(load_default=None)
    description = fields.Str(load_default=None)
    is_complete = fields.Bool(load_default=None)
    response = fields.Str(load_default=None)
    relates_to = fields.Str(load_default=None)


class FeedbackUpdateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    title = fields.Str(load_default=None)
    description = fields.Str(load_default=None)
    is_complete = fields.Bool(load_default=None)
    response = fields.Str(load_default=None)


class ProjectTagSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    name = fields.Str(required=True, validate=validate.Length(min=1, max=255))


class ProjectControlCreateSchema(Schema):
    """Catch-all for custom control creation via project."""
    class Meta:
        unknown = INCLUDE
    # TODO: tighten once add_custom_control() payload is documented
    name = fields.Str(load_default=None)
    ref_code = fields.Str(load_default=None)
    description = fields.Str(load_default=None)


# ===========================================================================
# integrations.py schemas
# ===========================================================================

class IntegrationCreateSchema(Schema):
    """Dynamic payload forwarded to external integration API."""
    class Meta:
        unknown = INCLUDE
    # TODO: tighten once integration API payload is documented


class DeploymentCreateSchema(Schema):
    """Dynamic payload forwarded to external deployment API."""
    class Meta:
        unknown = INCLUDE
    # TODO: tighten once deployment API payload is documented


class DeploymentUpdateSchema(Schema):
    """Dynamic payload forwarded to external deployment API."""
    class Meta:
        unknown = INCLUDE
    # TODO: tighten once deployment API payload is documented


class DeploymentIdsSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    deployment_ids = fields.List(fields.Str(), required=True, validate=validate.Length(min=1))


# ===========================================================================
# vendors.py schemas
# ===========================================================================

class VendorCreateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    name = fields.Str(required=True, validate=validate.Length(min=1, max=255))
    description = fields.Str(load_default=None)
    contact_email = fields.Str(load_default=None)
    vendor_contact_email = fields.Str(load_default=None)
    location = fields.Str(load_default=None)
    criticality = fields.Str(load_default=None)
    review_cycle = fields.Int(load_default=12)
    disabled = fields.Bool(load_default=False)
    notes = fields.Str(load_default=None)
    start_date = fields.Str(load_default=None)


class VendorUpdateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    description = fields.Str(load_default=None)
    status = fields.Str(load_default=None)
    contact_email = fields.Str(load_default=None)
    vendor_contact_email = fields.Str(load_default=None)
    location = fields.Str(load_default=None)
    start_date = fields.Str(load_default=None)
    end_date = fields.Str(load_default=None)
    criticality = fields.Str(load_default=None)
    review_cycle = fields.Str(load_default=None)
    notes = fields.Str(load_default=None)


class VendorAppCreateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    name = fields.Str(required=True, validate=validate.Length(min=1, max=255))
    description = fields.Str(load_default=None)
    contact_email = fields.Str(load_default=None)
    start_date = fields.Str(load_default=None)
    end_date = fields.Str(load_default=None)
    criticality = fields.Str(load_default=None)
    review_cycle = fields.Str(load_default=None)
    notes = fields.Str(load_default=None)
    category = fields.Str(load_default=None)
    business_unit = fields.Str(load_default=None)
    is_on_premise = fields.Bool(load_default=None)
    is_saas = fields.Bool(load_default=None)


class VendorNotesSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    data = fields.Str(load_default=None)


class AssessmentCreateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    name = fields.Str(required=True, validate=validate.Length(min=1, max=255))
    description = fields.Str(load_default=None)
    due_date = fields.Str(load_default=None)
    clone_from = fields.Str(load_default=None)


class ApplicationUpdateSchema(Schema):
    """Dynamic update — all keys set as attrs on the model."""
    class Meta:
        unknown = INCLUDE
    # TODO: tighten once application model fields are documented


class TenantRiskCreateSchema(Schema):
    class Meta:
        unknown = EXCLUDE
    title = fields.Str(load_default=None, validate=validate.Length(max=500))
    description = fields.Str(load_default=None)
    remediation = fields.Str(load_default=None)
    tags = fields.Raw(load_default=None)
    assignee = fields.Str(load_default=None)
    enabled = fields.Bool(load_default=None)
    status = fields.Str(load_default=None)
    risk = fields.Str(load_default=None)
    priority = fields.Str(load_default=None)
    vendor_id = fields.Str(load_default=None)


class TenantRiskUpdateSchema(Schema):
    """Dynamic update — forwarded to risk.update(**data)."""
    class Meta:
        unknown = EXCLUDE
    title = fields.Str(load_default=None)
    description = fields.Str(load_default=None)
    status = fields.Str(load_default=None)
    risk = fields.Str(load_default=None)
    priority = fields.Str(load_default=None)
    remediation = fields.Str(load_default=None)
    tags = fields.Raw(load_default=None)
    assignee = fields.Str(load_default=None)
    enabled = fields.Bool(load_default=None)


class EmailListSchema(Schema):
    """Validates that the payload is a list of email strings.

    Use as: validate_payload(EmailListSchema, {"emails": data})
    where data is the raw list from request.get_json().
    """
    class Meta:
        unknown = EXCLUDE
    emails = fields.List(fields.Email(), required=True)
