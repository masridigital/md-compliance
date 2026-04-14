# app/models/__init__.py
# ──────────────────────────────────────────────────────────────────────
# Backwards-compatible re-export layer.
#
# The monolith app/models.py has been split into domain modules under
# this package.  This __init__ re-exports every public name so that
# existing code using ``from app.models import X`` continues to work
# unchanged.
# ──────────────────────────────────────────────────────────────────────

from app import db  # noqa: F401 — many callers do ``from app.models import db``

# ── Domain modules ────────────────────────────────────────────────────
from app.models.vendor import (  # noqa: F401
    Finding, VendorFile, AppHistory, VendorHistory, VendorApp, Vendor,
)
from app.models.tenant import DataClass, Tenant  # noqa: F401
from app.models.framework import (  # noqa: F401
    Framework, Policy, Control, SubControl, PolicyAssociation,
)
from app.models.project import (  # noqa: F401
    ProjectEvidence, EvidenceAssociation, ProjectMember,
    CompletionHistory, Project, ProjectControl, ProjectSubControl,
    ProjectPolicyAssociation,
)
from app.models.policy import (  # noqa: F401
    ProjectPolicy, PolicyVersion, PolicyLabel, PolicyTags,
)
from app.models.risk import RiskRegister, RiskComment, RiskTags  # noqa: F401
from app.models.comments import (  # noqa: F401
    AuditorFeedback, SubControlComment, ControlComment,
    ProjectComment,
)
from app.models.tags import ControlTags, ProjectTags, Tag  # noqa: F401
from app.models.auth import (  # noqa: F401
    Role, TenantMember, TenantMemberRole, UserRole, User,
)
from app.models.assessment import (  # noqa: F401
    Form, AssessmentGuest, FormItemMessage, FormItem,
    FormSection, Assessment,
)
from app.models.config import ConfigStore, Logs  # noqa: F401

# ── Event listeners & login loader ────────────────────────────────────
# These cross model boundaries and live here intentionally.
from app import login
from sqlalchemy.event import listens_for


@login.user_loader
def load_user(user_id):
    return db.session.get(User, user_id)


@listens_for(FormItem.remediation_vendor_agreed, "set")
def before_update_vendor_remediation_listener(target, value, old_value, initiator):
    if value is True:
        target.review_status = "complete"
    if value is False:
        target.review_status = "pending"


@listens_for(ProjectSubControl.implemented, "set")
def after_update_project_sub_control_implementation_listener(
    target, value, old_value, initiator
):
    project = target.project
    if project.ready_for_completion_update():
        completion = project.completion_progress()
        project.add_completion_metric(completion=completion)


# ── Cross-module name injection ───────────────────────────────────────
# In the monolith, all 48 classes shared one namespace. After the split,
# methods that reference classes from other modules (e.g. tenant.py using
# User, Logs) would get NameError. We fix this by injecting cross-module
# names into each module's globals after ALL modules are loaded.
import app.models.vendor as _m_vendor
import app.models.tenant as _m_tenant
import app.models.framework as _m_framework
import app.models.project as _m_project
import app.models.policy as _m_policy
import app.models.risk as _m_risk
import app.models.comments as _m_comments
import app.models.tags as _m_tags
import app.models.auth as _m_auth
import app.models.assessment as _m_assessment
import app.models.config as _m_config

_m_assessment.User = User

_m_auth.Tenant = Tenant

_m_comments.User = User

_m_config.User = User
_m_config.Tenant = Tenant

_m_policy.User = User
_m_policy.Policy = Policy
_m_policy.ProjectPolicyAssociation = ProjectPolicyAssociation

_m_project.User = User
_m_project.Control = Control
_m_project.Policy = Policy
_m_project.RiskRegister = RiskRegister
_m_project.Tag = Tag
_m_project.ProjectTags = ProjectTags
_m_project.ControlTags = ControlTags
_m_project.ProjectPolicy = ProjectPolicy
_m_project.PolicyVersion = PolicyVersion
_m_project.AuditorFeedback = AuditorFeedback
_m_project.Tenant = Tenant

_m_risk.User = User
_m_risk.Project = Project
_m_risk.Vendor = Vendor
_m_risk.Tag = Tag

_m_tenant.User = User
_m_tenant.TenantMember = TenantMember
_m_tenant.Role = Role
_m_tenant.Logs = Logs
_m_tenant.Framework = Framework
_m_tenant.Control = Control
_m_tenant.Policy = Policy
_m_tenant.Form = Form
_m_tenant.FormSection = FormSection
_m_tenant.FormItem = FormItem
_m_tenant.AssessmentGuest = AssessmentGuest
_m_tenant.Project = Project
_m_tenant.ProjectEvidence = ProjectEvidence
_m_tenant.ProjectMember = ProjectMember
_m_tenant.RiskRegister = RiskRegister
_m_tenant.Vendor = Vendor
_m_tenant.Tag = Tag

_m_vendor.Assessment = Assessment
_m_vendor.Form = Form
