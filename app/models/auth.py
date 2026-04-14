"""app.models.auth — Auth domain models."""

from app import db, login
from app.utils.mixin_models import QueryMixin
from app.masri.settings_service import EncryptedText
from flask_login import UserMixin
from flask import current_app, render_template, abort
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func
from sqlalchemy.orm import validates
from datetime import datetime
from app.email import send_email
from app.utils.authorizer import Authorizer
from app.utils import misc
from uuid import uuid4
import email_validator
import shortuuid
import secrets
import logging
import random
import json
import arrow


class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    name = db.Column(db.String(50), nullable=False, server_default="")
    label = db.Column(db.Unicode(255), server_default="")

    @staticmethod
    def find_by_name(name):
        return db.session.execute(db.select(Role).filter(func.lower(Role.name) == func.lower(name))).scalars().first()

    @staticmethod
    def ids_to_names(list_of_role_ids):
        roles = []
        for role_id in list_of_role_ids:
            if role := db.session.get(Role, role_id):
                roles.append(role.name)
        return roles

    VALID_ROLE_NAMES = [
        "admin",
        "viewer",
        "user",
        "riskmanager",
        "riskviewer",
        "vendor",
    ]



class TenantMember(db.Model):
    """
    Represents a user in a specific tenant, with roles assigned.
    """

    __tablename__ = "tenant_members"
    __table_args__ = (db.UniqueConstraint("user_id", "tenant_id"),)

    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )

    user_id = db.Column(db.String, db.ForeignKey("users.id", ondelete="CASCADE"))
    tenant_id = db.Column(db.String, db.ForeignKey("tenants.id", ondelete="CASCADE"))

    # Many-to-Many Relationship: TenantMember <-> Role
    roles = db.relationship(
        "Role",
        secondary="tenant_member_roles",
        lazy="dynamic",
        backref=db.backref("tenant_members", lazy="dynamic"),
    )



class TenantMemberRole(db.Model):
    """
    This table assigns a specific role to a TenantMember (user in a specific tenant).
    """

    __tablename__ = "tenant_member_roles"

    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )

    tenant_member_id = db.Column(
        db.String, db.ForeignKey("tenant_members.id", ondelete="CASCADE")
    )
    role_id = db.Column(db.String, db.ForeignKey("roles.id", ondelete="CASCADE"))



class UserRole(db.Model):
    __tablename__ = "user_roles"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    user_id = db.Column(db.String(), db.ForeignKey("users.id", ondelete="CASCADE"))
    role_id = db.Column(db.String(), db.ForeignKey("roles.id", ondelete="CASCADE"))
    tenant_id = db.Column(db.String(), db.ForeignKey("tenants.id", ondelete="CASCADE"))

    @staticmethod
    def get_roles_for_user_in_tenant(user_id, tenant_id):
        roles = []
        role_mappings = db.session.execute(
            db.select(UserRole).filter(UserRole.user_id == user_id)
            .filter(UserRole.tenant_id == tenant_id)
        ).scalars().all()
        for mapping in role_mappings:
            role = db.session.get(Role, mapping.role_id)
            roles.append({"name": role.name.lower(), "user_role_id": mapping.id})
        return roles

    @staticmethod
    def get_mappings_for_role_in_tenant(role_name, tenant_id):
        role = Role.find_by_name(role_name)
        if not role:
            return []
        return db.session.execute(
            db.select(UserRole).filter(UserRole.role_id == role.id)
            .filter(UserRole.tenant_id == tenant_id)
        ).scalars().all()



class User(db.Model, UserMixin):
    __tablename__ = "users"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    is_active = db.Column(db.Boolean(), nullable=False, server_default="1")
    email = db.Column(db.String(255), nullable=False, unique=True)
    username = db.Column(db.String(100), unique=True)
    email_confirmed_at = db.Column(db.DateTime())
    email_confirm_code = db.Column(
        db.String,
        default=lambda: secrets.token_urlsafe(8),
    )
    password = db.Column(db.String(255), nullable=False, server_default="")
    last_password_change = db.Column(db.DateTime())
    login_count = db.Column(db.Integer, default=0)
    first_name = db.Column(db.String(100), nullable=False, server_default="")
    last_name = db.Column(db.String(100), nullable=False, server_default="")
    super = db.Column(db.Boolean(), nullable=False, server_default="0")
    built_in = db.Column(db.Boolean(), default=False)
    tenant_limit = db.Column(db.Integer, default=1)
    trial_days = db.Column(db.Integer, default=14)
    can_user_create_tenant = db.Column(db.Boolean(), nullable=False, server_default="1")
    license = db.Column(db.String(255), nullable=False, server_default="gold")
    memberships = db.relationship("TenantMember", backref="user", lazy="dynamic")
    projects = db.relationship("Project", backref="user", lazy="dynamic")
    assessments = db.relationship("AssessmentGuest", backref="user", lazy="dynamic")
    totp_secret_enc = db.Column(db.Text, nullable=True)  # Fernet-encrypted TOTP secret
    totp_enabled = db.Column(db.Boolean, default=False)
    session_timeout_minutes = db.Column(db.Integer, nullable=True)  # per-user override
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    VALID_LICENSE = ["trial", "silver", "gold"]

    @validates("license")
    def _validate_license(self, key, value):
        if value not in self.VALID_LICENSE:
            raise ValueError(f"Invalid license: {value}")
        return value

    @validates("email")
    def _validate_email(self, key, address):
        if address:
            try:
                email_validator.validate_email(address, check_deliverability=False)
            except Exception:
                abort(422, "Invalid email")
        return address

    @staticmethod
    def validate_registration(email, password, password2):
        if not email:
            abort(500, "Invalid or empty email")
        if not misc.perform_pwd_checks(password, password_two=password2):
            abort(500, "Invalid password")
        if User.find_by_email(email):
            abort(500, "Email already exists")
        if not User.validate_email(email):
            abort(500, "Invalid email")

    @staticmethod
    def validate_email(email):
        if not email:
            return False
        try:
            email_validator.validate_email(email, check_deliverability=False)
        except Exception:
            return False
        return True

    @staticmethod
    def email_to_object(user_or_email, or_404=False):
        if isinstance(user_or_email, User):
            return user_or_email
        if user := User.find_by_email(user_or_email):
            return user
        if or_404:
            abort(404, "User not found")
        return None

    def as_dict(self, tenant=None):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        if tenant:
            data["roles"] = self.roles_for_tenant(tenant)
        else:
            data["tenants"] = [tenant.name for tenant in self.get_tenants()]
        data.pop("password", None)
        return data

    def is_password_change_required(self):
        if not self.last_password_change:
            return True
        return False

    def setup_totp(self):
        """Generate a new TOTP secret, encrypt and store it. Returns the raw secret."""
        import pyotp
        from app.masri.settings_service import encrypt_value
        secret = pyotp.random_base32()
        self.totp_secret_enc = encrypt_value(secret)
        self.totp_enabled = False  # not enabled until verified
        db.session.commit()
        return secret

    def get_totp_secret(self):
        """Decrypt and return the TOTP secret."""
        if not self.totp_secret_enc:
            return None
        from app.masri.settings_service import decrypt_value
        return decrypt_value(self.totp_secret_enc)

    def verify_totp(self, code):
        """Verify a TOTP code against the stored secret."""
        import pyotp
        secret = self.get_totp_secret()
        if not secret:
            return False
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=1)

    def enable_totp(self):
        """Mark TOTP as enabled after initial verification."""
        self.totp_enabled = True
        db.session.commit()

    def disable_totp(self):
        """Disable and clear TOTP secret."""
        self.totp_enabled = False
        self.totp_secret_enc = None
        db.session.commit()

    def get_totp_uri(self, app_name="MD Compliance"):
        """Get the otpauth:// URI for QR code generation."""
        import pyotp
        secret = self.get_totp_secret()
        if not secret:
            return None
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(name=self.email, issuer_name=app_name)

    @staticmethod
    def add(
        email,
        password=None,
        username=None,
        first_name=None,
        last_name=None,
        confirmed=None,
        super=False,
        built_in=False,
        tenants=[],
        license="gold",
        is_active=True,
        require_pwd_change=False,
        send_notification=False,
        return_user_object=False,
    ):
        """
        Add user

        tenants: [{"id":1,"roles":["user"]}]
        """
        if not password:
            password = uuid4().hex

        User.validate_registration(email, password, password)

        email_confirmed_at = None
        if confirmed:
            email_confirmed_at = datetime.utcnow()
        if not username:
            username = f'{email.split("@")[0]}_{secrets.token_hex(4)}'

        new_user = User(
            email=email,
            username=username,
            first_name=first_name,
            last_name=last_name,
            email_confirmed_at=email_confirmed_at,
            built_in=built_in,
            super=super,
            license=license,
            is_active=is_active,
        )
        new_user.set_password(password, set_pwd_change=not require_pwd_change)
        db.session.add(new_user)
        db.session.commit()
        for record in tenants:
            if tenant := db.session.get(Tenant, record["id"]):
                tenant.add_member(
                    user_or_email=new_user,
                    attributes={"roles": record["roles"]},
                    send_notification=False,
                )

        token = User.generate_invite_token(email=new_user.email, expiration=604800)
        link = "{}{}?token={}".format(
            current_app.config["HOST_NAME"], "register", token
        )
        sent_email = False
        if send_notification and current_app.is_email_configured:
            title = f"{current_app.config['APP_NAME']}: Invite"
            content = f"You have been added as a super user to {current_app.config['APP_NAME']}"
            send_email(
                title,
                recipients=[new_user.email],
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
            sent_email = True

        if return_user_object:
            return new_user

        return {
            "id": new_user.id,
            "success": True,
            "message": f"Added {new_user.email}",
            "access_link": link,
            "sent-email": sent_email,
        }

    def send_email_confirmation(self):
        if self.email_confirmed_at:
            abort(422, "user is already confirmed")
        if not current_app.is_email_configured:
            abort(500, "email is not configured")

        title = "Confirm Email"
        content = f"Please enter the following code to confirm your email: {self.email_confirm_code}"
        link = "{}{}?code={}".format(
            current_app.config["HOST_NAME"], "confirm-email", self.email_confirm_code
        )
        send_email(
            title,
            recipients=[self.email],
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
                button_label="Confirm",
            ),
        )
        return True

    @staticmethod
    def find_by_email(email):
        if user := db.session.execute(db.select(User).filter(
            func.lower(User.email) == func.lower(email)
        )).scalars().first():
            return user
        return False

    @staticmethod
    def find_by_username(username):
        if user := db.session.execute(db.select(User).filter(
            func.lower(User.username) == func.lower(username)
        )).scalars().first():
            return user
        return False

    @staticmethod
    def verify_auth_token(token):
        data = misc.verify_jwt(token)
        if data is False:
            return False
        return db.session.get(User, data["id"])

    def generate_auth_token(self, expiration=600):
        data = {"id": self.id}
        return misc.generate_jwt(data, expiration)

    @staticmethod
    def verify_invite_token(token):
        if not token:
            return False
        data = misc.verify_jwt(token)
        if data is False:
            return False
        return data

    @staticmethod
    def generate_invite_token(email, tenant_id=None, expiration=600, attributes={}):
        data = {**attributes, **{"email": email}}
        if tenant_id:
            data["tenant_id"] = tenant_id
        return misc.generate_jwt(data, expiration)

    @staticmethod
    def verify_magic_token(token):
        data = misc.verify_jwt(token)
        if data is False:
            return False
        if data.get("type") != "magic_link":
            return False
        return data

    def generate_magic_link(self, tenant_id, expiration=600):
        data = {
            "email": self.email,
            "user_id": self.id,
            "tenant_id": tenant_id,
            "type": "magic_link",
        }
        return misc.generate_jwt(data, expiration)

    def get_username(self):
        if self.username:
            return self.username
        return self.email.split("@")[0]

    def get_projects(self, tenant_id=None):
        tenants = [t for t in self.get_tenants() if not tenant_id or t.id == tenant_id]
        return [
            project
            for tenant in tenants
            for project in tenant.projects.all()
            if Authorizer(self)._can_user_access_project(project)
        ]

    def get_tenants(self, own=False):
        if own:
            return db.session.execute(db.select(Tenant).filter(Tenant.owner_id == self.id)).scalars().all()
        if self.super:
            return db.session.execute(db.select(Tenant)).scalars().all()

        tenants_user_is_member_of = [member.tenant for member in self.memberships.all()]

        for tenant in db.session.execute(db.select(Tenant).filter(Tenant.owner_id == self.id)).scalars().all():
            if tenant not in tenants_user_is_member_of:
                tenants_user_is_member_of.append(tenant)
        return tenants_user_is_member_of

    def has_tenant(self, tenant):
        return tenant.has_member(self, get_user_object=True)

    def has_role_for_tenant(self, tenant, role_name):
        return tenant.has_member_with_role(self, role_name)

    def has_any_role_for_tenant(self, tenant, role_names):
        if not isinstance(role_names, list):
            role_names = [role_names]
        for role in role_names:
            if tenant.has_member_with_role(self, role):
                return True
        return False

    def has_all_roles_for_tenant(self, tenant, role_names):
        if not isinstance(role_names, list):
            role_names = [role_names]
        for role in role_names:
            if not tenant.has_member_with_role(self, role):
                return False
        return True

    def all_roles_by_tenant(self, tenant):
        data = []
        for role in db.session.execute(db.select(Role)).scalars().all():
            enabled = True if tenant.has_member_with_role(self, role.name) else False
            data.append(
                {"role_name": role.name, "role_id": role.id, "enabled": enabled}
            )
        return data

    def roles_for_tenant(self, tenant):
        return tenant.get_roles_for_member(self)

    def roles_for_tenant_by_id(self, tenant_id):
        tenant = db.session.get(Tenant, str(tenant_id))
        if not tenant:
            return []
        return self.roles_for_tenant(tenant)

    def set_password(self, password, set_pwd_change=True):
        if not misc.perform_pwd_checks(password, password_two=password):
            abort(422, "Invalid password - failed checks")

        self.password = generate_password_hash(password)
        if set_pwd_change:
            self.last_password_change = str(datetime.utcnow())

    def check_password(self, password):
        return check_password_hash(self.password, password)

    def set_confirmation(self):
        self.email_confirmed_at = str(arrow.utcnow())



