/* MCP Proxy web UI. Plain DOM, no build step. All text goes through
   textContent/attributes, never HTML parsing, so config values can't inject HTML. */
(function () {
  'use strict';

  var root = document.getElementById('app');
  var PREFIX = root.dataset.prefix;
  var BASE = PREFIX.replace(/\/config$/, '');
  var EXPOSURE_MODES = ['direct', 'search', 'search_per_server'];
  var CACHE_DEFAULTS = {
    enabled: true, ttl_seconds: 3600, max_inline_tokens: 3000, max_line_chars: 1200,
    retrieval_default_line_count: 100, retrieval_max_line_count: 500,
    retrieval_max_chars: 12000, strict: true
  };

  var state = { me: null, config: null, upstream: {}, flash: null };

  // ---------- helpers ----------

  function h(tag, attrs) {
    var el = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      var value = attrs[key];
      if (value === undefined || value === null || value === false) return;
      if (key.slice(0, 2) === 'on') el.addEventListener(key.slice(2), value);
      else if (key === 'class') el.className = value;
      else if (key === 'text') el.textContent = value;
      else if (key === 'value') el.value = value;
      else if (key in el && typeof value !== 'string') el[key] = value;
      else el.setAttribute(key, value === true ? '' : value);
    });
    for (var i = 2; i < arguments.length; i++) append(el, arguments[i]);
    return el;
  }

  function append(el, child) {
    if (child === null || child === undefined || child === false) return;
    if (Array.isArray(child)) child.forEach(function (c) { append(el, c); });
    else el.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
  }

  // Navigate, re-rendering even when the hash is unchanged.
  function go(hash) {
    state.keepFlash = true;
    if (window.location.hash === hash) route(); else window.location.hash = hash;
  }

  function clone(value) { return value === undefined ? undefined : JSON.parse(JSON.stringify(value)); }
  function isEmpty(obj) { return !obj || Object.keys(obj).length === 0; }
  function lines(text) { return text.split('\n').map(function (s) { return s.trim(); }).filter(Boolean); }
  function enc(name) { return encodeURIComponent(name); }

  function shellQuote(arg) {
    arg = String(arg);
    return /^[\w@%+=:,./-]+$/.test(arg) ? arg : "'" + arg.replace(/'/g, "'\\''") + "'";
  }

  function commandLine(server) {
    if (server.url) return server.url;
    return [server.command || ''].concat((server.args || []).map(shellQuote)).join(' ').trim();
  }

  async function api(method, path, body) {
    var headers = { 'Accept': 'application/json', 'X-MCP-Proxy-UI': '1' };
    var payload;
    if (typeof body === 'string') { headers['Content-Type'] = 'text/plain'; payload = body; }
    else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
    var response = await fetch(PREFIX + path, { method: method, headers: headers, body: payload, credentials: 'same-origin' });
    if (response.status === 401) {
      window.location.href = PREFIX + '/login?return_url=' + encodeURIComponent(window.location.pathname);
      throw new Error('Signing in…');
    }
    var type = response.headers.get('content-type') || '';
    var data = type.indexOf('json') >= 0 ? await response.json() : await response.text();
    if (!response.ok) {
      var message = data && typeof data === 'object'
        ? (data.details ? data.details.join('\n') : data.message || data.error)
        : data;
      throw new Error(message || response.statusText);
    }
    return data;
  }

  function flash(message, kind, withRestart) {
    state.flash = { message: message, kind: kind || 'ok', restart: !!withRestart };
    renderFlash();
    window.scrollTo(0, 0);
  }

  function renderFlash() {
    var holder = document.getElementById('flash');
    if (!holder) return;
    holder.replaceChildren();
    var f = state.flash;
    if (!f) return;
    holder.appendChild(h('div', { class: 'flash ' + f.kind, role: f.kind === 'error' ? 'alert' : 'status' },
      h('span', { text: f.message }), h('span', { class: 'spacer' }),
      f.restart && state.me.is_admin ? h('button', { class: 'small', onclick: restartServer, text: 'Restart now' }) : null,
      h('button', { class: 'link', 'aria-label': 'Dismiss', text: '×', onclick: function () { state.flash = null; renderFlash(); } })));
  }

  async function restartServer() {
    if (!window.confirm('Restart the proxy now? Connected clients will be disconnected.')) return;
    try {
      await api('POST', '/restart');
      flash('Restart initiated. Reloading in a few seconds…');
      setTimeout(function () { window.location.reload(); }, 4000);
    } catch (error) { flash('Restart failed: ' + error.message, 'error'); }
  }

  async function saveConfig(config, message) {
    await api('PUT', '/api', config);
    state.config = config;
    flash(message + ' Restart the server to apply changes.', 'ok', true);
  }

  // ---------- reusable editors ----------

  function field(label, input, hint, id) {
    if (id) input.id = id;
    return h('div', { class: 'field' },
      h('label', { for: input.id || null, text: label }), input,
      hint ? h('p', { class: 'hint', text: hint }) : null);
  }

  var idCounter = 0;
  function uid(prefix) { idCounter += 1; return prefix + '-' + idCounter; }

  function kvEditor(obj, keyLabel, valueLabel) {
    var rows = h('div');
    function addRow(key, value) {
      var row = h('div', { class: 'kv-row' },
        h('input', { type: 'text', value: key || '', placeholder: keyLabel, 'aria-label': keyLabel, class: 'k' }),
        h('input', { type: 'text', value: value || '', placeholder: valueLabel, 'aria-label': valueLabel, class: 'v' }),
        h('button', { type: 'button', class: 'secondary small', text: 'Remove', onclick: function () { row.remove(); } }));
      rows.appendChild(row);
    }
    Object.keys(obj || {}).forEach(function (k) { addRow(k, obj[k]); });
    return {
      el: h('div', null, rows, h('button', { type: 'button', class: 'secondary small', text: 'Add', onclick: function () { addRow(); } })),
      value: function () {
        var out = {};
        rows.querySelectorAll('.kv-row').forEach(function (row) {
          var k = row.querySelector('.k').value.trim();
          if (k) out[k] = row.querySelector('.v').value;
        });
        return out;
      }
    };
  }

  // Edits a {tool_name: ToolConfig} map. Fields without a form control
  // (aliases, parameters, cache_output) are preserved as-is.
  function toolsEditor(tools, available) {
    var listId = uid('tools');
    var rows = h('div');
    var datalist = h('datalist', { id: listId }, (available || []).map(function (t) {
      return h('option', { value: t.name, label: t.description ? t.description.slice(0, 80) : null });
    }));

    function addRow(name, cfg) {
      cfg = cfg || {};
      var extras = Object.keys(cfg).filter(function (k) { return ['name', 'description', 'enabled'].indexOf(k) < 0; });
      var row = h('div', { class: 'tool-row' },
        h('input', { type: 'text', class: 'tool-name', value: name || '', list: listId, placeholder: 'Upstream tool name', 'aria-label': 'Tool name' }),
        h('input', { type: 'text', class: 'tool-rename', value: cfg.name || '', placeholder: 'Rename to (optional)', 'aria-label': 'Rename tool to' }),
        h('label', { class: 'check' }, h('input', { type: 'checkbox', class: 'tool-enabled', checked: cfg.enabled !== false }), 'Enabled'),
        h('button', { type: 'button', class: 'secondary small', text: 'Remove', onclick: function () { row.remove(); } }),
        h('textarea', { class: 'tool-desc', placeholder: 'Description override (optional). Use {original} to include the upstream description.', 'aria-label': 'Description override', value: cfg.description || '' }),
        extras.length ? h('div', { class: 'extra', text: 'Also configured: ' + extras.join(', ') + ' (edit in JSON mode)' }) : null);
      row._original = cfg;
      rows.appendChild(row);
    }

    Object.keys(tools || {}).forEach(function (name) { addRow(name, tools[name]); });

    function addMissing() {
      var present = {};
      rows.querySelectorAll('.tool-name').forEach(function (input) { present[input.value.trim()] = true; });
      (available || []).forEach(function (t) { if (!present[t.name]) addRow(t.name, {}); });
    }

    return {
      el: h('div', null, datalist, rows, h('div', { class: 'actions' },
        h('button', { type: 'button', class: 'secondary small', text: 'Add tool', onclick: function () { addRow(); } }),
        available && available.length ? h('button', { type: 'button', class: 'secondary small', text: 'Add all ' + available.length + ' upstream tools', onclick: addMissing }) : null,
        available && available.length ? null : h('span', { class: 'hint', text: 'Upstream tool list unavailable; type tool names manually.' }))),
      value: function () {
        var out = {};
        rows.querySelectorAll('.tool-row').forEach(function (row) {
          var name = row.querySelector('.tool-name').value.trim();
          if (!name) return;
          var cfg = clone(row._original) || {};
          var rename = row.querySelector('.tool-rename').value.trim();
          var description = row.querySelector('.tool-desc').value;
          if (rename) cfg.name = rename; else delete cfg.name;
          if (description.trim()) cfg.description = description; else delete cfg.description;
          if (row.querySelector('.tool-enabled').checked) delete cfg.enabled; else cfg.enabled = false;
          out[name] = cfg;
        });
        return out;
      }
    };
  }

  function jsonField(value, label, hint) {
    var input = h('textarea', { class: 'code', value: JSON.stringify(value, null, 2) });
    return {
      el: field(label, input, hint, uid('json')),
      value: function () {
        try { return JSON.parse(input.value || 'null'); }
        catch (e) { throw new Error(label + ': invalid JSON (' + e.message + ')'); }
      }
    };
  }

  // Name + form/JSON editor for one entry of a config map.
  function entryEditor(opts) {
    var nameInput = h('input', { type: 'text', value: opts.name || '', required: true, autocomplete: 'off' });
    var body = h('div');
    var mode = 'form';
    var current = clone(opts.value) || {};
    var form = null;
    var jsonInput = null;
    var formBtn = h('button', { type: 'button', 'aria-pressed': 'true', text: 'Form', onclick: function () { switchMode('form'); } });
    var jsonBtn = h('button', { type: 'button', 'aria-pressed': 'false', text: 'JSON', onclick: function () { switchMode('json'); } });

    function readValue() {
      if (mode === 'form') return form.value();
      try { return JSON.parse(jsonInput.value); }
      catch (e) { throw new Error('Invalid JSON: ' + e.message); }
    }

    function show() {
      body.replaceChildren();
      if (mode === 'form') { form = opts.renderForm(current); body.appendChild(form.el); }
      else {
        jsonInput = h('textarea', { class: 'code tall', 'aria-label': 'JSON', value: JSON.stringify(current, null, 2) });
        body.appendChild(jsonInput);
        body.appendChild(h('p', { class: 'hint', text: 'Every field from the configuration reference can be set here.' }));
      }
      formBtn.setAttribute('aria-pressed', String(mode === 'form'));
      jsonBtn.setAttribute('aria-pressed', String(mode === 'json'));
    }

    function switchMode(next) {
      if (next === mode) return;
      try { current = readValue(); } catch (error) { flash(error.message, 'error'); return; }
      mode = next;
      show();
    }

    async function submit(event) {
      event.preventDefault();
      var name = nameInput.value.trim();
      var value;
      try { value = readValue(); } catch (error) { flash(error.message, 'error'); return; }
      if (!value || typeof value !== 'object' || Array.isArray(value)) { flash('Value must be a JSON object.', 'error'); return; }
      if (!name) { flash('Name is required.', 'error'); return; }
      if (name !== opts.name && opts.exists(name)) { flash('"' + name + '" already exists.', 'error'); return; }
      try { await opts.onSave(name, value); } catch (error) { flash(error.message, 'error'); }
    }

    show();
    return h('form', { onsubmit: submit },
      h('div', { class: 'panel' }, field(opts.nameLabel, nameInput, opts.nameHint, uid('name'))),
      h('div', { class: 'panel' }, h('div', { class: 'mode-tabs', role: 'group', 'aria-label': 'Editor mode' }, formBtn, jsonBtn), body),
      h('div', { class: 'actions' },
        h('button', { type: 'submit', text: 'Save' }),
        h('a', { class: 'button secondary', href: opts.backHref, text: 'Cancel' }),
        h('span', { class: 'spacer' }),
        opts.onDelete ? h('button', { type: 'button', class: 'danger', text: 'Delete', onclick: opts.onDelete }) : null));
  }

  function pageHead(title, crumb, extra) {
    return h('div', null,
      crumb ? h('div', { class: 'crumb' }, crumb) : null,
      h('div', { class: 'page-head' }, h('h2', { text: title }), extra || null));
  }

  // ---------- servers ----------

  function serversPage() {
    var servers = state.config.mcp_servers || {};
    var names = Object.keys(servers);
    var table = names.length ? h('table', null,
      h('thead', null, h('tr', null, ['Name', 'Type', 'Command / URL', 'Tools'].map(function (t) { return h('th', { text: t }); }))),
      h('tbody', null, names.map(function (name) {
        var s = servers[name] || {};
        var href = '#/servers/' + enc(name);
        return h('tr', { class: 'clickable', onclick: function () { location.hash = href; } },
          h('td', null, h('a', { href: href, text: name })),
          h('td', null, h('span', { class: 'badge', text: s.url ? 'HTTP' : 'stdio' })),
          h('td', null, h('code', { text: commandLine(s) })),
          h('td', { text: s.tools ? Object.keys(s.tools).length + ' allowed' : 'all' }));
      })))
      : h('p', { class: 'empty', text: 'No upstream servers yet.' });
    return [pageHead('Upstream servers', null, h('a', { class: 'button', href: '#/servers/new', text: 'Add server' })),
      h('div', { class: 'panel' }, table)];
  }

  function serverForm(value) {
    var isHttp = !!value.url;
    var typeName = uid('type');
    var stdioRadio = h('input', { type: 'radio', name: typeName, checked: !isHttp, onchange: toggle });
    var httpRadio = h('input', { type: 'radio', name: typeName, checked: isHttp, onchange: toggle });
    var command = h('input', { type: 'text', value: value.command || '', placeholder: 'uvx' });
    var args = h('textarea', { class: 'code', value: (value.args || []).join('\n'), placeholder: 'mcp-server-fetch\n--flag' });
    var cwd = h('input', { type: 'text', value: value.cwd || '' });
    var env = kvEditor(value.env, 'NAME', 'value or ${ENV_VAR}');
    var url = h('input', { type: 'url', value: value.url || '', placeholder: 'https://example.com/mcp' });
    var headers = kvEditor(value.headers, 'Header', 'value or ${ENV_VAR}');
    var limit = h('input', { type: 'checkbox', checked: !!value.tools, onchange: toggle });
    var tools = toolsEditor(value.tools, state.upstream[state.editingServer] || []);

    var stdioBox = h('div', null,
      field('Command', command, 'The executable to run.', uid('cmd')),
      field('Arguments', args, 'One argument per line. Spaces within a line are kept as part of that argument.', uid('args')),
      field('Working directory', cwd, 'Optional.', uid('cwd')),
      h('div', { class: 'field' }, h('span', { class: 'label', text: 'Environment variables' }), env.el));
    var httpBox = h('div', null,
      field('URL', url, null, uid('url')),
      h('div', { class: 'field' }, h('span', { class: 'label', text: 'Headers' }), headers.el));
    var toolsBox = h('div', null, tools.el);

    function toggle() {
      stdioBox.hidden = httpRadio.checked;
      httpBox.hidden = !httpRadio.checked;
      toolsBox.hidden = !limit.checked;
    }
    toggle();

    return {
      el: h('div', null,
        h('fieldset', null, h('legend', { text: 'Transport' }),
          h('label', { class: 'check' }, stdioRadio, 'stdio (local command)'),
          h('label', { class: 'check' }, httpRadio, 'HTTP (remote URL)')),
        stdioBox, httpBox,
        h('fieldset', null, h('legend', { text: 'Tools' }),
          h('label', { class: 'check' }, limit, 'Only expose the tools listed below'),
          h('p', { class: 'hint', text: 'Server-level renames and descriptions apply to every view.' }),
          toolsBox)),
      value: function () {
        var out = clone(value);
        ['command', 'args', 'cwd', 'env', 'url', 'headers', 'tools'].forEach(function (k) { delete out[k]; });
        if (httpRadio.checked) {
          out.url = url.value.trim();
          var hv = headers.value();
          if (!isEmpty(hv)) out.headers = hv;
        } else {
          out.command = command.value.trim();
          var argv = args.value.split('\n').filter(function (line) { return line.trim() !== ''; });
          if (argv.length) out.args = argv;
          if (cwd.value.trim()) out.cwd = cwd.value.trim();
          var ev = env.value();
          if (!isEmpty(ev)) out.env = ev;
        }
        if (limit.checked) out.tools = tools.value();
        return out;
      }
    };
  }

  function renameServerReferences(config, from, to) {
    Object.values(config.tool_views || {}).forEach(function (view) {
      if (view.tools && from in view.tools) {
        var renamed = {};
        Object.keys(view.tools).forEach(function (k) { renamed[k === from ? to : k] = view.tools[k]; });
        view.tools = renamed;
      }
      if (view.exclude_servers) view.exclude_servers = view.exclude_servers.map(function (s) { return s === from ? to : s; });
    });
  }

  function serverEditPage(name) {
    var isNew = name === null;
    var servers = state.config.mcp_servers || {};
    if (!isNew && !(name in servers)) return notFound('Server', name, '#/servers');
    state.editingServer = name;
    return [
      pageHead(isNew ? 'Add server' : name, h('a', { href: '#/servers', text: '← Servers' })),
      entryEditor({
        name: isNew ? '' : name,
        value: isNew ? { command: '' } : servers[name],
        nameLabel: 'Server name',
        nameHint: 'Used as the tool namespace and in view configuration.',
        backHref: '#/servers',
        exists: function (n) { return n in servers; },
        renderForm: serverForm,
        onSave: async function (newName, value) {
          var config = clone(state.config);
          config.mcp_servers = config.mcp_servers || {};
          if (!isNew && newName !== name) {
            delete config.mcp_servers[name];
            renameServerReferences(config, name, newName);
          }
          config.mcp_servers[newName] = value;
          await saveConfig(config, 'Server "' + newName + '" saved.');
          go('#/servers/' + enc(newName));
        },
        onDelete: isNew ? null : async function () {
          if (!window.confirm('Delete server "' + name + '"?')) return;
          var config = clone(state.config);
          delete config.mcp_servers[name];
          try {
            await saveConfig(config, 'Server "' + name + '" deleted.');
            go('#/servers');
          } catch (error) { flash(error.message, 'error'); }
        }
      })
    ];
  }

  // ---------- views ----------

  function viewEndpoint(name) { return window.location.origin + BASE + '/view/' + enc(name) + '/mcp'; }

  function viewsPage() {
    var views = state.config.tool_views || {};
    var names = Object.keys(views);
    var table = names.length ? h('table', null,
      h('thead', null, h('tr', null, ['Name', 'Description', 'Mode', 'Tools from'].map(function (t) { return h('th', { text: t }); }))),
      h('tbody', null, names.map(function (name) {
        var v = views[name] || {};
        var href = '#/views/' + enc(name);
        var from = v.include_all ? 'all servers' : Object.keys(v.tools || {}).join(', ') || '—';
        return h('tr', { class: 'clickable', onclick: function () { location.hash = href; } },
          h('td', null, h('a', { href: href, text: name })),
          h('td', { text: v.description || '' }),
          h('td', null, h('span', { class: 'badge', text: v.exposure_mode || 'direct' })),
          h('td', { text: from }));
      })))
      : h('p', { class: 'empty', text: 'No views yet. Without views, all server tools are exposed at the root endpoint.' });
    return [pageHead('Tool views', null, h('a', { class: 'button', href: '#/views/new', text: 'Add view' })),
      h('div', { class: 'panel' }, table)];
  }

  function viewForm(value) {
    var serverNames = Object.keys(state.config.mcp_servers || {});
    var description = h('textarea', { value: value.description || '' });
    var mode = h('select', null, EXPOSURE_MODES.map(function (m) {
      return h('option', { value: m, text: m, selected: (value.exposure_mode || 'direct') === m });
    }));
    var includeAll = h('input', { type: 'checkbox', checked: !!value.include_all, onchange: toggle });
    var excluded = {};
    var excludeBox = h('div', { class: 'field' }, h('span', { class: 'label', text: 'Exclude servers' }),
      serverNames.map(function (s) {
        excluded[s] = h('input', { type: 'checkbox', checked: (value.exclude_servers || []).indexOf(s) >= 0 });
        return h('label', { class: 'check' }, excluded[s], s);
      }));
    var viewTools = value.tools || {};
    var editors = {};
    var enabledBoxes = {};
    var toolSets = serverNames.concat(Object.keys(viewTools).filter(function (s) { return serverNames.indexOf(s) < 0; })).map(function (s) {
      editors[s] = toolsEditor(viewTools[s], state.upstream[s] || []);
      enabledBoxes[s] = h('input', { type: 'checkbox', checked: s in viewTools });
      var body = h('div', null, editors[s].el);
      function sync() { body.hidden = !enabledBoxes[s].checked; }
      enabledBoxes[s].addEventListener('change', sync);
      sync();
      return h('fieldset', null, h('legend', null, h('label', { class: 'check' }, enabledBoxes[s], s)),
        serverNames.indexOf(s) < 0 ? h('p', { class: 'hint status-error', text: 'This server is not configured.' }) : null, body);
    });
    var preCall = h('input', { type: 'text', value: (value.hooks || {}).pre_call || '', placeholder: 'myapp.hooks.before_call' });
    var postCall = h('input', { type: 'text', value: (value.hooks || {}).post_call || '', placeholder: 'myapp.hooks.after_call' });
    var customTools = jsonField(value.custom_tools || [], 'Custom tools', 'List of {"module": "package.module.tool_function"} entries.');
    var composite = jsonField(value.composite_tools || {}, 'Composite tools', 'Map of tool name to {description, inputs, parallel}.');
    var toolsBox = h('div', null, h('p', { class: 'hint', text: 'Check a server to include its tools. With no tools listed, nothing from that server is exposed.' }), toolSets);

    function toggle() { excludeBox.hidden = !includeAll.checked; }
    toggle();

    return {
      el: h('div', null,
        field('Description', description, 'Shown to MCP clients connecting to this view.', uid('desc')),
        field('Exposure mode', mode, 'direct: every tool is registered. search: one search_tools/call_tool pair. search_per_server: one pair per server.', uid('mode')),
        h('fieldset', null, h('legend', { text: 'Tools' }),
          h('label', { class: 'check' }, includeAll, 'Include every tool from all servers'),
          excludeBox, toolsBox),
        h('fieldset', null, h('legend', { text: 'Hooks' }),
          h('div', { class: 'row' }, field('Pre-call hook', preCall, null, uid('pre')), field('Post-call hook', postCall, null, uid('post')))),
        h('fieldset', null, h('legend', { text: 'Advanced' }), customTools.el, composite.el)),
      value: function () {
        var out = clone(value);
        ['description', 'exposure_mode', 'include_all', 'exclude_servers', 'tools', 'hooks', 'custom_tools', 'composite_tools'].forEach(function (k) { delete out[k]; });
        if (description.value.trim()) out.description = description.value;
        if (mode.value !== 'direct') out.exposure_mode = mode.value;
        if (includeAll.checked) {
          out.include_all = true;
          var ex = Object.keys(excluded).filter(function (s) { return excluded[s].checked; });
          if (ex.length) out.exclude_servers = ex;
        }
        var tools = {};
        Object.keys(editors).forEach(function (s) { if (enabledBoxes[s].checked) tools[s] = editors[s].value(); });
        if (!isEmpty(tools)) out.tools = tools;
        var hooks = {};
        if (preCall.value.trim()) hooks.pre_call = preCall.value.trim();
        if (postCall.value.trim()) hooks.post_call = postCall.value.trim();
        if (!isEmpty(hooks)) out.hooks = hooks;
        var ct = customTools.value();
        if (ct && ct.length) out.custom_tools = ct;
        var cp = composite.value();
        if (!isEmpty(cp)) out.composite_tools = cp;
        return out;
      }
    };
  }

  function viewEditPage(name) {
    var isNew = name === null;
    var views = state.config.tool_views || {};
    if (!isNew && !(name in views)) return notFound('View', name, '#/views');
    return [
      pageHead(isNew ? 'Add view' : name, h('a', { href: '#/views', text: '← Views' }),
        isNew ? null : h('a', { class: 'button secondary', href: '#/tools?view=' + enc(name), text: 'Browse exposed tools' })),
      isNew ? null : h('div', { class: 'panel' }, h('span', { class: 'label', text: 'MCP endpoint ' }), h('code', { text: viewEndpoint(name) })),
      entryEditor({
        name: isNew ? '' : name,
        value: isNew ? {} : views[name],
        nameLabel: 'View name',
        nameHint: 'Clients connect at /view/<name>/mcp. A view named "default" is served at the root endpoint.',
        backHref: '#/views',
        exists: function (n) { return n in views; },
        renderForm: viewForm,
        onSave: async function (newName, value) {
          var config = clone(state.config);
          config.tool_views = config.tool_views || {};
          if (!isNew && newName !== name) delete config.tool_views[name];
          config.tool_views[newName] = value;
          await saveConfig(config, 'View "' + newName + '" saved.');
          go('#/views/' + enc(newName));
        },
        onDelete: isNew ? null : async function () {
          if (!window.confirm('Delete view "' + name + '"?')) return;
          var config = clone(state.config);
          delete config.tool_views[name];
          try {
            await saveConfig(config, 'View "' + name + '" deleted.');
            go('#/views');
          } catch (error) { flash(error.message, 'error'); }
        }
      })
    ];
  }

  // ---------- settings ----------

  function settingsPage() {
    var config = state.config;
    var cache = Object.assign({}, CACHE_DEFAULTS, config.output_cache || {});
    var admins = h('textarea', { value: (config.admins || []).join('\n'), placeholder: 'you@example.com' });
    var inputs = {
      enabled: h('input', { type: 'checkbox', checked: cache.enabled }),
      strict: h('input', { type: 'checkbox', checked: cache.strict })
    };
    ['max_inline_tokens', 'max_line_chars', 'ttl_seconds', 'retrieval_max_chars', 'retrieval_default_line_count', 'retrieval_max_line_count'].forEach(function (k) {
      inputs[k] = h('input', { type: 'number', min: '0', value: String(cache[k]) });
    });
    var baseUrl = h('input', { type: 'url', value: config.cache_base_url || '', placeholder: 'https://proxy.example.com' });
    var secret = h('input', { type: 'password', value: config.cache_secret || '', autocomplete: 'off' });

    async function submit(event) {
      event.preventDefault();
      var next = clone(config);
      var adminList = lines(admins.value);
      if (adminList.length) next.admins = adminList; else delete next.admins;
      var me = state.me.email && state.me.email.toLowerCase();
      if (state.me.auth_enabled && adminList.map(function (a) { return a.toLowerCase(); }).indexOf(me) < 0 &&
          !window.confirm('Your email is not in the admin list. You will lose access to configuration. Continue?')) return;

      var oc = clone(config.output_cache) || {};
      Object.keys(inputs).forEach(function (k) {
        var v = inputs[k].type === 'checkbox' ? inputs[k].checked : Number(inputs[k].value);
        if (v === CACHE_DEFAULTS[k] && !(config.output_cache && k in config.output_cache)) delete oc[k];
        else oc[k] = v;
      });
      if (isEmpty(oc)) delete next.output_cache; else next.output_cache = oc;
      if (baseUrl.value.trim()) next.cache_base_url = baseUrl.value.trim(); else delete next.cache_base_url;
      if (secret.value) next.cache_secret = secret.value; else delete next.cache_secret;
      try { await saveConfig(next, 'Settings saved.'); go('#/settings'); } catch (error) { flash(error.message, 'error'); }
    }

    function num(label, key, hint) { return field(label, inputs[key], hint, uid(key)); }

    return [
      pageHead('Server settings'),
      h('form', { onsubmit: submit },
        h('div', { class: 'panel' }, h('h3', { text: 'Admins' }),
          field('Admin emails', admins, 'One per line. Signed-in users with these emails can change configuration. Everyone else who can sign in gets read-only access to tools and their own API keys.', uid('admins'))),
        h('div', { class: 'panel' }, h('h3', { text: 'Output handling' }),
          h('label', { class: 'check' }, inputs.enabled, 'Cache large outputs and return a bounded preview'),
          h('label', { class: 'check' }, inputs.strict, 'Strict (never return oversized output inline)'),
          h('div', { class: 'row' }, num('Max inline tokens', 'max_inline_tokens'), num('Max line length (chars)', 'max_line_chars'), num('Cache TTL (seconds)', 'ttl_seconds')),
          h('div', { class: 'row' }, num('Retrieval max chars', 'retrieval_max_chars'), num('Retrieval default lines', 'retrieval_default_line_count'), num('Retrieval max lines', 'retrieval_max_line_count')),
          h('div', { class: 'row' },
            field('Cache base URL', baseUrl, 'Public URL used in cached-output download links.', uid('baseurl')),
            field('Cache signing secret', secret, 'HMAC secret for cache URLs. Leave empty to generate one at startup.', uid('secret')))),
        h('div', { class: 'actions' }, h('button', { type: 'submit', text: 'Save settings' }), h('span', { class: 'spacer' }),
          h('button', { type: 'button', class: 'danger', text: 'Restart server', onclick: restartServer })))
    ];
  }

  // ---------- YAML ----------

  function yamlPage() {
    var area = h('textarea', { class: 'code tall', 'aria-label': 'Configuration YAML', value: 'Loading…', disabled: true });
    api('GET', '/api/yaml').then(function (text) { area.value = text; area.disabled = false; })
      .catch(function (error) { flash(error.message, 'error'); });
    async function submit(event) {
      event.preventDefault();
      try {
        await api('PUT', '/api/yaml', area.value);
        state.config = await api('GET', '/api');
        flash('Configuration saved. Restart the server to apply changes.', 'ok', true);
      } catch (error) { flash(error.message, 'error'); }
    }
    return [pageHead('Configuration YAML'),
      h('form', { onsubmit: submit },
        h('div', { class: 'panel' }, area,
          h('p', { class: 'hint', text: 'Saved as overrides next to the config file; the original YAML is not modified. Values like ${VAR} are expanded from the environment at startup.' })),
        h('div', { class: 'actions' }, h('button', { type: 'submit', text: 'Save' })))];
  }

  // ---------- tools registry ----------

  function toolsPage(params) {
    var select = h('select', { id: 'tool-view' }, h('option', { value: params.get('view') || 'default', text: params.get('view') || 'default' }));
    var filter = h('input', { type: 'search', id: 'tool-filter', placeholder: 'Filter by name or description', autocomplete: 'off' });
    var status = h('p', { class: 'muted', role: 'status', 'aria-live': 'polite' });
    var list = h('div');

    function applyFilter() {
      var q = filter.value.toLowerCase().trim();
      list.querySelectorAll('.tool-card').forEach(function (card) { card.hidden = q !== '' && card.dataset.search.indexOf(q) < 0; });
    }

    async function load() {
      status.textContent = 'Loading…';
      try {
        var snap = await api('GET', '/api/tools?view=' + enc(select.value));
        var current = select.value;
        select.replaceChildren.apply(select, (snap.available_views || [current]).map(function (v) {
          return h('option', { value: v, text: v, selected: v === current });
        }));
        list.replaceChildren();
        (snap.warnings || []).forEach(function (w) { list.appendChild(h('p', { class: 'flash error', text: w })); });
        (snap.tools || []).forEach(function (tool) {
          list.appendChild(h('article', { class: 'tool-card', 'data-search': (tool.name + ' ' + (tool.description || '')).toLowerCase() },
            h('h4', { text: tool.name }),
            h('p', { text: tool.description || 'No description' }),
            h('p', { class: 'muted' }, 'Server: ' + (tool.server || 'custom'),
              tool.supports_dry_run ? h('span', { class: 'badge ok', text: 'Dry-run preview' }) : null),
            h('div', null, h('strong', { text: 'Parameters: ' }),
              tool.accepted_parameter_names.length ? tool.accepted_parameter_names.map(function (p) { return h('code', { class: 'badge', text: p }); }) : 'none'),
            h('details', null, h('summary', { text: 'Input schema' }), h('pre', { text: JSON.stringify(tool.inputSchema || {}, null, 2) }))));
        });
        status.textContent = (snap.tools || []).length + ' tools' + (snap.snapshot_at ? ' · snapshot ' + snap.snapshot_at : '');
        applyFilter();
      } catch (error) { status.textContent = 'Could not load tools: ' + error.message; }
    }

    select.addEventListener('change', load);
    filter.addEventListener('input', applyFilter);
    load();
    return [pageHead('Exposed tools'),
      h('div', { class: 'panel' },
        h('div', { class: 'row' }, field('View', select), field('Filter', filter)),
        status, list)];
  }

  // ---------- API keys ----------

  function keysPage() {
    var tbody = h('tbody');
    var created = h('div');
    var name = h('input', { type: 'text', placeholder: 'e.g. laptop, CI', required: true });

    async function load() {
      try {
        var data = await api('GET', '/api/keys');
        tbody.replaceChildren();
        if (!data.keys.length) tbody.appendChild(h('tr', null, h('td', { colspan: '4', class: 'empty', text: 'You have no API keys.' })));
        data.keys.forEach(function (key) {
          tbody.appendChild(h('tr', null,
            h('td', { text: key.name }),
            h('td', null, h('code', { text: key.prefix + '…' })),
            h('td', { text: key.created_at }),
            h('td', null, h('button', { class: 'danger small', text: 'Revoke', onclick: async function () {
              if (!window.confirm('Revoke key "' + key.name + '"? Clients using it will stop working.')) return;
              try { await api('DELETE', '/api/keys/' + enc(key.id)); flash('Key revoked.'); load(); }
              catch (error) { flash(error.message, 'error'); }
            } }))));
        });
      } catch (error) { flash(error.message, 'error'); }
    }

    async function submit(event) {
      event.preventDefault();
      try {
        var key = await api('POST', '/api/keys', { name: name.value });
        name.value = '';
        var code = h('code', { text: key.key });
        created.replaceChildren(h('div', { class: 'panel' },
          h('h3', { text: 'New key "' + key.name + '"' }),
          h('p', { text: 'Copy this key now. It will not be shown again.' }),
          h('div', { class: 'secret-box' }, code, h('button', { type: 'button', class: 'secondary', text: 'Copy', onclick: function (e) {
            navigator.clipboard.writeText(key.key).then(function () { e.target.textContent = 'Copied'; });
          } })),
          h('p', { class: 'hint', text: 'Use it as a header: Authorization: Bearer <key>' })));
        load();
      } catch (error) { flash(error.message, 'error'); }
    }

    load();
    return [pageHead('API keys'),
      h('p', { class: 'muted', text: 'Keys authenticate MCP clients and API calls as you (' + state.me.email + ').' }),
      created,
      h('div', { class: 'panel' }, h('h3', { text: 'Create a key' }),
        h('form', { onsubmit: submit, class: 'actions' }, h('div', { style: 'flex:1' }, field('Name', name, null, uid('keyname'))), h('button', { type: 'submit', text: 'Create key' }))),
      h('div', { class: 'panel' }, h('table', null,
        h('thead', null, h('tr', null, ['Name', 'Key', 'Created', ''].map(function (t) { return h('th', { text: t }); }))), tbody))];
  }

  // ---------- shell & routing ----------

  function notFound(kind, name, back) {
    return [pageHead(kind + ' not found'), h('p', null, '"' + name + '" does not exist. ', h('a', { href: back, text: 'Go back' }))];
  }

  function navItems() {
    var items = [];
    if (state.me.is_admin) {
      items.push(['section', 'Configure'], ['#/servers', 'Servers'], ['#/views', 'Views'], ['#/settings', 'Settings'], ['#/yaml', 'YAML']);
    }
    items.push(['section', 'Use'], ['#/tools', 'Tools']);
    if (state.me.api_keys_enabled) items.push(['#/keys', 'API keys']);
    return items;
  }

  function route() {
    var hash = window.location.hash.replace(/^#/, '') || (state.me.is_admin ? '/servers' : '/tools');
    var parts = hash.split('?');
    var path = parts[0].split('/').filter(Boolean).map(decodeURIComponent);
    var params = new URLSearchParams(parts[1] || '');
    var section = path[0];
    var adminPages = { servers: 1, views: 1, settings: 1, yaml: 1 };
    var content;

    if (adminPages[section] && !state.me.is_admin) {
      content = [pageHead('Admins only'), h('p', { text: 'Ask an admin to add your email to the admin list.' })];
    } else if (section === 'servers') {
      content = path[1] === undefined ? serversPage() : serverEditPage(path[1] === 'new' ? null : path[1]);
    } else if (section === 'views') {
      content = path[1] === undefined ? viewsPage() : viewEditPage(path[1] === 'new' ? null : path[1]);
    } else if (section === 'settings') content = settingsPage();
    else if (section === 'yaml') content = yamlPage();
    else if (section === 'keys' && state.me.api_keys_enabled) content = keysPage();
    else content = toolsPage(params);

    var nav = h('nav', { class: 'sidebar', 'aria-label': 'Sections' }, navItems().map(function (item) {
      if (item[0] === 'section') return h('div', { class: 'section', text: item[1] });
      var active = item[0].slice(2) === (section || (state.me.is_admin ? 'servers' : 'tools'));
      return h('a', { href: item[0], class: active ? 'active' : null, 'aria-current': active ? 'page' : null, text: item[1] });
    }));

    root.replaceChildren(
      h('header', { class: 'topbar' },
        h('h1', { text: 'MCP Proxy' }),
        state.me.email ? h('span', { text: state.me.email }) : null,
        h('span', { class: 'badge', text: state.me.is_admin ? 'admin' : 'read-only' }),
        state.me.auth_enabled ? h('a', { href: PREFIX + '/logout', text: 'Sign out' }) : h('span', { class: 'badge off', text: 'auth disabled' })),
      h('div', { class: 'layout' }, nav, h('main', null, h('div', { id: 'flash' }), content)));
    renderFlash();
  }

  async function start() {
    try {
      state.me = await api('GET', '/api/me');
      if (state.me.is_admin) {
        var results = await Promise.all([api('GET', '/api'), api('GET', '/api/upstream-tools')]);
        state.config = results[0];
        state.upstream = results[1];
      }
    } catch (error) {
      root.replaceChildren(h('p', { class: 'flash error', text: 'Could not load: ' + error.message }));
      return;
    }
    window.addEventListener('hashchange', function () {
      if (!state.keepFlash) state.flash = null;
      state.keepFlash = false;
      route();
    });
    route();
  }

  start();
})();
