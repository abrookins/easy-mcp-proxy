"""Escaped, accessible HTML rendering for the proxy operator UI."""

# ruff: noqa: E501

import html
import json
from typing import Any

_CSS_STYLES = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       max-width: 1200px; margin: 0 auto; padding: 20px; background: #f5f5f5;
       color: #222; }
h1 { color: #333; }
.card { background: white; border-radius: 8px; padding: 20px;
        margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,.1); }
.card h2 { margin-top: 0; color: #555; border-bottom: 1px solid #eee;
           padding-bottom: 10px; }
.form-group { margin-bottom: 15px; }
label { display: block; margin-bottom: 5px; font-weight: 600; color: #444; }
input[type="text"], input[type="search"], select, textarea { width: 100%;
    padding: 10px; border: 1px solid #bbb; border-radius: 4px; background: white; }
textarea { font-family: ui-monospace, monospace; min-height: 200px; }
button { background: #0767c8; color: white; border: none; padding: 10px 20px;
         border-radius: 4px; cursor: pointer; margin-right: 10px; }
button:hover { background: #054f9b; }
button:focus-visible, input:focus-visible, select:focus-visible, summary:focus-visible {
    outline: 3px solid #ffbf47; outline-offset: 2px; }
button.danger { background: #b42331; }
button.danger:hover { background: #8f1b27; }
.alert { padding: 15px; border-radius: 4px; margin-bottom: 20px; }
.alert-success { background: #d4edda; color: #155724; }
.alert-error { background: #f8d7da; color: #721c24; }
.server-item, .view-item, .tool-item { border: 1px solid #ddd; padding: 15px;
    margin-bottom: 10px; border-radius: 6px; overflow-wrap: anywhere; }
.server-item h3, .view-item h3, .tool-item h3 { margin-top: 0; }
code, pre { background: #f4f4f4; border-radius: 3px; }
code { padding: 2px 5px; }
pre { padding: 12px; overflow: auto; max-height: 34rem; white-space: pre-wrap; }
.tabs { display: flex; flex-wrap: wrap; border-bottom: 1px solid #bbb;
        margin-bottom: 20px; gap: 2px; }
.tab { padding: 10px 20px; cursor: pointer; border: none; background: transparent;
       color: #333; margin: 0; }
.tab.active { border-bottom: 3px solid #0767c8; color: #054f9b; }
.tab-content[hidden] { display: none; }
.tool-controls { display: grid; grid-template-columns: minmax(12rem, 1fr) 2fr;
                 gap: 12px; margin-bottom: 16px; }
.tool-meta { color: #555; font-size: .92rem; }
.badge { display: inline-block; border-radius: 999px; padding: 3px 8px;
         margin: 2px 4px 2px 0; background: #e8eef6; }
.badge.preview { background: #dff4e5; color: #145c2d; font-weight: 600; }
.status-warning { color: #7a4d00; }
.status-error { color: #9b1c1c; }
@media (max-width: 600px) {
    body { padding: 10px; }
    .card { padding: 14px; }
    .tabs { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .tab { width: 100%; padding: 10px 6px; }
    .tool-controls { grid-template-columns: 1fr; }
    button { width: 100%; margin: 4px 0; }
}
"""

_JS_SCRIPT = r"""
function activateTab(button) {
    document.querySelectorAll('[role="tab"]').forEach(function(tab) {
        var active = tab === button;
        tab.classList.toggle('active', active);
        tab.setAttribute('aria-selected', String(active));
        tab.setAttribute('tabindex', active ? '0' : '-1');
        var panel = document.getElementById(tab.getAttribute('aria-controls'));
        if (panel) panel.hidden = !active;
    });
}
function appendText(parent, tag, text, className) {
    var node = document.createElement(tag);
    node.textContent = text;
    if (className) node.className = className;
    parent.appendChild(node);
    return node;
}
function renderTools(snapshot) {
    var list = document.getElementById('tool-list');
    var status = document.getElementById('tool-status');
    var stamp = document.getElementById('tool-snapshot-at');
    list.replaceChildren();
    status.textContent = snapshot.status === 'ready' ? 'Registry ready.' :
        snapshot.status === 'empty' ? 'No tools are exposed in this view.' :
        snapshot.status === 'warning' ? 'Registry loaded with warnings.' :
        'Registry metadata is unavailable.';
    status.className = 'status-' + snapshot.status;
    stamp.textContent = snapshot.snapshot_at ? 'Snapshot: ' + snapshot.snapshot_at : '';
    (snapshot.warnings || []).forEach(function(warning) {
        appendText(list, 'p', warning, 'alert alert-error');
    });
    (snapshot.tools || []).forEach(function(tool) {
        var card = document.createElement('article');
        card.className = 'tool-item';
        card.dataset.search = (tool.name + ' ' + tool.description).toLocaleLowerCase();
        appendText(card, 'h3', tool.name);
        appendText(card, 'p', tool.description || 'No description');
        appendText(card, 'p', 'Server: ' + (tool.server || 'custom'), 'tool-meta');
        var parameters = document.createElement('div');
        appendText(parameters, 'strong', 'Accepted parameters: ');
        if (!tool.accepted_parameter_names.length) appendText(parameters, 'span', 'none');
        tool.accepted_parameter_names.forEach(function(name) {
            appendText(parameters, 'code', name, 'badge');
        });
        card.appendChild(parameters);
        if (tool.supports_dry_run) appendText(card, 'span', 'Dry-run preview', 'badge preview');
        var details = document.createElement('details');
        appendText(details, 'summary', 'Show input schema');
        appendText(details, 'pre', JSON.stringify(tool.inputSchema || {}, null, 2));
        card.appendChild(details);
        list.appendChild(card);
    });
    filterTools();
}
function filterTools() {
    var input = document.getElementById('tool-filter');
    if (!input) return;
    var query = input.value.toLocaleLowerCase().trim();
    document.querySelectorAll('.tool-item').forEach(function(card) {
        card.hidden = query !== '' && !card.dataset.search.includes(query);
    });
}
async function loadTools() {
    var section = document.getElementById('tools');
    var select = document.getElementById('tool-view');
    var status = document.getElementById('tool-status');
    status.textContent = 'Loading registry…';
    try {
        var url = new URL(section.dataset.toolsApi, window.location.href);
        url.searchParams.set('view', select.value);
        var response = await fetch(url, {headers: {'Accept': 'application/json'}});
        var payload = await response.json();
        if (!response.ok) throw new Error(payload.message || payload.error || 'Request failed');
        renderTools(payload);
    } catch (error) {
        status.textContent = 'Could not load registry: ' + error.message;
        status.className = 'status-error';
    }
}
document.addEventListener('DOMContentLoaded', function() {
    var tabs = Array.from(document.querySelectorAll('[role="tab"]'));
    tabs.forEach(function(tab, index) {
        tab.addEventListener('click', function() { activateTab(tab); });
        tab.addEventListener('keydown', function(event) {
            if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
            event.preventDefault();
            var offset = event.key === 'ArrowRight' ? 1 : -1;
            var next = tabs[(index + offset + tabs.length) % tabs.length];
            activateTab(next); next.focus();
        });
    });
    var select = document.getElementById('tool-view');
    if (select) select.addEventListener('change', loadTools);
    var filter = document.getElementById('tool-filter');
    if (filter) filter.addEventListener('input', filterTools);
    var restart = document.getElementById('restart-server');
    if (restart) restart.addEventListener('click', function() {
        if (window.confirm('Restart?')) window.location = restart.dataset.restartUrl;
    });
});
"""

_RESTART_CSS = """
body { font-family: sans-serif; text-align: center; padding: 50px; }
.spinner { animation: spin 1s linear infinite; font-size: 2em; }
@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
"""


def build_error_html(title: str, message: str) -> str:
    """Build a simple escaped error page."""
    return f"<h1>{html.escape(title)}</h1><p>{html.escape(message)}</p>"


def render_tools_html(snapshot: dict[str, Any]) -> str:
    """Render canonical metadata without trusting any upstream-controlled text."""
    tools = snapshot.get("tools", [])
    warning_parts = [
        f'<p class="alert alert-error">{html.escape(str(warning))}</p>'
        for warning in snapshot.get("warnings", [])
    ]
    if not tools:
        warning_parts.append(
            '<p class="tool-empty">No tools are exposed in this view.</p>'
        )
        return "".join(warning_parts)
    parts: list[str] = warning_parts
    for tool in tools:
        name = html.escape(str(tool.get("name", "")))
        description = html.escape(str(tool.get("description", "") or "No description"))
        server = html.escape(str(tool.get("server", "") or "custom"))
        search = html.escape(
            f"{tool.get('name', '')} {tool.get('description', '')}".casefold(),
            quote=True,
        )
        accepted = tool.get("accepted_parameter_names", [])
        parameter_html = (
            "".join(
                f'<code class="badge">{html.escape(str(parameter))}</code>'
                for parameter in accepted
            )
            or "<span>none</span>"
        )
        preview_badge = (
            '<span class="badge preview">Dry-run preview</span>'
            if tool.get("supports_dry_run")
            else ""
        )
        schema = html.escape(
            json.dumps(tool.get("inputSchema", {}), indent=2, sort_keys=True)
        )
        parts.append(
            f'<article class="tool-item" data-search="{search}">'
            f"<h3>{name}</h3><p>{description}</p>"
            f'<p class="tool-meta">Server: {server}</p>'
            f"<div><strong>Accepted parameters: </strong>{parameter_html}</div>"
            f"{preview_badge}<details><summary>Show input schema</summary>"
            f"<pre>{schema}</pre></details></article>"
        )
    return "".join(parts)


def build_html_template(
    alert: str,
    servers_html: str,
    views_html: str,
    config_yaml: str,
    save_url: str,
    restart_url: str,
    tools_html: str = '<p class="tool-empty">No registry snapshot available.</p>',
    tool_views: list[str] | None = None,
    tools_api_url: str = "/config/api/tools",
    snapshot_at: str = "",
    registry_status: str = "empty",
) -> str:
    """Build the main operator page from already escaped fragments."""
    view_options = "".join(
        f'<option value="{html.escape(name, quote=True)}">{html.escape(name)}</option>'
        for name in (tool_views or ["default"])
    )
    panels = [
        ("servers", "Servers", "Upstream MCP Servers", servers_html),
        ("views", "Views", "Tool Views", views_html),
        ("tools", "Tools", "Exposed Tool Registry", ""),
        ("yaml", "YAML Editor", "Full Configuration (YAML)", ""),
    ]
    tabs = "".join(
        f'<button type="button" id="tab-{name}" class="tab{(" active" if i == 0 else "")}" '
        f'role="tab" aria-selected="{str(i == 0).lower()}" aria-controls="{name}" '
        f'tabindex="{0 if i == 0 else -1}">{label}</button>'
        for i, (name, label, _, _) in enumerate(panels)
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MCP Proxy Configuration</title><style>{_CSS_STYLES}</style></head>
<body><h1>MCP Proxy Configuration</h1>{alert}
<div class="tabs" role="tablist" aria-label="Configuration sections">{tabs}</div>
<section id="servers" class="tab-content" role="tabpanel" aria-labelledby="tab-servers" tabindex="0">
<div class="card"><h2>Upstream MCP Servers</h2>{servers_html}</div></section>
<section id="views" class="tab-content" role="tabpanel" aria-labelledby="tab-views" tabindex="0" hidden>
<div class="card"><h2>Tool Views</h2>{views_html}</div></section>
<section id="tools" class="tab-content" role="tabpanel" aria-labelledby="tab-tools" tabindex="0" hidden
 data-tools-api="{html.escape(tools_api_url, quote=True)}"><div class="card">
<h2>Exposed Tool Registry</h2><div class="tool-controls">
<div><label for="tool-view">View</label><select id="tool-view">{view_options}</select></div>
<div><label for="tool-filter">Filter tools</label><input id="tool-filter" type="search"
 placeholder="Filter by name or description" autocomplete="off"></div></div>
<p id="tool-status" class="status-{html.escape(registry_status, quote=True)}" role="status" aria-live="polite">
Registry status: {html.escape(registry_status)}.</p>
<p id="tool-snapshot-at" class="tool-meta">{html.escape(("Snapshot: " + snapshot_at) if snapshot_at else "")}</p>
<div id="tool-list">{tools_html}</div></div></section>
<section id="yaml" class="tab-content" role="tabpanel" aria-labelledby="tab-yaml" tabindex="0" hidden>
<div class="card"><h2>Full Configuration (YAML)</h2>
<form method="POST" action="{html.escape(save_url, quote=True)}"><div class="form-group">
<label for="config-yaml">Configuration YAML</label>
<textarea id="config-yaml" name="config_yaml">{html.escape(config_yaml)}</textarea></div>
<button type="submit">Save Configuration</button>
<button id="restart-server" type="button" class="danger" data-restart-url="{html.escape(restart_url, quote=True)}">
Restart Server</button></form></div></section><script>{_JS_SCRIPT}</script></body></html>"""


def build_restart_html(redirect_url: str) -> str:
    """Build the restart page HTML."""
    safe_url = html.escape(redirect_url, quote=True)
    return f"""<!DOCTYPE html><html lang="en"><head><title>Restarting...</title>
<meta http-equiv="refresh" content="3;url={safe_url}"><style>{_RESTART_CSS}</style></head>
<body><div class="spinner" aria-hidden="true">⟳</div><h1>Restarting Server...</h1>
<p>The server is restarting with the new configuration.</p>
<p>You will be redirected automatically in a few seconds.</p></body></html>"""


def render_servers_html(servers: dict[str, Any]) -> str:
    """Render an escaped server list."""
    if not servers:
        return "<p>No servers configured.</p>"
    parts = []
    for name, cfg in servers.items():
        server_type = "HTTP" if cfg.get("url") else "stdio"
        details = (
            cfg.get("url")
            or " ".join(
                [str(cfg.get("command", "")), *map(str, cfg.get("args", []))]
            ).strip()
        )
        parts.append(
            '<div class="server-item">'
            f"<h3>{html.escape(str(name))}</h3>"
            f"<p><strong>Type:</strong> {server_type}</p>"
            f"<p><strong>Details:</strong> <code>{html.escape(str(details))}</code></p>"
            "</div>"
        )
    return "".join(parts)


def render_views_html(views: dict[str, Any]) -> str:
    """Render an escaped view list."""
    if not views:
        return "<p>No views configured.</p>"
    parts = []
    for name, cfg in views.items():
        desc = cfg.get("description", "No description")
        mode = cfg.get("exposure_mode", "direct")
        parts.append(
            '<div class="view-item">'
            f"<h3>{html.escape(str(name))}</h3>"
            f"<p><strong>Description:</strong> {html.escape(str(desc))}</p>"
            f"<p><strong>Mode:</strong> {html.escape(str(mode))}</p></div>"
        )
    return "".join(parts)
