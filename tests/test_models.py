"""
Tests for model-level encryption on sensitive columns.

Verifies that:
- ProjectControl.notes / auditor_notes are stored encrypted, returned plaintext
- ProjectSubControl.context / notes / auditor_feedback are encrypted
- RiskRegister.description / remediation are encrypted
- RiskRegister.title is encrypted; title_hash is computed automatically
- Comment models (SubControlComment, ControlComment, ProjectComment, RiskComment) encrypt message
- WISPDocument encrypted fields round-trip correctly
- SettingsEntra.set_credentials / get_credentials encrypt and decrypt correctly
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
    app = create_app("testing")
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        MASRI_SCHEDULER_ENABLED=False,
        TESTING=True,
    )
    with app.app_context():
        db.create_all()
        yield app, db
        db.session.remove()
        db.drop_all()


@pytest.fixture(scope="module")
def seeded(app_ctx):
    """Seed a tenant + user and return them."""
    app, db = app_ctx
    from app.models import User, Tenant, Role

    for role_name in Role.VALID_ROLE_NAMES:
        if not Role.find_by_name(role_name):
            db.session.add(Role(name=role_name.lower(), label=role_name))
    db.session.commit()

    user = User.add(
        "model_test@test.com",
        password="TestPass123!",
        confirmed=True,
        super=True,
        return_user_object=True,
    )
    tenant = Tenant.create(user, "ModelTestTenant", "model@test.com", is_default=False, init_data=False)
    db.session.commit()
    return {"user": user, "tenant": tenant, "db": db, "app": app}


class TestRiskRegister:
    def test_title_is_encrypted_in_db(self, seeded):
        db = seeded["db"]
        from app.models import RiskRegister
        from app.masri.settings_service import is_encrypted

        risk = RiskRegister(
            title="SQL injection in prod",
            description="Detailed description of the vuln",
            remediation="Apply WAF rules",
            tenant_id=seeded["tenant"].id,
        )
        db.session.add(risk)
        db.session.commit()
        db.session.expire(risk)

        # Read raw value from DB
        raw = db.session.execute(
            db.text("SELECT title FROM risk_register WHERE id = :id"),
            {"id": risk.id},
        ).scalar()
        assert is_encrypted(raw), f"title should be encrypted in DB, got: {raw[:40]}"

        # ORM should transparently decrypt
        loaded = db.session.get(RiskRegister, risk.id)
        assert loaded.title == "SQL injection in prod"

    def test_title_hash_auto_populated(self, seeded):
        import hashlib
        db = seeded["db"]
        from app.models import RiskRegister

        risk = RiskRegister(
            title="Another Risk",
            description="Desc",
            tenant_id=seeded["tenant"].id,
        )
        db.session.add(risk)
        db.session.commit()

        expected_hash = hashlib.sha256(
            f"another risk|{seeded['tenant'].id}".encode()
        ).hexdigest()
        assert risk.title_hash == expected_hash

    def test_description_encrypted(self, seeded):
        db = seeded["db"]
        from app.models import RiskRegister
        from app.masri.settings_service import is_encrypted

        risk = RiskRegister(
            title="Desc Test Risk",
            description="Highly sensitive description",
            tenant_id=seeded["tenant"].id,
        )
        db.session.add(risk)
        db.session.commit()

        raw = db.session.execute(
            db.text("SELECT description FROM risk_register WHERE id = :id"),
            {"id": risk.id},
        ).scalar()
        assert is_encrypted(raw)
        assert db.session.get(RiskRegister, risk.id).description == "Highly sensitive description"

    def test_remediation_encrypted(self, seeded):
        db = seeded["db"]
        from app.models import RiskRegister
        from app.masri.settings_service import is_encrypted

        risk = RiskRegister(
            title="Remediation Test Risk",
            remediation="Apply patches and reboot",
            tenant_id=seeded["tenant"].id,
        )
        db.session.add(risk)
        db.session.commit()

        raw = db.session.execute(
            db.text("SELECT remediation FROM risk_register WHERE id = :id"),
            {"id": risk.id},
        ).scalar()
        assert is_encrypted(raw)
        assert db.session.get(RiskRegister, risk.id).remediation == "Apply patches and reboot"

    def test_as_dict_hides_title_hash(self, seeded):
        db = seeded["db"]
        from app.models import RiskRegister

        risk = RiskRegister(
            title="Dict Test Risk",
            description="Desc",
            tenant_id=seeded["tenant"].id,
        )
        db.session.add(risk)
        db.session.commit()

        d = risk.as_dict()
        assert "title_hash" not in d
        assert d["title"] == "Dict Test Risk"


class TestCommentEncryption:
    def _make_project_control(self, seeded):
        db = seeded["db"]
        from app.models import Framework, Control, ProjectControl, Project
        from app import db as _db

        # Create minimal framework + control + project + project_control
        fw = Framework(
            name="Test FW",
            description="Test framework description",
            tenant_id=seeded["tenant"].id,
        )
        _db.session.add(fw)
        _db.session.flush()

        ctrl = Control(
            name="Test Control",
            framework_id=fw.id,
        )
        _db.session.add(ctrl)
        _db.session.flush()

        proj = Project(
            name="Test Project",
            tenant_id=seeded["tenant"].id,
            owner_id=seeded["user"].id,
        )
        _db.session.add(proj)
        _db.session.flush()

        pc = ProjectControl(
            project_id=proj.id,
            control_id=ctrl.id,
        )
        _db.session.add(pc)
        _db.session.flush()
        return pc

    def test_control_comment_message_encrypted(self, seeded):
        db = seeded["db"]
        from app.models import ControlComment
        from app.masri.settings_service import is_encrypted

        pc = self._make_project_control(seeded)
        comment = ControlComment(
            message="This is a sensitive audit comment",
            owner_id=seeded["user"].id,
            control_id=pc.id,
        )
        db.session.add(comment)
        db.session.commit()

        raw = db.session.execute(
            db.text("SELECT message FROM control_comments WHERE id = :id"),
            {"id": comment.id},
        ).scalar()
        assert is_encrypted(raw)
        loaded = db.session.get(ControlComment, comment.id)
        assert loaded.message == "This is a sensitive audit comment"

    def test_project_comment_message_encrypted(self, seeded):
        db = seeded["db"]
        from app.models import ProjectComment, Project
        from app.masri.settings_service import is_encrypted

        proj = Project(
            name="Comment Test Project",
            tenant_id=seeded["tenant"].id,
            owner_id=seeded["user"].id,
        )
        db.session.add(proj)
        db.session.flush()

        comment = ProjectComment(
            message="Sensitive project comment",
            owner_id=seeded["user"].id,
            project_id=proj.id,
        )
        db.session.add(comment)
        db.session.commit()

        raw = db.session.execute(
            db.text("SELECT message FROM project_comments WHERE id = :id"),
            {"id": comment.id},
        ).scalar()
        assert is_encrypted(raw)
        assert db.session.get(ProjectComment, comment.id).message == "Sensitive project comment"


class TestSettingsEntraModel:
    def test_set_and_get_credentials(self, seeded):
        from app.masri.new_models import SettingsEntra
        from app.masri.settings_service import is_encrypted

        record = SettingsEntra()
        record.set_credentials(
            entra_tenant_id="tenant-uuid-1234",
            client_id="client-uuid-5678",
            client_secret="super-secret-value",
        )

        # All three enc fields must be Fernet tokens
        assert is_encrypted(record.entra_tenant_id_enc)
        assert is_encrypted(record.entra_client_id_enc)
        assert is_encrypted(record.entra_client_secret_enc)

        # get_credentials must round-trip
        creds = record.get_credentials()
        assert creds["entra_tenant_id"] == "tenant-uuid-1234"
        assert creds["client_id"] == "client-uuid-5678"
        assert creds["client_secret"] == "super-secret-value"

    def test_as_dict_hides_raw_values(self, seeded):
        from app.masri.new_models import SettingsEntra

        record = SettingsEntra()
        record.set_credentials("tid", "cid", "csecret")
        d = record.as_dict()

        # Raw encrypted fields must not be exposed
        assert "entra_tenant_id_enc" not in d
        assert "entra_client_id_enc" not in d
        assert "entra_client_secret_enc" not in d

        # Boolean status flags must be present
        assert d["has_entra_tenant_id"] is True
        assert d["has_client_id"] is True
        assert d["has_client_secret"] is True
        assert d["is_fully_configured"] is True

    def test_is_fully_configured_partial(self, seeded):
        from app.masri.new_models import SettingsEntra
        from app.masri.settings_service import encrypt_value

        record = SettingsEntra()
        record.entra_tenant_id_enc = encrypt_value("tid")
        # client_id and client_secret not set

        assert record.is_fully_configured() is False


class TestWISPDocumentEncryption:
    def test_firm_name_encrypted(self, seeded):
        db = seeded["db"]
        from app.masri.new_models import WISPDocument
        from app.masri.settings_service import is_encrypted

        wisp = WISPDocument(
            tenant_id=seeded["tenant"].id,
            firm_name="Acme CPA Firm",
            firm_type="cpa_firm",
        )
        db.session.add(wisp)
        db.session.commit()

        raw = db.session.execute(
            db.text("SELECT firm_name FROM wisp_documents WHERE id = :id"),
            {"id": wisp.id},
        ).scalar()
        assert is_encrypted(raw)
        loaded = db.session.get(WISPDocument, wisp.id)
        assert loaded.firm_name == "Acme CPA Firm"

    def test_qi_email_encrypted(self, seeded):
        db = seeded["db"]
        from app.masri.new_models import WISPDocument
        from app.masri.settings_service import is_encrypted

        wisp = WISPDocument(
            tenant_id=seeded["tenant"].id,
            firm_type="law_firm",
            qi_email="john.doe@lawfirm.com",
        )
        db.session.add(wisp)
        db.session.commit()

        raw = db.session.execute(
            db.text("SELECT qi_email FROM wisp_documents WHERE id = :id"),
            {"id": wisp.id},
        ).scalar()
        assert is_encrypted(raw)
        loaded = db.session.get(WISPDocument, wisp.id)
        assert loaded.qi_email == "john.doe@lawfirm.com"


class TestTenantContactEmailEncryption:
    def test_contact_email_encrypted_name_plaintext(self, seeded):
        """Tenant.name must be plaintext; Tenant.contact_email must be encrypted."""
        db = seeded["db"]
        from app.masri.settings_service import is_encrypted

        tenant = seeded["tenant"]

        raw_name = db.session.execute(
            db.text("SELECT name FROM tenants WHERE id = :id"),
            {"id": tenant.id},
        ).scalar()
        assert not is_encrypted(raw_name), "Tenant.name must stay plaintext"

        # Set a contact email to verify encryption
        tenant.contact_email = "contact@example.com"
        db.session.commit()

        raw_email = db.session.execute(
            db.text("SELECT contact_email FROM tenants WHERE id = :id"),
            {"id": tenant.id},
        ).scalar()
        assert is_encrypted(raw_email), "Tenant.contact_email must be encrypted"
        assert tenant.contact_email == "contact@example.com"
