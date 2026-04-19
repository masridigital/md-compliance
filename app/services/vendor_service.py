"""
Vendor service — DB mutations for Vendor + VendorApp + Assessment.

Covers the vendor-risk-management surface: vendor CRUD, vendor
applications, assessments, and tenant-level rollups of those.
See :mod:`app.services` for conventions.
"""

from typing import Any, Mapping, Optional

from app import db
from app.models import Assessment, Vendor, VendorApp


# ── Tenant-level queries ────────────────────────────────────────────────

def list_for_tenant(tenant) -> list:
    """Return all vendors owned by ``tenant``."""
    return tenant.vendors.all()


def list_applications_for_tenant(tenant) -> list:
    """Return every ``VendorApp`` in ``tenant`` (across all vendors)."""
    return (
        db.session.execute(
            db.select(VendorApp).filter(VendorApp.tenant_id == tenant.id)
        )
        .scalars()
        .all()
    )


def list_assessments_for_tenant(tenant) -> list:
    """Return every ``Assessment`` in ``tenant`` (across all vendors)."""
    return (
        db.session.execute(
            db.select(Assessment).filter(Assessment.tenant_id == tenant.id)
        )
        .scalars()
        .all()
    )


# ── Vendor lifecycle ────────────────────────────────────────────────────

def create(tenant, data: Mapping[str, Any]) -> Vendor:
    """Create a vendor under ``tenant`` and commit.

    ``review_cycle`` is coerced to ``int`` with a 12-month default.
    """
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
    tenant.vendors.append(vendor)
    db.session.commit()
    return vendor


_VENDOR_UPDATE_FIELDS = (
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
)


def update(vendor: Vendor, data: Mapping[str, Any]) -> Vendor:
    """Apply a ``VendorUpdateSchema`` payload and commit.

    Whitelisted fields only; anything not in ``_VENDOR_UPDATE_FIELDS``
    is ignored. Historical semantics include overwriting with ``None``
    when a field is absent from the payload — preserved here.
    """
    for field in _VENDOR_UPDATE_FIELDS:
        setattr(vendor, field, data.get(field))
    db.session.commit()
    return vendor


def set_notes(vendor: Vendor, text: Optional[str]) -> Vendor:
    """Update a vendor's notes field and commit."""
    vendor.notes = text
    db.session.commit()
    return vendor


# ── Vendor-scoped reads ─────────────────────────────────────────────────

def list_applications(vendor: Vendor) -> list:
    """Return all apps attached to ``vendor``."""
    return vendor.apps.all()


def list_assessments(vendor: Vendor) -> list:
    """Return all assessments attached to ``vendor``."""
    return vendor.get_assessments()


def get_categories(vendor: Vendor) -> list:
    """Return the distinct app categories present on ``vendor``."""
    return vendor.get_categories()


def get_business_units(vendor: Vendor) -> list:
    """Return the distinct business units present on ``vendor``."""
    return vendor.get_bus()


# ── Vendor application lifecycle ────────────────────────────────────────

def create_application(vendor: Vendor, data: Mapping[str, Any], *, owner):
    """Create an application under a vendor. Commits via ``vendor.create_app``."""
    return vendor.create_app(
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
        owner_id=owner.id,
    )


def update_application(application: VendorApp, data: Mapping[str, Any]) -> VendorApp:
    """Apply a generic field-level update to a ``VendorApp`` and commit.

    Accepts any key/value in ``data``; the historical route did the
    same via ``setattr``.  If the schema allows it, it propagates.
    """
    for key, value in data.items():
        setattr(application, key, value)
    db.session.commit()
    return application


# ── Assessments ─────────────────────────────────────────────────────────

def create_assessment(vendor: Vendor, data: Mapping[str, Any], *, owner) -> Assessment:
    """Create an assessment on a vendor. Commits via ``vendor.create_assessment``."""
    return vendor.create_assessment(
        name=data.get("name"),
        description=data.get("description"),
        due_date=data.get("due_date"),
        clone_from=data.get("clone_from"),
        owner_id=owner.id,
    )
