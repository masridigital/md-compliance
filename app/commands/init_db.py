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
