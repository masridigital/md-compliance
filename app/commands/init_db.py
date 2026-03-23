from flask import current_app
from flask_migrate import Migrate
from alembic import command
from app.models import User, Tenant, Role
from app import db


# ── Command classes (plain Python — no flask_script dependency) ───────────────

class InitDbCommand:
    """Drop all tables and recreate from SQLAlchemy models, then seed defaults."""

    def run(self):
        init_db()
        print("[INFO] Database has been initialized.")


class CreateDbCommand:
    """Create tables without dropping existing ones, then seed defaults."""

    def run(self):
        create_db()
        print("[INFO] Database has been created.")


class MigrateDbCommand:
    """Apply pending Alembic migrations."""

    def run(self):
        migrate_db()
        print("[INFO] Database has been migrated.")


class DataImportCommand:
    """Placeholder for data import tasks."""

    def run(self):
        raise NotImplementedError("DataImportCommand is not implemented.")


class ForceDropTablesCommand:
    """Drop all tables — DESTRUCTIVE."""

    def run(self):
        force_drop_all_tables()


class EncryptExistingCommand:
    """
    Re-encrypt all existing plaintext values in EncryptedText columns.

    Safe to run multiple times — already-encrypted values are detected by the
    Fernet token prefix (0x80 version byte) and skipped.

    Run after upgrading to the encrypted schema:
        python manage.py encrypt_existing
    """

    def run(self):
        encrypt_existing_data()


# ── Implementation functions ──────────────────────────────────────────────────

def init_db():
    """Drop everything and rebuild from models, then seed defaults."""
    db.drop_all()
    db.create_all()
    create_default_users()
    create_default_roles()


def create_db():
    """Create tables that don't already exist, then seed defaults."""
    db.create_all()
    create_default_users()
    create_default_roles()


def migrate_db():
    """Apply Alembic migrations to head."""
    cfg = Migrate(current_app, db).get_config()
    command.upgrade(cfg, "head")


def create_default_users():
    """Seed the default admin user and default tenant."""
    default_email = current_app.config.get("DEFAULT_EMAIL", "admin@example.com")
    default_password = current_app.config.get("DEFAULT_PASSWORD") or "admin1234567"

    existing = db.session.execute(
        db.select(User).filter(User.email == default_email)
    ).scalars().first()

    if not existing:
        user = User.add(
            default_email,
            password=default_password,
            confirmed=True,
            built_in=True,
            super=True,
            require_pwd_change=True,
            return_user_object=True,
        )
        Tenant.create(user, "Default", default_email, is_default=True, init_data=True)
    return True


def create_default_roles():
    """Seed the built-in roles (skips any that already exist)."""
    for role_name in Role.VALID_ROLE_NAMES:
        if not Role.find_by_name(role_name):
            r = Role(name=role_name.lower(), label=role_name)
            db.session.add(r)
    db.session.commit()
    return True


def force_drop_all_tables():
    meta = db.metadata
    meta.reflect(bind=db.engine)
    meta.drop_all(bind=db.engine)


def encrypt_existing_data():
    """
    Iterate all rows in every EncryptedText column and re-save any that are
    still plaintext.  The EncryptedText TypeDecorator skips already-encrypted
    values in process_bind_param, so this is fully idempotent.

    Tables and columns covered:
      tenants              : contact_email
      project_controls     : notes, auditor_notes
      project_subcontrols  : context, notes, auditor_feedback
      risk_register        : description, remediation
      subcontrol_comments  : message
      control_comments     : message
      project_comments     : message
      risk_comments        : message
      wisp_documents       : firm_name, qi_name, qi_email, qi_title,
                             asset_inventory_json, risk_assessment_json,
                             access_control_answers_json, encryption_answers_json,
                             third_party_vendors_json, incident_response_json,
                             training_program_json, physical_security_json,
                             business_continuity_json, annual_review_json,
                             generated_text_json
      wisp_versions        : snapshot_json
    """
    from app.masri.settings_service import is_encrypted, encrypt_value
    from app import db as _db

    # Each entry: (ModelClass, [field_names])
    from app.models import (
        Tenant, ProjectControl, ProjectSubControl, RiskRegister,
        SubControlComment, ControlComment, ProjectComment, RiskComment,
    )
    from app.masri.new_models import WISPDocument, WISPVersion

    targets = [
        (Tenant, ["contact_email"]),
        (ProjectControl, ["notes", "auditor_notes"]),
        (ProjectSubControl, ["context", "notes", "auditor_feedback"]),
        (RiskRegister, ["description", "remediation"]),
        (SubControlComment, ["message"]),
        (ControlComment, ["message"]),
        (ProjectComment, ["message"]),
        (RiskComment, ["message"]),
        (WISPDocument, [
            "firm_name", "qi_name", "qi_email", "qi_title",
            "asset_inventory_json", "risk_assessment_json",
            "access_control_answers_json", "encryption_answers_json",
            "third_party_vendors_json", "incident_response_json",
            "training_program_json", "physical_security_json",
            "business_continuity_json", "annual_review_json",
            "generated_text_json",
        ]),
        (WISPVersion, ["snapshot_json"]),
    ]

    total_rows = 0
    total_updated = 0

    for Model, fields in targets:
        rows = _db.session.execute(_db.select(Model)).scalars().all()
        updated_in_table = 0
        for row in rows:
            changed = False
            for field in fields:
                value = getattr(row, field)
                if value is None:
                    continue
                # EncryptedText.process_result_value already decrypted it if
                # it was a token, so the value we see here is always plaintext.
                # Re-assigning forces process_bind_param → encrypts it.
                setattr(row, field, value)
                changed = True
            if changed:
                updated_in_table += 1
        if updated_in_table:
            _db.session.commit()
        total_rows += len(rows)
        total_updated += updated_in_table
        print(f"  [{Model.__tablename__}] {len(rows)} rows, {updated_in_table} written")

    print(f"\nDone. {total_updated}/{total_rows} rows re-encrypted.")
    print("Run again to verify — subsequent runs should show 0 rows written.")
