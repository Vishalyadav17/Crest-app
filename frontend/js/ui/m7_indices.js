// ── Module 7: Custom Indices (Wavesight right-panel) ─────────────────────────
let _m4IndicesOpen  = localStorage.getItem('gp_indices_open') === '1';
let _indicesData    = [];   // [{id, name, kind, member_count, last_value, change_1d_pct, ...}]
let _indicesLoaded  = false;
let _activeIndexId  = null;
let _activeIndexMembers = new Set();   // member syms of the active index (for member-open behaviour)

// ── toggle ────────────────────────────────────────────────────────────────────
function _toggleIndicesPanel() {
  _m4IndicesOpen = !_m4IndicesOpen;
  localStorage.setItem('gp_indices_open', _m4IndicesOpen ? '1' : '0');
  _updateRightPanel();
  const btn = document.getElementById('m4IndBtn');
  if (btn) btn.classList.toggle('active', _m4IndicesOpen);
  if (_m4IndicesOpen && !_indicesLoaded) _fetchIndices();
  else if (_m4IndicesOpen) _renderIndicesPanel();
}

// ── fetch ─────────────────────────────────────────────────────────────────────
async function _fetchIndices() {
  const panel = document.getElementById('m4IndicesPanel');
  if (!panel) return;
  panel.innerHTML = `<div class="m4-rp-hdr"><span>Indices</span><button class="m4-rp-hdr-btn" onclick="_toggleIndicesPanel()">✕</button></div><div class="m4-info-loading">Loading…</div>`;
  try {
    const data = await fetch('/api/custom-indices').then(r => r.json());
    _indicesData = data.indices || [];
    _indicesLoaded = true;
    _renderIndicesPanel();
  } catch(e) {
    if (panel) panel.innerHTML = `<div class="m4-rp-hdr"><span>Indices</span><button class="m4-rp-hdr-btn" onclick="_toggleIndicesPanel()">✕</button></div><div class="m4-info-empty">Failed to load</div>`;
  }
}

// ── render panel ──────────────────────────────────────────────────────────────
function _renderIndicesPanel() {
  const panel = document.getElementById('m4IndicesPanel');
  if (!panel || !_m4IndicesOpen) return;

  const seeded = _indicesData.filter(i => i.kind === 'seeded');
  const user   = _indicesData.filter(i => i.kind === 'user');

  const rowHtml = (idx) => {
    const chg = idx.change_1d_pct;
    const chgStr = chg != null
      ? `<span class="m4-idx-chg ${chg >= 0 ? 'up' : 'dn'}">${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</span>`
      : '';
    const val = idx.last_value != null ? idx.last_value.toFixed(1) : '–';
    return `<div class="m4-idx-row ${_activeIndexId === idx.id ? 'active' : ''}" onclick="_onIndexRowClick(${idx.id}, '${_escHtml(idx.name)}')">
      <div class="m4-idx-row-left">
        <span class="m4-idx-name">${_escHtml(idx.name)}</span>
        <span class="m4-idx-meta">${idx.member_count} stocks</span>
      </div>
      <div class="m4-idx-row-right">
        <span class="m4-idx-val">${val}</span>
        ${chgStr}
      </div>
    </div>`;
  };

  panel.innerHTML = `
    <div class="m4-rp-hdr">
      <span>Indices</span>
      <button class="m4-rp-hdr-btn" onclick="_toggleIndicesPanel()">✕</button>
    </div>
    <div class="m4-idx-body">
      ${seeded.length ? `<div class="m4-idx-section">Pre-Built</div>${seeded.map(rowHtml).join('')}` : ''}
      ${user.length   ? `<div class="m4-idx-section">My Indices</div>${user.map(rowHtml).join('')}` : ''}
      <div class="m4-idx-new-wrap">
        <button class="m4-idx-new-btn" onclick="_showNewIndexModal()">+ New Index</button>
      </div>
    </div>`;
}

// ── row click = toggle ────────────────────────────────────────────────────────
// First click on an index → load chart + expand member list.
// Click the already-active index again → just collapse the member list (chart stays).
function _onIndexRowClick(idxId, name) {
  if (_activeIndexId === idxId) {
    const existing = document.getElementById('m4IdxMembers_' + idxId);
    if (existing) existing.remove();          // collapse
    else _loadIndexMembers(idxId);            // re-expand
    return;
  }
  _loadIndexChart(idxId, name);
}

// ── load index into chart ─────────────────────────────────────────────────────
// Index becomes pane 0's primary candlestick series (weighted OHLC), so the same
// _applyIndicators path recomputes 10/20/50 EMA + volume ON the index — they sync.
async function _loadIndexChart(idxId, name) {
  _activeIndexId = idxId;
  _renderIndicesPanel();

  // Symbol selector belongs to a stock, not a synthetic index — blank it.
  const _symSel = document.querySelector('.lc-pane[data-pane-id="0"] .lc-sym-sel');
  const _symInp = document.querySelector('.lc-pane[data-pane-id="0"] .lc-sym-inp');
  if (_symSel) { if (!_symSel.querySelector('option[value=""]')) _symSel.insertAdjacentHTML('afterbegin', '<option value=""></option>'); _symSel.value = ''; }
  if (_symInp) _symInp.value = '';

  try {
    const data = await fetch(`/api/custom-indices/${idxId}/history?period=1y`).then(r => r.json());
    const candles = data.candles || [];
    if (!candles.length) return;

    const pane = _chartPanes.get('0');
    if (!pane) return;

    // Stop live feed for the stock previously in pane 0
    try { _stopChartWs('0'); } catch(e) {}
    try { _stopChartPoller('0'); } catch(e) {}

    // Drop any leftover overlay line from older builds
    if (pane._indexLineSeries) {
      try { pane.lwChart.removeSeries(pane._indexLineSeries); } catch(e) {}
      pane._indexLineSeries = null;
    }

    pane._indexMode = true;
    pane._lastCandles = candles;
    pane.lwChart._series.setData(candles);
    _applyIndicators('0', candles);            // EMAs + volume recompute on the index
    if (typeof _onCrosshair === 'function') _onCrosshair('0', null);   // seed OHLC legend
    pane.lwChart.timeScale().fitContent();

    // Ticker bar carries the name (top-right) — no on-chart label
    const ticker = document.getElementById('lcTicker0');
    if (ticker) {
      ticker.querySelector('.lc-t-sym').textContent = name.replace(' Index', '');
      const nameEl = ticker.querySelector('.lc-t-name');
      if (nameEl) nameEl.textContent = 'Synthetic';
      const last = candles[candles.length - 1];
      const priceEl = ticker.querySelector('.lc-t-price');
      if (priceEl) {
        priceEl.textContent = last ? last.close.toFixed(1) : '–';
        priceEl.style.color = 'var(--muted)';
      }
    }

    _loadIndexMembers(idxId);
  } catch(e) {
    console.warn('[Indices] load chart failed:', e);
  }
}

// ── members panel (replaces / appends below active row) ───────────────────────
async function _loadIndexMembers(idxId) {
  try {
    const data = await fetch(`/api/custom-indices/${idxId}/members`).then(r => r.json());
    const members = data.members || [];
    if (idxId === _activeIndexId) _activeIndexMembers = new Set(members.map(m => m.sym));
    const existing = document.getElementById('m4IdxMembers_' + idxId);
    if (existing) existing.remove();

    const activeRow = document.querySelector(`.m4-idx-row.active`);
    if (!activeRow) return;

    const wrap = document.createElement('div');
    wrap.id = 'm4IdxMembers_' + idxId;
    wrap.className = 'm4-idx-members';
    wrap.innerHTML = members.map(m => {
      const chg = m.change_1d_pct;
      const chgStr = chg != null
        ? `<span class="${chg >= 0 ? 'up' : 'dn'}">${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</span>`
        : '<span>–</span>';
      return `<div class="m4-idx-mbr" onclick="openInCharts('${m.sym}')">
        <span class="m4-idx-mbr-sym">${m.sym}</span>
        <span class="m4-idx-mbr-ltp">${m.ltp != null ? m.ltp.toLocaleString('en-IN') : '–'}</span>
        ${chgStr}
      </div>`;
    }).join('');
    activeRow.insertAdjacentElement('afterend', wrap);
  } catch(e) {}
}

// ── new index modal ───────────────────────────────────────────────────────────
function _showNewIndexModal() {
  let modal = document.getElementById('idxNewModal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'idxNewModal';
    modal.className = 'sec-modal-overlay';
    modal.style.display = 'none';
    modal.onclick = e => { if (e.target === modal) _closeNewIndexModal(); };
    document.body.appendChild(modal);
  }
  modal.innerHTML = `
    <div class="sec-modal" style="max-width:480px">
      <div class="sec-modal-header">
        <div class="sec-modal-title">New Index</div>
        <span class="sec-modal-close" onclick="_closeNewIndexModal()">✕</span>
      </div>
      <div class="sec-modal-body" style="display:flex;flex-direction:column;gap:12px;padding-top:8px">
        <label class="inp-label">Name
          <input id="newIdxName" class="inp" placeholder="e.g. EV Battery Index" autocomplete="off">
        </label>
        <label class="inp-label">Weight Mode
          <select id="newIdxWeight" class="inp">
            <option value="mcap">MCap-Weighted</option>
            <option value="equal">Equal-Weighted</option>
          </select>
        </label>
        <label class="inp-label">Symbols (comma-separated)
          <textarea id="newIdxSyms" class="inp" rows="4" placeholder="RELIANCE, TATAMOTORS, ADANIGREEN…"></textarea>
        </label>
        <div id="newIdxErr" class="form-err hidden"></div>
        <button class="btn btn-primary" onclick="_submitNewIndex()">Create</button>
      </div>
    </div>`;
  modal.style.display = 'flex';
}

function _closeNewIndexModal() {
  const modal = document.getElementById('idxNewModal');
  if (modal) modal.style.display = 'none';
}

async function _submitNewIndex() {
  const name   = document.getElementById('newIdxName')?.value.trim();
  const weight = document.getElementById('newIdxWeight')?.value;
  const symsRaw= document.getElementById('newIdxSyms')?.value;
  const errEl  = document.getElementById('newIdxErr');

  const syms = (symsRaw || '').split(/[\s,]+/).map(s => s.trim().toUpperCase()).filter(Boolean);
  if (!name) { _showInlineErr(errEl, 'Name required'); return; }
  if (syms.length < 2) { _showInlineErr(errEl, 'At least 2 symbols required'); return; }

  try {
    const resp = await fetch('/api/custom-indices', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({name, symbols: syms, weight_mode: weight}),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      _showInlineErr(errEl, err.detail || 'Error creating index'); return;
    }
    _closeNewIndexModal();
    _indicesLoaded = false;
    await _fetchIndices();
  } catch(e) {
    _showInlineErr(errEl, 'Network error');
  }
}

function _showInlineErr(el, msg) {
  if (!el) return;
  el.textContent = msg;
  el.classList.remove('hidden');
}

// ── wire into _updateRightPanel ───────────────────────────────────────────────
// Extend the existing _updateRightPanel to handle the indices panel.
// We wrap it once after definition (m5_watchlist.js defines it first).
(function _patchUpdateRightPanel() {
  const _orig = typeof _updateRightPanel === 'function' ? _updateRightPanel : null;
  window._updateRightPanel = function() {
    if (_orig) _orig();
    const ip = document.getElementById('m4IndicesPanel');
    if (ip) ip.classList.toggle('rp-sec-hidden', !_m4IndicesOpen);
    const rp = document.getElementById('m4RightPanel');
    if (rp && _m4IndicesOpen) rp.classList.remove('rp-hidden');
  };
})();
