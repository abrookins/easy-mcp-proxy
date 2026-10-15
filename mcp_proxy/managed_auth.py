"""One OAuth resource for all managed views, with legacy token compatibility."""

from fastmcp.server.auth.jwt_issuer import JWTIssuer
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from joserfc.errors import JoseError


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


class ManagedOIDCProxy(SharedResourceOAuth, OIDCProxy):
    """OIDC token exchange for the managed gateway's shared OAuth resource."""
