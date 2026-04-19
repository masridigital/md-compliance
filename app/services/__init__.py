"""
app.services — Service layer for domain mutations.

Introduced in phase E2 (PHASES.md). Each module in this package owns
business logic for one domain aggregate. The goal is to keep Flask
view functions thin: parse request -> call service -> serialise
result. Authorisation still lives in the view via ``Authorizer``; the
services receive already-authorised domain objects.

Conventions
-----------
1. Services accept domain objects, not IDs. The caller (view) has
   already looked up + authorised the object.
2. Services own their ``db.session.commit()`` calls. Views never commit
   directly when delegating to a service.
3. Services return domain objects. Serialisation (``.as_dict()``) is
   done in the view.
4. Services may ``abort(...)`` on domain-invariant violations; views
   catch those naturally via Flask's error handling.
5. No Flask request/response objects in services. Only ``abort`` for
   HTTP error escalation is allowed.

Currently exported service modules:

- :mod:`app.services.project_service`
- :mod:`app.services.risk_service`
- :mod:`app.services.evidence_service`
- :mod:`app.services.compliance_service`
"""

from app.services import project_service  # noqa: F401
from app.services import risk_service  # noqa: F401
from app.services import evidence_service  # noqa: F401
from app.services import compliance_service  # noqa: F401

__all__ = [
    "project_service",
    "risk_service",
    "evidence_service",
    "compliance_service",
]
