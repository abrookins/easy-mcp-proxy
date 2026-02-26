"""HTML templates and rendering functions for web UI.

This module contains all HTML/CSS/JS templates and functions
for rendering the configuration UI pages.
"""

from typing import Any

# CSS styles for the main config page
_CSS_STYLES = """
body { font-family: -apple-system, sans-serif; max-width: 1200px;
       margin: 0 auto; padding: 20px; background: #f5f5f5; }
h1 { color: #333; }
.card { background: white; border-radius: 8px; padding: 20px;
        margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
.card h2 { margin-top: 0; color: #555;
           border-bottom: 1px solid #eee; padding-bottom: 10px; }
.form-group { margin-bottom: 15px; }
label { display: block; margin-bottom: 5px; font-weight: 600; color: #444; }
input[type="text"], textarea { width: 100%; padding: 10px;
    border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }
textarea { font-family: monospace; min-height: 200px; }
button { background: #007bff; color: white; border: none;
         padding: 10px 20px; border-radius: 4px;
         cursor: pointer; margin-right: 10px; }
button:hover { background: #0056b3; }
button.danger { background: #dc3545; }
button.danger:hover { background: #c82333; }
.alert { padding: 15px; border-radius: 4px; margin-bottom: 20px; }
.alert-success { background: #d4edda; color: #155724; }
.alert-error { background: #f8d7da; color: #721c24; }
.server-item, .view-item { border: 1px solid #eee; padding: 15px;
                           margin-bottom: 10px; border-radius: 4px; }
.server-item h3, .view-item h3 { margin-top: 0; }
code { background: #f4f4f4; padding: 2px 5px; border-radius: 3px; }
.tabs { display: flex; border-bottom: 1px solid #ddd; margin-bottom: 20px; }
.tab { padding: 10px 20px; cursor: pointer; border: none; background: none; }
.tab.active { border-bottom: 2px solid #007bff; color: #007bff; }
.tab-content { display: none; }
.tab-content.active { display: block; }
"""

# JavaScript for tab switching
_JS_SCRIPT = """
function showTab(name) {
    document.querySelectorAll('.tab').forEach(
        function(t) { t.classList.remove('active'); }
    );
    document.querySelectorAll('.tab-content').forEach(
        function(t) { t.classList.remove('active'); }
    );
    document.querySelector('[onclick*="' + name + '"]')
        .classList.add('active');
    document.getElementById(name).classList.add('active');
}
"""

# CSS for the restart page
_RESTART_CSS = """
body { font-family: sans-serif; text-align: center; padding: 50px; }
.spinner { animation: spin 1s linear infinite; font-size: 2em; }
@keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}
"""


def build_error_html(title: str, message: str) -> str:
    """Build a simple error HTML page."""
    return f"<h1>{title}</h1><p>{message}</p>"


def build_html_template(
    alert: str,
    servers_html: str,
    views_html: str,
    config_yaml: str,
    save_url: str,
    restart_url: str,
) -> str:
    """Build the main HTML page from parts."""
    restart_js = f"if(confirm('Restart?')) window.location='{restart_url}'"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MCP Proxy Configuration</title>
    <style>{_CSS_STYLES}</style>
</head>
<body>
    <h1>MCP Proxy Configuration</h1>
    {alert}
    <div class="tabs">
        <button class="tab active" onclick="showTab('servers')">Servers</button>
        <button class="tab" onclick="showTab('views')">Views</button>
        <button class="tab" onclick="showTab('yaml')">YAML Editor</button>
    </div>
    <div id="servers" class="tab-content active">
        <div class="card">
            <h2>Upstream MCP Servers</h2>
            {servers_html}
        </div>
    </div>
    <div id="views" class="tab-content">
        <div class="card">
            <h2>Tool Views</h2>
            {views_html}
        </div>
    </div>
    <div id="yaml" class="tab-content">
        <div class="card">
            <h2>Full Configuration (YAML)</h2>
            <form method="POST" action="{save_url}">
                <div class="form-group">
                    <textarea name="config_yaml">{config_yaml}</textarea>
                </div>
                <button type="submit">Save Configuration</button>
                <button type="button" class="danger" onclick="{restart_js}">
                    Restart Server
                </button>
            </form>
        </div>
    </div>
    <script>{_JS_SCRIPT}</script>
</body>
</html>"""


def build_restart_html(redirect_url: str) -> str:
    """Build the restart page HTML."""
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Restarting...</title>
    <meta http-equiv="refresh" content="3;url={redirect_url}">
    <style>{_RESTART_CSS}</style>
</head>
<body>
    <div class="spinner">⟳</div>
    <h1>Restarting Server...</h1>
    <p>The server is restarting with the new configuration.</p>
    <p>You will be redirected automatically in a few seconds.</p>
</body>
</html>"""


def render_servers_html(servers: dict[str, Any]) -> str:
    """Render HTML for server list."""
    if not servers:
        return "<p>No servers configured.</p>"
    html_parts = []
    for name, cfg in servers.items():
        server_type = "HTTP" if cfg.get("url") else "stdio"
        if cfg.get("url"):
            details = cfg.get("url")
        else:
            cmd = cfg.get("command", "")
            args = " ".join(cfg.get("args", []))
            details = f"{cmd} {args}".strip()
        html_parts.append(
            f'<div class="server-item">'
            f"<h3>{name}</h3>"
            f"<p><strong>Type:</strong> {server_type}</p>"
            f"<p><strong>Details:</strong> <code>{details}</code></p>"
            f"</div>"
        )
    return "".join(html_parts)


def render_views_html(views: dict[str, Any]) -> str:
    """Render HTML for views list."""
    if not views:
        return "<p>No views configured.</p>"
    html_parts = []
    for name, cfg in views.items():
        desc = cfg.get("description", "No description")
        mode = cfg.get("exposure_mode", "direct")
        html_parts.append(
            f'<div class="view-item">'
            f"<h3>{name}</h3>"
            f"<p><strong>Description:</strong> {desc}</p>"
            f"<p><strong>Mode:</strong> {mode}</p>"
            f"</div>"
        )
    return "".join(html_parts)
