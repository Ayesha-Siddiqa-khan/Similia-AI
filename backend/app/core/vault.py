"""Encrypt user-supplied secrets (their own AI API keys) before they touch the database.

Uses Fernet (AES-128-CBC + HMAC) with a server-side secret from APP_ENCRYPTION_KEY, which is
never stored in the database. Without that secret the stored ciphertext is useless, so a database
leak alone does not expose users' keys. Never log plaintext or ciphertext.
"""

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get_settings


class VaultError(RuntimeError):
    """The vault is unavailable or a value could not be decrypted."""


def _fernet() -> MultiFernet:
    """Encrypts with APP_ENCRYPTION_KEY; decrypts with it or any APP_ENCRYPTION_KEY_PREVIOUS.

    The previous keys (comma separated) exist only so a key can be replaced without locking
    anyone out: see docs/production-runbook.md.
    """
    settings = get_settings()
    secret = settings.app_encryption_key
    if not secret:
        raise VaultError("APP_ENCRYPTION_KEY is not set")
    older = [
        k.strip() for k in (getattr(settings, "app_encryption_key_previous", "") or "").split(",")
    ]
    try:
        return MultiFernet([Fernet(k.encode("utf-8")) for k in [secret, *older] if k])
    except (ValueError, TypeError):
        raise VaultError("An encryption key is not a valid Fernet key") from None


def vault_ready() -> bool:
    try:
        _fernet()
    except VaultError:
        return False
    return True


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        raise VaultError("Stored secret cannot be decrypted (wrong APP_ENCRYPTION_KEY?)") from None


def rotate_secret(token: str) -> str:
    """Re-encrypt a stored value with the current key (a no-op in effect if already current)."""
    try:
        return _fernet().rotate(token.encode("ascii")).decode("ascii")
    except InvalidToken:
        raise VaultError("Stored secret cannot be decrypted with any configured key") from None
