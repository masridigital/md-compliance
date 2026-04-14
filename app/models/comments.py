"""app.models.comments — Comments domain models."""

from app import db
from app.masri.settings_service import EncryptedText
from datetime import datetime
import shortuuid
import secrets


class AuditorFeedback(db.Model):
    __tablename__ = "auditor_feedback"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    title = db.Column(db.String())
    description = db.Column(db.String())
    response = db.Column(db.String())
    is_complete = db.Column(db.Boolean(), default=False)
    owner_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    control_id = db.Column(
        db.String, db.ForeignKey("project_controls.id"), nullable=False
    )
    relates_to = db.Column(db.String, db.ForeignKey("project_subcontrols.id"))
    risk_relation = db.Column(db.String, db.ForeignKey("risk_register.id"))
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        _owner = db.session.get(User, self.owner_id)
        data["auditor_email"] = _owner.email if _owner else None
        data["status"] = self.status
        return data

    @property
    def status(self):
        if self.is_complete:
            return "complete"
        if not self.response:
            return "response required from infoSec"
        return "waiting on auditor"

    def create_risk_record(self):
        title = f"[Auditor Feedback]: {self.title}"
        risk = self.control.project.create_risk(
            title=title, description=self.description
        )
        self.risk_relation = risk.id
        db.session.commit()
        return True



class SubControlComment(db.Model):
    __tablename__ = "subcontrol_comments"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    message = db.Column(EncryptedText)
    owner_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    subcontrol_id = db.Column(
        db.String, db.ForeignKey("project_subcontrols.id"), nullable=False
    )
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data["author_email"] = db.session.get(User, self.owner_id).email
        return data



class ControlComment(db.Model):
    __tablename__ = "control_comments"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    message = db.Column(EncryptedText)
    owner_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    control_id = db.Column(
        db.String, db.ForeignKey("project_controls.id"), nullable=False
    )
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data["author_email"] = db.session.get(User, self.owner_id).email
        return data



class ProjectComment(db.Model):
    __tablename__ = "project_comments"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    message = db.Column(EncryptedText)
    owner_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    project_id = db.Column(db.String, db.ForeignKey("projects.id"), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data["author_email"] = db.session.get(User, self.owner_id).email
        return data



