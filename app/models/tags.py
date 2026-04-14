"""app.models.tags — Tags domain models."""

from app import db
from flask import current_app
from datetime import datetime
import shortuuid
import secrets


class ProjectTags(db.Model):
    __tablename__ = "project_tags"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    project_id = db.Column(
        db.String(), db.ForeignKey("projects.id", ondelete="CASCADE")
    )
    tag_id = db.Column(db.String(), db.ForeignKey("tags.id", ondelete="CASCADE"))

    def as_dict(self):
        tag = db.session.get(Tag, self.tag_id)
        return {"name": tag.name, "color": tag.color}



class ControlTags(db.Model):
    __tablename__ = "control_tags"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    control_id = db.Column(
        db.String(), db.ForeignKey("project_controls.id", ondelete="CASCADE")
    )
    tag_id = db.Column(db.String(), db.ForeignKey("tags.id", ondelete="CASCADE"))



class Tag(db.Model):
    __tablename__ = "tags"
    __table_args__ = (db.UniqueConstraint("name", "tenant_id"),)
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    name = db.Column(db.String())
    color = db.Column(db.String(), default="blue")
    tenant_id = db.Column(db.String, db.ForeignKey("tenants.id"), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def as_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

    @staticmethod
    def find_by_name(name, tenant_id):
        tag_exists = db.session.execute(
            db.select(Tag).filter(Tag.tenant_id == tenant_id)
            .filter(func.lower(Tag.name) == func.lower(name))
        ).scalars().first()
        if tag_exists:
            return tag_exists
        return False

    @staticmethod
    def add(tag_name, tenant_id):
        if existing_tag := Tag.find_by_name(tag_name, tenant_id):
            return existing_tag

        tag = Tag(name=tag_name, tenant_id=tenant_id)
        db.session.add(tag)
        db.session.commit()
        return tag



