"""app.models.vendor — Vendor domain models."""

from app import db
from app.utils.mixin_models import QueryMixin
from app.masri.settings_service import EncryptedText
from flask import current_app, abort
from sqlalchemy import func
from sqlalchemy.orm import validates
from datetime import datetime
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename
from app.utils.file_handler import FileStorageHandler
import shortuuid
import secrets
import json
import os
import arrow
import email_validator
import shutil


class Finding(db.Model):
    __tablename__ = "findings"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    title = db.Column(db.String())
    description = db.Column(db.String())
    mitigation = db.Column(db.String())
    status = db.Column(db.String(), default="open")
    risk = db.Column(db.Integer(), default=0)
    project_id = db.Column(db.String, db.ForeignKey("projects.id"))
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    @staticmethod
    def get_status_list():
        return ["open", "in progress", "closed"]

    @validates("status")
    def _validate_status(self, key, status):
        if not status or status.lower() not in Finding.get_status_list():
            raise ValueError("invalid status")
        return status

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        return data



class VendorFile(db.Model, QueryMixin):
    __tablename__ = "vendor_files"
    __table_args__ = (db.UniqueConstraint("name", "vendor_id"),)
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    name = db.Column(db.String())
    description = db.Column(db.String())
    provider = db.Column(db.String(), nullable=False)
    collected_on = db.Column(db.DateTime, default=datetime.utcnow)
    vendor_id = db.Column(db.String, db.ForeignKey("vendors.id"), nullable=False)
    owner_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        return data

    def get_file(self):
        storage_method = current_app.config["STORAGE_METHOD"]
        if self.provider != storage_method:
            abort(
                500,
                f"Storage method mismatch. File provider:{self.provider}. STORAGE_METHOD:{storage_method}",
            )

        file_handler = FileStorageHandler(
            provider=current_app.config["STORAGE_METHOD"],
        )
        return file_handler.get_file(path=os.path.join(self.vendor_id, self.name))

    def save_file(self, file_object):
        storage_method = current_app.config["STORAGE_METHOD"]
        if self.provider != storage_method:
            abort(
                500,
                f"Storage method mismatch. File provider:{self.provider}. STORAGE_METHOD:{storage_method}",
            )

        if storage_method == "local":
            folder = self.vendor.create_evidence_folder()

        upload_params = {
            "file": file_object,
            "file_name": f"{self.id}_{self.name}",
            "folder": self.vendor.get_evidence_folder(),
        }
        file_handler = FileStorageHandler(provider=storage_method)
        return file_handler.upload_file(**upload_params)

    @validates("provider")
    def _validate_provider(self, key, value):
        if value not in current_app.config["STORAGE_PROVIDERS"]:
            raise ValueError(f"Provider:{value} not supported")
        return value



class AppHistory(db.Model, QueryMixin):
    __tablename__ = "app_history"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    name = db.Column(db.String(), nullable=False)
    description = db.Column(db.String())
    icon = db.Column(db.String())
    user_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    app_id = db.Column(db.String, db.ForeignKey("vendor_apps.id"), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        return data



class VendorHistory(db.Model, QueryMixin):
    __tablename__ = "vendor_history"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    name = db.Column(db.String(), nullable=False)
    description = db.Column(db.String())
    icon = db.Column(db.String())
    user_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    vendor_id = db.Column(db.String, db.ForeignKey("vendors.id"), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        return data



class VendorApp(db.Model, QueryMixin):
    __tablename__ = "vendor_apps"
    __table_args__ = (db.UniqueConstraint("name", "vendor_id"),)
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    name = db.Column(db.String(64), unique=True, nullable=False)
    disabled = db.Column(db.Boolean, default=False)
    description = db.Column(db.String())
    contact_email = db.Column(db.String())
    notes = db.Column(db.String())
    criticality = db.Column(db.String(), default="unknown")
    approved_use_cases = db.Column(db.String())
    exceptions = db.Column(db.String())
    start_date = db.Column(db.DateTime)
    end_date = db.Column(db.DateTime)
    category = db.Column(db.String(), default="general")
    business_unit = db.Column(db.String(), default="general")
    last_reviewed = db.Column(db.DateTime)
    review_cycle = db.Column(db.Integer, default=12)
    review_status = db.Column(db.String(), default="new")
    status = db.Column(db.String(), default="pending")

    is_on_premise = db.Column(db.Boolean(), default=False)
    is_saas = db.Column(db.Boolean(), default=False)
    owner_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    data_class_id = db.Column(db.String, db.ForeignKey("data_class.id"), nullable=True)
    vendor_id = db.Column(db.String, db.ForeignKey("vendors.id"), nullable=False)
    tenant_id = db.Column(db.String, db.ForeignKey("tenants.id"), nullable=False)
    history = db.relationship(
        "AppHistory", backref="app", lazy="dynamic", cascade="all, delete-orphan"
    )
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    VALID_CRITICALITY = ["unknown", "low", "moderate", "high"]
    VALID_REVIEW_STATUS = [
        "new",
        "pending_response",
        "pending_review",
        "info_required",
        "complete",
    ]
    VALID_STATUS = ["pending", "approved", "not approved"]

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data["risk"] = 0
        data["next_review_date"] = self.get_next_review_date()
        data["type"] = "application"
        data["vendor"] = self.vendor.name
        if self.data_class_id:
            data["data_classification"] = self.data_class.name
            data["data_classification_color"] = self.data_class.color

        data["next_review_date"] = self.get_next_review_date()
        data["days_until_next_review_date"] = self.days_until_next_review()
        data["next_review_date_humanize"] = self.days_until_next_review(humanize=True)

        data["review_description"] = "compliant"
        if not self.last_reviewed:
            data["review_description"] = "never reviewed"
        else:
            data["last_reviewed"] = arrow.get(self.last_reviewed).format("YYYY-MM-DD")

        data["review_upcoming"] = False
        if data["days_until_next_review_date"] <= 14:
            data["review_upcoming"] = True
            if self.last_reviewed:
                data["review_description"] = "upcoming review"

        data["review_past_due"] = False
        if data["days_until_next_review_date"] <= 0:
            data["review_past_due"] = True
            if self.last_reviewed:
                data["review_description"] = "past due"

        return data

    def days_until_next_review(self, humanize=False):
        next_review_date = self.get_next_review_date()
        if humanize:
            return arrow.get(next_review_date).humanize(granularity=["day"])
        return (arrow.get(next_review_date).date() - arrow.utcnow().date()).days

    def is_ready_for_review(self, grace_period=7):
        today = arrow.get(arrow.utcnow().format("YYYY-MM-DD"))
        future_date = today.shift(days=grace_period)
        next_review_date = arrow.get(self.get_next_review_date())
        if future_date >= next_review_date:
            return True
        return False

    def get_next_review_date(self):
        if not self.last_reviewed:
            return arrow.utcnow().format("YYYY-MM-DD")
        if not self.review_cycle:
            return arrow.utcnow().format("YYYY-MM-DD")
        return (
            arrow.get(self.last_reviewed)
            .shift(months=self.review_cycle)
            .format("YYYY-MM-DD")
        )

    @validates("contact_email")
    def _validate_email(self, key, address):
        if address:
            try:
                email_validator.validate_email(address, check_deliverability=False)
            except Exception:
                abort(422, "Invalid email")
        return address

    @validates("status")
    def _validate_status(self, key, value):
        if value.lower() not in self.VALID_STATUS:
            raise ValueError(f"Invalid status: {value}")
        return value.lower()

    @validates("review_status")
    def _validate_review_status(self, key, value):
        if value.lower() not in self.VALID_REVIEW_STATUS:
            raise ValueError(f"Invalid review status: {value}")
        return value.lower()

    @validates("criticality")
    def _validate_criticality(self, key, value):
        value = value or "unknown"
        if value.lower() not in self.VALID_CRITICALITY:
            raise ValueError(f"Invalid criticality: {value}")
        return value.lower()



class Vendor(db.Model, QueryMixin):
    __tablename__ = "vendors"
    __table_args__ = (db.UniqueConstraint("name", "tenant_id"),)
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    name = db.Column(db.String(64), unique=True, nullable=False)
    description = db.Column(db.String())
    contact_email = db.Column(db.String())
    vendor_contact_email = db.Column(db.String())
    location = db.Column(db.String())
    disabled = db.Column(db.Boolean(), default=False)
    review_status = db.Column(db.String(), default="new")
    status = db.Column(db.String(), default="pending")
    notes = db.Column(db.String())
    review_cycle = db.Column(db.Integer, default=12)
    last_reviewed = db.Column(db.DateTime)
    start_date = db.Column(db.DateTime)
    end_date = db.Column(db.DateTime)
    criticality = db.Column(db.String(), default="unknown")
    history = db.relationship(
        "VendorHistory", backref="vendor", lazy="dynamic", cascade="all, delete-orphan"
    )
    apps = db.relationship(
        "VendorApp", backref="vendor", lazy="dynamic", cascade="all, delete-orphan"
    )
    files = db.relationship(
        "VendorFile", backref="vendor", lazy="dynamic", cascade="all, delete-orphan"
    )
    assessments = db.relationship(
        "Assessment", backref="vendor", lazy="dynamic", cascade="all, delete-orphan"
    )
    data_class_id = db.Column(db.String, db.ForeignKey("data_class.id"), nullable=True)
    tenant_id = db.Column(db.String, db.ForeignKey("tenants.id"), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    VALID_CRITICALITY = ["unknown", "low", "moderate", "high"]
    VALID_REVIEW_STATUS = [
        "new",
        "pending_response",
        "pending_review",
        "info_required",
        "complete",
    ]
    VALID_STATUS = ["pending", "approved", "not approved"]

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data["risk"] = 0
        if self.data_class_id:
            data["data_classification"] = self.data_class.name
        data["application_count"] = self.apps.count()
        data["assessment_count"] = self.assessments.count()
        data["next_review_date"] = self.get_next_review_date()
        data["days_until_next_review_date"] = self.days_until_next_review()
        data["next_review_date_humanize"] = self.days_until_next_review(humanize=True)

        data["review_description"] = "compliant"
        if not self.last_reviewed:
            data["review_description"] = "never reviewed"
        else:
            data["last_reviewed"] = arrow.get(self.last_reviewed).format("YYYY-MM-DD")

        data["review_upcoming"] = False
        if data["days_until_next_review_date"] <= 14:
            data["review_upcoming"] = True
            if self.last_reviewed:
                data["review_description"] = "upcoming review"

        data["review_past_due"] = False
        if data["days_until_next_review_date"] <= 0:
            data["review_past_due"] = True
            if self.last_reviewed:
                data["review_description"] = "past due"

        data["type"] = "vendor"
        return data

    def create_evidence_folder(self):
        return self.tenant.create_vendor_evidence_folder(vendor_id=self.id)

    def get_evidence_folder(self):
        return self.tenant.get_vendor_evidence_folder(vendor_id=self.id)

    def days_until_next_review(self, humanize=False):
        next_review_date = self.get_next_review_date()
        if humanize:
            return arrow.get(next_review_date).humanize(granularity=["day"])
        return (arrow.get(next_review_date).date() - arrow.utcnow().date()).days

    def is_ready_for_review(self, grace_period=7):
        today = arrow.get(arrow.utcnow().format("YYYY-MM-DD"))
        future_date = today.shift(days=grace_period)
        next_review_date = arrow.get(self.get_next_review_date())
        if future_date >= next_review_date:
            return True
        return False

    def get_next_review_date(self):
        if not self.last_reviewed:
            return arrow.utcnow().format("YYYY-MM-DD")
        if not self.review_cycle:
            return arrow.utcnow().format("YYYY-MM-DD")
        return (
            arrow.get(self.last_reviewed)
            .shift(months=self.review_cycle)
            .format("YYYY-MM-DD")
        )

    @validates("contact_email", "vendor_contact_email")
    def _validate_email(self, key, address):
        if not address:
            return address
        try:
            email_validator.validate_email(address, check_deliverability=False)
        except Exception:
            abort(422, "Invalid email")
        return address

    @validates("status")
    def _validate_status(self, key, value):
        if value.lower() not in self.VALID_STATUS:
            raise ValueError(f"Invalid status: {value}")
        return value.lower()

    @validates("review_status")
    def _validate_review_status(self, key, value):
        if value.lower() not in self.VALID_REVIEW_STATUS:
            raise ValueError(f"Invalid review status: {value}")
        return value.lower()

    @validates("criticality")
    def _validate_criticality(self, key, value):
        value = value or "unknown"
        if value.lower() not in self.VALID_CRITICALITY:
            raise ValueError(f"Invalid criticality: {value}")
        return value.lower()

    def create_history(self, name, description, user_id, icon=None):
        record = VendorHistory(
            name=name, description=description, icon=icon, user_id=user_id
        )
        self.history.append(record)
        db.session.commit()
        return record

    def get_assessments(self):
        return db.session.execute(db.select(Assessment).filter(Assessment.vendor_id == self.id)).scalars().all()

    def get_categories(self):
        records = db.session.execute(
            db.select(VendorApp).filter(VendorApp.tenant_id == self.tenant_id)
            .distinct(VendorApp.category)
        ).scalars().all()
        return [record.category for record in records]

    def get_bus(self):
        records = db.session.execute(
            db.select(VendorApp).filter(VendorApp.tenant_id == self.tenant_id)
            .distinct(VendorApp.business_unit)
        ).scalars().all()
        return [record.business_unit for record in records]

    def create_assessment(
        self,
        name,
        description,
        owner_id,
        due_date=None,
        vendor_id=None,
        clone_from=None,
    ):
        if (
            db.session.execute(db.select(Assessment).filter(Assessment.vendor_id == self.id)
            .filter(func.lower(Assessment.name) == func.lower(name))).scalars()
            .first()
        ):
            abort(422, f"Name already exists: {name}")

        if not due_date:
            due_date = str(arrow.utcnow().shift(days=+30))

        # TODO - update
        assessment = Assessment(
            name=name.lower(),
            description=description,
            due_before=due_date,
            owner_id=owner_id,
            tenant_id=self.tenant_id,
        )
        self.assessments.append(assessment)
        db.session.commit()

        form = self.tenant.create_form(
            name=f"Form for {name}",
            description=f"Form for {name}",
            assessment_id=assessment.id,
            clone_from=clone_from,
        )
        assessment.form_id = form.id
        db.session.commit()
        return assessment

    def create_app(self, name, **kwargs):
        if not name:
            abort(422, "Name is required")
        if (
            db.session.execute(db.select(VendorApp).filter(VendorApp.vendor_id == self.id)
            .filter(func.lower(VendorApp.name) == func.lower(name))).scalars()
            .first()
        ):
            abort(422, f"Name already exists: {name}")

        # TODO - check if requested data class is below vendor approved data class
        # if data_classification := kwargs.get("data_classification"):
        #     self.data_class ...

        app = VendorApp(
            name=name.lower(),
            **kwargs,
            tenant_id=self.tenant_id,
        )
        self.apps.append(app)
        db.session.commit()
        return app

    def create_file(self, name, file_object, owner_id, description=None, provider=None):
        """
        Create file

        Args
            name (str): file name
            file_object (object): request.files['file']
            owner_id: user id of the uploader
        """
        if provider is None:
            provider = current_app.config["STORAGE_METHOD"]

        if self.files.filter(func.lower(VendorFile.name) == func.lower(name)).first():
            abort(422, f"File already exists with the name: {name}")

        if provider not in current_app.config["STORAGE_PROVIDERS"]:
            abort(422, f"Provider not supported:{provider}")

        file = VendorFile(
            name=name.lower(),
            owner_id=owner_id,
            description=description,
            provider=provider,
        )
        self.files.append(file)
        file.save_file(file_object)
        try:
            # file.save_file(file_object)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            abort(500, f"Failed up upload file: {e}")
        return file



