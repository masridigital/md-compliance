"""Compliance platform package — questionnaires, documents, deadlines.

All modules in this package extend the existing Flask app with capabilities
described in the compliance-platform spec: intelligent framework
questionnaires, exemption determination, AI document generation, template
upload with placeholder mapping, and deadline tracking.

The package deliberately reuses existing infrastructure:

    * :mod:`app.masri.llm_service` for all LLM calls (tier-routed)
    * :mod:`app.masri.storage_router` for .docx storage
    * :mod:`app.masri.new_models.DueDate` as the deadline store
    * :mod:`app.masri.notification_engine` for email delivery
    * :class:`app.models.Tenant` / :class:`app.models.Project` for multi-tenancy

Everything new lives under ``app.masri.compliance.*`` so the footprint is
obvious.
"""
