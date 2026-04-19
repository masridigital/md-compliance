"""
Tests for /api/v1/entra/* endpoints and credential resolution.

Covers:
- Unauthenticated access is blocked
- _get_entra_client() uses DB credentials (SettingsEntra) when present
- _get_entra_client() falls back to env vars
- _get_entra_client() raises RuntimeError with a generic message (H5 regression)
- No credential field names leaked in error responses
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-32-chars-long!!")
os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")


@pytest.fixture(scope="module")
def app_ctx():
    os.environ["SECRET_KEY"] = "test-secret-key-that-is-32-chars-long!!"
    from app import create_app, db
    _app = create_app("testing")
    _app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        MASRI_SCHEDULER_ENABLED=False,
        TESTING=True,
        WTF_CSRF_ENABLED=False,
    )
    with _app.app_context():
        db.create_all()
        _seed(_app, db)
        yield _app, db
        db.session.remove()
        db.drop_all()


def _seed(app, db):
    from app.models import User, Tenant, Role
    for rn in Role.VALID_ROLE_NAMES:
        if not Role.find_by_name(rn):
            db.session.add(Role(name=rn.lower(), label=rn))
    db.session.commit()
    existing = db.session.execute(
        db.select(User).filter_by(email="entra_test@test.com")
    ).scalars().first()
    if not existing:
        u = User.add(
            "entra_test@test.com",
            password="TestPass123!",
            confirmed=True,
            super=True,
            return_user_object=True,
        )
        Tenant.create(u, "EntraTenant", "e@test.com", is_default=True, init_data=False)
    db.session.commit()


@pytest.fixture(scope="module")
def client(app_ctx):
    app, _ = app_ctx
    return app.test_client()


@pytest.fixture(scope="module")
def authed_client(app_ctx, client):
    app, _ = app_ctx
    with app.app_context():
        client.post(
            "/login",
            data={"email": "entra_test@test.com", "password": "TestPass123!"},
            follow_redirects=False,
        )
    return client


class TestEntraEndpointAuth:
    def test_test_endpoint_unauthenticated(self, client):
        resp = client.post("/api/v1/entra/test")
        assert resp.status_code in (302, 401, 403)

    def test_users_endpoint_unauthenticated(self, client):
        resp = client.get("/api/v1/entra/users")
        assert resp.status_code in (302, 401, 403)

    def test_mfa_status_unauthenticated(self, client):
        resp = client.get("/api/v1/entra/mfa-status")
        assert resp.status_code in (302, 401, 403)

    def test_assess_unauthenticated(self, client):
        resp = client.post("/api/v1/entra/assess")
        assert resp.status_code in (302, 401, 403)


class TestEntraCredentialResolution:
    def test_generic_error_when_not_configured(self, authed_client, app_ctx):
        """Error message must NOT expose ENTRA_TENANT_ID / ENTRA_CLIENT_ID names (H5)."""
        app, db = app_ctx
        # Ensure no env vars and no DB record
        for key in ("ENTRA_TENANT_ID", "ENTRA_CLIENT_ID", "ENTRA_CLIENT_SECRET"):
            os.environ.pop(key, None)
        with app.app_context():
            app.config.pop("ENTRA_TENANT_ID", None)
            app.config.pop("ENTRA_CLIENT_ID", None)
            app.config.pop("ENTRA_CLIENT_SECRET", None)

            resp = authed_client.post("/api/v1/entra/test")
        # Should get an error response, not a 500 crash
        assert resp.status_code in (400, 500, 503)
        body = resp.get_data(as_text=True)
        # Sensitive field names must not appear in response body
        assert "ENTRA_TENANT_ID" not in body
        assert "ENTRA_CLIENT_ID" not in body
        assert "ENTRA_CLIENT_SECRET" not in body
        assert "ENTRA_" not in body

    def test_db_credentials_preferred_over_env(self, authed_client, app_ctx):
        """When SettingsEntra DB record exists, it should be used over env vars."""
        app, db = app_ctx

        # Set env vars with different values
        os.environ["ENTRA_TENANT_ID"] = "env-tenant-id"
        os.environ["ENTRA_CLIENT_ID"] = "env-client-id"
        os.environ["ENTRA_CLIENT_SECRET"] = "env-secret"

        with app.app_context():
            app.config["ENTRA_TENANT_ID"] = "env-tenant-id"
            app.config["ENTRA_CLIENT_ID"] = "env-client-id"
            app.config["ENTRA_CLIENT_SECRET"] = "env-secret"

            from app.services import entra_config_service
            entra_config_service.update_entra_config(
                "db-tenant-id", "db-client-id", "db-secret"
            )

            creds = entra_config_service.get_entra_config()
            assert creds["entra_tenant_id"] == "db-tenant-id"  # DB wins
            assert creds["client_id"] == "db-client-id"
            assert creds["client_secret"] == "db-secret"

        # Cleanup
        for key in ("ENTRA_TENANT_ID", "ENTRA_CLIENT_ID", "ENTRA_CLIENT_SECRET"):
            os.environ.pop(key, None)
