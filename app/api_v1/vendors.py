from flask import (
    jsonify,
    request,
)
from . import api
from app.models import *
from flask_login import current_user
from app.utils.authorizer import Authorizer
from app.utils.decorators import login_required
from app import limiter
from app.api_v1.schemas import (
    validate_payload,
    VendorCreateSchema,
    VendorUpdateSchema,
    VendorAppCreateSchema,
    VendorNotesSchema,
    AssessmentCreateSchema,
    ApplicationUpdateSchema,
    TenantRiskCreateSchema,
    TenantRiskUpdateSchema,
    EmailListSchema,
)
from app.services import risk_service, vendor_service


@api.route("/tenants/<string:id>/vendors", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_vendors(id):
    result = Authorizer(current_user).can_user_access_tenant(id)
    vendors = vendor_service.list_for_tenant(result["extra"]["tenant"])
    return jsonify([v.as_dict() for v in vendors])


@api.route("/vendors/<string:id>", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_vendor(id):
    result = Authorizer(current_user).can_user_access_vendor(id)
    vendor = result["extra"]["vendor"]
    return jsonify(vendor.as_dict())


@api.route("/tenants/<string:id>/vendors", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def create_vendor(id):
    result = Authorizer(current_user).can_user_manage_tenant(id)
    data, err = validate_payload(VendorCreateSchema, request.get_json(silent=True))
    if err:
        return err
    vendor = vendor_service.create(result["extra"]["tenant"], data)
    return jsonify(vendor.as_dict())


@api.route("/vendors/<string:id>", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def update_vendor(id):
    result = Authorizer(current_user).can_user_access_vendor(id)
    data, err = validate_payload(VendorUpdateSchema, request.get_json(silent=True))
    if err:
        return err
    vendor = vendor_service.update(result["extra"]["vendor"], data)
    return jsonify(vendor.as_dict())


@api.route("/vendors/<string:id>/applications", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_vendor_applications(id):
    result = Authorizer(current_user).can_user_access_vendor(id)
    apps = vendor_service.list_applications(result["extra"]["vendor"])
    return jsonify([a.as_dict() for a in apps])


@api.route("/vendors/<string:id>/applications", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def create_vendor_application(id):
    result = Authorizer(current_user).can_user_access_vendor(id)
    data, err = validate_payload(VendorAppCreateSchema, request.get_json(silent=True))
    if err:
        return err
    app = vendor_service.create_application(
        result["extra"]["vendor"], data, owner=current_user
    )
    return jsonify(app.as_dict())


@api.route("/vendors/<string:id>/categories", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_vendor_categories(id):
    result = Authorizer(current_user).can_user_access_vendor(id)
    return jsonify(vendor_service.get_categories(result["extra"]["vendor"]))


@api.route("/vendors/<string:id>/assessments", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_vendor_assessments(id):
    result = Authorizer(current_user).can_user_access_vendor(id)
    assessments = vendor_service.list_assessments(result["extra"]["vendor"])
    return jsonify([a.as_dict() for a in assessments])


@api.route("/vendors/<string:id>/bus", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_vendor_business_units(id):
    result = Authorizer(current_user).can_user_access_vendor(id)
    return jsonify(vendor_service.get_business_units(result["extra"]["vendor"]))


# Duplicate route removed — get_vendors (above) handles GET /tenants/<id>/vendors


@api.route("/tenants/<string:id>/applications", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_apps_for_tenant(id):
    result = Authorizer(current_user).can_user_access_tenant(id)
    apps = vendor_service.list_applications_for_tenant(result["extra"]["tenant"])
    return jsonify([a.as_dict() for a in apps])


@api.route("/tenants/<string:id>/assessments", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_assessments_for_tenant(id):
    result = Authorizer(current_user).can_user_access_tenant(id)
    assessments = vendor_service.list_assessments_for_tenant(result["extra"]["tenant"])
    return jsonify([a.as_dict() for a in assessments])


@api.route("/tenants/<string:id>/risks", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_risks_for_tenant(id):
    result = Authorizer(current_user).can_user_access_tenant(id)
    risks = risk_service.list_for_tenant(result["extra"]["tenant"])
    return jsonify([r.as_dict() for r in risks])


@api.route("/vendors/<string:id>/notes", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def update_notes_for_vendor(id):
    result = Authorizer(current_user).can_user_access_vendor(id)
    data, err = validate_payload(VendorNotesSchema, request.get_json(silent=True))
    if err:
        return err
    vendor = vendor_service.set_notes(result["extra"]["vendor"], data.get("data"))
    return jsonify(vendor.as_dict())


@api.route("/vendors/<string:id>/assessments", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def create_assessment_for_vendor(id):
    result = Authorizer(current_user).can_user_access_vendor(id)
    data, err = validate_payload(AssessmentCreateSchema, request.get_json(silent=True))
    if err:
        return err
    assessment = vendor_service.create_assessment(
        result["extra"]["vendor"], data, owner=current_user
    )
    return jsonify(assessment.as_dict())


@api.route("/applications/<string:id>", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def update_application(id):
    result = Authorizer(current_user).can_user_access_application(id)
    data, err = validate_payload(ApplicationUpdateSchema, request.get_json(silent=True))
    if err:
        return err
    app = vendor_service.update_application(result["extra"]["application"], data)
    return jsonify(app.as_dict())


@api.route("/tenants/<string:id>/risks", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def create_risk(id):
    result = Authorizer(current_user).can_user_manage_tenant(id)
    data, err = validate_payload(TenantRiskCreateSchema, request.get_json(silent=True))
    if err:
        return err
    risk = risk_service.create_for_tenant(result["extra"]["tenant"], data)
    return jsonify(risk.as_dict())


@api.route("/tenants/<string:tid>/risks/<string:rid>", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def update_risk(tid, rid):
    result = Authorizer(current_user).can_user_manage_risk(rid)
    data, err = validate_payload(TenantRiskUpdateSchema, request.get_json(silent=True))
    if err:
        return err
    risk = risk_service.update(result["extra"]["risk"], data, user=current_user)
    return jsonify(risk.as_dict())


@api.route("/tenants/<string:tid>/risks/<string:rid>", methods=["DELETE"])
@limiter.limit("30 per minute")
@login_required
def delete_risk(tid, rid):
    result = Authorizer(current_user).can_user_manage_risk(rid)
    risk_service.delete(result["extra"]["risk"])
    return jsonify({"message": "ok"})


@api.route("/tenants/<string:id>/risk-managers", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def set_risk_managers_for_tenant(id):
    result = Authorizer(current_user).can_user_manage_tenant(id)
    tenant = result["extra"]["tenant"]
    raw = request.get_json(silent=True)
    validated, err = validate_payload(EmailListSchema, {"emails": raw if isinstance(raw, list) else []})
    if err:
        return err
    data = validated["emails"]

    # remove all risk managers
    mappings = UserRole.get_mappings_for_role_in_tenant("riskmanager", tenant.id)
    for mapping in mappings:
        db.session.delete(mapping)
    db.session.commit()

    for email in data:
        if user := User.find_by_email(email):
            current_roles = tenant.get_roles_for_member(user)
            if "riskmanager" not in current_roles:
                current_roles.append("riskmanager")
                tenant.set_roles_for_user(user, list_of_role_names=current_roles)
    return jsonify({"message": "ok"})


@api.route("/tenants/<string:id>/risk-viewers", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def set_risk_viewers_for_tenant(id):
    result = Authorizer(current_user).can_user_manage_tenant(id)
    tenant = result["extra"]["tenant"]
    raw = request.get_json(silent=True)
    validated, err = validate_payload(EmailListSchema, {"emails": raw if isinstance(raw, list) else []})
    if err:
        return err
    data = validated["emails"]

    # remove all risk viewers
    mappings = UserRole.get_mappings_for_role_in_tenant("riskviewer", tenant.id)
    for mapping in mappings:
        db.session.delete(mapping)
    db.session.commit()

    for email in data:
        if user := User.find_by_email(email):
            current_roles = tenant.get_roles_for_member(user)
            if "riskviewer" not in current_roles:
                current_roles.append("riskviewer")
                tenant.set_roles_for_user(user, list_of_role_names=current_roles)
    return jsonify({"message": "ok"})


@api.route("/tenants/<string:id>/vendors", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def set_vendors_for_tenant(id):
    result = Authorizer(current_user).can_user_manage_tenant(id)
    tenant = result["extra"]["tenant"]
    raw = request.get_json(silent=True)
    validated, err = validate_payload(EmailListSchema, {"emails": raw if isinstance(raw, list) else []})
    if err:
        return err
    data = validated["emails"]

    # remove all risk vendors
    mappings = UserRole.get_mappings_for_role_in_tenant("vendor", tenant.id)
    for mapping in mappings:
        db.session.delete(mapping)
    db.session.commit()

    for email in data:
        if user := User.find_by_email(email):
            tenant.set_roles_for_user(user, list_of_role_names=["vendor"])
    return jsonify({"message": "ok"})
