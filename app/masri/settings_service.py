"""
Masri Digital Compliance Platform — Settings Encryption Utilities.

Module-level helpers for Fernet encryption/decryption derived from the
Flask ``SECRET_KEY`` via PBKDF2-HMAC-SHA256, plus the ``EncryptedText``
SQLAlchemy type used by model columns across the app.

Phase E3 split the former ``SettingsService`` god class into per-domain
services under :mod:`app.services` (``platform_service``,
``branding_service``, ``llm_config_service``, ``storage_config_service``,
``sso_service``, ``notification_service``, ``entra_config_service``).
This module now only exports crypto primitives; import the relevant
service module for settings operations.
"""

import base64
import logging
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

logger = logging.getLogger(__name__)

# Fixed application-level salt — NOT secret, just ensures key space separation.
# Never changes between deployments so key rotation (SECRET_KEY change) works predictably.
_KDF_SALT = b"masri-digital-compliance-v1-salt"
_KDF_ITERATIONS = 260_000  # OWASP 2023 minimum for PBKDF2-HMAC-SHA256


# ---------------------------------------------------------------------------
# Encryption utilities
# ---------------------------------------------------------------------------

def _get_fernet(app=None):
    """
    Derive a Fernet key from the Flask SECRET_KEY using PBKDF2-HMAC-SHA256.

    Fernet requires a URL-safe base64 32-byte key.  Using a proper KDF (not
    raw SHA-256) means:
      - Key space is fully utilised regardless of SECRET_KEY length/entropy.
      - Multiple invocations with the same SECRET_KEY always produce the
        same Fernet key → deterministic, no per-call state needed.
    """
    from flask import current_app
    secret = (app or current_app).config["SECRET_KEY"]
    if isinstance(secret, str):
        secret = secret.encode()

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_KDF_SALT,
        iterations=_KDF_ITERATIONS,
    )
    key = base64.urlsafe_b64encode(kdf.derive(secret))
    return Fernet(key)


def encrypt_value(value: str, app=None) -> str:
    """Encrypt a plaintext string. Returns a Fernet token (str)."""
    f = _get_fernet(app)
    return f.encrypt(value.encode()).decode()


def decrypt_value(encrypted: str, app=None) -> str:
    """Decrypt a Fernet token back to plaintext."""
    f = _get_fernet(app)
    try:
        return f.decrypt(encrypted.encode()).decode()
    except InvalidToken:
        raise ValueError(
            "Unable to decrypt value — key mismatch or data corruption. "
            "If SECRET_KEY was rotated, re-encrypt data with the new key."
        )


def is_encrypted(value: str) -> bool:
    """
    Return True if *value* is a valid Fernet token produced by this app.

    Fernet token structure (before base64):
      version(1) | timestamp(8) | iv(16) | ciphertext(>=0) | hmac(32)

    Minimum raw bytes = 1+8+16+0+32 = 57 → minimum base64 length = 76 chars.
    All tokens start with 0x80 (version byte) → first base64 char is 'g',
    second is 'A', 'B', 'C' or 'D' (only top 2 bits of second byte matter).
    We fully decode the base64 to confirm valid padding and structure, which
    eliminates false positives from arbitrary plaintext starting with 'gA'.
    """
    if not value or not isinstance(value, str):
        return False
    if len(value) < 76:
        return False
    try:
        raw = base64.urlsafe_b64decode(value.encode())
    except Exception:
        return False
    return len(raw) >= 57 and raw[0] == 0x80


# ---------------------------------------------------------------------------
# EncryptedText — SQLAlchemy TypeDecorator for transparent field encryption
# ---------------------------------------------------------------------------

class EncryptedText(TypeDecorator):
    """
    A SQLAlchemy column type that transparently Fernet-encrypts values on
    write and decrypts on read.

    Usage in a model::

        from app.masri.settings_service import EncryptedText
        notes = db.Column(EncryptedText)

    Behaviour:
    - On write: plaintext → Fernet token stored in the DB
    - On read:  if the stored value is already a Fernet token → decrypt it
                if the stored value is plaintext (pre-migration row) → return as-is
    - NULL values pass through untouched.

    Searchability: because Fernet uses a random nonce, encrypted values cannot
    be used in WHERE / ORDER BY / LIKE clauses. Index the column only if you
    need exact-match on the raw (encrypted) bytes — which is never useful.
    For columns that must be queryable (e.g. unique constraints) keep them
    plaintext or use a deterministic hash side-column.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        """Encrypt before writing to the DB."""
        if value is None:
            return value
        value = str(value)
        # Already encrypted — don't double-encrypt.
        if is_encrypted(value):
            return value
        return encrypt_value(value)

    def process_result_value(self, value, dialect):
        """Decrypt after reading from the DB; fall back to plaintext for legacy rows."""
        if value is None:
            return value
        if not is_encrypted(value):
            # Pre-migration plaintext row — return as-is; will be encrypted on next save.
            return value
        try:
            return decrypt_value(value)
        except (InvalidToken, ValueError) as exc:
            # Key rotation or corruption: log and return the raw token rather than crashing.
            logger.warning("EncryptedText: failed to decrypt column value: %s", exc)
            return value
        except Exception as exc:
            # Unexpected error — re-raise so real bugs aren't silently swallowed.
            logger.error("EncryptedText: unexpected decryption error: %s", exc)
            raise

