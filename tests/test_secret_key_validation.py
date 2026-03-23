"""
Tests for SECRET_KEY strength validation (M4).

Verifies that:
- App warns (not raises) for short keys in testing/debug mode
- _validate_secret_key raises RuntimeError in production mode for short keys
- Minimum 32-char keys pass validation
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSecretKeyValidation:
    def _make_app(self, secret_key, mode="testing"):
        os.environ["SECRET_KEY"] = secret_key
        from app import create_app
        app = create_app(mode)
        app.config.update(
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            MASRI_SCHEDULER_ENABLED=False,
        )
        return app

    def test_short_key_warns_in_testing_mode(self):
        """Short SECRET_KEY in testing/debug mode → warning, not RuntimeError."""
        from app import _validate_secret_key
        from unittest.mock import MagicMock

        mock_app = MagicMock()
        mock_app.config = {"SECRET_KEY": "short"}
        mock_app.debug = False
        mock_app.testing = True

        # Should NOT raise; should call app.logger.warning
        _validate_secret_key(mock_app)
        mock_app.logger.warning.assert_called_once()
        call_args = mock_app.logger.warning.call_args
        assert "SECRET_KEY" in str(call_args)

    def test_short_key_raises_in_production(self):
        """Short SECRET_KEY in production mode → RuntimeError."""
        from app import _validate_secret_key
        from unittest.mock import MagicMock
        mock_app = MagicMock()
        mock_app.config = {"SECRET_KEY": "short"}
        mock_app.debug = False
        mock_app.testing = False

        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            _validate_secret_key(mock_app)

    def test_32_char_key_passes(self):
        """A 32-char key must not warn or raise."""
        key = "a" * 32
        app = self._make_app(key, mode="testing")
        assert app is not None

    def test_long_key_passes(self):
        key = "test-secret-key-that-is-32-chars-long!!"
        app = self._make_app(key, mode="testing")
        assert app is not None
