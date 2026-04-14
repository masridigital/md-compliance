"""app.models.config — Config domain models."""

from app import db
from flask import current_app
from sqlalchemy import func
from datetime import datetime
import shortuuid
import secrets
import arrow
import logging


class ConfigStore(db.Model):
    __tablename__ = "config_store"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    key = db.Column(db.String())
    value = db.Column(db.String())
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def as_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

    @staticmethod
    def find(key):
        return db.session.execute(db.select(ConfigStore).filter(ConfigStore.key == key)).scalars().first()

    @staticmethod
    def upsert(key, value):
        found = ConfigStore.find(key)
        if found:
            found.value = value
            db.session.commit()
        else:
            c = ConfigStore(key=key, value=value)
            db.session.add(c)
            db.session.commit()
        return True



class Logs(db.Model):
    __tablename__ = "logs"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    namespace = db.Column(db.String(), nullable=False, default="general")
    level = db.Column(db.String(), nullable=False, default="info")
    action = db.Column(db.String(), default="get")
    message = db.Column(db.String(), nullable=False)
    success = db.Column(db.Boolean(), default=True)
    meta = db.Column(db.JSON(), default={})
    user_id = db.Column(db.String(), db.ForeignKey("users.id"), nullable=True)
    tenant_id = db.Column(db.String(), db.ForeignKey("tenants.id"), nullable=True)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    """
    """

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        if self.user_id:
            _user = db.session.get(User, self.user_id)
            data["user_email"] = _user.email if _user else "(deleted)"
        if self.tenant_id:
            _tenant = db.session.get(Tenant, self.tenant_id)
            data["tenant_name"] = _tenant.name if _tenant else "(deleted)"
        return data

    def as_readable(self):
        formatted_date = arrow.get(self.date_added).format("YYYY-MM-DD HH:mm:ss")
        user_str = f"User:{self.user_id}" if self.user_id else "User:N/A"
        tenant_str = f"Tenant:{self.tenant_id}" if self.tenant_id else "Tenant:N/A"
        level_str = f"{self.level.upper()}"
        action_str = f"Action:{self.action.upper()}"
        success_str = f"Success:{'Yes' if self.success else 'No'}"
        return f"[{formatted_date} - {level_str}] | {tenant_str} | {user_str} | {action_str} | {success_str} | {self.message}"

    @staticmethod
    def add_system_log(**kwargs):
        """
        Add system log - system logs are not necessarily tied to a tenant

        Logs.add_system_log(message="testing", level="error", action="put")
        """
        return Logs.add(namespace="system", **kwargs)

    @staticmethod
    def get_system_log(**kwargs):
        return Logs.get(namespace="system", **kwargs)

    @staticmethod
    def add(
        message="unknown",
        action="get",
        level="info",
        namespace="general",
        success=True,
        user_id=None,
        tenant_id=None,
        meta={},
        stdout=False,
    ):
        """
        Add log

        Logs.add(message="testing", level="error", action="put")
        """
        if level.lower() not in ["debug", "info", "warning", "error", "critical"]:
            level = "info"
        level = level.upper()
        action = action.upper()
        if meta is None:
            meta = {}
        msg = Logs(
            namespace=namespace.lower(),
            message=message,
            level=level,
            action=action,
            success=success,
            user_id=user_id,
            tenant_id=tenant_id,
            meta=meta,
        )
        db.session.add(msg)
        db.session.commit()
        if stdout:
            getattr(current_app.logger, level.lower())(
                f"Audit: {tenant_id} | {user_id} | {namespace} |  {success} | {action} | {message}"
            )
        return msg

    @staticmethod
    def get(
        id=None,
        message=None,
        action=None,
        namespace=None,
        level=None,
        user_id=None,
        tenant_id=None,
        success=None,
        limit=100,
        as_query=False,
        span=None,
        as_count=False,
        paginate=False,
        page=1,
        meta={},
        as_dict=False,
    ):
        """
        get_logs(level='error', namespace="my_namespace", meta={"key":"value":"key2":"value2"})
        """
        _query = db.select(Logs).order_by(Logs.date_added.desc()).limit(limit)

        if id:
            _query = _query.filter(Logs.id == id)
        if message:
            _query = _query.filter(Logs.message == message)
        if namespace:
            _query = _query.filter(func.lower(Logs.namespace) == func.lower(namespace))
        if action:
            _query = _query.filter(func.lower(Logs.action) == func.lower(action))
        if success is not None:
            _query = _query.filter(Logs.success == success)
        if user_id:
            _query = _query.filter(Logs.user_id == user_id)
        if tenant_id:
            _query = _query.filter(Logs.tenant_id == tenant_id)
        if level:
            if not isinstance(level, list):
                level = [level]
            _query = _query.filter(
                func.lower(Logs.level).in_([lvl.lower() for lvl in level])
            )

        if meta:
            for key, value in meta.items():
                _query = _query.filter(Logs.meta.op("->>")(key) == value)
        if span:
            _query = _query.filter(
                Logs.date_added >= arrow.utcnow().shift(hours=-span).datetime
            )
        if as_query:
            return _query
        if as_count:
            return db.session.execute(db.select(func.count()).select_from(_query.subquery())).scalar()
        if paginate:
            return db.paginate(_query, page=page, per_page=10)
        if as_dict:
            return [log.as_dict() for log in db.session.execute(_query).scalars().all()]
        return db.session.execute(_query).scalars().all()


@login.user_loader
def load_user(user_id):
    return db.session.get(User, user_id)


@listens_for(FormItem.remediation_vendor_agreed, "set")
def before_update_vendor_remediation_listener(target, value, old_value, initiator):
    """
    When remediation_vendor_agreed is set to True, we will update the review_status to complete
    b/c the vendor submitted a remediation plan and agreed to the Gap

    When set to False, we will update the review_status to "pending", so that the InfoSec team
    can review the rejected remediation
    """
    if value is True:
        target.review_status = "complete"
    if value is False:
        target.review_status = "pending"


@listens_for(ProjectSubControl.implemented, "set")
def after_update_project_sub_control_implementation_listener(
    target, value, old_value, initiator
):
    """
    When the implementation of a subcontrol is updated, we are going to calculate the project
    completion so that we can show a progress chart overtime
    """
    project = target.project
    if project.ready_for_completion_update():
        completion = project.completion_progress()
        project.add_completion_metric(completion=completion)


