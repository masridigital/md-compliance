"""
Tests for the EncryptedText TypeDecorator and encryption utilities.

Covers:
- encrypt_value / decrypt_value round-trip
- is_encrypted() detection (true positives, false positives, edge cases)
- Double-encryption guard in process_bind_param
- Plaintext passthrough for legacy rows in process_result_value
- PBKDF2 key derivation consistency
- Key-mismatch raises ValueError (not silent failure)
"""
import os
import sys
import base64
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-32-chars-long!!")
os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(secret_key="test-secret-key-that-is-32-chars-long!!"):
    os.environ["SECRET_KEY"] = secret_key
    from importlib import reload
    import app as app_module
    import config as config_module
    reload(config_module)
    reload(app_module)
    from app import create_app
    _app = create_app("testing")
    _app.config["SECRET_KEY"] = secret_key
    _app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    _app.config["MASRI_SCHEDULER_ENABLED"] = False
    return _app


# ---------------------------------------------------------------------------
# is_encrypted
# ---------------------------------------------------------------------------

class TestIsEncrypted:
    def setup_method(self):
        os.environ["SECRET_KEY"] = "test-secret-key-that-is-32-chars-long!!"
        from app.masri.settings_service import is_encrypted, encrypt_value
        self.is_encrypted = is_encrypted
        self.encrypt_value = encrypt_value

    def _fake_app_ctx(self):
        from app import create_app
        app = create_app("testing")
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        app.config["MASRI_SCHEDULER_ENABLED"] = False
        return app.app_context()

    def test_none_returns_false(self):
        assert self.is_encrypted(None) is False

    def test_empty_string_returns_false(self):
        assert self.is_encrypted("") is False

    def test_short_string_returns_false(self):
        assert self.is_encrypted("short") is False

    def test_plaintext_returns_false(self):
        assert self.is_encrypted("This is plaintext, not encrypted.") is False

    def test_plaintext_with_ga_prefix_returns_false(self):
        # A string that starts with 'gA' but is not a valid Fernet token.
        # Old code used prefix-only check and would false-positive here.
        fake = "gA" + "x" * 30  # only 32 chars, < 76 minimum
        assert self.is_encrypted(fake) is False

    def test_real_token_returns_true(self):
        with self._fake_app_ctx():
            token = self.encrypt_value("hello world")
        assert self.is_encrypted(token) is True

    def test_token_length_boundary(self):
        # Fernet minimum = 76 chars in base64
        with self._fake_app_ctx():
            token = self.encrypt_value("x")
        assert len(token) >= 76
        assert self.is_encrypted(token) is True

    def test_invalid_base64_returns_false(self):
        assert self.is_encrypted("gAAAAA!!!not-base64!!!AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA") is False

    def test_integer_returns_false(self):
        assert self.is_encrypted(12345) is False  # type: ignore


# ---------------------------------------------------------------------------
# encrypt_value / decrypt_value
# ---------------------------------------------------------------------------

class TestEncryptDecrypt:
    def setup_method(self):
        os.environ["SECRET_KEY"] = "test-secret-key-that-is-32-chars-long!!"
        from app.masri.settings_service import encrypt_value, decrypt_value
        self.encrypt = encrypt_value
        self.decrypt = decrypt_value

    def _ctx(self):
        from app import create_app
        app = create_app("testing")
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        app.config["MASRI_SCHEDULER_ENABLED"] = False
        return app.app_context()

    def test_round_trip(self):
        with self._ctx():
            token = self.encrypt("hello world")
            result = self.decrypt(token)
        assert result == "hello world"

    def test_empty_string_round_trip(self):
        with self._ctx():
            token = self.encrypt("")
            result = self.decrypt(token)
        assert result == ""

    def test_whitespace_round_trip(self):
        with self._ctx():
            token = self.encrypt("   ")
            assert self.decrypt(token) == "   "

    def test_unicode_round_trip(self):
        text = "Héllo wörld — 中文 — 🎉"
        with self._ctx():
            token = self.encrypt(text)
            result = self.decrypt(token)
        assert result == text

    def test_nonce_randomness(self):
        """Two encryptions of the same value must produce different tokens."""
        with self._ctx():
            t1 = self.encrypt("same value")
            t2 = self.encrypt("same value")
        assert t1 != t2

    def test_wrong_key_raises(self):
        """Decrypting with a different key raises ValueError."""
        with self._ctx():
            token = self.encrypt("secret data")

        # Change key
        os.environ["SECRET_KEY"] = "another-totally-different-32char-key!!"
        from importlib import reload
        import app.masri.settings_service as ss
        reload(ss)

        from app import create_app as ca2
        app2 = ca2("testing")
        app2.config["SECRET_KEY"] = "another-totally-different-32char-key!!"
        app2.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        app2.config["MASRI_SCHEDULER_ENABLED"] = False

        with app2.app_context():
            with pytest.raises(ValueError, match="Unable to decrypt"):
                ss.decrypt_value(token)

        # Restore key
        os.environ["SECRET_KEY"] = "test-secret-key-that-is-32-chars-long!!"
        reload(ss)

    def test_same_key_same_output(self):
        """Derived Fernet key must be deterministic for the same SECRET_KEY."""
        with self._ctx():
            t1 = self.encrypt("deterministic")
        with self._ctx():
            result = self.decrypt(t1)
        assert result == "deterministic"


# ---------------------------------------------------------------------------
# EncryptedText TypeDecorator
# ---------------------------------------------------------------------------

class TestEncryptedText:
    def setup_method(self):
        os.environ["SECRET_KEY"] = "test-secret-key-that-is-32-chars-long!!"
        from app.masri.settings_service import EncryptedText, encrypt_value, is_encrypted
        self.EncryptedText = EncryptedText
        self.encrypt = encrypt_value
        self.is_encrypted = is_encrypted

    def _ctx(self):
        from app import create_app
        app = create_app("testing")
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        app.config["MASRI_SCHEDULER_ENABLED"] = False
        return app.app_context()

    def test_bind_param_encrypts_plaintext(self):
        col = self.EncryptedText()
        with self._ctx():
            result = col.process_bind_param("my secret note", None)
        assert self.is_encrypted(result)

    def test_bind_param_skips_already_encrypted(self):
        """process_bind_param must NOT double-encrypt a Fernet token."""
        col = self.EncryptedText()
        with self._ctx():
            token = self.encrypt("already encrypted value")
            result = col.process_bind_param(token, None)
        assert result == token  # unchanged

    def test_bind_param_none_passthrough(self):
        col = self.EncryptedText()
        with self._ctx():
            assert col.process_bind_param(None, None) is None

    def test_result_value_decrypts(self):
        col = self.EncryptedText()
        with self._ctx():
            token = self.encrypt("stored note")
            result = col.process_result_value(token, None)
        assert result == "stored note"

    def test_result_value_plaintext_passthrough(self):
        """Legacy plaintext rows must be returned as-is (not crash)."""
        col = self.EncryptedText()
        with self._ctx():
            result = col.process_result_value("pre-migration plaintext", None)
        assert result == "pre-migration plaintext"

    def test_result_value_none_passthrough(self):
        col = self.EncryptedText()
        with self._ctx():
            assert col.process_result_value(None, None) is None
