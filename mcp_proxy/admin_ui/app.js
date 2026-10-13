"use strict";
const el = id => document.getElementById(id);
let base = null, candidate = null, busy = false;
const message = (text, error = false) => { el("message").textContent = text; el("message").className = error ? "error" : ""; };
async function api(action, payload) {
  if (window.proxyAdminTransport) return window.proxyAdminTransport(action, payload);
  const response = await fetch(`/config/api/${action}`, {method: payload === undefined ? "GET" : "POST", headers: {"Content-Type":"application/json"}, credentials:"same-origin", body: payload === undefined ? undefined : JSON.stringify(payload)});
  if (!response.ok) {
    const messages = {401:"Your session expired. Sign in again.",403:"Your account or application does not have permission for this change.",409:"Configuration changed since you loaded it. Reload and review your edits.",400:"Invalid configuration. Check JSON, names, references, and supported settings.",502:"The upstream could not be prepared. Your active configuration is unchanged."};
    throw new Error(messages[response.status] || `Request failed (${response.status}).`);
  }
  return response.json();
}
async function perform(operation) {
  if (busy) return;
  busy = true;
  try { await operation(); } catch (error) { message(error.message, true); }
  finally { busy = false; }
}
function invalidate() { candidate = null; el("apply").disabled = true; el("review-section").hidden = true; }
function readEditor() { return JSON.parse(el("config").value); }
function setEditor(value) { el("config").value = JSON.stringify(value, null, 2); invalidate(); renderViews(value); renderServers(value); }
function renderServers(config) {
  el("servers").replaceChildren();
  for (const [name, server] of Object.entries(config.mcp_servers || {})) {
    const row = document.createElement("div"); row.className = "item row";
    const label = document.createElement("span"); label.textContent = `${name} · ${server.url ? "HTTP" : "Local command"}`;
    const edit = document.createElement("button"); edit.className = "secondary"; edit.textContent = `Edit ${name}`;
    edit.onclick = () => { el("server-name").value = name; el("server-transport").value = server.url ? "url" : "command"; el("server-target").value = server.url || server.command; };
    const remove = document.createElement("button"); remove.className = "secondary"; remove.textContent = `Remove ${name}`;
    remove.onclick = () => perform(async () => { const next = readEditor(); delete next.mcp_servers[name]; setEditor(next); });
    row.append(label,edit,remove); el("servers").append(row);
  }
}
function renderViews(config) {
  el("views").replaceChildren();
  for (const [name, view] of Object.entries(config.tool_views || {})) {
    const row = document.createElement("div"); row.className = "item row";
    const label = document.createElement("label"); label.textContent = name;
    const mode = document.createElement("select"); mode.setAttribute("aria-label", `Exposure mode for ${name}`);
    for (const value of ["direct","search","search_per_server"]) { const opt = document.createElement("option"); opt.value = value; opt.textContent = value; mode.append(opt); }
    mode.value = view.exposure_mode || "direct";
    mode.onchange = () => perform(async () => { const next = readEditor(); next.tool_views[name].exposure_mode = mode.value; setEditor(next); });
    const remove = document.createElement("button"); remove.className = "secondary"; remove.textContent = `Remove ${name}`;
    remove.onclick = () => perform(async () => { const next = readEditor(); delete next.tool_views[name]; setEditor(next); });
    row.append(label, mode, remove); el("views").append(row);
  }
}
async function showStatus() { const status = await api("status"); el("identity").textContent = `Signed in as ${status.identity.subject} (${status.identity.issuer})`; el("status").textContent = `${status.runtime_revision ? "Configuration active" : "Ready to connect when a tool is requested"}. ${status.upstreams.length} upstream connections · ${status.in_flight} running calls · ${status.draining_calls} calls finishing on a previous revision.`; el("status-details").textContent = JSON.stringify(status,null,2); }
async function showHistory() {
  const data = await api("history"); el("history").replaceChildren();
  for (const revision of data.revisions) {
    const row = document.createElement("div"); row.className = "item";
    const text = document.createElement("p"); text.textContent = `${revision.id} · ${revision.state} · ${new Date(revision.created * 1000).toLocaleString()}`; row.append(text);
    if (revision.state === "active") { const button = document.createElement("button"); button.className = "secondary"; button.textContent = "Preview rollback"; button.onclick = () => perform(async () => showReview(await api("rollback", {base, target:revision.id}))); row.append(button); }
    el("history").append(row);
  }
}
async function load() { const data = await api("config"); base = data.revision; setEditor(data.config); await showStatus(); await showHistory(); message("Configuration loaded. Changes are saved only when you apply a preview."); }
function showReview(review) {
  candidate = review.revision; el("review").textContent = JSON.stringify(review, null, 2); el("review-section").hidden = false; el("apply").disabled = false; el("probes").replaceChildren();
  for (const server of [...review.impact.mcp_servers.added, ...review.impact.mcp_servers.changed]) {
    const button = document.createElement("button"); button.className = "secondary"; button.textContent = `Test ${server}`;
    button.onclick = () => perform(async () => { const result = await api("probe", {revision:candidate, server}); message(`${server}: ${result.state}, ${result.tool_count} tools.`); }); el("probes").append(button);
  }
  message("Preview ready. Review the changes, then apply.");
}
el("config").addEventListener("input", invalidate);
el("config").addEventListener("change", () => { try {renderViews(readEditor()); renderServers(readEditor());} catch {} });
el("save-server").onclick = () => perform(async () => { const name = el("server-name").value.trim(), kind = el("server-transport").value, target = el("server-target").value.trim(); if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(name) || !target) throw new Error("Enter a server name and connection target."); const config = readEditor(); config.mcp_servers ||= {}; const previous = Object.hasOwn(config.mcp_servers,name) ? config.mcp_servers[name] : {}; const value = {...previous,[kind]:target}; delete value[kind === "url" ? "command" : "url"]; Object.defineProperty(config.mcp_servers,name,{value,enumerable:true,writable:true,configurable:true}); setEditor(config); message("Connection edited. Preview and test it before applying."); });
el("add-view").onclick = () => perform(async () => { const name = el("view-name").value.trim(); if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(name) || ["search","_search","admin"].includes(name)) throw new Error("Enter a valid, non-reserved view name."); const config = readEditor(); config.tool_views ||= {}; if (Object.hasOwn(config.tool_views,name)) throw new Error("View already exists."); Object.defineProperty(config.tool_views,name,{value:{include_all:true,exposure_mode:"direct"},enumerable:true,writable:true,configurable:true}); setEditor(config); el("view-name").value = ""; });
el("preview").onclick = () => perform(async () => { const config = readEditor(); invalidate(); showReview(await api("preview", {base, config})); });
el("apply").onclick = () => perform(async () => { if (!candidate) return; const revision = candidate; el("apply").disabled = true; try { await api("apply", {revision}); await load(); message("Changes applied. Refresh the connector’s tool list if it still shows old tools."); } catch (error) {el("apply").disabled = false; throw error;} });
el("reload").onclick = () => perform(load);
el("refresh").onclick = () => perform(showStatus);
el("logout").onclick = () => perform(async () => { const response = await fetch("/config/logout",{method:"POST",credentials:"same-origin",redirect:"manual"}); if (response.status === 403) throw new Error("Sign out failed. Reload and try again."); location.assign("/config"); });
perform(load);
