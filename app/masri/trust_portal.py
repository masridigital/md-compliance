"""
Masri Digital Compliance Platform — Trust Portal

Public-facing compliance status page accessible without authentication.
Tenants configure which frameworks and info are visible.  Rate-limited
to prevent abuse.

Blueprint: ``trust_bp`` at url_prefix ``/trust``
"""

import json
import logging
from datetime import datetime

from flask import Blueprint, jsonify, request, render_template, abort
from flask_login import login_required
from app import db, limiter

logger = logging.getLogger(__name__)

trust_bp = Blueprint("trust_bp", __name__, url_prefix="/trust")


# ===========================================================================
# Public API
# ===========================================================================

@trust_bp.route("/<string:tenant_slug>/status", methods=["GET"])
@limiter.limit("60 per minute; 500 per hour")
def trust_status_api(tenant_slug):
    """
    GET /trust/<slug>/status — Public JSON API for compliance status.

    Returns compliance percentages per framework, last audit date,
    and contact info.  Only includes data the tenant has opted to share.
    """
    tenant, config = _resolve_tenant(tenant_slug)
    if not tenant or not config:
        return jsonify({"error": "Not found"}), 404

    if not config.get("enabled"):
        return jsonify({"error": "Trust portal is not enabled for this organization"}), 404

    data = _build_trust_data(tenant, config)
    return jsonify(data)


@trust_bp.route("/<string:tenant_slug>", methods=["GET"])
@limiter.limit("30 per minute; 200 per hour")
def trust_page(tenant_slug):
    """
    GET /trust/<slug> — Public HTML trust portal page.
    """
    tenant, config = _resolve_tenant(tenant_slug)
    if not tenant or not config:
        abort(404)

    if not config.get("enabled"):
        abort(404)

    data = _build_trust_data(tenant, config)
    return render_template(
        "trust_portal.html",
        tenant=tenant,
        trust_data=data,
        config=config,
    )


# ===========================================================================
# NDA Acceptance Logging
# ===========================================================================

@trust_bp.route("/<string:tenant_slug>/nda-accept", methods=["POST"])
@limiter.limit("10 per minute; 30 per hour")
def accept_nda(tenant_slug):
    """POST /trust/<slug>/nda-accept — Log NDA acceptance (public, rate-limited)."""
    tenant, config = _resolve_tenant(tenant_slug)
    if not tenant or not config or not config.get("enabled") or not config.get("nda_required"):
        return jsonify({"error": "Not found"}), 404

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()

    # Basic email validation
    if not email or "@" not in email or len(email) > 255:
        return jsonify({"error": "Valid email required"}), 400

    # Log acceptance in ConfigStore
    from app.models import ConfigStore
    key = f"nda_acceptances_{tenant.id}"
    record = ConfigStore.find(key)
    acceptances = []
    if record and record.value:
        try:
            acceptances = json.loads(record.value)
        except (json.JSONDecodeError, TypeError):
            acceptances = []

    # Prevent duplicate entries from same email (keep latest)
    acceptances = [a for a in acceptances if a.get("email") != email]
    acceptances.append({
        "email": email,
        "accepted_at": datetime.utcnow().isoformat(),
        "ip": request.remote_addr,
    })

    # Cap at 1000 entries to prevent unbounded growth
    if len(acceptances) > 1000:
        acceptances = acceptances[-1000:]

    ConfigStore.upsert(key, json.dumps(acceptances))
    db.session.commit()

    logger.info("NDA accepted for tenant %s by %s", tenant.id, email)
    return jsonify({"accepted": True})


# ===========================================================================
# Configuration API (authenticated)
# ===========================================================================

@trust_bp.route("/config", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_trust_config():
    """GET /trust/config — Get trust portal config for current tenant (requires auth)."""
    from app.utils.authorizer import Authorizer

    tenant_id = Authorizer.get_tenant_id()
    config = _get_trust_config(tenant_id)
    return jsonify(config)


@trust_bp.route("/config", methods=["PUT"])
@limiter.limit("10 per minute")
@login_required
def update_trust_config():
    """PUT /trust/config — Update trust portal configuration."""
    from flask_login import current_user
    from app.utils.authorizer import Authorizer

    if not current_user.super:
        return jsonify({"error": "Admin access required"}), 403

    tenant_id = Authorizer.get_tenant_id()
    data = request.get_json(silent=True) or {}

    config = _get_trust_config(tenant_id)
    for key in ("enabled", "visible_frameworks", "show_contact", "contact_email",
                "security_contact", "show_certifications", "certifications",
                "nda_required", "custom_message"):
        if key in data:
            config[key] = data[key]

    # Generate slug from tenant name if not set
    if not config.get("slug"):
        from app.models import Tenant
        tenant = db.session.get(Tenant, tenant_id)
        if tenant:
            config["slug"] = _slugify(tenant.name)

    if data.get("slug"):
        new_slug = _slugify(data["slug"])
        if new_slug:
            config["slug"] = new_slug

    from app.models import ConfigStore
    ConfigStore.upsert(
        f"trust_portal_config_{tenant_id}",
        json.dumps(config, default=str),
    )
    db.session.commit()

    # Rebuild slug index so public lookups stay fast
    if config.get("slug"):
        try:
            record = ConfigStore.find("trust_portal_slug_index")
            slug_index = json.loads(record.value) if record and record.value else {}
            slug_index[config["slug"]] = tenant_id
            _rebuild_slug_index(slug_index)
        except Exception:
            pass

    return jsonify(config)


# ===========================================================================
# Helpers
# ===========================================================================

def _slugify(text):
    """Create a URL-safe slug from text."""
    import re
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:50].strip("-")


def _resolve_tenant(slug):
    """
    Find tenant by trust portal slug.

    Only matches explicitly configured slugs — never exposes tenant IDs.
    Uses ConfigStore index to avoid loading all tenants.

    Returns (tenant, config) or (None, None).
    """
    from app.models import Tenant, ConfigStore

    # Look up the slug-to-tenant mapping (fast indexed lookup)
    mapping_record = ConfigStore.find("trust_portal_slug_index")
    if mapping_record and mapping_record.value:
        try:
            slug_index = json.loads(mapping_record.value)
            tenant_id = slug_index.get(slug)
            if tenant_id:
                tenant = db.session.get(Tenant, tenant_id)
                if tenant:
                    config = _get_trust_config(tenant_id)
                    if config.get("enabled") and config.get("slug") == slug:
                        return tenant, config
        except (json.JSONDecodeError, TypeError):
            pass

    # Fallback: scan trust configs (only if index doesn't exist yet)
    tenants = db.session.execute(db.select(Tenant)).scalars().all()
    slug_index = {}
    for tenant in tenants:
        config = _get_trust_config(tenant.id)
        if config.get("slug"):
            slug_index[config["slug"]] = tenant.id
        if config.get("slug") == slug and config.get("enabled"):
            # Rebuild index while we're here
            _rebuild_slug_index(slug_index)
            return tenant, config

    # Rebuild index for future lookups
    if slug_index:
        _rebuild_slug_index(slug_index)

    return None, None


def _rebuild_slug_index(slug_index):
    """Rebuild the slug → tenant_id index in ConfigStore."""
    from app.models import ConfigStore
    try:
        ConfigStore.upsert("trust_portal_slug_index", json.dumps(slug_index))
        db.session.commit()
    except Exception:
        pass


def _get_trust_config(tenant_id):
    """Get trust portal configuration for a tenant."""
    from app.models import ConfigStore

    record = ConfigStore.find(f"trust_portal_config_{tenant_id}")
    if record and record.value:
        try:
            return json.loads(record.value)
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "enabled": False,
        "slug": "",
        "visible_frameworks": [],
        "show_contact": False,
        "contact_email": "",
        "security_contact": "",
        "show_certifications": False,
        "certifications": [],
        "nda_required": False,
        "custom_message": "",
    }


def _build_trust_data(tenant, config):
    """Build the public trust data response."""
    from app.models import Project, ProjectControl, Framework

    data = {
        "organization": tenant.name,
        "last_updated": datetime.utcnow().isoformat(),
        "frameworks": [],
    }

    if config.get("show_contact"):
        data["contact_email"] = config.get("contact_email", "")
        data["security_contact"] = config.get("security_contact", "")

    if config.get("show_certifications"):
        data["certifications"] = config.get("certifications", [])

    if config.get("custom_message"):
        data["message"] = config["custom_message"]

    # Get compliance percentage for each visible framework
    visible_fws = config.get("visible_frameworks", [])
    if not visible_fws:
        return data

    frameworks = db.session.execute(
        db.select(Framework).filter_by(tenant_id=tenant.id)
    ).scalars().all()

    for fw in frameworks:
        if fw.name not in visible_fws:
            continue

        # Find the latest project using this framework
        projects = db.session.execute(
            db.select(Project).filter_by(
                tenant_id=tenant.id, framework_id=fw.id
            ).order_by(Project.date_updated.desc())
        ).scalars().all()

        if not projects:
            continue

        project = projects[0]

        # Calculate compliance percentage
        controls = db.session.execute(
            db.select(ProjectControl).filter_by(project_id=project.id)
        ).scalars().all()

        total = len(controls)
        if total == 0:
            continue

        complete = sum(1 for c in controls if c.review_status == "complete")
        ready = sum(1 for c in controls if c.review_status == "ready for auditor")

        compliance_pct = round((complete + ready) / total * 100, 1)

        data["frameworks"].append({
            "name": fw.name,
            "compliance_percentage": compliance_pct,
            "total_controls": total,
            "complete": complete,
            "in_review": ready,
        })

    return data
