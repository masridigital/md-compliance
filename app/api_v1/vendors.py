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


@api.route("/tenants/<string:id>/vendors", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_vendors(id):
    result = Authorizer(current_user).can_user_access_tenant(id)
    vendors = result["extra"]["tenant"].vendors.all()
    return jsonify([vendor.as_dict() for vendor in vendors])


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
    data, err = validate_payload(VendorCreateSchema, request.get_json())
    if err:
        return err
    vendor = Vendor(
        name=data.get("name"),
        description=data.get("description"),
        contact_email=data.get("contact_email"),
        vendor_contact_email=data.get("vendor_contact_email"),
        location=data.get("location"),
        criticality=data.get("criticality"),
        review_cycle=int(data.get("review_cycle", 12)),
        disabled=data.get("disabled", False),
        notes=data.get("notes"),
        start_date=data.get("start_date"),
    )
    result["extra"]["tenant"].vendors.append(vendor)
    db.session.commit()
    return jsonify(vendor.as_dict())


@api.route("/vendors/<string:id>", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def update_vendor(id):
    result = Authorizer(current_user).can_user_access_vendor(id)
    vendor = result["extra"]["vendor"]
    data, err = validate_payload(VendorUpdateSchema, request.get_json())
    if err:
        return err
    for field in [
        "description",
        "status",
        "contact_email",
        "vendor_contact_email",
        "location",
        "start_date",
        "end_date",
        "criticality",
        "review_cycle",
        "notes",
    ]:
        setattr(vendor, field, data.get(field))
    db.session.commit()
    return jsonify(vendor.as_dict())


@api.route("/vendors/<string:id>/applications", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_vendor_applications(id):
    result = Authorizer(current_user).can_user_access_vendor(id)
    vendor = result["extra"]["vendor"]
    return jsonify([application.as_dict() for application in vendor.apps.all()])


@api.route("/vendors/<string:id>/applications", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def create_vendor_application(id):
    result = Authorizer(current_user).can_user_access_vendor(id)
    vendor = result["extra"]["vendor"]
    data, err = validate_payload(VendorAppCreateSchema, request.get_json())
    if err:
        return err
    app = vendor.create_app(
        name=data.get("name"),
        description=data.get("description"),
        contact_email=data.get("contact_email"),
        start_date=data.get("start_date"),
        end_date=data.get("end_date"),
        criticality=data.get("criticality"),
        review_cycle=data.get("review_cycle"),
        notes=data.get("notes"),
        category=data.get("category"),
        business_unit=data.get("business_unit"),
        is_on_premise=data.get("is_on_premise"),
        is_saas=data.get("is_saas"),
        owner_id=current_user.id,
    )
    return jsonify(app.as_dict())


@api.route("/vendors/<string:id>/categories", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_vendor_categories(id):
    result = Authorizer(current_user).can_user_access_vendor(id)
    vendor = result["extra"]["vendor"]
    return jsonify(vendor.get_categories())


@api.route("/vendors/<string:id>/assessments", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_vendor_assessments(id):
    result = Authorizer(current_user).can_user_access_vendor(id)
    vendor = result["extra"]["vendor"]
    return jsonify([assessment.as_dict() for assessment in vendor.get_assessments()])


@api.route("/vendors/<string:id>/bus", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_vendor_business_units(id):
    result = Authorizer(current_user).can_user_access_vendor(id)
    vendor = result["extra"]["vendor"]
    return jsonify(vendor.get_bus())


@api.route("/tenants/<string:id>/vendors", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_vendors_for_tenant(id):
    result = Authorizer(current_user).can_user_access_tenant(id)
    vendors = db.session.execute(db.select(Vendor).filter(
        Vendor.tenant_id == result["extra"]["tenant"].id
    )).scalars().all()
    return jsonify([vendor.as_dict() for vendor in vendors])


@api.route("/tenants/<string:id>/applications", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_apps_for_tenant(id):
    result = Authorizer(current_user).can_user_access_tenant(id)
    applications = db.session.execute(db.select(VendorApp).filter(
        VendorApp.tenant_id == result["extra"]["tenant"].id
    )).scalars().all()
    return jsonify([application.as_dict() for application in applications])


@api.route("/tenants/<string:id>/assessments", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_assessments_for_tenant(id):
    result = Authorizer(current_user).can_user_access_tenant(id)
    assessments = db.session.execute(db.select(Assessment).filter(
        Assessment.tenant_id == result["extra"]["tenant"].id
    )).scalars().all()
    return jsonify([assessment.as_dict() for assessment in assessments])


@api.route("/tenants/<string:id>/risks", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_risks_for_tenant(id):
    result = Authorizer(current_user).can_user_access_tenant(id)
    data = []
    for risk in db.session.execute(db.select(RiskRegister).filter(RiskRegister.tenant_id == id)).scalars().all():
        data.append(risk.as_dict())
    return jsonify(data)


@api.route("/vendors/<string:id>/notes", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def update_notes_for_vendor(id):
    result = Authorizer(current_user).can_user_access_vendor(id)
    vendor = result["extra"]["vendor"]
    data, err = validate_payload(VendorNotesSchema, request.get_json())
    if err:
        return err
    vendor.notes = data.get("data")
    db.session.commit()
    return jsonify(vendor.as_dict())


@api.route("/vendors/<string:id>/assessments", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def create_assessment_for_vendor(id):
    result = Authorizer(current_user).can_user_access_vendor(id)
    data, err = validate_payload(AssessmentCreateSchema, request.get_json())
    if err:
        return err

    assessment = result["extra"]["vendor"].create_assessment(
        name=data.get("name"),
        description=data.get("description"),
        due_date=data.get("due_date"),
        clone_from=data.get("clone_from"),
        owner_id=current_user.id,
    )
    return jsonify(assessment.as_dict())


@api.route("/applications/<string:id>", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def update_application(id):
    result = Authorizer(current_user).can_user_access_application(id)
    app = result["extra"]["application"]
    data, err = validate_payload(ApplicationUpdateSchema, request.get_json())
    if err:
        return err
    for key, value in data.items():
        setattr(app, key, value)
    db.session.commit()
    return jsonify(app.as_dict())


@api.route("/tenants/<string:id>/risks", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def create_risk(id):
    result = Authorizer(current_user).can_user_manage_tenant(id)
    data, err = validate_payload(TenantRiskCreateSchema, request.get_json())
    if err:
        return err
    risk = result["extra"]["tenant"].create_risk(
        title=data.get("title"),
        description=data.get("description"),
        remediation=data.get("remediation"),
        tags=data.get("tags"),
        assignee=data.get("assignee"),
        enabled=data.get("enabled"),
        status=data.get("status"),
        risk=data.get("risk"),
        priority=data.get("priority"),
        vendor_id=data.get("vendor_id"),
    )

    db.session.add(risk)
    db.session.commit()
    return jsonify(risk.as_dict())


@api.route("/tenants/<string:tid>/risks/<string:rid>", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def update_risk(tid, rid):
    result = Authorizer(current_user).can_user_manage_risk(rid)
    data, err = validate_payload(TenantRiskUpdateSchema, request.get_json())
    if err:
        return err
    risk = result["extra"]["risk"]

    # Update the risk using the model's update method
    print(data)
    risk.update(**data)

    # Add audit log entry
    risk.tenant.add_log(
        message=f"Updated risk: {risk.title}",
        namespace="risks",
        action="update",
        user_id=current_user.id,
    )

    return jsonify(risk.as_dict())


@api.route("/tenants/<string:tid>/risks/<string:rid>", methods=["DELETE"])
@limiter.limit("30 per minute")
@login_required
def delete_risk(tid, rid):
    result = Authorizer(current_user).can_user_manage_risk(rid)
    risk = result["extra"]["risk"]
    db.session.delete(risk)
    db.session.commit()
    return jsonify({"message": "ok"})


@api.route("/tenants/<string:id>/risk-managers", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def set_risk_managers_for_tenant(id):
    result = Authorizer(current_user).can_user_manage_tenant(id)
    tenant = result["extra"]["tenant"]
    raw = request.get_json()
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
    raw = request.get_json()
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
    raw = request.get_json()
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
