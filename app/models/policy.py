"""app.models.policy — Policy domain models."""

from app import db
from app.masri.settings_service import EncryptedText
from flask import current_app
from sqlalchemy.orm import validates
from datetime import datetime
import shortuuid
import secrets
import json


class ProjectPolicy(db.Model):
    __tablename__ = "project_policies"
    __table_args__ = (db.UniqueConstraint("name", "project_id"),)
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    name = db.Column(db.String(), nullable=True)
    ref_code = db.Column(db.String())
    description = db.Column(db.String())
    visible = db.Column(db.Boolean(), default=True)
    tags = db.relationship(
        "Tag",
        secondary="policy_tags",
        lazy="dynamic",
        backref=db.backref("project_policies", lazy="dynamic"),
    )
    versions = db.relationship("PolicyVersion", backref="policy", lazy="dynamic", cascade="all, delete-orphan")
    project_id = db.Column(db.String, db.ForeignKey("projects.id"), nullable=False)
    owner_id = db.Column(db.String(), db.ForeignKey("users.id"))
    reviewer_id = db.Column(db.String(), db.ForeignKey("users.id"))
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def as_dict(self, include=[]):
        data = {}
        for c in self.__table__.columns:
            if c.name in include or not include:
                data[c.name] = getattr(self, c.name)
        data["owner"] = self.owner_email()
        data["reviewer"] = self.reviewer_email()
        data["version_id"] = 1

        """
        By default, load the published version and then the 
        latest version (if there is not a published version)
        """
        if not (version := self.get_published_version()):
            version = self.get_latest_version()

        if version:
            data["version_id"] = version.id
            data["content"] = version.content
            data["version"] = version.version

        versions = self.get_versions()
        data["versions"] = versions
        data["is_published"] = False
        for record in versions:
            if record["published"]:
                data["is_published"] = True
                break
        return data

    def get_published_version(self):
        return self.versions.filter(PolicyVersion.published == True).first()

    def publish_version(self, version):
        if not (has_version := self.get_version(version)):
            abort(404, f"Version:{version} not found")
        has_version.published = True
        for record in self.versions.all():
            if record != has_version:
                record.published = False
        db.session.commit()
        return has_version

    def delete(self):
        db.session.execute(db.delete(PolicyVersion).where(PolicyVersion.policy_id == self.id))
        db.session.execute(db.delete(ProjectPolicyAssociation).where(ProjectPolicyAssociation.policy_id == self.id))
        db.session.delete(self)
        db.session.commit()
        return True

    def update(self, name=None, description=None, reviewer=None):
        if name:
            self.name = name
        if description:
            self.description = description
        if reviewer:
            if member := self.project.has_member(reviewer):
                self.reviewer_id = member.user_id
        db.session.commit()
        return self

    def update_version(self, version, content=None, status=None, publish=False):
        record = self.get_version(version)
        if content is not None:
            record.content = content
        if status:
            record.status = status
        db.session.commit()
        if publish:
            self.publish_version(version)
        return record

    def get_versions(self, content=False, include_object=False):
        data = []
        latest = True
        for version in self.versions.order_by(PolicyVersion.version.desc()).all():
            last_changed = arrow.get(version.date_updated or version.date_added).format(
                "MMM, YY"
            )
            record = {
                "version_id": version.id,
                "version": version.version,
                "status": version.status,
                "published": version.published,
                "last_changed": last_changed,
                "is_latest": latest,
            }
            latest = False
            if content:
                record["content"] = version.content
            if include_object:
                record["object"] = version
            data.append(record)
        return data

    def get_latest_version(self, status=None):
        _query = self.versions
        if status:
            _query = _query.filter(PolicyVersion.status == status)
        return _query.order_by(PolicyVersion.version.desc()).first()

    def delete_version(self, version):
        if record := self.get_version(version):
            db.session.delete(record)
            db.session.commit()
        return True

    def get_version(self, version, status=None, published=None, as_dict=False):
        if version == "latest":
            record = self.get_latest_version(status=status)
            """
            If there are no versions, create one and return it.
            Should probably move this to init of a policy
            """
            if not record:
                record = self.add_version(content="")

        elif version == "published":
            if not (record := self.get_published_version()):
                abort(404, "Policy has not been published")
        else:
            record = self.versions.filter(PolicyVersion.version == version).first()
        if not record:
            abort(404, "Version not found")
        if as_dict:
            return record.as_dict()
        return record

    def add_version(self, content, status="draft"):
        latest_version = self.get_latest_version()
        next_version = latest_version.version + 1 if latest_version else 1
        new_version = PolicyVersion(
            content=content, status=status, version=next_version
        )
        self.versions.append(new_version)
        db.session.commit()
        return new_version

    def get_controls(self):
        return db.session.execute(db.select(ProjectPolicyAssociation).filter(
            ProjectPolicyAssociation.policy_id == self.id
        )).scalars().all()

    def has_control(self, id):
        return db.session.execute(
            db.select(ProjectPolicyAssociation).filter(
                ProjectPolicyAssociation.policy_id == self.id
            )
            .filter(ProjectPolicyAssociation.control_id == id)
        ).scalars().first()

    def add_control(self, id):
        if not self.has_control(id):
            pa = ProjectPolicyAssociation(policy_id=self.id, control_id=id)
            db.session.add(pa)
            db.session.commit()
        return True

    def remove_control(self, id):
        if assoc := self.has_control(id):
            db.session.delete(assoc)
            db.session.commit()
        return True

    def owner_email(self):
        if user := db.session.get(User, self.owner_id):
            return user.email
        return None

    def reviewer_email(self):
        if user := db.session.get(User, self.reviewer_id):
            return user.email
        return None

    def get_template_variables(self):
        template = self.as_dict(
            include=["uuid", "version", "name", "description", "ref_code"]
        )
        template["organization"] = self.project.tenant.name
        template["owner_email"] = self.owner_email()
        template["reviewer_email"] = self.reviewer_email()
        for label in db.session.execute(db.select(PolicyLabel)).scalars().all():
            template[label.key] = label.value
        return template

    def translate_to_html(self):
        class CustomFormatter(Formatter):
            def get_value(self, key, args, kwds):
                if isinstance(key, str):
                    try:
                        return kwds[key]
                    except KeyError:
                        return key
                else:
                    return Formatter.get_value(key, args, kwds)

        fmt = CustomFormatter()
        return fmt.format(self.content, **self.get_template_variables())



class PolicyVersion(db.Model):
    __tablename__ = "policy_versions"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    content = db.Column(db.String())
    version = db.Column(db.Integer())
    status = db.Column(db.String(), default="draft")
    published = db.Column(db.Boolean(), default=False)
    policy_id = db.Column(
        db.String, db.ForeignKey("project_policies.id", ondelete="CASCADE"), nullable=False
    )
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    VALID_STATUSES = ["draft", "in_review", "ready"]

    def as_dict(self):
        data = {}
        for c in self.__table__.columns:
            data[c.name] = getattr(self, c.name)
        data["is_latest"] = self.is_latest()
        if not self.status:
            data["status"] = "draft"
        return data

    def is_latest(self):
        latest = db.session.execute(
            db.select(PolicyVersion).filter(PolicyVersion.policy_id == self.policy_id)
            .order_by(PolicyVersion.version.desc())
        ).scalars().first()
        if latest == self:
            return True
        return False



class PolicyLabel(db.Model):
    __tablename__ = "policy_labels"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    key = db.Column(db.String(), unique=True, nullable=False)
    value = db.Column(db.String(), nullable=False)
    owner_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    tenant_id = db.Column(db.String, db.ForeignKey("tenants.id"), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        return data

    @validates("key")
    def validate_key(self, table_key, key):
        if not key.startswith("policy_label_"):
            raise ValueError("key must start with policy_label_")
        return key



class PolicyTags(db.Model):
    __tablename__ = "policy_tags"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    policy_id = db.Column(
        db.String(), db.ForeignKey("project_policies.id", ondelete="CASCADE")
    )
    tag_id = db.Column(db.String(), db.ForeignKey("tags.id", ondelete="CASCADE"))



