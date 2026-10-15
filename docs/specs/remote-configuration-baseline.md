# Configuration baseline and compatibility evidence

Recorded 2026-10-13 on `feat/user-owned-live-configuration`, before implementation.
This is historical baseline evidence, not the current managed-service behavior
or test status. See the [acceptance record](remote-configuration-acceptance.md)
for implementation results and remaining checks.

## Verified baseline

The unchanged suite ran 1,228 tests: 1,227 passed and one failed, with 100%
coverage. The failure is the sibling Upskill build reporting `dev` while
`test_hosted_fixture_smoke_registry_hash_and_version` expects `0.1.0`. The
fixture builds the current sibling checkout without version linker flags.

The launchd service points at a separate `easy-mcp-proxy-deploy` checkout, commit
`73c6449`, and invokes uv. Its environment explicitly configures the upstream
timeout. The development checkout is not the live deployment. No service was
restarted and no live credentials were printed or changed.

The browser cookie fallback fails an immediate create/verify roundtrip without
an Auth0 secret: `_get_session_secret()` creates new material on every call.
The callback also accepts an unsigned return URL as state and derives the user
from token-response fields with a generic `user` fallback. These paths cannot
establish the authenticated user boundary required by this project.

Local FastMCP stores OAuth client registrations, reference-token mappings and
refresh metadata in an encrypted file store by default. The key derives from
the upstream client secret. Losing the store or changing that secret can reject
existing tokens. The reported live restart/login failure is not yet reproduced:
no live restart was performed, and local defaults do not prove deployed storage
durability. Process-level tests must separate this from MCP transport-session loss.

HTTP startup currently shares a config and client manager across default, named,
and search views. Routes and tools are registered at startup. Direct wrappers,
ToolView, search helpers, Python custom tools, hooks and parallel compositions
all need user-owned runtime instances. Output cache files and signed HTTP URLs
also need explicit ownership; changing tool discovery alone is insufficient.

Security plan `1ff53bcd` records changes and rollbacks to resource discovery and
per-view OAuth providers. Preserve root OAuth compatibility and the separate
default `/mcp` and restricted `/view/remote/mcp` semantics during migration.

## Client evidence

| Surface | Documented support | Actual-account verification |
| --- | --- | --- |
| Claude web/desktop | Interactive connectors | Pending private-app test |
| Claude iOS/Android | Interactive connectors | No native device session available in this run |
| ChatGPT web | Private custom MCP apps subject to plan/permissions | Pending private-app test |
| ChatGPT native mobile | Custom MCP help says web only | Unavailable per current documentation |
| Mobile browser | Planned responsive management UI | Pending implementation and browser test |

Sources checked 2026-10-13:

- [Claude interactive connectors](https://support.claude.com/en/articles/13454812-use-interactive-connectors-in-claude)
- [ChatGPT custom MCP apps](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt)

OpenAI's custom-app help distinguishes OAuth login from refresh support and
documents tool-list refresh in workspace settings. Do not assume a server-side
generation update refreshes an existing model conversation automatically.
Private account installation and native-device tests remain explicit release
checks, not claims established by these documentation sources.
