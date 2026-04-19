"""app.models.tenant — Tenant domain models."""

from app import db
from app.utils.mixin_models import QueryMixin, AuthorizerMixin
from app.masri.settings_service import EncryptedText
from flask import current_app, abort, render_template
from sqlalchemy import func
from app.utils.file_handler import FileStorageHandler
import email_validator
from sqlalchemy.orm import validates
from datetime import datetime
from typing import List
from app.utils.authorizer import Authorizer
from app.utils import misc
from app.email import send_email
import os
import shortuuid
import secrets
import json
import arrow
import logging
import hashlib
import shutil


class DataClass(db.Model, QueryMixin):
    __tablename__ = "data_class"
    __table_args__ = (db.UniqueConstraint("name", "tenant_id"),)
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    name = db.Column(db.String(64), nullable=False)
    order = db.Column(db.Integer)
    color = db.Column(db.String)
    vendors = db.relationship("Vendor", backref="data_class", lazy="dynamic")
    apps = db.relationship("VendorApp", backref="data_class", lazy="dynamic")
    tenant_id = db.Column(db.String, db.ForeignKey("tenants.id"), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)



class Tenant(db.Model, QueryMixin, AuthorizerMixin):
    __tablename__ = "tenants"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    name = db.Column(db.String, nullable=False)  # plaintext — used in SQL queries and display
    logo_ref = db.Column(db.String())
    contact_email = db.Column(EncryptedText)  # encrypted — PII
    license = db.Column(
        db.String(),
        server_default="gold",
        info={"authorizer": {"update": Authorizer.can_user_manage_platform}},
    )
    is_default = db.Column(db.Boolean(), default=False)
    approved_domains = db.Column(db.String())  # plaintext — used for domain-matching auth logic
    magic_link_login = db.Column(db.Boolean(), default=False)
    archived = db.Column(db.Boolean(), default=False)
    ai_enabled = db.Column(db.Boolean(), default=True)
    ai_token_usage = db.Column(db.Integer(), default=0)
    ai_token_cap = db.Column(db.Integer(), default=500)
    user_cap = db.Column(db.Integer(), default=500)
    project_cap = db.Column(db.Integer(), default=2)
    storage_cap = db.Column(db.String(), default="10000000")
    data_class = db.relationship(
        "DataClass", backref="tenant", lazy="dynamic", cascade="all, delete-orphan"
    )
    members = db.relationship(
        "TenantMember", backref="tenant", lazy="dynamic", cascade="all, delete-orphan"
    )
    frameworks = db.relationship(
        "Framework", backref="tenant", lazy="dynamic", cascade="all, delete-orphan"
    )
    projects = db.relationship(
        "Project", backref="tenant", lazy="dynamic", cascade="all, delete-orphan"
    )
    policies = db.relationship(
        "Policy", backref="tenant", lazy="dynamic", cascade="all, delete-orphan"
    )
    controls = db.relationship(
        "Control", backref="tenant", lazy="dynamic", cascade="all, delete-orphan"
    )
    tags = db.relationship(
        "Tag", backref="tenant", lazy="dynamic", cascade="all, delete-orphan"
    )
    forms = db.relationship(
        "Form", backref="tenant", lazy="dynamic", cascade="all, delete-orphan"
    )
    assessments = db.relationship(
        "Assessment", backref="tenant", lazy="dynamic", cascade="all, delete-orphan"
    )
    vendors = db.relationship(
        "Vendor", backref="tenant", lazy="dynamic", cascade="all, delete-orphan"
    )
    risks = db.relationship(
        "RiskRegister", backref="tenant", lazy="dynamic", cascade="all, delete-orphan"
    )
    integration_facts = db.relationship(
        "IntegrationFact", backref="tenant", lazy="dynamic", cascade="all, delete-orphan"
    )
    owner_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    labels = db.relationship(
        "PolicyLabel", backref="tenant", lazy="dynamic", cascade="all, delete-orphan"
    )
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    VALID_LICENSE = ["trial", "silver", "gold"]

    def add_log(self, **kwargs):
        return Logs.add(tenant_id=self.id, **kwargs)

    def get_logs(self, **kwargs):
        return Logs.get(tenant_id=self.id, **kwargs)

    @staticmethod
    def get_default_tenant():
        return db.session.execute(db.select(Tenant).filter(Tenant.is_default)).scalars().first()

    def get_members(self):
        members = []
        for member in self.members.all():
            user = member.user.as_dict()
            roles = [role.name for role in member.roles.all()]
            user["roles"] = roles
            if "vendor" in roles:
                user["is_vendor"] = True
            user.pop("tenants", None)
            members.append(user)
        return members

    def send_member_email_invite(self, user):
        """
        Send email invite to a member of the tenant
        """
        response = {"access_link": None, "sent-email": False}

        if not self.has_member(user):
            response["message"] = "User is not a member of tenant"
            return response

        token = User.generate_invite_token(
            email=user.email, expiration=604800, attributes={"tenant": self.name}
        )
        link = "{}{}?token={}".format(current_app.config["HOST_NAME"], "accept", token)
        response["access_link"] = link

        if not current_app.is_email_configured:
            response["message"] = "Email is not configured"
            return response

        title = f"{current_app.config['APP_NAME']}: Tenant invite"
        content = f"You have been added to a new tenant: {self.name.capitalize()}"
        send_email(
            title,
            recipients=[user.email],
            text_body=render_template(
                "email/basic_template.txt",
                title=title,
                content=content,
                button_link=link,
            ),
            html_body=render_template(
                "email/basic_template.html",
                title=title,
                content=content,
                button_link=link,
            ),
        )
        response["sent-email"] = True
        response["access_link"] = link
        return response

    def has_member(self, user_or_email, get_user_object=False):
        if (
            isinstance(user_or_email, TenantMember)
            and user_or_email.tenant_id == self.id
        ):
            if get_user_object:
                return user_or_email.user
            return user_or_email

        if not (user := User.email_to_object(user_or_email)):
            return None

        if member := self.members.filter(TenantMember.user_id == user.id).first():
            if get_user_object:
                return user
        return member

    def get_roles_for_member(self, user_or_email):
        if not (user := self.has_member(user_or_email)):
            return []
        return [role.name for role in user.roles.all()]

    def has_member_with_role(self, user_or_email, role_name):
        if not role_name:
            return False
        if not (user := self.has_member(user_or_email)):
            return False
        if role_name.lower() in self.get_roles_for_member(user):
            return True
        return False

    def add_member(
        self,
        user_or_email,
        attributes={},
        send_notification=False,
    ):
        """
        Add user to the tenant. If user does not exist, they will be created and then added to tenant

        user_or_email: user object or email address
        attributes: see User class
        send_notification: send email notification

        Usage:
        response, user = tenant.add_member(
            user_or_email=data.get("email"),
            attributes={"roles": data.get("roles", [])},
            send_notification=True
        )
        """
        roles = self.get_default_roles(attributes.get("roles"))
        attributes.pop("roles", None)

        # User already exists
        if isinstance(user_or_email, User):
            user = user_or_email
            email = user.email

        # User does not exist
        else:
            email = user_or_email
            user = User.find_by_email(email)

        can_we_invite, error = self.can_we_invite_user(email)
        if not can_we_invite:
            abort(500, error)

        # If the user does not exist, create them
        if not user:
            user = User.add(email, **attributes, return_user_object=True)

        new_member = TenantMember(user_id=user.id, tenant_id=self.id)
        db.session.add(new_member)
        db.session.commit()

        # Set roles for the member
        self.patch_roles_for_member(user, role_names=roles)

        response = {
            "id": user.id,
            "success": True,
            "message": f"Added {user.email} to {self.name}",
            "sent-email": False,
            # confirm_code intentionally NOT exposed in API response (security)
        }
        if send_notification:
            # haaaa
            email_invite = self.send_member_email_invite(user)
            response["sent-email"] = email_invite["sent-email"]
            response["access_link"] = email_invite["access_link"]

        return response, user

    def patch_roles_for_member(self, user, role_names):
        """
        Replaces a user's roles with new ones. Pass an empty list to remove all roles
        """
        member = self.has_member(user)
        if not member:
            raise ValueError(f"User {user.email} is not a member of {self.name}")

        new_roles = []
        for role_name in role_names:
            role = Role.find_by_name(role_name)
            if role:
                new_roles.append(role)

        member.roles = new_roles
        db.session.commit()
        return member

    def remove_member(self, user):
        """
        Removes a user from the tenant.
        """
        member = self.has_member(user)
        if member:
            db.session.delete(member)
            db.session.commit()
        return True

    def add_role_for_member(self, user, role_names):
        """
        Adds roles to a user in the tenant without affecting existing roles.

        :param user: User object to update
        :param role_names: List of role names (strings) to add
        """
        member = db.session.execute(db.select(TenantMember).filter_by(
            user_id=user.id, tenant_id=self.id
        )).scalars().first()

        if not member:
            raise ValueError(f"User {user.email} is not a member of {self.name}")

        for role_name in role_names:
            role = Role.find_by_name(role_name)
            if role and role not in member.roles:
                member.roles.append(role)

        db.session.commit()
        return member

    def remove_role_for_member(self, user, role_names):
        """
        Removes roles from a user in the tenant without affecting other roles.

        :param user: User object to update
        :param role_names: List of role names (strings) to remove
        """
        member = db.session.execute(db.select(TenantMember).filter_by(
            user_id=user.id, tenant_id=self.id
        )).scalars().first()

        if not member:
            raise ValueError(f"User {user.email} is not a member of {self.name}")

        for role_name in role_names:
            role = Role.find_by_name(role_name)
            if role and role in member.roles:
                member.roles.remove(role)

        db.session.commit()
        return member

    @validates("license")
    def _validate_license(self, key, value):
        if value not in self.VALID_LICENSE:
            raise ValueError(f"Invalid license: {value}")
        return value

    @validates("contact_email")
    def _validate_email(self, key, address):
        if address:
            try:
                email_validator.validate_email(address, check_deliverability=False)
            except Exception:
                abort(422, "Invalid email")
        return address

    @validates("name")
    def _validate_name(self, key, name):
        special_characters = r"!\"#$%&'()*+,-./:;<=>?@[\]^`{|}~"
        if any(c in special_characters for c in name):
            raise ValueError("Illegal characters in name")
        return name

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data["owner_email"] = self.get_owner_email()
        data["approved_domains"] = []
        if self.approved_domains:
            data["approved_domains"] = self.approved_domains.split(",")
        return data

    def populate_data_classification(self):
        if self.data_class.count():
            return True

        defaults = [
            {"name": "restricted", "order": 1, "color": "red"},
            {"name": "confidential", "order": 2, "color": "orange"},
            {"name": "internal", "order": 3, "color": "yellow"},
            {"name": "public", "order": 4, "color": "green"},
        ]
        for record in defaults:
            dc = DataClass(
                name=record["name"], order=record["order"], color=record["color"]
            )
            self.data_class.append(dc)

        db.session.commit()
        return True

    def get_form_templates(self):
        return self.forms.filter(Form.assessment_id == None).all()

    def create_form(
        self,
        name,
        description=None,
        assessment_id=None,
        clone_from=None,
    ):
        """
        Create form for a tenant

        assessment_id: Attach the form to an existing assessment
        clone_form: Makes a clone of an existing form if supplied with the form ID
        """

        clone = None
        if clone_from:
            clone = self.forms.filter(Form.id == clone_from).first()
            if not clone:
                abort(400, f"Form: {clone_from} not found in the tenant")

        form = Form(
            name=name,
            description=description,
            assessment_id=assessment_id,
        )

        if clone:
            for section in clone.sections.all():
                new_section = FormSection(title=section.title, order=section.order)
                for item in section.items.all():
                    new_item = FormItem(
                        data_type=item.data_type,
                        order=item.order,
                        editable=item.editable,
                        disabled=item.disabled,
                        applicable=item.applicable,
                        score=item.score,
                        critical=item.critical,
                        attributes=item.attributes,
                        rule=item.rule,
                        rule_action=item.rule_action,
                    )
                    new_section.items.append(new_item)
                form.sections.append(new_section)

        self.forms.append(form)
        db.session.commit()

        if not clone:
            form.create_section(title="general")
        return form

    def create_risk(
        self,
        title,
        description=None,
        remediation=None,
        tags=[],
        assignee=None,
        enabled=True,
        status="new",
        risk="unknown",
        priority="unknown",
        project_id=None,
        vendor_id=None,
    ):
        risk = RiskRegister(
            title=title,
            description=description,
            remediation=remediation,
            enabled=enabled,
            status=status,
            risk=risk,
            priority=priority,
            project_id=project_id,
            vendor_id=vendor_id,
        )
        if tags:
            if not isinstance(tags, list):
                tags = [tags]

            for name in tags:
                tag = Tag(name=name, tenant_id=self.id)
                risk.tags.append(tag)

        if assignee:
            user = self.has_member(assignee, get_user_object=True)
            if not user:
                abort(
                    422, f"User:{assignee} does not exist or not a member of the tenant"
                )
            risk.assignee = user.id
        self.risks.append(risk)
        db.session.commit()
        return risk

    def create_vendor(self, name, contact_email):
        vendor = Vendor.find_by("name", name, tenant_id=self.id)
        if vendor:
            abort(422, f"Vendor already exists with name: {name}")

        vendor = Vendor(name=name.lower(), contact_email=contact_email)
        self.vendors.append(vendor)
        db.session.commit()
        return vendor

    def get_owner_email(self):
        if not (user := db.session.get(User, self.owner_id)):
            return "unknown"
        return user.email

    def get_valid_frameworks(self):
        frameworks = []
        folder = current_app.config["FRAMEWORK_FOLDER"]
        for file in os.listdir(folder):
            if file.endswith(".json"):
                name = file.split(".json")[0]
                frameworks.append(name.lower())
        return frameworks

    def check_valid_framework(self, name):
        if name.lower() not in self.get_valid_frameworks():
            raise ValueError("framework is not implemented")
        return True

    def create_framework(self, name, add_controls=False, add_policies=False):
        if Framework.find_by_name(name, self.id):
            return False
        Framework.create(name, self)
        if add_controls:
            self.create_base_controls_for_framework(name)
        if add_policies:
            self.create_base_policies()
        return True

    def create_base_controls_for_framework(self, name):
        name = name.lower()
        with open(
            os.path.join(current_app.config["FRAMEWORK_FOLDER"], f"{name}.json")
        ) as f:
            controls = json.load(f)
            Control.create({"controls": controls, "framework": name}, self.id)

        # Populate cross-framework mappings for newly created controls
        try:
            from app.masri.control_mappings import populate_mappings
            populate_mappings(self.id)
        except Exception:
            pass  # Non-fatal — mappings can be populated later via API

        return True

    def create_base_frameworks(self, init_controls=False):
        folder = current_app.config["FRAMEWORK_FOLDER"]
        if not os.path.isdir(folder):
            abort(422, f"Folder does not exist: {folder}")
        for file in os.listdir(folder):
            if file.endswith(".json"):
                name = file.split(".json")[0]
                existing = Framework.find_by_name(name, self.id)
                if not existing:
                    # Check JSON for deprecation metadata
                    is_deprecated = False
                    dep_msg = None
                    try:
                        with open(os.path.join(folder, file)) as f:
                            controls = json.load(f)
                            if controls and isinstance(controls, list) and controls[0].get("_deprecated"):
                                is_deprecated = True
                                dep_msg = controls[0].get("_deprecated_message")
                    except Exception:
                        pass
                    Framework.create(name, self, deprecated=is_deprecated, deprecated_message=dep_msg)
                    if init_controls:
                        self.create_base_controls_for_framework(name)
        return True

    def create_base_policies(self):
        for filename in os.listdir(current_app.config["POLICY_FOLDER"]):
            if filename.endswith(".html"):
                name = filename.split(".html")[0].lower()
                if not Policy.find_by_name(name, self.id):
                    with open(
                        os.path.join(current_app.config["POLICY_FOLDER"], filename)
                    ) as f:
                        _body = f.read()
                        p = Policy(
                            name=name,
                            description=f"Content for the {name} policy",
                            content=_body,
                            template=_body,
                            tenant_id=self.id,
                        )
                        db.session.add(p)
        db.session.commit()
        return True

    def get_assessments_for_user(self, user):
        user_roles = self.get_roles_for_member(user)
        data = []
        if user.super or any(role in ["admin"] for role in user_roles):
            return self.assessments.all()
        for assessment in self.assessments.all():
            if assessment.has_guest(user.email):
                data.append(assessment)
        return data

    def can_we_invite_user(self, email):
        if not User.validate_email(email):
            return (False, "Invalid email")

        if self.has_member(email):
            return (False, "User already exists in the tenant")

        user_count = self.members.count()
        if user_count >= int(self.user_cap):
            return (False, "Tenant has reached user capacity")

        if not self.approved_domains:
            return (True, None)

        name, tld = email.split("@")
        for domain in self.approved_domains.split(","):
            if domain == tld:
                return (True, None)
        return (False, "User domain is not within the approved domains of the tenant")

    def remove_user_from_projects(self, user):
        for project in self.projects.all():
            project.members.filter(ProjectMember.user_id == user.id).delete()
        db.session.commit()
        return True

    def remove_user_from_assessments(self, user):
        for assessment in self.assessments:
            db.session.execute(db.delete(AssessmentGuest).where(
                AssessmentGuest.assessment_id == assessment.id,
                AssessmentGuest.user_id == user.id
            ))
            db.session.commit()
        return True

    def get_default_roles(self, roles):
        if not roles:
            return ["user"]

        if not isinstance(roles, list):
            roles = [roles]

        if "vendor" in roles:
            roles = ["vendor"]
        else:
            if "user" not in roles:
                roles.append("user")
        return roles

    def get_vendor_evidence_folder(self, vendor_id, provider="local"):
        if provider not in current_app.config["STORAGE_PROVIDERS"]:
            abort(422, f"Provider not supported:{provider}")
        if provider != "local":
            # TODO - might have to remove the leading slash for s3 and maybe gcs
            path = os.path.join("vendors", vendor_id.lower())
            return path.lstrip(os.sep)
        return os.path.join(
            current_app.config["EVIDENCE_FOLDER"], "vendors", vendor_id.lower()
        )

    def get_evidence(self, as_dict=False):
        records = self.evidence.all()
        if as_dict:
            return [record.as_dict() for record in records]
        return records

    def get_evidence_folder(self, project_id=None, provider="local"):
        if provider not in current_app.config["STORAGE_PROVIDERS"]:
            abort(422, f"Provider not supported:{provider}")
        if provider != "local":
            path = os.path.join(
                "tenants",
                self.id.lower(),
                *(["projects", project_id.lower()] if project_id else []),
            )
            return path.lstrip(os.sep)
        return os.path.join(
            current_app.config["EVIDENCE_FOLDER"],
            "tenants",
            self.id.lower(),
            *(["projects", project_id.lower()] if project_id else []),
        )

    def can_save_file_in_folder(self, provider=None):
        if not provider:
            provider = current_app.config["STORAGE_METHOD"]
        handler = FileStorageHandler(provider=provider)
        current_size = handler.get_size(folder=self.get_evidence_folder())

        if current_size < int(self.storage_cap):
            return True

        return False

    def get_tenant_info(self):
        data = {
            "projects": self.projects.count(),
            "users": self.members.count(),
            "risks": self.risks.count(),
        }
        return data

    @staticmethod
    def create(
        user,
        name,
        email,
        approved_domains=None,
        license="gold",
        is_default=False,
        init_data=False,
    ):

        # Ensure proper capitalization (e.g. "masri digital" → "Masri Digital")
        if name and name == name.lower():
            name = name.title()

        tenant = Tenant(
            owner_id=user.id,
            name=name,
            contact_email=email,
            approved_domains=approved_domains,
            is_default=is_default,
            license=license,
        )
        db.session.add(tenant)
        db.session.commit()

        tenant.populate_data_classification()

        # Add user as Admin to the tenant
        response, user = tenant.add_member(
            user_or_email=user,
            attributes={"roles": ["admin"]},
            send_notification=False,
        )

        if init_data:
            tenant.create_base_frameworks()
            tenant.create_base_policies()
        # create folder for evidence
        tenant.create_evidence_folder()
        return tenant

    def create_vendor_evidence_folder(self, vendor_id):
        vendor_folder = self.get_vendor_evidence_folder(vendor_id)
        if not os.path.exists(vendor_folder):
            os.makedirs(vendor_folder)
        return vendor_folder

    def create_evidence_folder(self, project_id=None):
        evidence_folder = self.get_evidence_folder(project_id=project_id)
        if not os.path.exists(evidence_folder):
            os.makedirs(evidence_folder)
        return evidence_folder

    def delete(self):
        evidence_folder = self.get_evidence_folder()
        if os.path.exists(evidence_folder):
            shutil.rmtree(evidence_folder)
        db.session.delete(self)
        db.session.commit()
        return True

    def create_project(
        self,
        name: str,
        owner_id: int,
        framework_id: int,
        description: str = None,
        controls: List[int] = [],
    ):
        if self.projects.count() >= int(self.project_cap):
            abort(422, f"Tenant has reached project capacity:{self.project_cap}")

        if not description:
            description = name

        project = Project(
            name=name, description=description, owner_id=owner_id, tenant_id=self.id
        )
        if framework_id:
            project.framework_id = framework_id

        self.projects.append(project)
        for control in controls:
            project.add_control(control, commit=False)

        evidence = ProjectEvidence(
            name="Evidence N/A",
            description="Default evidence object. Used to satisfy evidence collection.",
        )
        project.evidence.append(evidence)


class IntegrationFact(db.Model, QueryMixin):
    __tablename__ = "integration_facts"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    source = db.Column(db.String(), nullable=False)
    subject = db.Column(db.String(), nullable=False)
    assertion = db.Column(db.String(), nullable=False)
    fingerprint = db.Column(db.String(), nullable=False)
    collected_at = db.Column(db.DateTime, default=datetime.utcnow)
    tenant_id = db.Column(db.String, db.ForeignKey("tenants.id"), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)
