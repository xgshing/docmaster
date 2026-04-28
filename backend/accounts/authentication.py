from __future__ import annotations

import uuid

from rest_framework import exceptions
from rest_framework_simplejwt.authentication import JWTAuthentication


class SingleSessionJWTAuthentication(JWTAuthentication):
    """
    Enforces "single active session per user" using a per-login session id (sid).

    We keep using accounts.User.current_session_key as the authoritative sid.
    When a user logs in, we mint a new sid, store it on the user, and embed it in the JWT.
    Any older tokens will be rejected once current_session_key changes.
    """

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if not getattr(user, "is_enabled", True):
            raise exceptions.PermissionDenied("账号已禁用。")

        token_sid = str(validated_token.get("sid") or "")
        current_sid = str(getattr(user, "current_session_key", "") or "")
        if current_sid and token_sid and token_sid != current_sid:
            raise exceptions.AuthenticationFailed(
                {"detail": "您的账号已在其他设备登录，当前会话已结束。", "code": "session_invalid"},
                code="session_invalid",
            )
        return user


def new_session_id() -> str:
    return uuid.uuid4().hex

