"""Identity from verified OAuth claims, never from user-supplied tool arguments."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator


class AccessDenied(PermissionError):
    """The caller lacks a provisioned identity or an explicit permission."""


@dataclass(frozen=True)
class Identity:
    issuer: str
    subject: str
    client_id: str

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
        return cls(issuer, subject, client)


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
