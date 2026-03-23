"""
Masri Digital Compliance Platform — New View Routes (Phase 1)

Stub routes that register the Flask endpoint names referenced by the
Masri frontend templates.  These are added to the existing ``main``
blueprint so that ``url_for('main.index')``, ``url_for('main.compliance')``,
etc. all resolve correctly.

After merge, this file lives at ``app/main/masri_views.py`` and is
imported by ``app/main/__init__.py``.
"""

from flask import render_template, redirect, url_for, request
from . import main
from app.utils.decorators import login_required
from app.utils.authorizer import Authorizer
from flask_login import current_user


# ---------------------------------------------------------------------------
# Home / Dashboard
# ---------------------------------------------------------------------------

@main.route("/dashboard", methods=["GET"])
@login_required
def index():
    """Masri home dashboard — aliased as ``main.index``."""
    return render_template("home_masri.html")


# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------

@main.route("/compliance", methods=["GET"])
@login_required
def compliance():
    """Compliance controls view."""
    return render_template("compliance_masri.html")


# ---------------------------------------------------------------------------
# Risk  (tenant-scoped, but also a top-level nav link)
# ---------------------------------------------------------------------------

@main.route("/risk", methods=["GET"])
@login_required
def risk():
    """Top-level risk redirect — delegates to tenant-scoped risk view."""
    tenant_id = getattr(current_user, "default_tenant_id", None) or request.args.get("tenant_id")
    if tenant_id:
        return redirect(url_for("main.risks", id=tenant_id))
    return render_template("risk_register.html")


# ---------------------------------------------------------------------------
# WISP
# ---------------------------------------------------------------------------

@main.route("/wisp", methods=["GET"])
@login_required
def wisp():
    """WISP wizard entry point."""
    return render_template("wisp/wizard_masri.html")


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------

@main.route("/vendors", methods=["GET"])
@login_required
def vendors():
    """Vendor management list."""
    return render_template("vendors.html")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@main.route("/settings", methods=["GET"])
@login_required
def masri_settings():
    """Settings hub (macOS-style settings page)."""
    return render_template("management/settings_masri.html")


# ---------------------------------------------------------------------------
# Tenant operations
# ---------------------------------------------------------------------------

@main.route("/tenants/new", methods=["GET"])
@login_required
def new_tenant():
    """Create a new tenant / client."""
    return render_template("new_tenant.html")


@main.route("/tenants/<string:tenant_id>", methods=["GET"])
@login_required
def tenant_detail(tenant_id):
    """View tenant detail page."""
    Authorizer(current_user).can_user_access_tenant(tenant_id)
    return render_template("tenant_detail.html", tenant_id=tenant_id)


@main.route("/tenants/<string:tenant_id>/switch", methods=["GET"])
@login_required
def switch_tenant(tenant_id):
    """Switch the user's active tenant context."""
    Authorizer(current_user).can_user_access_tenant(tenant_id)
    # Store the active tenant in session or user profile
    from flask import session
    session["active_tenant_id"] = tenant_id
    return redirect(url_for("main.index"))
