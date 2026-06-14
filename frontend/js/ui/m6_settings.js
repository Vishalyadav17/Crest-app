/* m6_settings.js — Settings module */

let _m6Loaded = false;
let _m6ActiveTab = 'profile';
let _m6Profile = null;
let _m6Prefs = null;

function loadSettings() {
  if (_m6Loaded) return;
  _m6Loaded = true;
  _m6RenderShell();
  _m6SwitchTab('profile');
}

function _m6RenderShell() {
  const tabs = [
    { id: 'profile',     icon: 'person',         label: 'Profile' },
    { id: 'holdings',    icon: 'refresh',         label: 'Holdings' },
    { id: 'preferences', icon: 'tune',            label: 'Preferences' },
    { id: 'model',       icon: 'psychology',      label: 'Model Config' },
    { id: 'mf',          icon: 'account_balance', label: 'MF Tools' },
    { id: 'backup',      icon: 'backup',          label: 'Backup' },
    { id: 'connections', icon: 'link',            label: 'Connections' },
    { id: 'order_flow',  icon: 'trending_up',     label: 'Order Flow' },
  ];
  const railHtml = tabs.map(t => `
    <div class="m6-tab" data-m6tab="${t.id}" onclick="_m6SwitchTab('${t.id}')">
      <span class="material-symbols-outlined">${t.icon}</span>
      ${t.label}
      ${t.badge ? `<span class="m6-tab-badge">${t.badge}</span>` : ''}
    </div>`).join('');

  document.getElementById('m6Shell').innerHTML = `
    <div class="m6-layout">
      <nav class="m6-rail">
        <div class="m6-rail-hdr">Settings</div>
        ${railHtml}
      </nav>
      <div class="m6-content" id="m6Pane"></div>
    </div>
    <div class="m6-toast" id="m6Toast"></div>`;
}

function _m6SwitchTab(tab) {
  _m6ActiveTab = tab;
  document.querySelectorAll('.m6-tab').forEach(el => {
    el.classList.toggle('active', el.dataset.m6tab === tab);
  });
  const pane = document.getElementById('m6Pane');
  if (!pane) return;
  const render = { profile: _m6RenderProfile, holdings: _m6RenderHoldings,
    preferences: _m6RenderPreferences, model: _m6RenderModel,
    mf: _m6RenderMF, backup: _m6RenderBackup, connections: _m6RenderConnections,
    order_flow: _m6RenderOrderFlow };
  (render[tab] || _m6RenderProfile)();
}

function _m6ShowToast(msg, type = 'ok') {
  const t = document.getElementById('m6Toast');
  if (!t) return;
  t.textContent = msg;
  t.className = `m6-toast ${type} show`;
  setTimeout(() => { t.classList.remove('show'); }, 3000);
}

/* ── Profile ─────────────────────────────────────────────────────────────── */
async function _m6RenderProfile() {
  const pane = document.getElementById('m6Pane');
  pane.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:24px">Loading…</div>';
  try { _m6Profile = await api('/api/settings/profile'); } catch(e) { _m6Profile = null; }
  if (!_m6Profile) {
    pane.innerHTML = '<div style="color:var(--red);font-size:12px;padding:24px">Failed to load profile.</div>';
    return;
  }
  const p = _m6Profile;
  const memberSince = p.created_at ? new Date(p.created_at).toLocaleDateString('en-IN', {year:'numeric',month:'short',day:'numeric'}) : '–';
  pane.innerHTML = `
    <div class="m6-section-title">Profile</div>
    <div class="m6-section-sub">Your account details and session control.</div>
    <div class="m6-card">
      <div class="m6-card-title">Account</div>
      <div class="m6-field-row">
        <div><div class="m6-field-label">Email</div></div>
        <div class="m6-field-val">${p.email}</div>
      </div>
      <div class="m6-field-row">
        <div><div class="m6-field-label">Name</div></div>
        <div class="m6-field-val">${p.name || '–'}</div>
      </div>
      <div class="m6-field-row">
        <div><div class="m6-field-label">Tier</div></div>
        <span class="m6-badge ${p.tier}">${p.tier.toUpperCase()}</span>
      </div>
      <div class="m6-field-row">
        <div><div class="m6-field-label">Member since</div></div>
        <div class="m6-field-val">${memberSince}</div>
      </div>
    </div>
    <div class="m6-card">
      <div class="m6-card-title">Session</div>
      <div style="display:flex;align-items:center;justify-content:space-between;">
        <div>
          <div class="m6-field-label">Sign out</div>
          <div style="font-size:10px;color:var(--muted);margin-top:2px;font-family:var(--font-display)">Clears your session and returns to login.</div>
        </div>
        <button class="m6-btn m6-btn-danger" onclick="doLogout()">Sign out</button>
      </div>
    </div>`;
}

/* ── Holdings ────────────────────────────────────────────────────────────── */
function _m6RenderHoldings() {
  document.getElementById('m6Pane').innerHTML = `
    <div class="m6-section-title">Holdings</div>
    <div class="m6-section-sub">Sync your portfolio data from Zerodha Kite.</div>
    <div class="m6-card">
      <div class="m6-card-title">Refresh from broker</div>
      <div style="display:flex;align-items:center;justify-content:space-between;">
        <div>
          <div class="m6-field-label">Recompute portfolio snapshot</div>
          <div style="font-size:10px;color:var(--muted);margin-top:2px;font-family:var(--font-display)">Recalculates total wealth, P&L, and allocation from current holdings.</div>
        </div>
        <button class="m6-btn m6-btn-primary" id="m6RefreshBtn" data-action="m6-refresh-holdings">
          <span class="material-symbols-outlined" style="font-size:15px">refresh</span>
          Refresh
        </button>
      </div>
      <div id="m6RefreshResult" style="margin-top:12px;font-size:11px;color:var(--muted);font-family:var(--font-display)"></div>
    </div>`;
}

async function _m6DoRefreshHoldings() {
  const btn = document.getElementById('m6RefreshBtn');
  const res = document.getElementById('m6RefreshResult');
  if (!btn) return;
  btn.disabled = true;
  btn.innerHTML = '<span class="material-symbols-outlined" style="font-size:15px;animation:spin360 0.7s linear infinite">refresh</span> Refreshing…';
  try {
    const data = await apiFetch('/api/settings/refresh-holdings', { method: 'POST' });
    if (data && data.ok) {
      const at = data.computed_at ? new Date(data.computed_at).toLocaleTimeString('en-IN') : '';
      if (res) res.textContent = `Snapshot updated${at ? ' at ' + at : ''}`;
      _m6ShowToast('Holdings refreshed', 'ok');
    }
  } catch(e) {
    if (res) res.textContent = 'Refresh failed — check server logs.';
    _m6ShowToast('Refresh failed', 'err');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span class="material-symbols-outlined" style="font-size:15px">refresh</span> Refresh';
  }
}

/* ── Preferences ─────────────────────────────────────────────────────────── */
async function _m6RenderPreferences() {
  const pane = document.getElementById('m6Pane');
  pane.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:24px">Loading…</div>';
  try { _m6Prefs = await api('/api/settings/preferences'); } catch(e) { _m6Prefs = {}; }
  const p = _m6Prefs || {};
  pane.innerHTML = `
    <div class="m6-section-title">Preferences</div>
    <div class="m6-section-sub">UI and notification settings.</div>
    <div class="m6-card">
      <div class="m6-card-title">Display</div>
      ${_m6ToggleRow('privacy_mode', 'Privacy mode', 'Blur sensitive numbers in the portfolio view.', p.privacy_mode)}
    </div>
    <div class="m6-card">
      <div class="m6-card-title">Notifications</div>
      ${_m6ToggleRow('digest_morning_opt_in', 'Morning digest', 'Daily 7:30 AM IST email with portfolio + market summary.', p.digest_morning_opt_in)}
      ${_m6ToggleRow('digest_eod_opt_in', 'End-of-day digest', 'Daily 4:30 PM IST email + Telegram with P&L and scanner picks.', p.digest_eod_opt_in)}
    </div>
    <div class="m6-card">
      <div class="m6-card-title">Alert Channels</div>
      ${_m6ToggleRow('alert_telegram_enabled', 'Telegram alerts', 'Price-band entry zones, SL/target hits, scan picks & pruning via Telegram bot. Link in Connections.', p.alert_telegram_enabled)}
      ${_m6ToggleRow('alert_email_enabled', 'Email alerts', 'Send the same alerts and digests over email.', p.alert_email_enabled)}
    </div>
    <div class="m6-card">
      <div class="m6-card-title">Automation</div>
      ${_m6ToggleRow('auto_prune_enabled', 'Auto-prune picks', 'Nightly job removes scanner picks whose thesis has broken (SL hit, sharp drop).', p.auto_prune_enabled)}
    </div>`;
}

function _m6ToggleRow(key, label, sub, checked) {
  const id = `m6pref_${key}`;
  return `<div class="m6-toggle-row">
    <div class="m6-toggle-left">
      <div class="label">${label}</div>
      <div class="sub">${sub}</div>
    </div>
    <label class="m6-toggle">
      <input type="checkbox" id="${id}" ${checked ? 'checked' : ''} onchange="_m6SavePref('${key}', this.checked)">
      <div class="m6-toggle-track"></div>
      <div class="m6-toggle-thumb"></div>
    </label>
  </div>`;
}

async function _m6SavePref(key, value) {
  try {
    await apiFetch('/api/settings/preferences', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [key]: value }),
    });
    _m6ShowToast('Saved', 'ok');
  } catch(e) {
    _m6ShowToast('Save failed', 'err');
  }
}

/* ── Model Config (BYOK keys) ────────────────────────────────────────────── */
const _M6_PROVIDERS_DEFAULT = [
  { id: 'groq',       label: 'Groq',          hint: 'Free · fast · used first' },
  { id: 'openrouter', label: 'OpenRouter',    hint: 'Free models routed' },
  { id: 'gemini',     label: 'Google Gemini', hint: 'Free tier' },
  { id: 'github',     label: 'GitHub Models', hint: 'Free with PAT' },
  { id: 'ollama',     label: 'Ollama',        hint: 'Local · no key' },
];
let _M6_PROVIDERS = _M6_PROVIDERS_DEFAULT;
api('/api/settings/providers').then(rows => {
  if (rows?.length) _M6_PROVIDERS = rows.map(r => ({ id: r.name, label: r.label, hint: r.key_hint }));
}).catch(() => {});

async function _m6RenderModel() {
  const pane = document.getElementById('m6Pane');
  pane.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:24px">Loading…</div>';
  let keys = [];
  try { const d = await api('/api/settings/keys'); keys = d.keys || []; } catch(e) {}

  const opts = _M6_PROVIDERS.map(p => `<option value="${p.id}">${p.label} — ${p.hint}</option>`).join('');

  pane.innerHTML = `
    <div class="m6-section-title">Model Config</div>
    <div class="m6-section-sub">Bring your own keys. Crest routes free models first (Groq → OpenRouter → …); your keys unlock AI verdicts, scan reviews and the daily market note. Keys are encrypted at rest and never leave this server.</div>

    <div class="m6-card">
      <div class="m6-card-title">Add a provider key</div>
      <div class="m6-key-form">
        <select id="m6KeyProvider" class="m6-input">${opts}</select>
        <input id="m6KeyLabel" class="m6-input" placeholder="Label (optional)" maxlength="40">
        <input id="m6KeyValue" class="m6-input" type="password" placeholder="Paste API key" autocomplete="off">
        <button class="m6-btn m6-btn-primary" data-action="m6-key-add">
          <span class="material-symbols-outlined" style="font-size:15px">add</span> Add key
        </button>
      </div>
      <div id="m6KeyFormMsg" class="m6-key-formmsg"></div>
    </div>

    <div class="m6-card">
      <div class="m6-card-title">Your keys</div>
      <div id="m6KeyList">${_m6KeyListHtml(keys)}</div>
    </div>`;
}

function _m6KeyListHtml(keys) {
  if (!keys.length) {
    return `<div style="font-size:11px;color:var(--muted);font-family:var(--font-display);padding:8px 0">No keys yet. Add one above to enable AI features. Until then, free providers are used when available.</div>`;
  }
  return keys.map(k => {
    const prov = _M6_PROVIDERS.find(p => p.id === k.provider);
    const provLabel = prov ? prov.label : k.provider;
    const st = (k.status || 'untested').toLowerCase();
    const stClass = st === 'active' || st === 'ok' || st === 'valid' ? 'ok' : st === 'invalid' || st === 'error' ? 'err' : 'idle';
    const cooling = k.rl_cooldown_until && new Date(k.rl_cooldown_until) > new Date();
    return `<div class="m6-key-row" data-id="${k.id}">
      <div class="m6-key-main">
        <div class="m6-key-prov">${provLabel}${k.key_label && k.key_label !== 'default' ? ` · ${k.key_label}` : ''}</div>
        <div class="m6-key-mask">${k.key_masked || '••••'}</div>
      </div>
      <span class="m6-key-status ${stClass}">${cooling ? 'cooling down' : st}</span>
      <div class="m6-key-actions">
        <button class="m6-btn m6-btn-secondary m6-btn-sm" data-action="m6-key-test" data-id="${k.id}">Test</button>
        <button class="m6-btn m6-btn-danger m6-btn-sm" data-action="m6-key-delete" data-id="${k.id}">Delete</button>
      </div>
    </div>`;
  }).join('');
}

async function _m6DoKeyAdd() {
  const prov = document.getElementById('m6KeyProvider')?.value;
  const label = document.getElementById('m6KeyLabel')?.value.trim() || 'default';
  const key = document.getElementById('m6KeyValue')?.value.trim();
  const msg = document.getElementById('m6KeyFormMsg');
  if (!key) { if (msg) { msg.className = 'm6-key-formmsg err'; msg.textContent = 'Paste an API key first.'; } return; }
  try {
    await apiFetch('/api/settings/keys', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: prov, key_label: label, key }),
    });
    _m6ShowToast('Key added', 'ok');
    document.getElementById('m6KeyValue').value = '';
    document.getElementById('m6KeyLabel').value = '';
    _m6RenderModel();
  } catch(e) {
    if (msg) { msg.className = 'm6-key-formmsg err'; msg.textContent = 'Could not add key — ' + (e.message || 'rejected'); }
    _m6ShowToast('Add failed', 'err');
  }
}

function _m6ShortErr(err) {
  if (!err) return 'failed';
  const m = String(err).match(/"message"\s*:\s*"([^"]+)"/);
  let s = m ? m[1] : String(err);
  return s.length > 90 ? s.slice(0, 90) + '…' : s;
}

async function _m6DoKeyTest(id) {
  const row = document.querySelector(`.m6-key-row[data-id="${id}"]`);
  const badge = row?.querySelector('.m6-key-status');
  if (badge) { badge.className = 'm6-key-status idle'; badge.textContent = 'testing…'; }
  try {
    const d = await apiFetch('/api/settings/keys/' + id + '/test', { method: 'POST' });
    if (badge) {
      const ok = d && d.ok;
      badge.className = 'm6-key-status ' + (ok ? 'ok' : 'err');
      badge.textContent = ok ? 'active' : 'failed';
      badge.title = ok ? '' : (d.error || 'failed');
    }
    if (!(d && d.ok) && d && d.error) _m6ShowToast(_m6ShortErr(d.error), 'err');
    else _m6ShowToast(d && d.ok ? 'Key works' : 'Key test failed', d && d.ok ? 'ok' : 'err');
  } catch(e) {
    if (badge) { badge.className = 'm6-key-status err'; badge.textContent = 'failed'; badge.title = String(e.message || e); }
    _m6ShowToast('Test failed', 'err');
  }
}

async function _m6DoKeyDelete(id) {
  try {
    await apiFetch('/api/settings/keys/' + id, { method: 'DELETE' });
    _m6ShowToast('Key removed', 'ok');
    _m6RenderModel();
  } catch(e) {
    _m6ShowToast('Delete failed', 'err');
  }
}

function _m6RenderMF() {
  const pane = document.getElementById('m6Pane');
  pane.innerHTML = `
    <div class="m6-section-title">MF Tools</div>
    <div class="m6-section-sub">Import mutual fund holdings and manage scheme codes.</div>

    <div class="m6-card">
      <div class="m6-card-title">Import CAS (Consolidated Account Statement)</div>
      <div style="font-size:11px;color:var(--muted);margin-bottom:12px">
        Upload your CAMS / KFin CAS PDF. Password is usually your PAN in uppercase.
        Existing CAS holdings will be replaced; Kite and manual entries are untouched.
      </div>
      <div style="display:flex;flex-direction:column;gap:8px">
        <label class="m6-field-label">CAS PDF</label>
        <div class="m6-file">
          <label class="m6-file-btn"><span class="material-symbols-outlined">upload_file</span>Choose PDF
            <input type="file" id="casFileInput" accept=".pdf" onchange="document.getElementById('casFileName').textContent=this.files[0]?this.files[0].name:'No file selected'">
          </label>
          <span class="m6-file-name" id="casFileName">No file selected</span>
        </div>
        <label class="m6-field-label" style="margin-top:4px">Password (PAN)</label>
        <input type="password" id="casPasswordInput" class="m6-input" placeholder="e.g. ABCDE1234F" autocomplete="off">
        <button class="m6-btn m6-btn-primary" style="margin-top:8px;width:max-content" data-action="m6-cas-upload" id="casUploadBtn">
          Parse &amp; Preview
        </button>
      </div>
      <div id="casError" style="color:var(--red);font-size:11px;margin-top:8px;display:none"></div>
      <div id="casPreview" style="display:none;margin-top:16px">
        <div id="casSummaryLine" style="font-size:12px;color:var(--muted);margin-bottom:8px"></div>
        <div style="overflow-x:auto;max-height:280px;overflow-y:auto">
          <table style="width:100%;font-size:11px" id="casPreviewTable"></table>
        </div>
        <div style="display:flex;gap:8px;margin-top:12px">
          <button class="m6-btn m6-btn-primary" data-action="m6-cas-confirm" id="casConfirmBtn">Confirm Import</button>
          <button class="m6-btn m6-btn-secondary" data-action="m6-cas-cancel">Cancel</button>
        </div>
      </div>
      <div id="casSuccess" style="color:var(--green);font-size:11px;margin-top:8px;display:none"></div>
    </div>

    <div class="m6-card">
      <div class="m6-card-title">Scheme Codes</div>
      <div style="font-size:11px;color:var(--muted);margin-bottom:12px">
        Link each holding to its AMFI scheme code to unlock NAV history charts and accurate daily NAV.
      </div>
      <div id="mfSchemeLinkList"><div style="color:var(--muted);font-size:12px">Loading holdings…</div></div>
    </div>`;
  _m6LoadSchemeLinkList();
}

async function _m6LoadSchemeLinkList() {
  const el = document.getElementById('mfSchemeLinkList');
  if (!el) return;
  let d;
  try { d = await api('/api/portfolio/mf'); } catch (e) { d = null; }
  const holdings = (d && d.holdings) || [];
  if (!holdings.length) { el.innerHTML = '<div style="color:var(--muted);font-size:12px">No mutual fund holdings.</div>'; return; }
  el.innerHTML = holdings.map(f => {
    const linked = !!f.scheme_code;
    const right = linked
      ? `<span class="m6-link-ok"><span class="material-symbols-outlined">check_circle</span>${f.scheme_code}</span>`
      : `<button class="m6-btn m6-btn-secondary m6-btn-sm" onclick="_openMFSchemeSearch(${f.id},'${(f.name||'').replace(/'/g,'')}')">Link code</button>`;
    return `<div class="m6-link-row">
      <div><div class="m6-link-name">${f.name}</div>${f.amc ? `<div class="m6-link-sub">${f.amc}</div>` : ''}</div>
      ${right}
    </div>`;
  }).join('');
}

let _casParsedFunds = null;

async function _m6DoCasUpload() {
  const fileInput = document.getElementById('casFileInput');
  const pwInput   = document.getElementById('casPasswordInput');
  const errEl     = document.getElementById('casError');
  const previewEl = document.getElementById('casPreview');
  const successEl = document.getElementById('casSuccess');
  const btn       = document.getElementById('casUploadBtn');

  errEl.style.display = 'none';
  successEl.style.display = 'none';
  previewEl.style.display = 'none';
  _casParsedFunds = null;

  if (!fileInput.files.length) { errEl.textContent = 'Select a PDF file.'; errEl.style.display = ''; return; }
  const pw = pwInput.value.trim();
  if (!pw) { errEl.textContent = 'Enter the PDF password.'; errEl.style.display = ''; return; }

  btn.disabled = true; btn.textContent = 'Parsing…';

  const fd = new FormData();
  fd.append('file', fileInput.files[0]);
  fd.append('password', pw);

  try {
    const resp = await fetch('/api/settings/mf/cas-upload', { method: 'POST', body: fd });
    const d    = await resp.json();
    if (!resp.ok) {
      const detail = d.detail || d.error || 'Parse failed.';
      errEl.textContent = detail;
      errEl.style.display = '';
      return;
    }
    _casParsedFunds = d.funds;
    document.getElementById('casSummaryLine').textContent =
      `Found ${d.imported} fund(s) across ${d.folios} folio(s). Review below then confirm.`;
    const rows = (d.funds || []).map(f => `<tr>
      <td style="padding:4px 6px;max-width:220px">${f.name}</td>
      <td style="padding:4px 6px;color:var(--muted)">${f.amc||'–'}</td>
      <td class="mono" style="padding:4px 6px">${f.units!=null?f.units.toFixed(3):'–'}</td>
      <td class="mono amt" style="padding:4px 6px">${f.invested!=null?'₹'+(f.invested/100000).toFixed(2)+'L':'–'}</td>
      <td class="mono amt" style="padding:4px 6px">${f.current_value!=null?'₹'+(f.current_value/100000).toFixed(2)+'L':'–'}</td>
    </tr>`).join('');
    document.getElementById('casPreviewTable').innerHTML =
      `<thead><tr style="font-size:10px;color:var(--muted)"><th style="text-align:left;padding:4px 6px">Fund</th><th style="padding:4px 6px">AMC</th><th style="padding:4px 6px">Units</th><th style="padding:4px 6px">Invested</th><th style="padding:4px 6px">Value</th></tr></thead><tbody>${rows}</tbody>`;
    previewEl.style.display = '';
  } catch(e) {
    errEl.textContent = 'Network error: ' + e.message;
    errEl.style.display = '';
  } finally {
    btn.disabled = false; btn.textContent = 'Parse & Preview';
  }
}

async function _m6DoCasConfirm() {
  // The actual import already happened server-side during parse (upsert_cas_holdings called).
  // This just acknowledges.
  const previewEl = document.getElementById('casPreview');
  const successEl = document.getElementById('casSuccess');
  previewEl.style.display = 'none';
  successEl.textContent = `Import confirmed. Reload Vault (M1) to see updated MF holdings.`;
  successEl.style.display = '';
  _casParsedFunds = null;
}

function _m6DoCasCancel() {
  document.getElementById('casPreview').style.display = 'none';
  _casParsedFunds = null;
}

async function _m6RenderBackup() {
  const pane = document.getElementById('m6Pane');
  pane.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:24px">Loading…</div>';

  let backups = [];
  try { const d = await api('/api/settings/backup/list'); backups = d.backups || []; } catch(e) {}

  const lastRun = backups.length ? backups[0].date : null;
  const listRows = backups.map(b => `<tr>
    <td style="padding:4px 8px;font-family:var(--font-mono);font-size:12px">${b.date}</td>
    <td style="padding:4px 8px;font-size:11px;color:var(--muted)">${b.size_kb!=null?b.size_kb+' KB':'–'}</td>
    <td style="padding:4px 8px">
      ${b.has_zip ? `<a href="/api/settings/backup/download/${b.date}" class="m6-btn m6-btn-secondary" style="font-size:11px;text-decoration:none" download>Download</a>` : '–'}
    </td>
  </tr>`).join('');

  pane.innerHTML = `
    <div class="m6-section-title">Backup</div>
    <div class="m6-section-sub">Export all portfolio data as JSON + CSV for tax filing and disaster recovery. Auto-runs every Sunday 02:00.</div>

    <div class="m6-card">
      <div class="m6-card-title">Manual Backup</div>
      <div style="display:flex;align-items:center;justify-content:space-between;">
        <div style="font-size:11px;color:var(--muted)">
          ${lastRun ? 'Last backup: ' + lastRun : 'No backups yet.'}
        </div>
        <button class="m6-btn m6-btn-primary" data-action="m6-backup-run" id="backupRunBtn">Run Backup Now</button>
      </div>
      <div id="backupStatus" style="margin-top:8px;font-size:11px;display:none"></div>
    </div>

    ${backups.length ? `
    <div class="m6-card">
      <div class="m6-card-title">Available Backups</div>
      <div style="overflow-x:auto">
        <table style="width:100%">
          <thead><tr style="font-size:10px;color:var(--muted)">
            <th style="text-align:left;padding:4px 8px">Date</th>
            <th style="padding:4px 8px">Size</th>
            <th style="padding:4px 8px">Download</th>
          </tr></thead>
          <tbody>${listRows}</tbody>
        </table>
      </div>
    </div>` : ''}`;
}

async function _m6DoBackupRun() {
  const btn    = document.getElementById('backupRunBtn');
  const status = document.getElementById('backupStatus');
  btn.disabled = true; btn.textContent = 'Running…';
  status.style.display = 'none';
  try {
    const d = await apiFetch('/api/settings/backup/run', { method: 'POST' });
    if (d && d.ok) {
      status.textContent = `Backup complete: ${d.date}. Reload page to see it in the list.`;
      status.style.color = 'var(--green)';
    } else {
      status.textContent = 'Backup failed.';
      status.style.color = 'var(--red)';
    }
  } catch(e) {
    status.textContent = 'Error: ' + e.message;
    status.style.color = 'var(--red)';
  } finally {
    status.style.display = '';
    btn.disabled = false; btn.textContent = 'Run Backup Now';
  }
}
async function _m6RenderConnections() {
  const pane = document.getElementById('m6Pane');
  pane.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:24px">Loading…</div>';

  let tgStatus = { linked: false };
  try { tgStatus = await api('/api/settings/telegram/status'); } catch(e) {}
  let kiteStatus = { authenticated: false };
  try { kiteStatus = await api('/api/kite/status'); } catch(e) {}

  pane.innerHTML = `
    <div class="m6-section-title">Connected Accounts</div>
    <div class="m6-section-sub">Link external services to receive instant alerts and live data sync.</div>

    <div class="m6-card" id="m6TelegramCard">
      <div class="m6-card-title">Telegram Bot</div>
      ${tgStatus.linked
        ? `<div style="display:flex;align-items:center;justify-content:space-between;">
             <div>
               <div class="m6-field-label">Status</div>
               <div style="font-size:10px;color:var(--green);margin-top:2px;font-family:var(--font-display)">Linked — price alerts active</div>
             </div>
             <button class="m6-btn m6-btn-danger" data-action="m6-telegram-unlink">Unlink</button>
           </div>`
        : `<div>
             <div class="m6-field-label">Not linked</div>
             <div style="font-size:10px;color:var(--muted);margin-top:2px;font-family:var(--font-display)">
               Generate a one-time code, then send it to the bot in Telegram to start receiving alerts.
             </div>
             <div id="m6TgCodeBox" style="margin-top:12px"></div>
             <button class="m6-btn m6-btn-primary" style="margin-top:12px" data-action="m6-telegram-link">Generate link code</button>
           </div>`
      }
    </div>

    <div class="m6-card">
      <div class="m6-card-title">Email Digests</div>
      <div style="display:flex;align-items:center;justify-content:space-between;">
        <div>
          <div class="m6-field-label">Preview digest</div>
          <div style="font-size:10px;color:var(--muted);margin-top:2px;font-family:var(--font-display)">
            Opens the HTML digest in a new tab without sending. Enable opt-in in Preferences.
          </div>
        </div>
        <div style="display:flex;gap:8px">
          <a class="m6-btn m6-btn-secondary" href="/api/settings/test-digest?kind=morning" target="_blank" style="text-decoration:none">Morning</a>
          <a class="m6-btn m6-btn-secondary" href="/api/settings/test-digest?kind=eod" target="_blank" style="text-decoration:none">EOD</a>
        </div>
      </div>
    </div>

    <div class="m6-card" id="m6KiteCard">
      <div class="m6-card-title">Zerodha Kite</div>
      ${_m6KiteCardHtml(kiteStatus)}
    </div>`;
}

function _m6KiteCardHtml(s) {
  if (s && s.authenticated) {
    const tools = [
      { name: 'get_holdings',    label: 'Holdings' },
      { name: 'get_mf_holdings', label: 'Mutual Funds' },
      { name: 'get_positions',   label: 'Positions' },
      { name: 'get_orders',      label: 'Orders' },
      { name: 'get_margins',     label: 'Margins' },
    ];
    const btns = tools.map(t =>
      `<button class="m6-btn m6-btn-secondary m6-btn-sm" data-action="m6-kite-fetch" data-tool="${t.name}">${t.label}</button>`
    ).join('');
    return `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <div>
          <div class="m6-field-label">Status</div>
          <div style="font-size:10px;color:var(--green);margin-top:2px;font-family:var(--font-display)">Connected — read-only live sync</div>
        </div>
        <button class="m6-btn m6-btn-secondary m6-btn-sm" data-action="m6-kite-recheck">Re-check</button>
      </div>
      <div class="m6-field-label" style="margin-bottom:6px">Fetch &amp; sync to Vault</div>
      <div class="m6-kite-btns">${btns}</div>
      <div id="m6KiteFetchMsg" class="m6-key-formmsg"></div>`;
  }
  return `
    <div class="m6-field-label">Not connected</div>
    <div style="font-size:10px;color:var(--muted);margin-top:2px;font-family:var(--font-display)">
      Connect read-only to pull live holdings, mutual funds, positions and orders into your Vault. Opens Kite login in a new tab — no order placement is ever permitted.
    </div>
    <div id="m6KiteConnectBox" style="margin-top:12px"></div>
    <button class="m6-btn m6-btn-primary" style="margin-top:12px" data-action="m6-kite-connect">
      <span class="material-symbols-outlined" style="font-size:15px">link</span> Connect Kite
    </button>`;
}

async function _m6DoKiteConnect() {
  const box = document.getElementById('m6KiteConnectBox');
  if (box) box.textContent = 'Opening Kite login…';
  try {
    const d = await apiFetch('/api/kite/connect', { method: 'POST' });
    if (d && d.login_url) {
      window.open(d.login_url, '_blank');
      if (box) box.innerHTML = `
        <div style="font-size:11px;color:var(--muted2);font-family:var(--font-display);line-height:1.6">
          Logged in on the new tab? Come back and
          <button class="m6-btn m6-btn-secondary m6-btn-sm" data-action="m6-kite-recheck" style="margin-left:4px">Re-check status</button>
        </div>`;
    } else if (box) box.textContent = 'Could not start login.';
  } catch(e) {
    if (box) box.textContent = 'Connect failed — ' + (e.message || 'broker unreachable');
    _m6ShowToast('Kite connect failed', 'err');
  }
}

async function _m6DoKiteRecheck() {
  const card = document.getElementById('m6KiteCard');
  if (card) {
    let s = { authenticated: false };
    try { s = await api('/api/kite/status'); } catch(e) {}
    card.innerHTML = `<div class="m6-card-title">Zerodha Kite</div>${_m6KiteCardHtml(s)}`;
    _m6ShowToast(s.authenticated ? 'Kite connected' : 'Not connected yet', s.authenticated ? 'ok' : 'err');
  }
}

async function _m6DoKiteFetch(tool, btnEl) {
  const msg = document.getElementById('m6KiteFetchMsg');
  if (btnEl) { btnEl.disabled = true; btnEl.dataset.label = btnEl.textContent; btnEl.textContent = '…'; }
  try {
    const d = await apiFetch('/api/kite/tool/' + tool, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    const data = d && d.data;
    const count = Array.isArray(data) ? data.length : (data && typeof data === 'object' ? Object.keys(data).length : 0);
    if (msg) { msg.className = 'm6-key-formmsg ok'; msg.textContent = `Synced ${count} record${count === 1 ? '' : 's'} from ${tool.replace('get_', '')}.`; }
    _m6ShowToast('Synced to Vault', 'ok');
  } catch(e) {
    if (msg) { msg.className = 'm6-key-formmsg err'; msg.textContent = 'Fetch failed — ' + (e.message || 'reconnect Kite'); }
    _m6ShowToast('Fetch failed', 'err');
  } finally {
    if (btnEl) { btnEl.disabled = false; btnEl.textContent = btnEl.dataset.label || 'Fetch'; }
  }
}

function _m6EmptyContent(desc) {
  return `<div style="font-size:11px;color:var(--muted);font-family:var(--font-display);padding:8px 0">${desc}</div>`;
}
function _m6EmptyState(containerId, icon, title, desc) {
  document.getElementById(containerId).innerHTML = `
    <div class="m6-section-title">${title}</div>
    <div class="m6-empty-state">
      <div class="m6-empty-icon"><span class="material-symbols-outlined">${icon}</span></div>
      <div class="m6-empty-title">${title}</div>
      <div class="m6-empty-desc">${desc}</div>
    </div>`;
}

/* ── Delegated action handler ────────────────────────────────────────────── */
document.addEventListener('click', e => {
  if (e.target.closest('[data-action="m6-refresh-holdings"]')) _m6DoRefreshHoldings();
  if (e.target.closest('[data-action="m6-telegram-link"]'))   _m6DoTelegramLink();
  if (e.target.closest('[data-action="m6-telegram-unlink"]')) _m6DoTelegramUnlink();
  const keyAdd = e.target.closest('[data-action="m6-key-add"]');
  if (keyAdd) _m6DoKeyAdd();
  const keyTest = e.target.closest('[data-action="m6-key-test"]');
  if (keyTest) _m6DoKeyTest(keyTest.dataset.id);
  const keyDel = e.target.closest('[data-action="m6-key-delete"]');
  if (keyDel) _m6DoKeyDelete(keyDel.dataset.id);
  if (e.target.closest('[data-action="m6-kite-connect"]')) _m6DoKiteConnect();
  if (e.target.closest('[data-action="m6-kite-recheck"]')) _m6DoKiteRecheck();
  const kiteFetch = e.target.closest('[data-action="m6-kite-fetch"]');
  if (kiteFetch) _m6DoKiteFetch(kiteFetch.dataset.tool, kiteFetch);
  if (e.target.closest('[data-action="m6-cas-upload"]'))  _m6DoCasUpload();
  if (e.target.closest('[data-action="m6-cas-confirm"]')) _m6DoCasConfirm();
  if (e.target.closest('[data-action="m6-cas-cancel"]'))  _m6DoCasCancel();
  if (e.target.closest('[data-action="m6-backup-run"]'))  _m6DoBackupRun();
});

async function _m6DoTelegramLink() {
  const box = document.getElementById('m6TgCodeBox');
  if (!box) return;
  box.textContent = 'Generating…';
  try {
    const data = await apiFetch('/api/settings/telegram/link-code', { method: 'POST' });
    if (data && data.code) {
      box.innerHTML = `
        <div style="display:flex;align-items:center;gap:12px;background:var(--bg-card);border:1px solid var(--border);border-radius:6px;padding:10px 14px">
          <div>
            <div style="font-size:11px;color:var(--muted);font-family:var(--font-display);text-transform:uppercase;letter-spacing:0.06em">Link code (10 min)</div>
            <div style="font-size:22px;font-weight:700;letter-spacing:0.12em;color:var(--accent);font-family:var(--font-display);margin-top:2px">${data.code}</div>
          </div>
          ${data.deep_link ? `<a class="m6-btn m6-btn-primary" href="${data.deep_link}" target="_blank" style="text-decoration:none;white-space:nowrap">Open in Telegram</a>` : ''}
        </div>
        <div style="font-size:10px;color:var(--muted);margin-top:6px;font-family:var(--font-display)">
          Send <code>/start ${data.code}</code> to the bot, or click the button above.
        </div>`;
    }
  } catch(e) {
    if (box) box.textContent = 'Failed to generate code.';
  }
}

async function _m6DoTelegramUnlink() {
  try {
    await apiFetch('/api/settings/telegram/unlink', { method: 'POST' });
    _m6ShowToast('Telegram unlinked', 'ok');
    _m6RenderConnections();
  } catch(e) {
    _m6ShowToast('Unlink failed', 'err');
  }
}

/* ── Order Flow ──────────────────────────────────────────────────────────── */
async function _m6RenderOrderFlow() {
  const pane = document.getElementById('m6Pane');
  pane.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:24px">Loading…</div>';
  let data;
  try { data = await api('/api/settings/order-flow'); } catch(e) { data = null; }
  if (!data) {
    pane.innerHTML = '<div style="color:var(--red);font-size:12px;padding:24px">Failed to load order flow data.</div>';
    return;
  }

  const scoreChip = s => {
    const cls = { strong: 'buy', building: 'warn', neutral: '', unknown: '' }[s] || '';
    const label = (s || 'unknown').charAt(0).toUpperCase() + (s || 'unknown').slice(1);
    return `<span class="m3-flag-pill ${cls}" style="font-size:10px">${label}</span>`;
  };

  const all = data.tracked_syms || [];
  // A symbol is "active" when it has any real signal worth a full card.
  const hasSignal = s => s.score === 'strong' || s.score === 'building'
    || (s.qtd_orders_cr || 0) > 0 || (s.recent_announcements || []).length > 0 || !!s.guidance;
  const rank = { strong: 0, building: 1, neutral: 2, unknown: 3 };
  const active = all.filter(hasSignal).sort((a, b) =>
    (rank[a.score] ?? 3) - (rank[b.score] ?? 3) || (b.qtd_orders_cr || 0) - (a.qtd_orders_cr || 0));
  const idle = all.filter(s => !hasSignal(s));

  const nStrong = all.filter(s => s.score === 'strong').length;
  const nBuilding = all.filter(s => s.score === 'building').length;
  const nGuidance = all.filter(s => s.guidance).length;

  // Indian financial year (Apr–Mar) + quarter for the current date. FY27 = Apr 2026–Mar 2027.
  const _fyq = (() => {
    const d = new Date(), m = d.getMonth(), y = d.getFullYear();
    const fyEnd = m >= 3 ? y + 1 : y;               // Apr–Dec → next year; Jan–Mar → this year
    const q = m >= 3 && m <= 5 ? 'Q1' : m >= 6 && m <= 8 ? 'Q2' : m >= 9 && m <= 11 ? 'Q3' : 'Q4';
    return { fy: 'FY' + String(fyEnd).slice(-2), q };
  })();

  const card = sym => {
    const vsPQ = sym.vs_prev_q != null ? `${(sym.vs_prev_q * 100).toFixed(0)}%` : '—';
    const vsG  = sym.vs_guidance != null ? `${(sym.vs_guidance * 100).toFixed(0)}%` : '—';
    const annHtml = (sym.recent_announcements || []).map(a => `
      <div class="m6-ann-row">
        <span class="m6-ann-date">${a.ann_date}</span>
        <span class="m6-ann-val">${a.value_cr != null ? '₹' + a.value_cr.toFixed(1) + ' cr' : '—'}</span>
        ${a.source_url ? `<a href="${a.source_url}" target="_blank" class="m6-ann-link">PDF</a>` : ''}
      </div>`).join('');
    const guidNote = sym.guidance
      ? `${_fyq.fy} REV: ₹${sym.guidance.fy_revenue_guidance_cr != null ? sym.guidance.fy_revenue_guidance_cr + ' cr' : '—'} | ${_fyq.fy} ${_fyq.q} REV: ₹${sym.guidance.q_revenue_guidance_cr != null ? sym.guidance.q_revenue_guidance_cr + ' cr' : '—'}`
      : 'No guidance set';
    const edge = sym.score === 'strong' ? ' signal' : sym.score === 'building' ? ' building' : '';
    return `
    <div class="m6-of-card${edge}">
      <div class="m6-of-header">
        <span class="m6-of-sym">${sym.sym}</span>
        <span class="m6-of-name" style="color:var(--muted);font-size:11px">${sym.name || ''}</span>
        ${scoreChip(sym.score)}
      </div>
      <div class="m6-of-stats">
        <span>QTD: <b>${sym.qtd_orders_cr > 0 ? '₹' + sym.qtd_orders_cr.toFixed(1) + ' cr' : '—'}</b></span>
        <span>vs prev Q: <b>${vsPQ}</b></span>
        <span>vs guidance: <b>${vsG}</b></span>
        ${sym.next_earnings_date ? `<span>Earnings: ${sym.next_earnings_date}</span>` : ''}
      </div>
      <div class="m6-of-guidance">
        <span style="color:var(--muted);font-size:11px">${guidNote}</span>
        <button class="m6-btn-sm" onclick="_m6EditGuidance('${sym.sym}', ${JSON.stringify(sym.guidance || {}).replace(/"/g,"'")})">Edit</button>
      </div>
      <div class="m6-of-anns">${annHtml || '<span style="color:var(--muted);font-size:11px">No announcements this quarter</span>'}</div>
    </div>`;
  };

  const summary = `
    <div class="m6-of-summary">
      <div class="m6-of-stat"><div class="v">${all.length}</div><div class="l">Tracked symbols</div></div>
      <div class="m6-of-stat"><div class="v ${nStrong ? 'accent' : ''}">${nStrong}</div><div class="l">Strong setups</div></div>
      <div class="m6-of-stat"><div class="v">${nBuilding}</div><div class="l">Building</div></div>
      <div class="m6-of-stat"><div class="v">${nGuidance}</div><div class="l">Guidance set</div></div>
    </div>`;

  const activeHtml = active.length
    ? `<div class="m6-of-group-hdr">Active signals <span class="cnt">· ${active.length}</span></div>${active.map(card).join('')}`
    : `<div style="color:var(--muted);font-size:12px;padding:8px 0">No order-win activity in the current quarter yet. Set guidance below or wait for the next NSE poll.</div>`;

  const idleHtml = idle.length ? `
    <div class="m6-of-idle">
      <div class="m6-of-group-hdr">Watching <span class="cnt">· ${idle.length} with no order flow yet</span>
        <button class="m6-of-toggle" id="ofIdleToggle" onclick="_m6ToggleIdle()" style="margin-left:auto">Show all</button>
      </div>
      <div class="m6-of-idle-grid" id="ofIdleGrid" style="display:none">
        ${idle.map(s => `<span class="m6-of-chip" onclick="_m6EditGuidance('${s.sym}', ${JSON.stringify(s.guidance || {}).replace(/"/g,"'")})" title="Set guidance"><span class="sym">${s.sym}</span></span>`).join('')}
      </div>
    </div>` : '';

  pane.innerHTML = `
    <div class="m6-section-hdr">Order Flow Intelligence</div>
    <p style="color:var(--muted);font-size:12px;margin:0 0 16px">
      QTD order wins vs prev-quarter revenue &amp; guidance. Polled twice daily from NSE.
    </p>
    ${all.length ? summary + activeHtml + idleHtml
      : '<div style="color:var(--muted);font-size:12px">No tracked symbols yet — run a scan or open a swing trade.</div>'}`;
}

function _m6ToggleIdle() {
  const grid = document.getElementById('ofIdleGrid');
  const btn = document.getElementById('ofIdleToggle');
  if (!grid) return;
  const open = grid.style.display !== 'none';
  grid.style.display = open ? 'none' : 'flex';
  if (btn) btn.textContent = open ? 'Show all' : 'Hide';
}

function _m6EditGuidance(sym, existing) {
  const fyCr  = existing.fy_revenue_guidance_cr != null ? existing.fy_revenue_guidance_cr : '';
  const qCr   = existing.q_revenue_guidance_cr  != null ? existing.q_revenue_guidance_cr  : '';
  const note  = existing.guidance_note || '';
  const _d = new Date(), _m = _d.getMonth(), _y = _d.getFullYear();
  const _fy = 'FY' + String(_m >= 3 ? _y + 1 : _y).slice(-2);
  const _q = _m >= 3 && _m <= 5 ? 'Q1' : _m >= 6 && _m <= 8 ? 'Q2' : _m >= 9 && _m <= 11 ? 'Q3' : 'Q4';
  const pane  = document.getElementById('m6Pane');
  // simple inline edit form
  const form = document.createElement('div');
  form.className = 'm6-of-edit-form';
  form.innerHTML = `
    <div class="m6-section-hdr">Edit Guidance — ${sym}</div>
    <label>${_fy} Revenue Guidance (₹ cr)</label>
    <input id="m6ofFyCr" class="m6-input" type="number" step="0.01" value="${fyCr}" placeholder="e.g. 1200">
    <label>${_fy} ${_q} Revenue Guidance (₹ cr)</label>
    <input id="m6ofQCr" class="m6-input" type="number" step="0.01" value="${qCr}" placeholder="e.g. 300">
    <label>Note</label>
    <input id="m6ofNote" class="m6-input" type="text" value="${note}" placeholder="e.g. Q1 FY27 concall">
    <div style="display:flex;gap:8px;margin-top:12px">
      <button class="m6-btn" onclick="_m6SaveGuidance('${sym}')">Save</button>
      <button class="m6-btn-outline" onclick="_m6RenderOrderFlow()">Cancel</button>
    </div>`;
  pane.innerHTML = '';
  pane.appendChild(form);
}

async function _m6SaveGuidance(sym) {
  const fyCr  = parseFloat(document.getElementById('m6ofFyCr').value) || null;
  const qCr   = parseFloat(document.getElementById('m6ofQCr').value) || null;
  const note  = document.getElementById('m6ofNote').value.trim();
  try {
    await apiFetch(`/api/settings/order-flow/guidance/${sym}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fy_revenue_guidance_cr: fyCr, q_revenue_guidance_cr: qCr, guidance_note: note }),
    });
    _m6ShowToast('Guidance saved', 'ok');
    _m6RenderOrderFlow();
  } catch(e) {
    _m6ShowToast('Save failed', 'err');
  }
}
