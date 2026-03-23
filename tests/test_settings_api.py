"""
Tests for the Settings API endpoints:
- /api/v1/settings/entra (GET, POST, DELETE)
- /api/v1/settings/notifications auth guard (H3 regression test)
- /api/v1/settings/platform
- /api/v1/settings/llm
- /api/v1/settings/sso
- /api/v1/settings/mcp-keys
"""
import os
import sys
import json
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-32-chars-long!!")
os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")


@pytest.fixture(scope="module")
def app_and_db():
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
        db.select(User).filter_by(email="api_admin@test.com")
    ).scalars().first()
    if not existing:
        user = User.add(
            "api_admin@test.com",
            password="AdminPass123!",
            confirmed=True,
            built_in=True,
            super=True,
            require_pwd_change=False,
            return_user_object=True,
        )
        Tenant.create(user, "API Test Tenant", "api@test.com", is_default=True, init_data=False)
    db.session.commit()


@pytest.fixture(scope="module")
def client(app_and_db):
    app, db = app_and_db
    return app.test_client()


@pytest.fixture(scope="module")
def authed_client(app_and_db, client):
    """Log in as admin and return the client."""
    app, db = app_and_db
    with app.app_context():
        client.post(
            "/login",
            data={"email": "api_admin@test.com", "password": "AdminPass123!"},
            follow_redirects=False,
        )
    return client


# ---------------------------------------------------------------------------
# /api/v1/settings/entra
# ---------------------------------------------------------------------------

class TestEntraSettingsAPI:
    def test_get_entra_unauthenticated_returns_redirect(self, client):
        resp = client.get("/api/v1/settings/entra")
        assert resp.status_code in (302, 401, 403)

    def test_get_entra_no_config(self, authed_client, app_and_db):
        app, db = app_and_db
        with app.app_context():
            resp = authed_client.get("/api/v1/settings/entra")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["configured"] is False

    def test_post_entra_missing_fields(self, authed_client, app_and_db):
        app, _ = app_and_db
        with app.app_context():
            resp = authed_client.post(
                "/api/v1/settings/entra",
                json={"entra_tenant_id": "tid"},  # missing client_id and secret
                content_type="application/json",
            )
        assert resp.status_code == 400
        assert "required" in resp.get_json().get("error", "").lower()

    def test_post_entra_saves_encrypted(self, authed_client, app_and_db):
        from app.masri.settings_service import is_encrypted
        app, db = app_and_db
        with app.app_context():
            resp = authed_client.post(
                "/api/v1/settings/entra",
                json={
                    "entra_tenant_id": "test-tenant-uuid",
                    "client_id": "test-client-id",
                    "client_secret": "test-client-secret",
                },
                content_type="application/json",
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["is_fully_configured"] is True
        assert data["has_entra_tenant_id"] is True
        # Raw encrypted values must NOT be in response
        assert "entra_tenant_id_enc" not in data
        assert "entra_client_id_enc" not in data
        assert "entra_client_secret_enc" not in data

        # Verify raw DB values are actually encrypted
        with app.app_context():
            from app.masri.new_models import SettingsEntra
            from app import db as _db
            record = _db.session.execute(
                _db.select(SettingsEntra).filter_by(tenant_id=None)
            ).scalars().first()
            assert record is not None
            assert is_encrypted(record.entra_tenant_id_enc)
            assert is_encrypted(record.entra_client_id_enc)
            assert is_encrypted(record.entra_client_secret_enc)

    def test_get_entra_after_save(self, authed_client, app_and_db):
        app, _ = app_and_db
        with app.app_context():
            resp = authed_client.get("/api/v1/settings/entra")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["source"] == "database"
        assert data["is_fully_configured"] is True

    def test_delete_entra_config(self, authed_client, app_and_db):
        app, _ = app_and_db
        with app.app_context():
            resp = authed_client.delete("/api/v1/settings/entra")
        assert resp.status_code == 200
        # Confirm it's gone
        with app.app_context():
            resp2 = authed_client.get("/api/v1/settings/entra")
        assert resp2.get_json()["configured"] is False


# ---------------------------------------------------------------------------
# Notification auth guard — H3 regression
# ---------------------------------------------------------------------------

class TestNotificationAuthGuard:
    def test_get_notifications_unauthenticated(self, client):
        resp = client.get("/api/v1/settings/notifications")
        assert resp.status_code in (302, 401, 403)

    def test_get_notifications_platform_level_requires_admin(self, authed_client, app_and_db):
        """GET /notifications without tenant_id → platform admin required (should succeed for superuser)."""
        app, _ = app_and_db
        with app.app_context():
            resp = authed_client.get("/api/v1/settings/notifications")
        # Should succeed for superuser admin
        assert resp.status_code == 200

    def test_put_notification_no_tenant_requires_admin(self, authed_client, app_and_db):
        """PUT without tenant_id → platform admin required (should succeed for superuser)."""
        app, _ = app_and_db
        with app.app_context():
            resp = authed_client.put(
                "/api/v1/settings/notifications/email",
                json={"enabled": True},
                content_type="application/json",
            )
        # Superuser should succeed (200 or 400 for validation, never 403)
        assert resp.status_code != 403


# ---------------------------------------------------------------------------
# /api/v1/settings/platform
# ---------------------------------------------------------------------------

class TestPlatformSettings:
    def test_get_platform_settings(self, authed_client, app_and_db):
        app, _ = app_and_db
        with app.app_context():
            resp = authed_client.get("/api/v1/settings/platform")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "app_name" in data

    def test_update_platform_settings(self, authed_client, app_and_db):
        app, _ = app_and_db
        with app.app_context():
            resp = authed_client.put(
                "/api/v1/settings/platform",
                json={"app_name": "Updated App"},
                content_type="application/json",
            )
        assert resp.status_code == 200
        assert resp.get_json()["app_name"] == "Updated App"


# ---------------------------------------------------------------------------
# /api/v1/settings/llm
# ---------------------------------------------------------------------------

class TestLLMSettings:
    def test_get_llm_config(self, authed_client, app_and_db):
        app, _ = app_and_db
        with app.app_context():
            resp = authed_client.get("/api/v1/settings/llm")
        # 200 if config exists, 404 if not yet configured — both are valid
        assert resp.status_code in (200, 404)
        data = resp.get_json()
        # api_key must never be in response regardless of status
        assert "api_key_enc" not in data

    def test_update_llm_api_key_does_not_leak(self, authed_client, app_and_db):
        app, _ = app_and_db
        with app.app_context():
            resp = authed_client.put(
                "/api/v1/settings/llm",
                json={"provider": "openai", "api_key": "sk-test-key-12345"},
                content_type="application/json",
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "api_key_enc" not in data
        assert "api_key" not in data
        assert data.get("has_api_key") is True


# ---------------------------------------------------------------------------
# /api/v1/settings/mcp-keys
# ---------------------------------------------------------------------------

class TestMCPKeys:
    def test_create_mcp_key_returns_raw_once(self, authed_client, app_and_db):
        app, _ = app_and_db
        with app.app_context():
            resp = authed_client.post(
                "/api/v1/settings/mcp-keys",
                json={"name": "Test Key"},
                content_type="application/json",
            )
        assert resp.status_code == 201
        data = resp.get_json()
        # raw_key present on creation
        assert "raw_key" in data
        raw_key = data["raw_key"]
        assert raw_key.startswith("mcp_")
        # key must be at least 64 url-safe chars after "mcp_"
        assert len(raw_key) > 70  # mcp_ (4) + 64-byte base64 (86)
        # key_hash must NOT be in response
        assert "key_hash" not in data

    def test_list_mcp_keys_hides_hash(self, authed_client, app_and_db):
        app, _ = app_and_db
        with app.app_context():
            resp = authed_client.get("/api/v1/settings/mcp-keys")
        assert resp.status_code == 200
        for key_data in resp.get_json():
            assert "key_hash" not in key_data


# ---------------------------------------------------------------------------
# /api/v1/settings/sso
# ---------------------------------------------------------------------------

class TestSSOSettings:
    def test_get_sso_config(self, authed_client, app_and_db):
        app, _ = app_and_db
        with app.app_context():
            resp = authed_client.get("/api/v1/settings/sso")
        # 200 if SSO config exists, 404 if not yet configured — both are valid
        assert resp.status_code in (200, 404)
        data = resp.get_json()
        assert "client_secret_enc" not in data

    def test_update_sso_client_secret_not_exposed(self, authed_client, app_and_db):
        app, _ = app_and_db
        with app.app_context():
            resp = authed_client.put(
                "/api/v1/settings/sso",
                json={"provider": "microsoft", "client_id": "my-client", "client_secret": "my-secret"},
                content_type="application/json",
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "client_secret_enc" not in data
        assert "client_secret" not in data
        assert data.get("has_client_secret") is True
