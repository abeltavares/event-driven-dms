import logging
from datetime import datetime, timedelta, timezone

import jwt

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class JWTAuth:
    """Simple JWT authentication for WebSocket connections."""

    @staticmethod
    def create_token(
        user_id: str,
        email: str,
        expires_delta: timedelta | None = None
    ) -> str:
        """Create JWT token."""
        if expires_delta is None:
            expires_delta = timedelta(hours=24)

        now = datetime.now(timezone.utc)
        expire = now + expires_delta

        payload = {
            "sub": user_id,
            "email": email,
            "exp": expire,
            "iat": now,
        }

        token = jwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm
        )

        return token

    @staticmethod
    def verify_token(token: str) -> dict | None:
        """Verify JWT token and return payload."""
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm]
            )

            logger.info(f"Token verified for user: {payload.get('email')}")
            return payload

        except jwt.ExpiredSignatureError:
            logger.warning("Token expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {e}")
            return None


jwt_auth = JWTAuth()
