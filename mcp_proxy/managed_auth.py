"""Managed OAuth compatibility and consent-bound client grants."""

import logging

import httpx
from fastmcp.server.auth.jwt_issuer import JWTIssuer
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from joserfc.errors import JoseError

from mcp_proxy.identity import AccessDenied, Identity

logger = logging.getLogger(__name__)


class MigratingJWTIssuer(JWTIssuer):
    """Mint shared-resource tokens; verify the former /mcp audience as well.

    Both verifiers enforce signature, issuer, expiry and token use. A legacy
    audience never grants access by itself: owner/client/view checks still run.
    """

    def __init__(self, *, legacy_audience, **kwargs):
        super().__init__(**kwargs)
        self.legacy = JWTIssuer(**{**kwargs, "audience": legacy_audience})

    def verify_token(self, token, expected_token_use="access"):
        try:
            return super().verify_token(token, expected_token_use)
        except JoseError:
            return self.legacy.verify_token(token, expected_token_use)


class SharedResourceOAuth:
    """Use the public base URL for discovery and newly issued token audiences.

    Views are authorized within this single resource. Never mutate the shared
    issuer for an incoming view request, which would race concurrent clients.
    """

    def _get_resource_url(self, path=None):
        return self.base_url

    def set_mcp_path(self, mcp_path):
        super().set_mcp_path(mcp_path)
        self._jwt_issuer = MigratingJWTIssuer(
            issuer=str(self.base_url),
            audience=str(self._resource_url),
            signing_key=self._jwt_signing_key,
            legacy_audience=str(self.base_url).rstrip("/") + "/mcp",
        )

    async def authorize(self, client, params):
        # Clients with cached discovery can still request the former resource.
        legacy = str(self.base_url).rstrip("/") + "/mcp"
        if params.resource == legacy:
            params = params.model_copy(update={"resource": str(self._resource_url)})
        return await super().authorize(client, params)


class UserinfoEmailClaims:
    """Best effort: carry the user's email from OIDC userinfo in proxy tokens.

    Access tokens often omit email. The result is embedded in the signed proxy
    token as upstream claims and used only to match the admin email list.
    """

    async def _extract_upstream_claims(self, idp_tokens):
        endpoint = self.oidc_config.userinfo_endpoint
        token = idp_tokens.get("access_token")
        if not endpoint or not token:
            return None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    str(endpoint), headers={"Authorization": f"Bearer {token}"}
                )
                response.raise_for_status()
                info = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        if not isinstance(info, dict):
            return None
        claims = {k: info[k] for k in ("email", "email_verified") if k in info}
        return claims or None


class ConsentedClientGrants:
    """Grant configured views only after upstream identity verification."""

    def enable_self_service_grants(self, store, views) -> None:
        configured = tuple(views)
        if configured and self._require_authorization_consent not in (
            True,
            "remember",
        ):
            raise ValueError("Self-service grants require FastMCP consent")
        self._self_service_store = store
        self._self_service_views = configured

    async def exchange_authorization_code(self, client, authorization_code):
        store = getattr(self, "_self_service_store", None)
        views = getattr(self, "_self_service_views", ())
        if store is None or not views:
            return await super().exchange_authorization_code(client, authorization_code)

        code = await self._code_store.get(key=authorization_code.code)
        verified = None
        if code is not None:
            token_name = (
                "id_token" if self._uses_alternate_verification() else "access_token"
            )
            raw = code.idp_tokens.get(token_name)
            if raw:
                verified = await self._token_validator.verify_token(raw)

        result = await super().exchange_authorization_code(client, authorization_code)
        if verified is None:
            logger.warning(
                "Skipping OAuth self-service grant: upstream identity was not verified"
            )
            return result

        try:
            access = verified.model_copy(update={"client_id": client.client_id})
            identity = Identity.from_verified_token(access)
        except AccessDenied:
            logger.warning(
                "Skipping OAuth self-service grant: verified identity was incomplete"
            )
            return result
        store.grant_consented(identity, views)
        return result


class ManagedOIDCProxy(
    ConsentedClientGrants, UserinfoEmailClaims, SharedResourceOAuth, OIDCProxy
):
    """OIDC token exchange for the managed gateway's shared OAuth resource."""
