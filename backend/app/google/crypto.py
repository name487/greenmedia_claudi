import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from ..config import settings

log = logging.getLogger("greenmedia.google")


def _fernet() -> Fernet:
    key = settings.token_encryption_key
    if not key:
        # Dev fallback so the flow works out of the box; production must set TOKEN_ENCRYPTION_KEY.
        log.warning("TOKEN_ENCRYPTION_KEY not set — deriving a key from JWT_SECRET (development only)")
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.jwt_secret.encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as e:
        raise ValueError("Stored Google token cannot be decrypted — was TOKEN_ENCRYPTION_KEY changed? Reconnect Google.") from e
