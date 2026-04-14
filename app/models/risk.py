"""app.models.risk — Risk domain models."""

from app import db
from app.masri.settings_service import EncryptedText
from flask import current_app
from datetime import datetime
import shortuuid
import secrets
import hashlib
import json


class RiskRegister(db.Model):
    __tablename__ = "risk_register"
    # Uniqueness is enforced via title_hash (deterministic SHA-256 of title+tenant_id)
    # so that the title column itself can be Fernet-encrypted (non-deterministic).
    __table_args__ = (db.UniqueConstraint("title_hash", "tenant_id", name="uq_risk_title_hash_tenant"),)
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    # title_hash: deterministic SHA-256(title.lower() + "|" + tenant_id) for uniqueness checks.
    # Never expose this column to the client — it reveals nothing about the plaintext title
    # but it allows the DB to enforce per-tenant uniqueness without requiring plaintext storage.
    title_hash = db.Column(db.String(64), nullable=True)
    title = db.Column(EncryptedText, nullable=False)
    description = db.Column(EncryptedText, default="No description")
    summary = db.Column(db.String, nullable=True)  # Brief one-liner
    evidence_data = db.Column(db.JSON(), default=list)  # Raw findings: IPs, users, devices, breaches
    remediation = db.Column(EncryptedText)
    enabled = db.Column(db.Boolean(), default=True)
    risk = db.Column(db.String, default="unknown", nullable=False)
    status = db.Column(db.String, default="new", nullable=False)
    priority = db.Column(db.String, default="unknown", nullable=False)
    assignee = db.Column(db.String, db.ForeignKey("users.id"))
    tags = db.relationship(
        "Tag",
        secondary="risk_tags",
        lazy="dynamic",
        backref=db.backref("risk_register", lazy="dynamic"),
    )
    comments = db.relationship(
        "RiskComment",
        backref="risk",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    vendor_id = db.Column(db.String, db.ForeignKey("vendors.id"), nullable=True)
    project_id = db.Column(db.String, db.ForeignKey("projects.id"), nullable=True)
    tenant_id = db.Column(db.String, db.ForeignKey("tenants.id"), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    ALLOWED_RISKS = ["unknown", "low", "moderate", "high", "critical"]
    ALLOWED_PRIORITY = ["unknown", "low", "moderate", "high"]
    ALLOWED_STATUS = ["new", "in_progress", "accepted", "mitigated"]

    @staticmethod
    def _compute_title_hash(title: str, tenant_id: str) -> str:
        """SHA-256(title.lower() + '|' + tenant_id) — deterministic, safe to index."""
        raw = f"{title.lower()}|{tenant_id or ''}".encode()
        return hashlib.sha256(raw).hexdigest()

    @validates("title")
    def _set_title_hash_on_title(self, key, value):
        """Keep title_hash in sync whenever title is set."""
        if value and self.tenant_id:
            self.title_hash = self._compute_title_hash(value, self.tenant_id)
        return value

    @validates("tenant_id")
    def _set_title_hash_on_tenant(self, key, value):
        """Recompute title_hash when tenant_id is set (handles construction order)."""
        if value and self.title:
            self.title_hash = self._compute_title_hash(self.title, value)
        return value

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data.pop("title_hash", None)  # internal deduplication aid — never expose to clients
        data["scope"] = "tenant"
        parsed_date = arrow.get(self.date_added)
        data["created_at"] = parsed_date.format("MMM D, YYYY")
        if self.project_id:
            data["scope"] = "project"
            _proj = db.session.get(Project, self.project_id)
            data["project"] = _proj.name if _proj else "(deleted)"

        if self.vendor_id:
            _vendor = db.session.get(Vendor, self.vendor_id)
            data["vendor"] = _vendor.name if _vendor else "(deleted)"

        data["comments"] = [comment.as_dict() for comment in self.comments.all()]
        data["tags"] = []
        if self.tags:
            for tag in self.tags.all():
                data["tags"].append(tag.as_dict())
        return data

    @validates("status")
    def _validate_status(self, key, value):
        value = value or "new"
        if value not in self.ALLOWED_STATUS:
            raise ValueError(f"Invalid status: {value}")
        return value

    @validates("priority")
    def _validate_priority(self, key, value):
        value = value or "unknown"
        if value not in self.ALLOWED_PRIORITY:
            raise ValueError(f"Invalid priority: {value}")
        return value

    @validates("risk")
    def _validate_risk(self, key, value):
        value = value or "unknown"
        if value not in self.ALLOWED_RISKS:
            raise ValueError(f"Invalid risk: {value}")
        return value

    def update(self, **kwargs):
        """
        Update the risk with the provided fields.
        Validates the input fields and updates the risk accordingly.

        Args:
            **kwargs: Fields to update with their new values

        Returns:
            self: The updated risk object

        Raises:
            ValueError: If any of the provided values are invalid
        """
        allowed_fields = {
            "title": str,
            "description": str,
            "remediation": str,
            "status": str,
            "risk": str,
            "priority": str,
            "assignee": str,
            "owner_id": str,
            "enabled": bool,
        }

        for field, value in kwargs.items():
            if field not in allowed_fields:
                continue

            if field in ["status", "risk", "priority"]:
                # Use the existing validators
                setattr(self, field, value)
            else:
                setattr(self, field, value)
        db.session.commit()
        return self



class RiskComment(db.Model):
    __tablename__ = "risk_comments"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    message = db.Column(EncryptedText)
    owner_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    risk_id = db.Column(db.String, db.ForeignKey("risk_register.id"), nullable=False)
    tenant_id = db.Column(db.String, db.ForeignKey("tenants.id"), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data["author_email"] = db.session.get(User, self.owner_id).email
        return data



class RiskTags(db.Model):
    __tablename__ = "risk_tags"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    risk_id = db.Column(
        db.String(), db.ForeignKey("risk_register.id", ondelete="CASCADE")
    )
    tag_id = db.Column(db.String(), db.ForeignKey("tags.id", ondelete="CASCADE"))

    def as_dict(self):
        tag = db.session.get(Tag, self.tag_id)
        return {"name": tag.name, "color": tag.color}



