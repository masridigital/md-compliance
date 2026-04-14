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
