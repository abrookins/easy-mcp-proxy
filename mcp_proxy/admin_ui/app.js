/* MCP Proxy administration. Plain DOM, no build step for the browser. All text
   goes through textContent/attributes, never HTML parsing, so config values
   can't inject markup. The embedded MCP App provides window.proxyAdminTransport. */
(function () {
  'use strict';

  var NAME = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/;
  var RESERVED_VIEWS = ['admin', 'search', '_search'];
  var EXPOSURE_MODES = ['direct', 'search', 'search_per_server'];
  var CACHE_DEFAULTS = {
    enabled: true, ttl_seconds: 3600, max_inline_tokens: 3000, max_line_chars: 1200,
    retrieval_default_line_count: 100, retrieval_max_line_count: 500,
    retrieval_max_chars: 12000, strict: true
  };
  var STATUS_MESSAGES = {
    401: 'Your session expired. Sign in again.',
    403: 'Your account or application does not have permission for this change.',
    409: 'Configuration changed since you loaded it. Reload and review your edits.',
    400: 'Invalid request. Check names, references, and supported settings.',
    413: 'The configuration is too large.',
    502: 'The upstream could not be prepared. Your active configuration is unchanged.'
  };

  var embedded = typeof window.proxyAdminTransport === 'function';
  var state = { session: null, base: null, config: null, review: null };

  // ---------- helpers ----------

  function $(id) { return document.getElementById(id); }

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
    // Sandboxed MCP App frames block form submission, so submit buttons call
    // the handler directly; Enter still submits normally in the browser.
    if (tag === 'form' && attrs && attrs.onsubmit) {
      el.addEventListener('click', function (event) {
        if (event.target.closest('button[type="submit"]')) attrs.onsubmit(event);
      });
    }
    return el;
  }

  function append(el, child) {
    if (child === null || child === undefined || child === false) return;
    if (Array.isArray(child)) child.forEach(function (c) { append(el, c); });
    else el.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
  }

  function clone(value) { return value === undefined ? undefined : JSON.parse(JSON.stringify(value)); }
  function isEmpty(obj) { return !obj || Object.keys(obj).length === 0; }
  function enc(name) { return encodeURIComponent(name); }
  function isSecret(v) { return !!v && typeof v === 'object' && Object.keys(v).length === 1 && typeof v.$secret === 'string'; }
  function when(seconds) { return seconds ? new Date(seconds * 1000).toLocaleString() : '—'; }
  // Own-property assignment, so a name like "__proto__" can't touch prototypes.
  function put(obj, key, value) { Object.defineProperty(obj, key, { value: value, enumerable: true, writable: true, configurable: true }); }

  function shellQuote(arg) {
    if (isSecret(arg)) return '••••';
    arg = String(arg);
    return /^[\w@%+=:,./-]+$/.test(arg) ? arg : "'" + arg.replace(/'/g, "'\\''") + "'";
  }

  function commandLine(server) {
    if (server.url) return server.url;
    return [server.command || ''].concat((server.args || []).map(shellQuote)).join(' ').trim();
  }

  function message(text, kind) {
    var el = $('message');
    el.textContent = text || '';
    el.className = kind || '';
    if (text) window.scrollTo(0, 0);
  }

  async function request(method, path, body) {
    var response = await fetch(path, {
      method: method, credentials: 'same-origin',
      headers: body === undefined ? { 'Accept': 'application/json' } : { 'Accept': 'application/json', 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    if (response.status === 401) {
      window.location.assign('/config/login');
      throw new Error(STATUS_MESSAGES[401]);
    }
    if (!response.ok) throw new Error(STATUS_MESSAGES[response.status] || 'Request failed (' + response.status + ').');
    return response.json();
  }

  function api(action, payload) {
    if (embedded) return window.proxyAdminTransport(action, payload);
    return request(payload === undefined ? 'GET' : 'POST', '/config/api/' + action, payload);
  }

  async function perform(operation) {
    try { await operation(); } catch (error) { message(error.message, 'error'); }
  }

  async function loadConfig() {
    var data = await api('config');
    state.base = data.revision;
    state.config = data.config || { mcp_servers: {}, tool_views: {} };
  }

  function isAdmin() { return embedded || (state.session && state.session.admin); }

  // ---------- review / apply ----------

  // Every edit becomes an immutable candidate that must be reviewed and applied.
  async function stage(config, label, afterApply) {
    var review = await api('preview', { base: state.base, config: config });
    state.review = { data: review, label: label, afterApply: afterApply };
    renderReview();
    message('Preview ready. Review the changes, then apply.');
  }

  function changeList(title, section) {
    var items = [];
    ['added', 'changed', 'removed'].forEach(function (kind) {
      section[kind].forEach(function (name) { items.push(h('li', { text: kind + ': ' + name })); });
    });
    return items.length ? h('div', null, h('strong', { text: title }), h('ul', { class: 'changes' }, items)) : null;
  }

  function renderReview() {
    var box = $('review');
    box.replaceChildren();
    box.hidden = !state.review;
    box.className = state.review ? 'panel' : '';
    if (!state.review) return;
    var review = state.review.data;
    var impact = review.impact;
    var servers = impact.mcp_servers;
    var probes = servers.added.concat(servers.changed).map(function (server) {
      return h('button', { type: 'button', class: 'secondary small', text: 'Test ' + server, onclick: function () {
        perform(async function () {
          message('Testing ' + server + '…');
          var result = await api('probe', { revision: review.revision, server: server });
          message(server + ': ' + result.state + ', ' + result.tool_count + ' tools.', result.state === 'connected' ? 'ok' : 'error');
        });
      } });
    });
    var fields = impact.fields.map(function (f) {
      return h('li', null, h('code', { text: f.path.join('.') || '(root)' }), ' ',
        h('span', { class: 'muted', text: JSON.stringify(f.before) + ' → ' + JSON.stringify(f.after) }));
    });
    var unchanged = !servers.added.length && !servers.changed.length && !servers.removed.length &&
      !impact.tool_views.added.length && !impact.tool_views.changed.length && !impact.tool_views.removed.length && !fields.length;
    box.append(
      h('h3', { text: 'Review changes: ' + state.review.label }),
      unchanged ? h('p', { class: 'muted', text: 'No changes from the active configuration.' }) : null,
      changeList('Upstream servers', servers),
      changeList('Views', impact.tool_views),
      impact.upstream_replacements.length ? h('p', { text: 'Connections restarted: ' + impact.upstream_replacements.join(', ') }) : null,
      fields.length ? h('details', null, h('summary', { text: fields.length + ' field changes' }), h('ul', { class: 'changes' }, fields)) : null,
      h('p', { class: 'hint', text: 'Upstream discovery and tool names are checked when you apply. Active calls finish on the current configuration.' }),
      h('div', { class: 'actions' },
        h('button', { type: 'button', id: 'apply', text: 'Apply changes', onclick: applyReview }),
        probes,
        h('span', { class: 'spacer' }),
        h('button', { type: 'button', class: 'secondary', text: 'Discard', onclick: function () {
          state.review = null; renderReview(); message('Changes discarded.');
        } })));
  }

  function applyReview() {
    perform(async function () {
      var pending = state.review;
      $('apply').disabled = true;
      try { await api('apply', { revision: pending.data.revision }); }
      catch (error) { $('apply').disabled = false; throw error; }
      state.review = null;
      await loadConfig();
      renderReview();
      go(pending.afterApply || currentHash() || '#/servers');
      message('Changes applied. Refresh your client’s tool list if it still shows old tools.', 'ok');
    });
  }

  // ---------- reusable editors ----------

  var idCounter = 0;
  function uid(prefix) { idCounter += 1; return prefix + '-' + idCounter; }

  function field(label, input, hint, id) {
    if (id) input.id = id;
    return h('div', { class: 'field' },
      h('label', { for: input.id || null, text: label }), input,
      hint ? h('p', { class: 'hint', text: hint }) : null);
  }

  // A text value that may be a stored secret reference. References are kept
  // unless the user chooses to replace them with a new value.
  function valueInput(value, label, placeholder) {
    var holder = h('span', { class: 'secret' });
    var input = null;
    function edit(initial) {
      input = h('input', { type: 'text', value: initial, placeholder: placeholder, 'aria-label': label, autocomplete: 'off' });
      holder.replaceChildren(input);
    }
    if (isSecret(value)) {
      holder.append(h('code', { text: 'Stored value (hidden)' }),
        h('button', { type: 'button', class: 'secondary small', text: 'Replace', 'aria-label': 'Replace ' + label, onclick: function () { edit(''); input.focus(); } }));
    } else edit(value === undefined || value === null ? '' : String(value));
    return { el: holder, value: function () { return input ? input.value : value; } };
  }

  function kvEditor(obj, keyLabel, valueLabel) {
    var rows = h('div');
    function addRow(key, value) {
      var v = valueInput(value, valueLabel, valueLabel);
      var k = h('input', { type: 'text', value: key || '', placeholder: keyLabel, 'aria-label': keyLabel });
      var row = h('div', { class: 'kv-row' }, k, v.el,
        h('button', { type: 'button', class: 'secondary small', text: 'Remove', onclick: function () { row.remove(); } }));
      row._read = function () { return [k.value.trim(), v.value()]; };
      rows.appendChild(row);
    }
    Object.keys(obj || {}).forEach(function (k) { addRow(k, obj[k]); });
    return {
      el: h('div', null, rows, h('button', { type: 'button', class: 'secondary small', text: 'Add', onclick: function () { addRow(); } })),
      value: function () {
        var out = {};
        Array.prototype.forEach.call(rows.children, function (row) {
          var pair = row._read();
          if (pair[0]) put(out, pair[0], pair[1]);
        });
        return out;
      }
    };
  }

  function listEditor(items, label) {
    var rows = h('div');
    function addRow(value) {
      var v = valueInput(value, label, label);
      var row = h('div', { class: 'kv-row' }, v.el,
        h('button', { type: 'button', class: 'secondary small', text: 'Remove', onclick: function () { row.remove(); } }));
      row._read = v.value;
      rows.appendChild(row);
    }
    (items || []).forEach(addRow);
    return {
      el: h('div', null, rows, h('button', { type: 'button', class: 'secondary small', text: 'Add ' + label.toLowerCase(), onclick: function () { addRow(''); } })),
      value: function () {
        return Array.prototype.map.call(rows.children, function (row) { return row._read(); })
          .filter(function (v) { return isSecret(v) || v !== ''; });
      }
    };
  }

  // Edits a {tool_name: ToolConfig} map. Fields without a form control
  // (aliases, parameters, cache_output) are preserved as-is.
  function toolsEditor(tools) {
    var rows = h('div');
    function addRow(name, cfg) {
      cfg = cfg || {};
      var extras = Object.keys(cfg).filter(function (k) { return ['name', 'description', 'enabled'].indexOf(k) < 0; });
      var row = h('div', { class: 'tool-row' },
        h('input', { type: 'text', class: 'tool-name', value: name || '', placeholder: 'Upstream tool name', 'aria-label': 'Tool name' }),
        h('input', { type: 'text', class: 'tool-rename', value: cfg.name || '', placeholder: 'Rename to (optional)', 'aria-label': 'Rename tool to' }),
        h('label', { class: 'check' }, h('input', { type: 'checkbox', class: 'tool-enabled', checked: cfg.enabled !== false }), 'Enabled'),
        h('button', { type: 'button', class: 'secondary small', text: 'Remove', onclick: function () { row.remove(); } }),
        h('textarea', { class: 'tool-desc', placeholder: 'Description override (optional). Use {original} to include the upstream description.', 'aria-label': 'Description override', value: cfg.description || '' }),
        extras.length ? h('div', { class: 'extra', text: 'Also configured: ' + extras.join(', ') + ' (edit in JSON mode)' }) : null);
      row._original = cfg;
      rows.appendChild(row);
    }
    Object.keys(tools || {}).forEach(function (name) { addRow(name, tools[name]); });
    return {
      el: h('div', null, rows, h('div', { class: 'actions' },
        h('button', { type: 'button', class: 'secondary small', text: 'Add tool', onclick: function () { addRow(); } }))),
      value: function () {
        var out = {};
        Array.prototype.forEach.call(rows.children, function (row) {
          var name = row.querySelector('.tool-name').value.trim();
          if (!name) return;
          var cfg = clone(row._original) || {};
          var rename = row.querySelector('.tool-rename').value.trim();
          var description = row.querySelector('.tool-desc').value;
          if (rename) cfg.name = rename; else delete cfg.name;
          if (description.trim()) cfg.description = description; else delete cfg.description;
          if (row.querySelector('.tool-enabled').checked) delete cfg.enabled; else cfg.enabled = false;
          put(out, name, cfg);
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
    var nameInput = h('input', { type: 'text', value: opts.name || '', required: true, autocomplete: 'off', id: opts.nameId });
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
        jsonInput = h('textarea', { class: 'code tall', 'aria-label': 'JSON', spellcheck: 'false', value: JSON.stringify(current, null, 2) });
        body.append(jsonInput, h('p', { class: 'hint', text: 'Keep {"$secret": "…"} references to preserve stored values; replace one with a new value to rotate it.' }));
      }
      formBtn.setAttribute('aria-pressed', String(mode === 'form'));
      jsonBtn.setAttribute('aria-pressed', String(mode === 'json'));
    }

    function switchMode(next) {
      if (next === mode) return;
      try { current = readValue(); } catch (error) { message(error.message, 'error'); return; }
      mode = next;
      show();
    }

    function submit(event) {
      event.preventDefault();
      perform(async function () {
        var name = nameInput.value.trim();
        var value = readValue();
        if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Value must be a JSON object.');
        opts.validateName(name);
        if (name !== opts.name && opts.exists(name)) throw new Error('"' + name + '" already exists.');
        await opts.onSave(name, value);
      });
    }

    show();
    return h('form', { onsubmit: submit },
      h('div', { class: 'panel' }, field(opts.nameLabel, nameInput, opts.nameHint)),
      h('div', { class: 'panel' }, h('div', { class: 'mode-tabs', role: 'group', 'aria-label': 'Editor mode' }, formBtn, jsonBtn), body),
      h('div', { class: 'actions' },
        h('button', { type: 'submit', text: 'Preview changes' }),
        h('a', { class: 'button secondary', href: opts.backHref, text: 'Cancel' }),
        h('span', { class: 'spacer' }),
        opts.onDelete ? h('button', { type: 'button', class: 'danger', text: 'Delete', onclick: opts.onDelete }) : null));
  }

  function pageHead(title, crumb, extra) {
    return h('div', null,
      crumb ? h('div', { class: 'crumb' }, crumb) : null,
      h('div', { class: 'page-head' }, h('h2', { text: title }), extra || null));
  }

  function table(headers, rows, empty) {
    if (!rows.length) return h('p', { class: 'empty', text: empty });
    return h('table', null,
      h('thead', null, h('tr', null, headers.map(function (t) { return h('th', { text: t }); }))),
      h('tbody', null, rows));
  }

  function linkRow(href, cells) {
    return h('tr', { class: 'clickable', onclick: function () { go(href); } }, cells);
  }

  // ---------- servers ----------

  function serversPage() {
    var servers = state.config.mcp_servers || {};
    return [pageHead('Upstream servers', null, h('a', { class: 'button', href: '#/servers/new', text: 'Add server' })),
      h('p', { class: 'muted', text: 'Adding or changing a connection requires installation operator permission.' }),
      h('div', { class: 'panel', id: 'servers' }, table(['Name', 'Type', 'Command / URL', 'Tools'], Object.keys(servers).map(function (name) {
        var s = servers[name] || {};
        var href = '#/servers/' + enc(name);
        return linkRow(href, [
          h('td', null, h('a', { href: href, text: name })),
          h('td', null, h('span', { class: 'badge', text: s.url ? 'HTTP' : 'stdio' })),
          h('td', null, h('code', { text: commandLine(s) })),
          h('td', { text: s.tools ? Object.keys(s.tools).length + ' allowed' : 'all' })]);
      }), 'No upstream servers yet.'))];
  }

  function serverForm(value) {
    var isHttp = !!value.url;
    var typeName = uid('type');
    var stdioRadio = h('input', { type: 'radio', name: typeName, checked: !isHttp, onchange: toggle });
    var httpRadio = h('input', { type: 'radio', name: typeName, checked: isHttp, onchange: toggle });
    var command = h('input', { type: 'text', value: value.command || '', placeholder: 'uvx' });
    var args = listEditor(value.args, 'Argument');
    var cwd = h('input', { type: 'text', value: value.cwd || '' });
    var env = kvEditor(value.env, 'NAME', 'Value');
    var url = h('input', { type: 'url', value: value.url || '', placeholder: 'https://example.com/mcp' });
    var headers = kvEditor(value.headers, 'Header', 'Value');
    var limit = h('input', { type: 'checkbox', checked: !!value.tools, onchange: toggle });
    var tools = toolsEditor(value.tools);

    var stdioBox = h('div', null,
      field('Command', command, 'The executable to run.', uid('cmd')),
      h('div', { class: 'field' }, h('span', { class: 'label', text: 'Arguments' }), args.el,
        h('p', { class: 'hint', text: 'One argument per row, in order. Stored arguments stay hidden; replace one to change it.' })),
      field('Working directory', cwd, 'Optional.', uid('cwd')),
      h('div', { class: 'field' }, h('span', { class: 'label', text: 'Environment variables' }), env.el));
    var httpBox = h('div', null,
      field('URL', url, 'No credentials or query string; put credentials in headers.', uid('url')),
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
          var argv = args.value();
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
    Object.keys(config.tool_views || {}).forEach(function (key) {
      var view = config.tool_views[key];
      if (view.tools && Object.prototype.hasOwnProperty.call(view.tools, from)) {
        var renamed = {};
        Object.keys(view.tools).forEach(function (k) { put(renamed, k === from ? to : k, view.tools[k]); });
        view.tools = renamed;
      }
      if (view.exclude_servers) view.exclude_servers = view.exclude_servers.map(function (s) { return s === from ? to : s; });
    });
  }

  function validName(kind, reserved) {
    return function (name) {
      if (!NAME.test(name)) throw new Error(kind + ' names use letters, digits, ".", "_" and "-", starting with a letter or digit.');
      if (reserved && reserved.indexOf(name) >= 0) throw new Error('"' + name + '" is reserved.');
    };
  }

  function has(obj, key) { return !!obj && Object.prototype.hasOwnProperty.call(obj, key); }

  function serverEditPage(name) {
    var isNew = name === null;
    var servers = state.config.mcp_servers || {};
    if (!isNew && !has(servers, name)) return notFound('Server', name, '#/servers');
    return [
      pageHead(isNew ? 'Add server' : name, h('a', { href: '#/servers', text: '← Servers' })),
      entryEditor({
        name: isNew ? '' : name,
        nameId: 'server-name',
        value: isNew ? { command: '' } : servers[name],
        nameLabel: 'Server name',
        nameHint: 'Used as the tool namespace and in view configuration.',
        backHref: '#/servers',
        validateName: validName('Server'),
        exists: function (n) { return has(servers, n); },
        renderForm: serverForm,
        onSave: function (newName, value) {
          var config = clone(state.config);
          config.mcp_servers = config.mcp_servers || {};
          if (!isNew && newName !== name) {
            delete config.mcp_servers[name];
            renameServerReferences(config, name, newName);
          }
          put(config.mcp_servers, newName, value);
          return stage(config, 'server "' + newName + '"', '#/servers/' + enc(newName));
        },
        onDelete: isNew ? null : function () {
          if (!window.confirm('Remove server "' + name + '"? You can review before applying.')) return;
          var config = clone(state.config);
          delete config.mcp_servers[name];
          Object.keys(config.tool_views || {}).forEach(function (v) {
            var view = config.tool_views[v];
            if (view.tools) delete view.tools[name];
            if (view.exclude_servers) view.exclude_servers = view.exclude_servers.filter(function (s) { return s !== name; });
          });
          perform(function () { return stage(config, 'remove server "' + name + '"', '#/servers'); });
        }
      })
    ];
  }

  // ---------- views ----------

  function viewEndpoint(name) { return window.location.origin + (name === 'default' ? '/mcp' : '/view/' + enc(name) + '/mcp'); }

  function viewsPage() {
    var views = state.config.tool_views || {};
    return [pageHead('Tool views', null, h('a', { class: 'button', href: '#/views/new', text: 'Add view' })),
      h('p', { class: 'muted', text: 'Give each client a focused set of tools. Client access to views is granted by the installation operator.' }),
      h('div', { class: 'panel', id: 'views' }, table(['Name', 'Description', 'Mode', 'Tools from'], Object.keys(views).map(function (name) {
        var v = views[name] || {};
        var href = '#/views/' + enc(name);
        return linkRow(href, [
          h('td', null, h('a', { href: href, text: name })),
          h('td', { text: v.description || '' }),
          h('td', null, h('span', { class: 'badge', text: v.exposure_mode || 'direct' })),
          h('td', { text: v.include_all ? 'all servers' : Object.keys(v.tools || {}).join(', ') || '—' })]);
      }), 'No views yet.'))];
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
      editors[s] = toolsEditor(viewTools[s]);
      enabledBoxes[s] = h('input', { type: 'checkbox', checked: has(viewTools, s) });
      var body = h('div', null, editors[s].el);
      function sync() { body.hidden = !enabledBoxes[s].checked; }
      enabledBoxes[s].addEventListener('change', sync);
      sync();
      return h('fieldset', null, h('legend', null, h('label', { class: 'check' }, enabledBoxes[s], s)),
        serverNames.indexOf(s) < 0 ? h('p', { class: 'hint status-error', text: 'This server is not configured.' }) : null, body);
    });
    var preCall = h('input', { type: 'text', value: (value.hooks || {}).pre_call || '', placeholder: 'myapp.hooks.before_call' });
    var postCall = h('input', { type: 'text', value: (value.hooks || {}).post_call || '', placeholder: 'myapp.hooks.after_call' });
    var customTools = jsonField(value.custom_tools || [], 'Custom tools', 'List of {"module": "package.module.tool_function"} entries. Requires operator permission.');
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
          h('p', { class: 'hint', text: 'Hooks run trusted Python and require operator permission.' }),
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
        Object.keys(editors).forEach(function (s) { if (enabledBoxes[s].checked) put(tools, s, editors[s].value()); });
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
    if (!isNew && !has(views, name)) return notFound('View', name, '#/views');
    return [
      pageHead(isNew ? 'Add view' : name, h('a', { href: '#/views', text: '← Views' })),
      isNew ? null : h('div', { class: 'panel' }, h('span', { class: 'label', text: 'MCP endpoint ' }), h('code', { text: viewEndpoint(name) })),
      entryEditor({
        name: isNew ? '' : name,
        nameId: 'view-name',
        value: isNew ? { include_all: true } : views[name],
        nameLabel: 'View name',
        nameHint: 'Clients connect at /view/<name>/mcp. The "default" view is served at /mcp.',
        backHref: '#/views',
        validateName: validName('View', RESERVED_VIEWS),
        exists: function (n) { return has(views, n); },
        renderForm: viewForm,
        onSave: function (newName, value) {
          var config = clone(state.config);
          config.tool_views = config.tool_views || {};
          if (!isNew && newName !== name) delete config.tool_views[name];
          put(config.tool_views, newName, value);
          return stage(config, 'view "' + newName + '"', '#/views/' + enc(newName));
        },
        onDelete: isNew ? null : function () {
          if (!window.confirm('Remove view "' + name + '"? You can review before applying.')) return;
          var config = clone(state.config);
          delete config.tool_views[name];
          perform(function () { return stage(config, 'remove view "' + name + '"', '#/views'); });
        }
      })
    ];
  }

  // ---------- settings ----------

  function settingsPage() {
    var config = state.config;
    var cache = Object.assign({}, CACHE_DEFAULTS, config.output_cache || {});
    var inputs = {
      enabled: h('input', { type: 'checkbox', checked: cache.enabled }),
      strict: h('input', { type: 'checkbox', checked: cache.strict })
    };
    ['max_inline_tokens', 'max_line_chars', 'ttl_seconds', 'retrieval_max_chars', 'retrieval_default_line_count', 'retrieval_max_line_count'].forEach(function (k) {
      inputs[k] = h('input', { type: 'number', min: '0', value: String(cache[k]) });
    });

    function submit(event) {
      event.preventDefault();
      perform(function () {
        var next = clone(config);
        var oc = clone(config.output_cache) || {};
        Object.keys(inputs).forEach(function (k) {
          var v = inputs[k].type === 'checkbox' ? inputs[k].checked : Number(inputs[k].value);
          if (v === CACHE_DEFAULTS[k] && !has(config.output_cache, k)) delete oc[k];
          else oc[k] = v;
        });
        if (isEmpty(oc)) delete next.output_cache; else next.output_cache = oc;
        return stage(next, 'output handling', '#/settings');
      });
    }

    function num(label, key) { return field(label, inputs[key], null, uid(key)); }
    var s = state.session;

    return [
      pageHead('Settings'),
      s ? h('div', { class: 'panel' }, h('h3', { text: 'Account' }),
        h('p', null, 'Signed in as ', h('code', { text: s.identity.subject }), ' (', h('code', { text: s.identity.issuer }), ')',
          s.identity.email ? [' · ', h('code', { text: s.identity.email })] : null),
        h('p', null, 'Application ', h('code', { text: s.identity.client_id }), ' · ',
          h('span', { class: 'badge', text: s.admin ? 'admin' : 'no admin' }),
          h('span', { class: 'badge', text: s.operator ? 'operator' : 'not operator' }),
          ' views: ' + s.views.join(', ')),
        h('p', { class: 'hint', text: 'Grants are managed by the installation operator with "mcp-proxy users grant". Verified emails listed in MCP_PROXY_ADMIN_EMAILS are also admins.' })) : null,
      h('form', { onsubmit: submit },
        h('div', { class: 'panel' }, h('h3', { text: 'Output handling' }),
          h('label', { class: 'check' }, inputs.enabled, 'Cache large outputs and return a bounded preview'),
          h('label', { class: 'check' }, inputs.strict, 'Strict (never return oversized output inline)'),
          h('div', { class: 'row' }, num('Max inline tokens', 'max_inline_tokens'), num('Max line length (chars)', 'max_line_chars'), num('Cache TTL (seconds)', 'ttl_seconds')),
          h('div', { class: 'row' }, num('Retrieval max chars', 'retrieval_max_chars'), num('Retrieval default lines', 'retrieval_default_line_count'), num('Retrieval max lines', 'retrieval_max_line_count')),
          h('p', { class: 'hint', text: 'Cache signing and URLs are managed by the service.' })),
        h('div', { class: 'actions' }, h('button', { type: 'submit', text: 'Preview changes' })))
    ];
  }

  // ---------- advanced JSON ----------

  function jsonPage() {
    var area = h('textarea', { id: 'config', class: 'code tall', 'aria-label': 'Configuration JSON', spellcheck: 'false', value: JSON.stringify(state.config, null, 2) });
    function submit(event) {
      event.preventDefault();
      perform(function () {
        var config;
        try { config = JSON.parse(area.value); } catch (e) { throw new Error('Invalid JSON: ' + e.message); }
        return stage(config, 'full configuration', '#/json');
      });
    }
    return [pageHead('Configuration JSON'),
      h('form', { onsubmit: submit },
        h('div', { class: 'panel' }, area,
          h('p', { class: 'hint', text: embedded
            ? 'Existing credentials appear as {"$secret": "…"} references. Use the browser to enter or rotate credentials; embedded tools reject inline secrets.'
            : 'Existing credentials appear as {"$secret": "…"} references. Keep them to preserve values; replace one with a new value to rotate it. Credentials are encrypted after preview.' })),
        h('div', { class: 'actions' }, h('button', { type: 'submit', id: 'preview', text: 'Preview changes' }),
          h('button', { type: 'button', class: 'secondary', text: 'Reload saved configuration', onclick: function () {
            perform(async function () { await loadConfig(); route(); message('Configuration reloaded.'); });
          } })))];
  }

  // ---------- history & status ----------

  function historyPage() {
    var list = h('div', { id: 'history' }, h('p', { class: 'muted', text: 'Loading…' }));
    perform(async function () {
      var data = await api('history');
      list.replaceChildren(table(['Revision', 'State', 'Created', ''], data.revisions.map(function (r) {
        var current = r.id === state.base;
        return h('tr', null,
          h('td', null, h('code', { text: r.id.slice(0, 12) })),
          h('td', null, h('span', { class: 'badge' + (current ? ' ok' : ''), text: current ? 'current' : r.state + (r.error ? ' (' + r.error + ')' : '') })),
          h('td', { text: when(r.created) }),
          h('td', null, r.state === 'active' && !current ? h('button', { type: 'button', class: 'secondary small', text: 'Preview rollback', onclick: function () {
            perform(async function () {
              var review = await api('rollback', { base: state.base, target: r.id });
              state.review = { data: review, label: 'rollback to ' + r.id.slice(0, 12), afterApply: '#/history' };
              renderReview();
              message('Rollback preview ready. Review, then apply.');
            });
          } }) : null));
      }), 'No revisions yet.'));
    });
    return [pageHead('History'), h('p', { class: 'muted', text: 'Rollback creates a new preview and rechecks your current permissions.' }), h('div', { class: 'panel' }, list)];
  }

  function statusPage() {
    var body = h('div', null, h('p', { class: 'muted', text: 'Loading…' }));
    async function load() {
      var s = await api('status');
      body.replaceChildren(
        h('p', { id: 'status', text: (s.runtime_revision ? 'Configuration active' : 'Ready to connect when a tool is requested') + '. ' +
          s.upstreams.length + ' upstream connections · ' + s.in_flight + ' running calls · ' + s.draining_calls + ' calls finishing on a previous revision.' }),
        s.desired_revision && s.runtime_revision && s.desired_revision !== s.runtime_revision
          ? h('p', { class: 'status-error', text: 'The running revision differs from the saved one.' }) : null,
        s.upstreams.length ? h('p', null, 'Connected: ', s.upstreams.map(function (u) { return h('code', { class: 'badge', text: u }); })) : null,
        h('h3', { text: 'Recent events' }),
        table(['Event', 'Revision', 'Application', 'When'], (s.events || []).map(function (e) {
          return h('tr', null, h('td', { text: e.event }), h('td', null, h('code', { text: (e.revision || '').slice(0, 12) })), h('td', { text: e.actor }), h('td', { text: when(e.created) }));
        }), 'No events yet.'),
        h('p', { class: 'hint', text: s.discovery_refresh }));
    }
    perform(load);
    return [pageHead('Status', null, h('button', { type: 'button', class: 'secondary', id: 'refresh', text: 'Refresh', onclick: function () { perform(load); } })),
      h('div', { class: 'panel' }, body)];
  }

  // ---------- API keys ----------

  function keyViewChoices() {
    var granted = state.session.views;
    var names = granted.indexOf('*') >= 0
      ? ['default', 'search'].concat(Object.keys((state.config || {}).tool_views || {}), state.session.admin ? ['admin'] : [])
      : granted.slice();
    return names.filter(function (v, i) { return names.indexOf(v) === i; });
  }

  function keysPage() {
    var tbody = h('tbody');
    var created = h('div');
    var name = h('input', { type: 'text', placeholder: 'e.g. claude-desktop', required: true });
    var viewBoxes = keyViewChoices().map(function (v) {
      return { name: v, input: h('input', { type: 'checkbox', checked: v === 'default' }) };
    });
    var admin = h('input', { type: 'checkbox' });
    var expiry = h('select', null, [['', 'Never'], ['30', '30 days'], ['90', '90 days'], ['365', '1 year']].map(function (o) {
      return h('option', { value: o[0], text: o[1] });
    }));

    async function load() {
      var data = await request('GET', '/config/api/keys');
      tbody.replaceChildren();
      if (!data.keys.length) tbody.appendChild(h('tr', null, h('td', { colspan: '6', class: 'empty', text: 'You have no API keys.' })));
      data.keys.forEach(function (key) {
        var expired = key.expires && key.expires * 1000 <= Date.now();
        var status = key.revoked ? 'revoked' : expired ? 'expired' : 'active';
        tbody.appendChild(h('tr', null,
          h('td', { text: key.name }),
          h('td', { text: key.views.join(', ') || '—' }),
          h('td', { text: key.admin ? 'yes' : 'no' }),
          h('td', { text: when(key.created) }),
          h('td', null, h('span', { class: 'badge' + (status === 'active' ? ' ok' : ' off'), text: status === 'active' && key.expires ? 'expires ' + when(key.expires) : status })),
          h('td', null, status === 'revoked' ? null : h('button', { class: 'danger small', text: 'Revoke', onclick: function () {
            if (!window.confirm('Revoke key "' + key.name + '"? Clients using it stop working immediately. This cannot be undone.')) return;
            perform(async function () { await request('DELETE', '/config/api/keys/' + enc(key.id)); message('Key revoked.', 'ok'); await load(); });
          } }))));
      });
    }

    function submit(event) {
      event.preventDefault();
      perform(async function () {
        var views = viewBoxes.filter(function (b) { return b.input.checked; }).map(function (b) { return b.name; });
        if (!views.length) throw new Error('Choose at least one view.');
        var body = { name: name.value.trim(), views: views, admin: admin.checked };
        if (expiry.value) body.expires_in = Number(expiry.value) * 86400;
        var key = await request('POST', '/config/api/keys', body);
        name.value = '';
        created.replaceChildren(h('div', { class: 'panel' },
          h('h3', { text: 'New key "' + body.name + '"' }),
          h('p', { text: 'Copy this key now. It will not be shown again.' }),
          h('div', { class: 'secret-box' }, h('code', { text: key.token }), h('button', { type: 'button', class: 'secondary', text: 'Copy', onclick: function (e) {
            navigator.clipboard.writeText(key.token).then(function () { e.target.textContent = 'Copied'; });
          } })),
          h('p', { class: 'hint', text: 'Send it as "Authorization: Bearer <key>" to ' + window.location.origin + '/view/<name>/mcp for a granted view.' })));
        await load();
      });
    }

    perform(load);
    return [pageHead('API keys'),
      h('p', { class: 'muted', text: 'Keys let agents connect as you without browser sign-in. A key can use only the views you choose, within your own access.' }),
      created,
      h('div', { class: 'panel' }, h('h3', { text: 'Create a key' }),
        h('form', { onsubmit: submit },
          h('div', { class: 'row' }, field('Name', name, null, uid('keyname')), field('Expires', expiry, null, uid('expiry'))),
          h('div', { class: 'field' }, h('span', { class: 'label', text: 'Views' }),
            viewBoxes.map(function (b) { return h('label', { class: 'check' }, b.input, b.name); })),
          state.session.admin ? h('label', { class: 'check' }, admin, 'Allow configuration administration (also choose the "admin" view to use the admin MCP endpoint)') : null,
          h('div', { class: 'actions' }, h('button', { type: 'submit', text: 'Create key' })))),
      h('div', { class: 'panel' }, h('table', null,
        h('thead', null, h('tr', null, ['Name', 'Views', 'Admin', 'Created', 'Status', ''].map(function (t) { return h('th', { text: t }); }))), tbody))];
  }

  // ---------- shell & routing ----------

  function notFound(kind, name, back) {
    return [pageHead(kind + ' not found'), h('p', null, '"' + name + '" does not exist. ', h('a', { href: back, text: 'Go back' }))];
  }

  // Embedded apps run in about:srcdoc frames, where hash links would navigate
  // away, so they route in memory instead.
  function currentHash() { return embedded ? state.hash || '' : window.location.hash; }

  // Navigate (re-rendering even if the hash is unchanged), keeping the message.
  function go(hash) {
    if (embedded || currentHash() === hash) { state.hash = hash; route(); return; }
    state.keepMessage = true;
    window.location.hash = hash;
  }

  function navItems() {
    var items = [];
    if (isAdmin()) {
      items.push(['section', 'Configure'], ['#/servers', 'Servers'], ['#/views', 'Views'], ['#/settings', 'Settings'], ['#/json', 'JSON'],
        ['section', 'Monitor'], ['#/status', 'Status'], ['#/history', 'History']);
    }
    if (!embedded) items.push(['section', 'Access'], ['#/keys', 'API keys']);
    return items;
  }

  function route() {
    var fallback = isAdmin() ? 'servers' : 'keys';
    var path = (currentHash().replace(/^#/, '').split('?')[0] || '').split('/').filter(Boolean).map(decodeURIComponent);
    var section = path[0] || fallback;
    var pages = {
      servers: function () { return path[1] === undefined ? serversPage() : serverEditPage(path[1] === 'new' ? null : path[1]); },
      views: function () { return path[1] === undefined ? viewsPage() : viewEditPage(path[1] === 'new' ? null : path[1]); },
      settings: settingsPage, json: jsonPage, status: statusPage, history: historyPage
    };
    var content;
    if (section === 'keys' && !embedded) content = keysPage();
    else if (pages[section] && isAdmin()) content = pages[section]();
    else { section = fallback; content = isAdmin() ? serversPage() : keysPage(); }

    $('nav').replaceChildren.apply($('nav'), navItems().map(function (item) {
      if (item[0] === 'section') return h('div', { class: 'section', text: item[1] });
      var active = item[0].slice(2) === section;
      return h('a', { href: item[0], class: active ? 'active' : null, 'aria-current': active ? 'page' : null, text: item[1] });
    }));
    $('page').replaceChildren.apply($('page'), content);
  }

  async function start() {
    if (!embedded) {
      state.session = await request('GET', '/config/api/session');
      $('identity').textContent = state.session.identity.email || state.session.identity.subject;
      $('role').textContent = state.session.admin ? (state.session.operator ? 'operator' : 'admin') : 'keys only';
      $('role').hidden = false;
      $('logout').addEventListener('click', function () {
        perform(async function () {
          var response = await fetch('/config/logout', { method: 'POST', credentials: 'same-origin', redirect: 'manual' });
          if (response.status === 403) throw new Error('Sign out failed. Reload and try again.');
          window.location.assign('/config');
        });
      });
    }
    if (isAdmin()) await loadConfig();
    // The host bridge reveals its "open in browser" link from the status result.
    if (embedded) await api('status');
    document.addEventListener('click', function (event) {
      var link = event.target.closest && event.target.closest('a[href^="#"]');
      if (!link || !embedded) return;
      event.preventDefault();
      message('');
      go(link.getAttribute('href'));
    });
    window.addEventListener('hashchange', function () {
      if (!state.keepMessage) message('');
      state.keepMessage = false;
      route();
    });
    route();
    message(isAdmin() ? 'Configuration loaded. Changes take effect only after you preview and apply them.' : '');
  }

  perform(start);
})();
