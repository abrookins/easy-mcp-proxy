"""Identity from verified OAuth claims, never from user-supplied tool arguments."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Iterator


class AccessDenied(PermissionError):
    """The caller lacks a provisioned identity or an explicit permission."""


@dataclass(frozen=True)
class Identity:
    issuer: str
    subject: str
    client_id: str
    # Best-effort, verified email used only to match the admin email list.
    # It never identifies the account; issuer and subject do.
    email: str | None = field(default=None, compare=False)

    @classmethod
    def from_verified_token(cls, token) -> "Identity":
        """Accept only the verifier's subject/issuer, with no email fallback."""
        claims = getattr(token, "claims", None)
        if not isinstance(claims, dict):
            raise AccessDenied("Verified OAuth identity required")
        issuer, subject = claims.get("iss"), claims.get("sub")
        client = getattr(token, "client_id", None)
        if not all(isinstance(v, str) and v.strip() for v in (issuer, subject, client)):
            raise AccessDenied("Verified OAuth issuer, subject and client required")
        return cls(issuer, subject, client, verified_email(claims))


def verified_email(claims: dict) -> str | None:
    """Return the token's email if present and verified (when required).

    Falls back to userinfo claims the proxy embedded at sign-in.
    """
    from mcp_proxy.auth import require_verified_email

    upstream = claims.get("upstream_claims")
    if "email" not in claims and isinstance(upstream, dict):
        claims = upstream
    email = claims.get("email")
    if not isinstance(email, str) or not email.strip():
        return None
    if require_verified_email() and claims.get("email_verified") is not True:
        return None
    return email.strip()


@dataclass(frozen=True)
class Principal:
    user_id: str
    identity: Identity
    view: str = "default"


_principal: ContextVar[Principal | None] = ContextVar("proxy_principal", default=None)


def current_principal() -> Principal:
    principal = _principal.get()
    if principal is None:
        raise AccessDenied("Authenticated user required")
    return principal


@contextmanager
def principal_context(principal: Principal) -> Iterator[Principal]:
    marker = _principal.set(principal)
    try:
        yield principal
    finally:
        _principal.reset(marker)
