"""app.models.framework — Framework domain models."""

from app import db
from app.masri.settings_service import EncryptedText
from flask import current_app, abort
from sqlalchemy import func
from datetime import datetime
import shortuuid
import secrets
import json


class PolicyAssociation(db.Model):
    __tablename__ = "policy_associations"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    policy_id = db.Column(db.String(), db.ForeignKey("policies.id", ondelete="CASCADE"))
    control_id = db.Column(
        db.String(), db.ForeignKey("controls.id", ondelete="CASCADE")
    )
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)



class Framework(db.Model):
    __tablename__ = "frameworks"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    name = db.Column(db.String(), nullable=False)
    description = db.Column(db.String(), nullable=False)
    reference_link = db.Column(db.String())
    guidance = db.Column(db.String)
    """framework specific features"""
    feature_evidence = db.Column(db.Boolean(), default=False)
    deprecated = db.Column(db.Boolean(), default=False)
    deprecated_message = db.Column(db.String(), nullable=True)

    controls = db.relationship("Control", backref="framework", lazy="dynamic")
    projects = db.relationship("Project", backref="framework", lazy="dynamic")
    tenant_id = db.Column(db.String, db.ForeignKey("tenants.id"), nullable=True)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data["controls"] = self.controls.count()
        return data

    @staticmethod
    def create(name, tenant, deprecated=False, deprecated_message=None):
        data = {
            "name": name.lower(),
            "description": f"Framework for {name.capitalize()}",
            "feature_evidence": True,
            "tenant_id": tenant.id,
            "deprecated": deprecated,
            "deprecated_message": deprecated_message,
        }
        f = Framework(**data)
        db.session.add(f)
        db.session.commit()
        return True

    @staticmethod
    def find_by_name(name, tenant_id):
        framework_exists = db.session.execute(
            db.select(Framework).filter(Framework.tenant_id == tenant_id)
            .filter(func.lower(Framework.name) == func.lower(name))
        ).scalars().first()
        if framework_exists:
            return framework_exists
        return False

    def get_features(self):
        features = []
        for c in self.__table__.columns:
            if c.startswith("feature_"):
                features.append(c)
        return features

    def has_feature(self, name):
        """
        helper method to check if the framework has a specific feature
        for adding new features, the Framework model must be extended
        with new fields such as feature_something
        """
        if not name.startswith("feature_"):
            raise ValueError("name must start with feature_")
        if not hasattr(self, name):
            return False
        return getattr(self, name)

    def has_controls(self):
        if self.controls.count():
            return True
        return False

    def init_controls(self):
        self.tenant.create_base_controls_for_framework(self.name)



class Policy(db.Model):
    __tablename__ = "policies"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    name = db.Column(db.String(), nullable=False)
    ref_code = db.Column(db.String())
    description = db.Column(db.String())
    content = db.Column(db.String())
    template = db.Column(db.String())
    tenant_id = db.Column(db.String, db.ForeignKey("tenants.id"), nullable=True)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def as_dict(self, include=[]):
        data = {}
        for c in self.__table__.columns:
            if c.name in include or not include:
                data[c.name] = getattr(self, c.name)
        return data

    @staticmethod
    def find_by_name(name, tenant_id):
        policy_exists = db.session.execute(
            db.select(Policy).filter(Policy.tenant_id == tenant_id)
            .filter(func.lower(Policy.name) == func.lower(name))
        ).scalars().first()
        if policy_exists:
            return policy_exists
        return False

    def controls(self, as_id_list=False):
        control_id_list = []
        for assoc in db.session.execute(db.select(PolicyAssociation).filter(
            PolicyAssociation.policy_id == self.id
        )).scalars().all():
            control_id_list.append(assoc.control_id)
        if as_id_list:
            return control_id_list
        return db.session.execute(db.select(Control).filter(Control.id.in_(control_id_list))).scalars().all()

    def has_control(self, id):
        return db.session.execute(
            db.select(PolicyAssociation).filter(PolicyAssociation.policy_id == self.id)
            .filter(PolicyAssociation.control_id == id)
        ).scalars().first()

    def add_control(self, id):
        if not self.has_control(id):
            pa = PolicyAssociation(policy_id=self.id, control_id=id)
            db.session.add(pa)
            db.session.commit()
        return True

    def get_template_variables(self):
        template_vars = {}
        for label in self.tenant.labels.all():
            template_vars[label.key] = label.value
        template_vars["organization"] = self.tenant.name
        return template_vars



class Control(db.Model):
    __tablename__ = "controls"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    name = db.Column(db.String(), nullable=False)
    description = db.Column(db.String())
    ref_code = db.Column(db.String())
    abs_ref_code = db.Column(db.String())
    visible = db.Column(db.Boolean(), default=True)
    system_level = db.Column(db.Boolean(), default=True)
    category = db.Column(db.String())
    subcategory = db.Column(db.String())
    guidance = db.Column(db.String)
    references = db.Column(db.String())
    mapping = db.Column(db.JSON(), default={})
    is_custom = db.Column(db.Boolean(), default=False)
    vendor_recommendations = db.Column(db.JSON(), default={})
    """framework specific fields"""
    # CMMC
    level = db.Column(db.Integer, default=1)

    # ISO27001
    operational_capability = db.Column(db.String())
    control_type = db.Column(db.String())

    # HIPAA
    dti = db.Column(db.String(), default="easy")
    dtc = db.Column(db.String(), default="easy")
    meta = db.Column(db.JSON(), default=dict)
    subcontrols = db.relationship(
        "SubControl", backref="control", lazy="dynamic", cascade="all, delete"
    )
    framework_id = db.Column(db.String, db.ForeignKey("frameworks.id"), nullable=False)
    project_controls = db.relationship(
        "ProjectControl", backref="control", lazy="dynamic", cascade="all, delete"
    )
    tenant_id = db.Column(db.String, db.ForeignKey("tenants.id"), nullable=True)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def as_dict(self, include=[], with_subcontrols=True):
        data = {}
        if with_subcontrols:
            data["subcontrols"] = []
            data["framework"] = self.framework.name
            subcontrols = self.subcontrols.all()
            data["subcontrol_count"] = len(subcontrols)
            for sub in subcontrols:
                data["subcontrols"].append(sub.as_dict())
        for c in self.__table__.columns:
            if c.name in include or not include:
                data[c.name] = getattr(self, c.name)
        return data

    @staticmethod
    def find_by_abs_ref_code(framework, ref_code):
        if not framework or not ref_code:
            raise ValueError("framework and ref_code is required")
        abs_ref_code = f"{framework.lower()}__{ref_code}"
        return db.session.execute(db.select(Control).filter(
            func.lower(Control.abs_ref_code) == func.lower(abs_ref_code)
        )).scalars().first()

    def policies(self, as_id_list=False):
        policy_id_list = []
        for assoc in db.session.execute(db.select(PolicyAssociation).filter(
            PolicyAssociation.control_id == self.id
        )).scalars().all():
            policy_id_list.append(assoc.policy_id)
        if as_id_list:
            return policy_id_list
        return db.session.execute(db.select(Policy).filter(Policy.id.in_(policy_id_list))).scalars().all()

    def in_policy(self, policy_id):
        return policy_id in self.policies(as_id_list=True)

    @staticmethod
    def create(data, tenant_id):
        """
        data = {
            "framework": data.get("framework"),
            "controls": [
                {
                    "name": data.get("name"),
                    "description": data.get("description"),
                    "ref_code": data.get("ref_code"),
                }
            ]
        }
        """
        created_controls = []
        if framework := data.get("framework"):
            if not (f := Framework.find_by_name(framework, tenant_id)):
                f = Framework(
                    name=framework,
                    description=data.get(
                        "framework_description", f"Framework for {framework}"
                    ),
                    tenant_id=tenant_id,
                )
                db.session.add(f)
                db.session.commit()
        else:
            abort(400, "Framework is required")

        # create controls and subcontrols
        for control in data.get("controls", []):
            c = Control(
                name=control.get("name"),
                description=control.get("description"),
                ref_code=control.get("ref_code"),
                abs_ref_code=f"{framework.lower()}__{control.get('ref_code')}",
                system_level=control.get("system_level"),
                category=control.get("category"),
                subcategory=control.get("subcategory"),
                references=control.get("references"),
                level=int(control.get("level", 1)),
                guidance=control.get("guidance"),
                mapping=control.get("mapping"),
                vendor_recommendations=control.get("vendor_recommendations"),
                dti=control.get("dti"),
                dtc=control.get("dtc"),
                meta=control.get("meta", {}),
                tenant_id=tenant_id,
            )
            """
            if there are no subcontrols for the control, we are going to add the
            top-level control itself as the first subcontrol
            """
            subcontrols = control.get("subcontrols", [])
            if not subcontrols:
                subcontrols = [
                    {
                        "name": c.name,
                        "description": c.description,
                        "ref_code": c.ref_code,
                        "mitigation": control.get(
                            "mitigation", "The mitigation has not been documented"
                        ),
                        "guidance": control.get("guidance"),
                        "tasks": control.get("tasks"),
                    }
                ]
            for sub in subcontrols:
                fa = SubControl(
                    name=sub.get("name"),
                    description=sub.get(
                        "description", "The description has not been documented"
                    ),
                    ref_code=sub.get("ref_code", c.ref_code),
                    mitigation=sub.get("mitigation"),
                    guidance=sub.get("guidance"),
                    implementation_group=sub.get("implementation_group"),
                    meta=sub.get("meta", {}),
                    tasks=sub.get("tasks", []),
                )
                c.subcontrols.append(fa)
            f.controls.append(c)
            created_controls.append(c)
        db.session.commit()
        return created_controls



class SubControl(db.Model):
    __tablename__ = "subcontrols"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    name = db.Column(db.String(), nullable=False)
    description = db.Column(db.String())
    ref_code = db.Column(db.String())
    mitigation = db.Column(db.String())
    guidance = db.Column(db.String)
    meta = db.Column(db.JSON(), default={})
    tasks = db.Column(db.JSON(), default={})
    """framework specific fields"""
    # CSC
    implementation_group = db.Column(db.Integer)

    control_id = db.Column(db.String, db.ForeignKey("controls.id"), nullable=False)
    project_subcontrols = db.relationship(
        "ProjectSubControl", backref="subcontrol", lazy="dynamic", cascade="all, delete"
    )
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def as_dict(self, include=[]):
        data = {}
        for c in self.__table__.columns:
            if c.name in include or not include:
                data[c.name] = getattr(self, c.name)
        return data



