"""app.models.project — Project domain models."""

from app import db
from app.utils.mixin_models import QueryMixin, ControlMixin, SubControlMixin, DateMixin
from app.masri.settings_service import EncryptedText
from flask import current_app, abort
from sqlalchemy import func, case, distinct
from sqlalchemy.orm import validates
from datetime import datetime
from typing import List
from app.utils import misc
from app.utils.file_handler import FileStorageHandler
from app.utils.exceptions import FileDoesNotExist
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage
import os
import shortuuid
import secrets
import json
import arrow
import logging


class ProjectEvidence(db.Model, QueryMixin):
    __tablename__ = "project_evidence"
    __table_args__ = (db.UniqueConstraint("name", "project_id"),)
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    name = db.Column(db.String(), nullable=False)
    description = db.Column(db.String(), default="Empty description")
    content = db.Column(db.String())
    group = db.Column(db.String(), default="default")
    collected_on = db.Column(db.DateTime, default=datetime.utcnow)
    file_name = db.Column(db.String())
    file_provider = db.Column(db.String(), default="local")
    owner_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=True)
    project_id = db.Column(db.String, db.ForeignKey("projects.id"))
    tenant_id = db.Column(db.String, db.ForeignKey("tenants.id"))
    
    # Extended fields for methodology
    kind = db.Column(db.String, nullable=False, default="uploaded")
    status = db.Column(db.String, nullable=False, default="draft")
    source = db.Column(db.String, nullable=True)
    integration_fingerprint = db.Column(db.String, nullable=True)
    reviewed_by_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)

    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data["control_count"] = self.control_count()
        data["controls"] = [
            {"id": control.id, "name": control.subcontrol.name}
            for control in self.get_controls()
        ]
        data["has_file"] = self.has_file()
        return data

    def has_file(self):
        if self.file_name:
            return True
        return False

    def delete(self):
        try:
            self.delete_file()
        except Exception:
            pass
        db.session.delete(self)
        db.session.commit()
        return True

    def update(
        self,
        name=None,
        owner_id=None,
        description=None,
        content=None,
        group=None,
        collected_on=None,
        file=None,
        associate_with=[],
    ):
        """
        Update evidence for a project

        Args:
            name: Name of the evidence
            owner_id: ID of the user who owns the evidence
            description: Description of the evidence
            content: Content, typically JSON/CSV results that represents the evidence
            group: Logically group the evidence for filtering
            collected_on: Date at which it is collected
            file: FileStorage file
            associate_with: List of control IDs to associate the evidence with

        Returns:
            evidence object
        """
        if file is not None and not isinstance(file, FileStorage):
            abort(500, "File must be type FileStorage")

        if name:
            self.name = name
        if description:
            self.description = description
        if content:
            self.content = content
        if group:
            self.group = group
        if collected_on:
            self.collected_on = collected_on
        if owner_id:
            self.owner_id = owner_id
        if file:
            self.save_file(file, overwrite=True)
        if associate_with:
            self.associate_with_controls(associate_with)
        db.session.commit()

        return self

    def remove_controls(self, control_ids: List[int] = []):
        if control_ids:
            db.session.execute(db.delete(EvidenceAssociation).where(
                EvidenceAssociation.evidence_id == self.id,
                EvidenceAssociation.control_id.in_(control_ids)
            ))
        else:
            db.session.execute(db.delete(EvidenceAssociation).where(
                EvidenceAssociation.evidence_id == self.id
            ))
        db.session.commit()

    def associate_with_controls(self, control_ids: List[int]):
        """
        Associate evidence with a list of control_ids. This will patch the existing association.
        Passing an empty list will delete all associations with the evidence

        Args:
            control_ids: list of ProjectSubControls ids

        Returns:
            None
        """
        self.remove_controls()
        EvidenceAssociation.add(control_ids, self.id)

    def get_controls(self):
        id_list = [
            x.control_id
            for x in db.session.execute(db.select(EvidenceAssociation).filter(
                EvidenceAssociation.evidence_id == self.id
            )).scalars().all()
        ]
        return db.session.execute(db.select(ProjectSubControl).filter(ProjectSubControl.id.in_(id_list))).scalars().all()

    def control_count(self):
        return db.session.execute(db.select(db.func.count()).select_from(EvidenceAssociation).filter(
            EvidenceAssociation.evidence_id == self.id
        )).scalar()

    def has_control(self, control_id):
        return EvidenceAssociation.exists(control_id, self.id)

    def get_file(self, as_blob=False):
        if not self.file_name:
            return {}

        storage_method = current_app.config["STORAGE_METHOD"]
        if self.file_provider != storage_method:
            abort(500, f"File storage backend: {self.file_provider} is not enabled.")

        path = os.path.join(
            self.project.get_evidence_folder(provider=self.file_provider),
            self.file_name,
        )

        file_handler = FileStorageHandler(
            provider=self.file_provider,
        )
        return file_handler.get_file(path=path, as_blob=as_blob)

    def remove_file(self):
        """
        Disassociates the file with the evidence.
        If you want to delete the file, see delete_file()
        """
        if not self.file_name:
            abort(500, "Evidence does not contain a file")
        self.file_name = None
        db.session.commit()
        return True

    def delete_file(self, safe_delete=True):
        if not self.file_name:
            abort(500, "Evidence does not contain a file")

        if safe_delete:
            file_assoc = db.session.execute(db.select(db.func.count()).select_from(ProjectEvidence).filter(
                ProjectEvidence.file_name == self.file_name
            )).scalar()
            if file_assoc > 1:
                abort(
                    500,
                    f"Unable to delete the file. It is associated with {file_assoc} other evidence objects.",
                )

        storage_method = current_app.config["STORAGE_METHOD"]
        if self.file_provider != storage_method:
            abort(500, f"File storage backend: {self.file_provider} is not enabled.")

        path = os.path.join(
            self.project.tenant.get_evidence_folder(
                project_id=self.project_id, provider=self.file_provider
            ),
            self.file_name,
        )
        file_handler = FileStorageHandler(
            provider=self.file_provider,
        )
        file_handler.delete_file(path=path)
        self.remove_file()
        return True

    def save_file(self, file_object, file_name=None, provider=None, overwrite=False):
        if not isinstance(file_object, FileStorage):
            abort(500, "File object must be type FileStorage")

        if self.file_name and not overwrite:
            abort(500, "File already exists for the evidence")

        if not file_name:
            file_name = file_object.filename

        file_name = secure_filename(file_name).lower()

        # Validate file extension against allowlist
        allowed_extensions = current_app.config.get(
            "UPLOAD_EXTENSIONS",
            {".pdf", ".png", ".jpg", ".jpeg", ".docx", ".xlsx", ".txt", ".csv"},
        )
        if isinstance(allowed_extensions, str):
            allowed_extensions = {e.strip() for e in allowed_extensions.split(",")}
        _, ext = os.path.splitext(file_name)
        if ext not in allowed_extensions:
            abort(400, f"File type '{ext}' is not allowed. Permitted: {', '.join(sorted(allowed_extensions))}")

        # Try the new storage router first (uses configured provider for "evidence" role)
        try:
            from app.masri.storage_router import store_file
            folder = f"projects/{self.project_id}"
            tenant_id = self.tenant_id or (self.project.tenant_id if self.project else None)
            result = store_file(
                file_data=file_object,
                file_name=file_name,
                folder=folder,
                role="evidence",
                tenant_id=tenant_id,
            )
            self.file_name = file_name
            self.file_provider = result.get("provider", "local")
            db.session.commit()
            return True
        except Exception as e:
            # Fall back to legacy FileStorageHandler
            import logging
            logging.getLogger(__name__).debug("Storage router failed, using legacy handler: %s", e)

        # Legacy path — direct FileStorageHandler
        if not provider:
            provider = current_app.config["STORAGE_METHOD"]

        if provider not in current_app.config["STORAGE_PROVIDERS"]:
            abort(500, "Invalid storage provider")

        self.file_name = file_name
        self.file_provider = provider

        if not self.project.tenant.can_save_file_in_folder(provider=provider):
            abort(400, "Tenant has exceeded storage limits")

        file_handler = FileStorageHandler(provider=provider)
        try:
            does_file_exist = file_handler.get_file(
                path=os.path.join(
                    self.project.get_evidence_folder(provider=self.file_provider),
                    file_name,
                )
            )
        except FileDoesNotExist:
            does_file_exist = False

        if does_file_exist:
            abort(422, f"File already exists with the name: {file_name}")

        if provider == "local":
            self.project.create_evidence_folder()

        upload_params = {
            "file": file_object,
            "file_name": file_name,
            "folder": self.project.tenant.get_evidence_folder(
                project_id=self.project_id, provider=provider
            ),
        }
        result = file_handler.upload_file(**upload_params)
        if result is False:
            self.file_name = None
            self.file_provider = None
            db.session.commit()
            abort(500, "Unable to upload file")
        return True



class EvidenceAssociation(db.Model):
    __tablename__ = "evidence_association"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    control_id = db.Column(
        db.String(), db.ForeignKey("project_subcontrols.id", ondelete="CASCADE")
    )
    evidence_id = db.Column(
        db.String(), db.ForeignKey("project_evidence.id", ondelete="CASCADE")
    )
    requirement_slot = db.Column(db.String, nullable=True)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    @staticmethod
    def exists(control_id, evidence_id):
        return db.session.execute(
            db.select(EvidenceAssociation).filter(
                EvidenceAssociation.control_id == control_id
            )
            .filter(EvidenceAssociation.evidence_id == evidence_id)
        ).scalars().first()

    @staticmethod
    def add(control_ids, evidence_id, commit=True):
        if not isinstance(control_ids, list):
            control_ids = [control_ids]

        for control_id in control_ids:
            if not EvidenceAssociation.exists(control_id, evidence_id):
                evidence = EvidenceAssociation(
                    control_id=control_id, evidence_id=evidence_id
                )
                db.session.add(evidence)
        if commit:
            db.session.commit()
        return True

    @staticmethod
    def remove(control_ids, evidence_id, commit=True):
        if not isinstance(control_ids, list):
            control_ids = [control_ids]

        for control_id in control_ids:
            assoc = EvidenceAssociation.exists(control_id, evidence_id)
            if assoc:
                db.session.delete(assoc)
        if commit:
            db.session.commit()
        return True



class ProjectMember(db.Model):
    __tablename__ = "project_members"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    user_id = db.Column(db.String(), db.ForeignKey("users.id", ondelete="CASCADE"))
    project_id = db.Column(
        db.String(), db.ForeignKey("projects.id", ondelete="CASCADE")
    )
    access_level = db.Column(db.String(), nullable=False, default="viewer")
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    VALID_ACCESS_LEVELS = ["manager", "contributor", "viewer", "auditor"]

    def user(self):
        return db.session.get(User, self.user_id)



class CompletionHistory(db.Model):
    __tablename__ = "completion_history"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    value = db.Column(db.Integer, nullable=False)
    project_id = db.Column(db.String, db.ForeignKey("projects.id"), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)



class Project(db.Model, DateMixin):
    __tablename__ = "projects"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    name = db.Column(db.String(), nullable=False)
    description = db.Column(db.String())
    last_completion_update = db.Column(db.DateTime)
    controls = db.relationship(
        "ProjectControl",
        backref="project",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    policies = db.relationship(
        "ProjectPolicy", backref="project", lazy="dynamic", cascade="all, delete-orphan"
    )
    evidence = db.relationship(
        "ProjectEvidence",
        backref="project",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    format = db.Column(db.String(), default="default")  # ["default", "simple"]
    show_driver = db.Column(db.Boolean(), default=True)
    """
    permission toggles for project
    """
    auditor_enabled = db.Column(db.Boolean(), default=True)
    can_auditor_read_scratchpad = db.Column(db.Boolean(), default=True)
    can_auditor_write_scratchpad = db.Column(db.Boolean(), default=False)
    can_auditor_read_comments = db.Column(db.Boolean(), default=True)
    can_auditor_write_comments = db.Column(db.Boolean(), default=True)
    policies_require_cc = db.Column(db.Boolean(), default=True)

    """
    framework specific fields
    """
    # CMMC
    target_level = db.Column(db.Integer, default=1)

    # HIPAA
    tags = db.relationship(
        "Tag",
        secondary="project_tags",
        lazy="dynamic",
        backref=db.backref("projects", lazy="dynamic"),
    )
    comments = db.relationship(
        "ProjectComment",
        backref="project",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    completion_history = db.relationship(
        "CompletionHistory",
        backref="project",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    notes = db.Column(db.String())
    members = db.relationship(
        "ProjectMember", backref="project", lazy="dynamic", cascade="all, delete-orphan"
    )
    findings = db.relationship(
        "Finding", backref="project", lazy="dynamic", cascade="all, delete-orphan"
    )
    risks = db.relationship(
        "RiskRegister", backref="project", lazy="dynamic", cascade="all, delete-orphan"
    )
    owner_id = db.Column(db.String(), db.ForeignKey("users.id"), nullable=False)
    tenant_id = db.Column(db.String, db.ForeignKey("tenants.id"), nullable=False)
    framework_id = db.Column(db.String, db.ForeignKey("frameworks.id"))
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def as_dict(self, with_summary=False, with_controls=False, exclude_timely=False):
        # TODO - refactor
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data["owner"] = self.user.email
        data["tenant"] = self.tenant.name
        data["auditors"] = [
            {"id": user.id, "email": user.email} for user in self.get_auditors()
        ]
        data["members"] = [
            {"id": member.user().id, "email": member.user().email}
            for member in self.members.all()
        ]
        if self.framework:
            data["framework"] = self.framework.name

        if with_summary:
            summary = self._fast_summary()
            data["completion_progress"] = summary["completion_progress"]
            data["total_controls"] = summary["total_controls"]
            data["applicable_controls"] = summary["applicable_controls"]
            data["total_policies"] = summary["total_policies"]
            data["total_risks"] = summary["total_risks"]

            if with_controls:
                controls = self.controls.all()
                data["controls"] = [control.as_dict() for control in controls]

            # Policy acceptance progress
            policy_stats = summary["policy_stats"]
            data["policy_progress"] = policy_stats["progress"]
            data["policies_accepted"] = policy_stats["accepted"]
            data["policies_current"] = policy_stats["current"]
            data["policies_expired"] = policy_stats["expired"]

            # Status factors in both control completion and policy acceptance
            data["status"] = "not started"
            if data["completion_progress"] > 0 or policy_stats["accepted"] > 0:
                data["status"] = "in progress"
            if data["completion_progress"] == 100 and policy_stats["progress"] == 100:
                data["status"] = "complete"

            if not exclude_timely:
                data["implemented_progress"] = summary["implemented_progress"]
                data["evidence_progress"] = summary["evidence_progress"]
                data["review_summary"] = self.review_summary()

        return data

    def generate_last_30_days(self):
        data_list = self.completion_history.order_by(
            CompletionHistory.date_added.desc()
        ).all()
        if not data_list:
            return []

        # Convert input data_list into a dictionary for easier lookup
        data_by_date = {
            arrow.get(item.date_added).date(): item.value for item in data_list
        }

        last_date = arrow.get(data_list[0].date_added).date()
        start_date = arrow.get(last_date).shift(days=-29).date()

        # Initialize the result list
        result = []
        last_valid_value = 0  # Default value if no prior data exists

        # Iterate from start_date to last_date
        for single_date in arrow.Arrow.range(
            "day", arrow.get(start_date), arrow.get(last_date)
        ):
            current_date = single_date.date()

            if current_date in data_by_date:
                # Use the value from the data_list if the date exists
                last_valid_value = data_by_date[current_date]
                result.append(
                    {
                        "date": current_date.strftime("%m/%d/%Y"),
                        "value": last_valid_value,
                    }
                )
            else:
                # Copy the last valid value if available
                result.append(
                    {
                        "date": current_date.strftime("%m/%d/%Y"),
                        "value": last_valid_value,
                    }
                )

        return result

    def add_custom_control(self, control):
        """
        See Control.create for data format
        """
        if not isinstance(control, dict):
            abort(400, "Control must be a dictionary")
        control["ref_code"] = f"cu-{secrets.token_hex(3)}"
        data = {"framework": "custom", "controls": [control]}
        control = Control.create(data, tenant_id=self.tenant_id)
        if not control:
            abort(400, "Failed to create control")
        # Control.create returns a list of controls
        project_control = self.add_control(control[0])
        return project_control

    def ready_for_completion_update(self):
        if not self.last_completion_update:
            return True

        time_difference = arrow.now() - arrow.get(self.last_completion_update)

        return time_difference.days >= 1

    def create_tag(self, name):
        tag = Tag.add(name, tenant_id=self.tenant_id)
        project_tag = ProjectTags(tag_id=tag.id, project_id=self.id)
        db.session.add(project_tag)
        db.session.commit()
        return tag

    def add_completion_metric(self, completion=None):
        if completion is None:
            completion = self.completion_progress()
        history = CompletionHistory(value=completion)
        self.completion_history.append(history)
        self.last_completion_update = arrow.utcnow().format()
        db.session.commit()

    def get_evidence_folder(self, provider="local"):
        return self.tenant.get_evidence_folder(project_id=self.id, provider=provider)

    def create_evidence_folder(self):
        return self.tenant.create_evidence_folder(project_id=self.id)

    def create_evidence(
        self,
        name,
        owner_id,
        description=None,
        content=None,
        group=None,
        collected_on=None,
        file=None,
        associate_with=[],
    ):
        """
        Create evidence for a project

        Args:
            name: Name of the evidence
            owner_id: ID of the user who owns the evidence
            description: Description of the evidence
            content: Content, typically JSON/CSV results that represents the evidence
            group: Logically group the evidence for filtering
            collected_on: Date at which it is collected
            file: FileStorage file
            associate_with: List of control IDs to associate the evidence with

        Returns:
            evidence object
        """
        if file is not None and not isinstance(file, FileStorage):
            abort(500, "File must be type FileStorage")

        if self.evidence.filter(ProjectEvidence.name == name).first():
            abort(422, f"Evidence already exists with name:{name}")

        evidence = ProjectEvidence(
            name=name,
            description=description,
            content=content,
            group=group,
            collected_on=collected_on,
            owner_id=owner_id,
            tenant_id=self.tenant_id,
        )
        self.evidence.append(evidence)
        db.session.commit()
        if file:
            evidence.save_file(file_object=file, file_name=file.filename)

        if associate_with:
            evidence.associate_with_controls(associate_with)
        return evidence

    def create_risk(
        self, title, description, status="new", priority="unknown", risk="unknown"
    ):
        risk = RiskRegister(
            title=title,
            description=description,
            status=status,
            priority=priority,
            risk=risk,
            project_id=self.id,
            tenant_id=self.tenant_id,
        )
        db.session.add(risk)
        db.session.commit()
        return risk

    def review_summary(self):
        data = {"total": 0}
        for record in db.session.execute(
            db.select(
                ProjectControl.review_status,
                func.count(ProjectControl.review_status),
            )
            .group_by(ProjectControl.review_status)
            .filter(ProjectControl.project_id == self.id)
        ).all():
            data[record[0]] = record[1]
            data["total"] += record[1]
        return data

    def get_auditors(self):
        auditors = []
        for member in self.members.filter(
            ProjectMember.access_level == "auditor"
        ).all():
            auditors.append(member.user())
        return auditors

    def has_auditor(self, user):
        return self.has_member_with_access(user, "auditor")

    def add_member(self, user, access_level="viewer"):
        if self.has_member(user):
            return True
        db.session.add(
            ProjectMember(
                user_id=user.id, access_level=access_level, project_id=self.id
            )
        )
        db.session.commit()
        return True

    def remove_member(self, user):
        if not self.has_member(user):
            return True
        self.members.filter(ProjectMember.user_id == user.id).delete()
        db.session.commit()
        return True

    def has_member(self, user_or_email):
        if not (user := User.email_to_object(user_or_email)):
            return False
        if result := self.members.filter(ProjectMember.user_id == user.id).first():
            return result
        return False

    def has_member_with_access(self, user_or_email, access):
        if not (user := User.email_to_object(user_or_email)):
            return False
        if not isinstance(access, list):
            access = [access]
        if result := self.members.filter(ProjectMember.user_id == user.id).first():
            if result.access_level in access:
                return True
        return False

    def update_member_access(self, user_id, access_level):
        if member := self.members.filter(ProjectMember.user_id == user_id).first():
            if access_level not in ProjectMember.VALID_ACCESS_LEVELS:
                return False
            member.access_level = access_level
            db.session.commit()
            return True
        return False

    def get_applicable_control_count(self):
        # SA 2.0: use db.session.execute + db.select
        subq = (
            db.select(ProjectControl.id)
            .join(
                ProjectSubControl,
                ProjectControl.id == ProjectSubControl.project_control_id,
            )
            .where(
                ProjectControl.project_id == self.id,
                ProjectSubControl.is_applicable == True,
            )
            .group_by(ProjectControl.id)
            .having(
                func.count(ProjectSubControl.id)
                == func.sum(
                    case((ProjectSubControl.is_applicable == True, 1), else_=0)
                )
            )
            .subquery()
        )
        applicable_controls_count = db.session.execute(
            db.select(func.count()).select_from(subq)
        ).scalar() or 0
        _ = applicable_controls_count  # assigned below
        return applicable_controls_count

    def evidence_groupings(self):
        """Group evidence by evidence id across every subcontrol in the project.

        Returns a dict keyed by evidence id, each value is a summary of
        the evidence (id, name) with a ``count`` of subcontrols it is
        linked to. Used by the ``/evidence/controls`` endpoint.
        """
        data = {}
        for pc in self.controls.all():
            for sub in pc.subcontrols:
                for evidence in sub.evidence:
                    if evidence.id not in data:
                        data[evidence.id] = {
                            "id": evidence.id,
                            "name": evidence.name,
                            "count": 1,
                        }
                    else:
                        data[evidence.id]["count"] += 1
        return data

    def _fast_summary(self):
        """Compute project summary stats with bulk SQL — avoids N+1 queries.

        Returns dict with: completion_progress, implemented_progress,
        evidence_progress, applicable_controls, total_controls,
        total_policies, total_risks, policy_stats.
        """

        # ── 1. Per-control aggregate in ONE query ──
        # For each control: count applicable subs, sum implemented, avg completion
        sub_stats = (
            db.session.execute(
                db.select(
                    ProjectSubControl.project_control_id,
                    func.count(ProjectSubControl.id).label("total_subs"),
                    func.sum(
                        case((ProjectSubControl.is_applicable == True, 1), else_=0)
                    ).label("applicable_subs"),
                    func.sum(
                        case(
                            (ProjectSubControl.is_applicable == True, ProjectSubControl.implemented),
                            else_=0,
                        )
                    ).label("impl_sum"),
                )
                .join(ProjectControl, ProjectControl.id == ProjectSubControl.project_control_id)
                .where(ProjectControl.project_id == self.id)
                .group_by(ProjectSubControl.project_control_id)
            ).all()
        )

        # ── 2. Subcontrol IDs that have evidence ──
        subs_with_evidence = set()
        ev_rows = db.session.execute(
            db.select(distinct(EvidenceAssociation.control_id))
            .join(ProjectSubControl, ProjectSubControl.id == EvidenceAssociation.control_id)
            .join(ProjectControl, ProjectControl.id == ProjectSubControl.project_control_id)
            .where(
                ProjectControl.project_id == self.id,
                ProjectSubControl.is_applicable == True,
            )
        ).all()
        for row in ev_rows:
            subs_with_evidence.add(row[0])

        # ── 3. All applicable subcontrol IDs (for evidence % calc) ──
        applicable_sub_rows = db.session.execute(
            db.select(ProjectSubControl.id, ProjectSubControl.project_control_id, ProjectSubControl.implemented)
            .join(ProjectControl, ProjectControl.id == ProjectSubControl.project_control_id)
            .where(
                ProjectControl.project_id == self.id,
                ProjectSubControl.is_applicable == True,
            )
        ).all()

        # Build per-control evidence counts
        evidence_by_control = {}
        applicable_by_control = {}
        for sub_id, ctrl_id, impl in applicable_sub_rows:
            applicable_by_control.setdefault(ctrl_id, 0)
            applicable_by_control[ctrl_id] += 1
            if sub_id in subs_with_evidence:
                evidence_by_control.setdefault(ctrl_id, 0)
                evidence_by_control[ctrl_id] += 1

        # ── 4. Compute per-control completion (matching mixin logic) ──
        total_controls = len(sub_stats)
        applicable_controls = 0
        completion_total = 0.0
        implemented_total = 0.0
        evidence_total = 0.0

        for ctrl_id, total_subs, applicable_subs, impl_sum in sub_stats:
            if not applicable_subs:
                continue
            applicable_controls += 1

            # Implemented progress = avg implemented across applicable subs
            avg_impl = (impl_sum or 0) / applicable_subs
            implemented_total += avg_impl

            # Evidence progress = % of applicable subs with evidence
            ev_count = evidence_by_control.get(ctrl_id, 0)
            if applicable_subs:
                ev_pct = (ev_count / applicable_subs) * 100
            else:
                ev_pct = 0
            evidence_total += ev_pct

            # Completion progress per subcontrol (matching get_completion_progress):
            # For each applicable sub: base = implemented, reduce by 25% if no evidence,
            # but at least 25 if has evidence.
            # Approximate with aggregate: use per-sub detail from applicable_sub_rows
            ctrl_completion = 0.0
            ctrl_applicable = 0
            for sub_id, sc_ctrl_id, sub_impl in applicable_sub_rows:
                if sc_ctrl_id != ctrl_id:
                    continue
                ctrl_applicable += 1
                has_ev = sub_id in subs_with_evidence
                impl_val = sub_impl or 0
                if has_ev:
                    sub_progress = max(impl_val, 25.0)
                else:
                    sub_progress = impl_val * 0.75
                ctrl_completion += sub_progress
            if ctrl_applicable:
                completion_total += round(ctrl_completion / ctrl_applicable, 0)

        # ── 5. Policy acceptance (bulk) ──
        policies = self.policies.all()
        total_policies = len(policies)
        policy_accepted = 0
        policy_current = 0
        policy_expired = 0
        if total_policies:
            # Batch-load published versions
            policy_ids = [p.id for p in policies]
            published_versions = {}
            if policy_ids:
                pv_rows = db.session.execute(
                    db.select(PolicyVersion.policy_id, PolicyVersion.date_updated, PolicyVersion.date_added)
                    .where(
                        PolicyVersion.policy_id.in_(policy_ids),
                        PolicyVersion.published == True,
                    )
                ).all()
                for pv_pid, pv_updated, pv_added in pv_rows:
                    published_versions[pv_pid] = pv_updated or pv_added
            now = datetime.utcnow()
            for policy in policies:
                accepted_dt = published_versions.get(policy.id)
                if accepted_dt:
                    policy_accepted += 1
                    if (now - accepted_dt).days <= 365:
                        policy_current += 1
                    else:
                        policy_expired += 1
        # When the project has no policies at all, "100%" is misleading (it's
        # zero-of-zero). Report 0 so the UI can show an empty/encouraging state
        # instead of a full green bar.
        policy_progress = round((policy_current / total_policies) * 100, 0) if total_policies else 0

        # ── 6. Counts ──
        total_risks = db.session.execute(
            db.select(func.count(RiskRegister.id)).where(RiskRegister.project_id == self.id)
        ).scalar() or 0

        return {
            "total_controls": total_controls,
            "applicable_controls": applicable_controls,
            # Same principle for completion: a project with zero applicable
            # controls isn't "complete" — it's uninitialised.
            "completion_progress": round(completion_total / applicable_controls, 0) if applicable_controls else 0,
            "implemented_progress": round(implemented_total / applicable_controls, 0) if applicable_controls else 0,
            "evidence_progress": round(evidence_total / applicable_controls, 0) if applicable_controls else 0,
            "total_policies": total_policies,
            "total_risks": total_risks,
            "policy_stats": {
                "total": total_policies,
                "accepted": policy_accepted,
                "current": policy_current,
                "expired": policy_expired,
                "progress": policy_progress,
            },
        }

    def completion_progress(self, controls=None, default=100):
        total = 0
        applicable_count = 0
        if controls is None:
            controls = self.controls.all()
        for control in controls:
            if control.is_applicable():
                total += control.completed_progress()
                applicable_count += 1
        if not applicable_count:
            return default
        return round((total / applicable_count), 0)

    def evidence_progress(self, controls=None):
        total = 0
        applicable_count = 0
        if controls is None:
            controls = self.controls.all()
        if not controls:
            return total
        for control in controls:
            if control.is_applicable():
                total += control.progress("with_evidence")
                applicable_count += 1
        if not applicable_count:
            return 0
        return round((total / applicable_count), 0)

    def implemented_progress(self, controls=None):
        total = 0
        applicable_count = 0
        if not controls:
            controls = self.controls.all()
        if not controls:
            return total
        for control in controls:
            if control.is_applicable():
                total += control.implemented_progress()
                applicable_count += 1
        if not applicable_count:
            return 0
        return round((total / applicable_count), 0)

    def policy_acceptance_summary(self):
        """Returns policy acceptance stats: total, accepted, current (within 12 months), expired."""
        policies = self.policies.all()
        total = len(policies)
        if not total:
            return {"total": 0, "accepted": 0, "current": 0, "expired": 0, "progress": 100}
        accepted = 0
        current = 0
        expired = 0
        now = datetime.utcnow()
        for policy in policies:
            published = policy.get_published_version()
            if published:
                accepted += 1
                accepted_dt = published.date_updated or published.date_added
                if accepted_dt and (now - accepted_dt).days <= 365:
                    current += 1
                else:
                    expired += 1
        progress = round((current / total) * 100, 0) if total else 100
        return {"total": total, "accepted": accepted, "current": current, "expired": expired, "progress": progress}

    def has_control(self, control_id):
        return self.controls.filter(ProjectControl.control_id == control_id).first()

    def has_policy(self, name):
        return self.policies.filter(ProjectPolicy.name == name).first()

    def add_control(self, control, commit=True):
        if not control:
            return False
        if self.has_control(control.id):
            return control
        project_control = ProjectControl(control_id=control.id)
        for sub in control.subcontrols.all():
            control_sub = ProjectSubControl(subcontrol_id=sub.id, project_id=self.id)
            project_control.subcontrols.append(control_sub)
            # Add tasks (e.g. AuditorFeedback)
            if sub.tasks:
                for task in sub.tasks:
                    control_sub.feedback.append(
                        AuditorFeedback(
                            title=task.get("title"),
                            description=task.get("description"),
                            owner_id=self.owner_id,
                        )
                    )

        self.controls.append(project_control)
        if commit:
            db.session.commit()
        return project_control

    def create_policy(self, name, description, template=None):
        policy = ProjectPolicy(name=name, description=description)

        self.policies.append(policy)
        db.session.commit()

        if template:
            if policy_template := (
                self.tenant.policies.filter(
                    func.lower(Policy.name) == func.lower(template)
                ).first()
            ):
                policy.add_version(policy_template.content)

        return policy

    def remove_policy(self, id):
        policy = self.policies.filter_by(id=id).first_or_404()
        db.session.execute(db.delete(PolicyVersion).where(PolicyVersion.policy_id == policy.id))
        db.session.execute(db.delete(ProjectPolicyAssociation).where(ProjectPolicyAssociation.policy_id == policy.id))
        db.session.delete(policy)
        db.session.commit()
        return True

    def remove_control(self, id):
        if control := self.controls.filter(ProjectControl.id == id).first():
            db.session.delete(control)
            db.session.commit()
        return True



class ProjectPolicyAssociation(db.Model):
    __tablename__ = "project_policy_associations"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    policy_id = db.Column(
        db.String(), db.ForeignKey("project_policies.id", ondelete="CASCADE")
    )
    control_id = db.Column(
        db.String(), db.ForeignKey("project_controls.id", ondelete="CASCADE")
    )
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)



class ProjectControl(db.Model, ControlMixin):
    __tablename__ = "project_controls"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    notes = db.Column(EncryptedText)
    auditor_notes = db.Column(EncryptedText)
    evidence_requirements = db.Column(db.JSON(), default={})
    review_status = db.Column(db.String(), default="infosec action")
    comments = db.relationship(
        "ControlComment",
        backref="control",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    tags = db.relationship(
        "Tag",
        secondary="control_tags",
        lazy="select",
        backref=db.backref("project_controls", lazy="dynamic"),
    )
    feedback = db.relationship(
        "AuditorFeedback",
        backref="control",
        lazy="select",
        cascade="all, delete-orphan",
    )
    subcontrols = db.relationship(
        "ProjectSubControl",
        backref="p_control",
        lazy="select",
        cascade="all, delete-orphan",
    )
    project_id = db.Column(db.String, db.ForeignKey("projects.id"), nullable=False)
    control_id = db.Column(db.String, db.ForeignKey("controls.id"), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    VALID_REVIEW_STATUS = ["infosec action", "ready for auditor", "complete"]

    def set_as_applicable(self):
        for subcontrol in self.subcontrols:
            subcontrol.is_applicable = True
        db.session.commit()

    def set_as_not_applicable(self):
        for subcontrol in self.subcontrols:
            subcontrol.is_applicable = False
        db.session.commit()

    def set_assignee(self, assignee_id):
        for subcontrol in self.subcontrols:
            subcontrol.owner_id = assignee_id
        db.session.commit()

    def add_tag(self, tag_name):
        if self.has_tag(tag_name):
            return True

        if not (tag := Tag.find_by_name(tag_name, self.project.tenant_id)):
            tag = Tag.add(tag_name.lower(), tenant_id=self.project.tenant_id)

        control_tag = ControlTags(control_id=self.id, tag_id=tag.id)
        db.session.add(control_tag)
        db.session.commit()
        return tag

    def remove_tag(self, tag_name):
        if tag := self.has_tag(tag_name):
            self.tags.remove(tag)
            db.session.commit()
        return True

    def has_tag(self, tag_name):
        has_tag = next(
            (i for i in self.tags if i.name.lower() == tag_name.lower()), False
        )
        return has_tag

    def set_tags(self, tag_names):
        db.session.execute(db.delete(ControlTags).where(ControlTags.control_id == self.id))
        db.session.commit()
        # Add new tags
        for tag_name in tag_names:
            self.add_tag(tag_name)
        return True

    def create_feedback(
        self,
        title,
        owner_id,
        description=None,
        is_complete=None,
        response=None,
        relates_to=None,
    ):
        feedback = AuditorFeedback(title=title, owner_id=owner_id)
        if description:
            feedback.description = description
        if response:
            feedback.response = response
        if is_complete is not None:
            feedback.is_complete = is_complete
        if relates_to and isinstance(relates_to, int):
            if any(s.id == relates_to for s in self.subcontrols):
                feedback.relates_to = relates_to

        self.feedback.append(feedback)
        db.session.commit()
        return feedback

    def update_feedback(
        self,
        feedback_id,
        title=None,
        description=None,
        is_complete=None,
        response=None,
        relates_to=None,
    ):
        feedback = next((f for f in self.feedback if f.id == feedback_id), None)
        if not feedback:
            abort(422, f"Feedback:{feedback_id} not found")
        if title:
            feedback.title = title
        if description:
            feedback.description = description
        if response:
            feedback.response = response
        if is_complete is not None:
            feedback.is_complete = is_complete
        if relates_to and isinstance(relates_to, int):
            if any(s.id == relates_to for s in self.subcontrols):
                feedback.relates_to = relates_to
        db.session.commit()
        return feedback



class ProjectSubControl(db.Model, SubControlMixin):
    __tablename__ = "project_subcontrols"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    sort_id = db.Column(
        db.Integer,
        default=lambda: secrets.randbelow(1000),
    )
    implemented = db.Column(db.Integer(), default=0)
    is_applicable = db.Column(db.Boolean(), default=True)
    context = db.Column(EncryptedText)
    notes = db.Column(EncryptedText)
    verified_at = db.Column(db.DateTime, nullable=True)
    verified_by_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=True)
    verification_note = db.Column(db.Text, nullable=True)
    """
    framework specific fields
    """
    # SOC2
    auditor_feedback = db.Column(EncryptedText)
    # CMMC
    process_maturity = db.Column(db.Integer(), default=0)

    """
    may have multiple evidence items for each control
    """
    evidence = db.relationship(
        "ProjectEvidence",
        secondary="evidence_association",
        lazy="select",
        backref=db.backref("project_subcontrols", lazy="dynamic"),
    )
    comments = db.relationship(
        "SubControlComment",
        backref="subcontrol",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    operator_id = db.Column(db.String(), db.ForeignKey("users.id"))
    owner_id = db.Column(db.String(), db.ForeignKey("users.id"))
    subcontrol_id = db.Column(
        db.String, db.ForeignKey("subcontrols.id"), nullable=False
    )
    project_control_id = db.Column(
        db.String, db.ForeignKey("project_controls.id"), nullable=False
    )
    project_id = db.Column(db.String, db.ForeignKey("projects.id"), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    @property
    def project(self):
        return db.session.get(Project, self.project_id)

    def associate_with_evidence(self, evidence_id):
        if isinstance(evidence_id, str):
            evidence_id = [evidence_id]

        for record in evidence_id:
            EvidenceAssociation.add(self.id, record)
        return True

    def disassociate_with_evidence(self, evidence_id):
        if isinstance(evidence_id, str):
            evidence_id = [evidence_id]

        for record in evidence_id:
            EvidenceAssociation.remove(self.id, record)
        return True

    def update(
        self,
        applicable=None,
        implemented=None,
        notes=None,
        context=None,
        evidence=None,
        owner_id=None,
    ):
        """
        Update subcontrol for a project

        Args:

        Returns:
            subcontrol object
        """
        if applicable is not None:
            self.is_applicable = applicable
        if implemented is not None:
            self.implemented = implemented
        if notes is not None:
            self.notes = notes
        if context is not None:
            self.context = context
        if evidence:
            self.associate_with_evidence(evidence)

        if owner_id:
            self.owner_id = owner_id

        db.session.commit()
        return self



class AiSuggestion(db.Model, QueryMixin):
    __tablename__ = "ai_suggestions"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    project_id = db.Column(db.String, db.ForeignKey("projects.id"), nullable=False)
    subject_type = db.Column(db.String, nullable=False)
    subject_id = db.Column(db.String, nullable=False)
    kind = db.Column(db.String, nullable=False)
    payload = db.Column(db.JSON, nullable=False)
    confidence = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    dismissed_at = db.Column(db.DateTime, nullable=True)
    accepted_at = db.Column(db.DateTime, nullable=True)
    reviewed_by_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=True)
