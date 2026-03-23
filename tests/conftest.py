"""
Pytest configuration and shared fixtures for the MD Compliance test suite.

Uses an in-memory SQLite database so tests run without a live Postgres instance.
"""
import os
import sys
import pytest

# Ensure the project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Strong test SECRET_KEY (≥32 chars so _validate_secret_key doesn't raise)
TEST_SECRET_KEY = "test-secret-key-that-is-32-chars-long!!"


@pytest.fixture(scope="session")
def app():
    """Create a Flask app configured for testing with SQLite in-memory DB."""
    os.environ["SECRET_KEY"] = TEST_SECRET_KEY
    os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

    from app import create_app, db as _db

    _app = create_app("testing")
    _app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        WTF_CSRF_ENABLED=False,
        MASRI_SCHEDULER_ENABLED=False,
        SERVER_NAME=None,
    )

    with _app.app_context():
        _db.create_all()
        _seed_db(_app, _db)
        yield _app
        _db.session.remove()
        _db.drop_all()


def _seed_db(app, db):
    """Seed minimal test data: admin user + default tenant + roles."""
    from app.models import User, Tenant, Role

    # Create roles
    for role_name in Role.VALID_ROLE_NAMES:
        if not Role.find_by_name(role_name):
            db.session.add(Role(name=role_name.lower(), label=role_name))
    db.session.commit()

    # Create admin user + default tenant
    existing = db.session.execute(
        db.select(User).filter_by(email="admin@test.com")
    ).scalars().first()

    if not existing:
        user = User.add(
            "admin@test.com",
            password="AdminPass123!",
            confirmed=True,
            built_in=True,
            super=True,
            require_pwd_change=False,
            return_user_object=True,
        )
        Tenant.create(user, "TestTenant", "admin@test.com", is_default=True, init_data=False)

    db.session.commit()


@pytest.fixture(scope="session")
def db(app):
    from app import db as _db
    return _db


@pytest.fixture(scope="function")
def client(app):
    return app.test_client()


@pytest.fixture(scope="function")
def auth_client(app, client):
    """A test client pre-authenticated as the admin user."""
    with app.app_context():
        resp = client.post(
            "/login",
            json={"email": "admin@test.com", "password": "AdminPass123!"},
            follow_redirects=False,
        )
    return client


@pytest.fixture(scope="function")
def admin_user(app, db):
    from app.models import User
    with app.app_context():
        return db.session.execute(
            db.select(User).filter_by(email="admin@test.com")
        ).scalars().first()


@pytest.fixture(scope="function")
def default_tenant(app, db):
    from app.models import Tenant
    with app.app_context():
        return Tenant.get_default_tenant()
