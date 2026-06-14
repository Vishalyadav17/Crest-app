// ── Watchlist ─────────────────────────────────────────────────────────────────
const _DEFAULT_WATCHLISTS = [
  { id:'lt',     name:'Long Term',  symbols:[] },
  { id:'crypto', name:'Crypto',     symbols:[] },
];
// Watchlists — backed by /api/watchlists. localStorage kept as migration source only.
let _watchlists = _DEFAULT_WATCHLISTS;  // replaced on first API load
let _m4WatchlistOpen = localStorage.getItem('gp_wl_open') === '1';
let _wlCollapsed = {};
let _wlLoaded = false;

async function _fetchWatchlists() {
  try {
    const data = await fetch('/api/watchlists').then(r => r.json());
    if (!Array.isArray(data)) return;
    // One-time migration from localStorage
    if (data.length === 0) {
      const ls = (() => { try { return JSON.parse(localStorage.getItem('gp_watchlists')||'null'); } catch(e){return null;} })();
      if (ls && ls.length) {
        for (const wl of ls) {
          const created = await fetch('/api/watchlists', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({name: wl.name, list_type:'custom'})
          }).then(r=>r.json());
          if (created.id) {
            const syms = Array.isArray(wl.symbols) ? wl.symbols : (wl.symbols||[]).map(s=>typeof s==='string'?s:s.sym);
            for (const sym of syms) {
              await fetch(`/api/watchlists/${created.id}/items`, {
                method:'POST', headers:{'Content-Type':'application/json'},
                body: JSON.stringify({sym})
              }).catch(()=>{});
            }
          }
        }
        localStorage.removeItem('gp_watchlists');
        const migrated = await fetch('/api/watchlists').then(r=>r.json());
        _watchlists = Array.isArray(migrated) ? migrated : _DEFAULT_WATCHLISTS;
        _wlLoaded = true;
        _renderWatchlist();
        return;
      }
    }
    _watchlists = data;
    _wlLoaded = true;
    _renderWatchlist();
  } catch(e) {
    console.warn('Watchlist API unavailable, using defaults', e);
    _wlLoaded = true;
  }
}

function _renderWatchlist() {
  const panel = document.getElementById('m4Watchlist');
  if (!panel || !_m4WatchlistOpen) return;
  panel.innerHTML = `
    <div class="m4-rp-hdr">
      <span>Watchlists</span>
      <div class="m4-rp-hdr-btns">
        <button class="m4-rp-hdr-btn" onclick="_addWatchlist()" title="New list">+</button>
        <button class="m4-rp-hdr-btn" onclick="_toggleWatchlistPanel()" title="Close">✕</button>
      </div>
    </div>
    <div class="m4-wl-body">
      ${_watchlists.map((list, li) => {
        const collapsed = !!_wlCollapsed[li];
        const syms = list.symbols || [];
        return `<div class="m4-wl-group">
          <div class="m4-wl-group-hdr" onclick="_toggleWlGroup(${li})">
            <span class="m4-wl-chevron">${collapsed?'▶':'▼'}</span>
            <span class="m4-wl-group-name">${list.name}</span>
            <button class="m4-wl-del-list" onclick="event.stopPropagation();_deleteWatchlist(${li})">×</button>
          </div>
          <div class="m4-wl-items" id="wlItems${li}" style="${collapsed?'display:none':''}">
            ${syms.map((item) => {
              const sym = typeof item === 'string' ? item : item.sym;
              const nm  = typeof item === 'string' ? item : (item.name || item.sym);
              return `<div class="m4-wl-item" onclick="_openWlSymbol('${sym}')">
                <span title="${nm}">${sym}</span>
                <button class="m4-wl-del-sym" onclick="event.stopPropagation();_removeFromWatchlist(${li},'${sym}')">×</button>
              </div>`;
            }).join('')}
            <div class="m4-wl-add-row">
              <input class="m4-wl-inp" id="wlInp${li}" placeholder="ticker…" onkeydown="if(event.key==='Enter')_addToWatchlist(${li})">
              <button onclick="_addToWatchlist(${li})">+</button>
            </div>
          </div>
        </div>`;
      }).join('')}
    </div>`;
}

function _toggleWlGroup(li) {
  _wlCollapsed[li] = !_wlCollapsed[li];
  const items = document.getElementById('wlItems' + li);
  const chev  = document.querySelector(`#m4Watchlist .m4-wl-body .m4-wl-group:nth-child(${li+1}) .m4-wl-chevron`);
  if (items) items.style.display = _wlCollapsed[li] ? 'none' : '';
  if (chev)  chev.textContent = _wlCollapsed[li] ? '▶' : '▼';
}

async function _addWatchlist() {
  const name = prompt('Watchlist name:');
  if (!name?.trim()) return;
  await fetch('/api/watchlists', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name:name.trim(), list_type:'custom'})
  });
  await _fetchWatchlists();
}

async function _deleteWatchlist(li) {
  const wl = _watchlists[li];
  if (!wl || !confirm(`Delete "${wl.name}"?`)) return;
  await fetch(`/api/watchlists/${wl.id}`, {method:'DELETE'});
  await _fetchWatchlists();
}

async function _addToWatchlist(li) {
  const inp = document.getElementById('wlInp' + li);
  if (!inp) return;
  const sym = inp.value.trim().toUpperCase().replace('.NS','');
  if (!sym) return;
  inp.value = '';
  const wl = _watchlists[li];
  if (!wl) return;
  // Optimistic: add immediately to local state + re-render
  if (!wl.symbols) wl.symbols = [];
  if (!wl.symbols.includes(sym)) {
    wl.symbols.push(sym);
    _renderWatchlist();
  }
  try {
    await fetch(`/api/watchlists/${wl.id}/items`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({sym})
    });
  } catch(_) {
    // Revert on error
    wl.symbols = wl.symbols.filter(s => s !== sym);
    _renderWatchlist();
  }
}

async function _removeFromWatchlist(li, sym) {
  const wl = _watchlists[li];
  if (!wl) return;
  // Optimistic: remove immediately from local state + re-render
  const prev = [...(wl.symbols || [])];
  wl.symbols = prev.filter(s => s !== sym);
  _renderWatchlist();
  try {
    await fetch(`/api/watchlists/${wl.id}/items/${sym}`, {method:'DELETE'});
  } catch(_) {
    // Revert on error
    wl.symbols = prev;
    _renderWatchlist();
  }
}

function _openWlSymbol(sym) { openInCharts(sym); }

function _toggleWatchlistPanel() {
  _m4WatchlistOpen = !_m4WatchlistOpen;
  localStorage.setItem('gp_wl_open', _m4WatchlistOpen ? '1' : '0');
  _renderWatchlist();
  _updateRightPanel();
  _updateToolbarBtns();
}

// ── Stock Info Panel ──────────────────────────────────────────────────────────
let _m4InfoOpen    = localStorage.getItem('gp_info_open') === '1';
let _m4InfoSymbol  = null;
let _stockNameMap  = {};

function _toggleInfoPanel() {
  _m4InfoOpen = !_m4InfoOpen;
  localStorage.setItem('gp_info_open', _m4InfoOpen ? '1' : '0');
  _updateRightPanel();
  _updateToolbarBtns();
  if (_m4InfoOpen) {
    const panel = document.getElementById('m4InfoPanel');
    if (_m4InfoSymbol) _loadAndShowInfo(_m4InfoSymbol);
    else if (panel) panel.innerHTML = `<div class="m4-rp-hdr"><span>Stock Info</span><button class="m4-rp-hdr-btn" onclick="_toggleInfoPanel()">✕</button></div><div class="m4-info-empty">Select a stock to view details</div>`;
  }
}

async function _loadAndShowInfo(symbol) {
  if (!_m4InfoOpen) return;
  _m4InfoSymbol = symbol;
  const panel = document.getElementById('m4InfoPanel');
  if (!panel || panel.classList.contains('rp-sec-hidden')) return;
  const base = symbol.replace('.NS','').replace('^','');
  panel.innerHTML = `<div class="m4-rp-hdr"><span class="m4-info-sym" style="font-size:13px;text-transform:none;letter-spacing:0">${base}</span><button class="m4-rp-hdr-btn" onclick="_toggleInfoPanel()">✕</button></div><div class="m4-info-loading">Loading…</div>`;
  try {
    const data = await fetch(`/api/charts/stock-info?symbol=${encodeURIComponent(symbol)}`).then(r => r.json());
    if (_m4InfoSymbol === symbol) _renderInfoPanel(symbol, data);
  } catch(e) {
    if (_m4InfoSymbol === symbol) panel.innerHTML = `<div class="m4-rp-hdr"><span>${base}</span><button class="m4-rp-hdr-btn" onclick="_toggleInfoPanel()">✕</button></div><div class="m4-info-empty">Info unavailable</div>`;
  }
}

function _thesisCardHtml(thesis) {
  if (!thesis || !thesis.why_holding) return '';
  const stars = '●'.repeat(Math.min(5, thesis.conviction || 3)) + '○'.repeat(Math.max(0, 5 - (thesis.conviction || 3)));
  return `<div class="m4-info-section m4-thesis-card">
    <div class="m4-info-lbl" style="display:flex;justify-content:space-between;align-items:center">
      <span>Your Thesis</span>
      <span style="font-size:10px;letter-spacing:0.08em;color:var(--accent)" title="Conviction ${thesis.conviction}/5">${stars}</span>
    </div>
    <p class="m4-thesis-why">${thesis.why_holding}</p>
    ${thesis.entry_trigger ? `<div class="m4-thesis-row"><span class="m4-thesis-lbl">Entry</span><span>${thesis.entry_trigger}</span></div>` : ''}
    ${thesis.exit_trigger  ? `<div class="m4-thesis-row"><span class="m4-thesis-lbl">Exit</span><span>${thesis.exit_trigger}</span></div>` : ''}
    ${thesis.review_date   ? `<div class="m4-thesis-row" style="margin-top:4px"><span class="m4-thesis-lbl" style="color:var(--muted)">Reviewed</span><span style="color:var(--muted)">${thesis.review_date}</span></div>` : ''}
  </div>`;
}

function _renderInfoPanel(symbol, data) {
  const panel = document.getElementById('m4InfoPanel');
  if (!panel) return;

  const base = symbol.replace('.NS','').replace('^','');
  const price = data.price ? data.price.toLocaleString('en-IN',{maximumFractionDigits:2}) : '–';
  const chgPct = data.change_pct;
  const chgClass = chgPct == null ? '' : (chgPct >= 0 ? 'green' : 'red');
  const chgStr  = chgPct == null ? '' : `${chgPct >= 0 ? '+':''}${chgPct.toFixed(2)}%`;
  const mcap = data.mcap_cr
    ? (data.mcap_cr >= 10000 ? (data.mcap_cr/1000).toFixed(1)+'K Cr' : Math.round(data.mcap_cr)+' Cr')
    : '–';

  let rangeHtml = '';
  if (data.fifty_two_week_high && data.fifty_two_week_low && data.price) {
    const span = data.fifty_two_week_high - data.fifty_two_week_low;
    const pct  = span > 0 ? Math.min(100, Math.round((data.price - data.fifty_two_week_low) / span * 100)) : 50;
    const lo = data.fifty_two_week_low.toLocaleString('en-IN',{maximumFractionDigits:1});
    const hi = data.fifty_two_week_high.toLocaleString('en-IN',{maximumFractionDigits:1});
    rangeHtml = `<div class="m4-info-section" style="padding-bottom:4px">
      <div class="m4-info-lbl">52-Week Range</div>
      <div class="m4-52w-bar"><div style="width:${pct}%"></div></div>
      <div class="m4-52w-labels"><span>₹${lo}</span><span>${pct}%</span><span>₹${hi}</span></div>
    </div>`;
  }

  const wlOpts = _watchlists.map((wl,i)=>`<option value="${i}">${wl.name}</option>`).join('');
  const nseLink = `https://www.nseindia.com/get-quotes/equity?symbol=${base}`;
  const scrLink = `https://www.screener.in/company/${base}/`;

  panel.innerHTML = `
    <div class="m4-rp-hdr">
      <div style="min-width:0;overflow:hidden">
        <span class="m4-info-sym">${base}</span>
        ${data.sector ? `<span style="display:block;font-size:9px;color:var(--muted);font-weight:400;letter-spacing:0.04em;margin-top:1px;text-transform:uppercase;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${data.sector}</span>` : ''}
      </div>
      <button class="m4-rp-hdr-btn" onclick="_toggleInfoPanel()">✕</button>
    </div>
    <div class="m4-info-body">
      <div class="m4-info-hdr">
        <div class="m4-info-name">${data.name || base}</div>
      </div>
      <div class="m4-info-price-row">
        <span class="m4-info-price-val">₹${price}</span>
        <span class="${chgClass}" style="font-size:12px;font-weight:600">${chgStr}</span>
      </div>
      ${rangeHtml}
      <div class="m4-info-section">
        <div class="m4-info-lbl">Key Stats</div>
        <table class="m4-info-tbl">
          <tr><td>Market Cap</td><td>₹${mcap}</td></tr>
        </table>
      </div>
      <div class="m4-info-section">
        <div class="m4-info-lbl">Links</div>
        <div class="m4-info-links">
          <a href="${nseLink}" target="_blank" class="m4-info-link">NSE ↗</a>
          <a href="${scrLink}" target="_blank" class="m4-info-link">Screener ↗</a>
        </div>
      </div>
      <div class="m4-info-section">
        <div class="m4-info-lbl">Add to Watchlist</div>
        <div class="m4-info-wl-row">
          <select id="m4InfoWlSel">${wlOpts}</select>
          <button onclick="_addFromInfoPanel('${base}')">+ Add</button>
        </div>
      </div>
      <div class="m4-info-section" style="padding-bottom:10px">
        <button class="m4-more-info-btn" id="m4NewsBtn_${base}" onclick="_toggleNewsSection('${base}')">↓ News</button>
      </div>
      <div class="m4-news-section hidden" id="m4NewsSection"></div>
      ${_thesisCardHtml(data.thesis)}
    </div>`;
}

async function _addFromInfoPanel(sym) {
  const sel = document.getElementById('m4InfoWlSel');
  if (!sel) return;
  const li = parseInt(sel.value);
  const wl = _watchlists[li];
  if (!wl) return;
  await fetch(`/api/watchlists/${wl.id}/items`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({sym: sym.replace('.NS','')})
  });
  await _fetchWatchlists();
}

function _updateRightPanel() {
  const rp = document.getElementById('m4RightPanel');
  const wl = document.getElementById('m4Watchlist');
  const ip = document.getElementById('m4InfoPanel');
  if (!rp) return;
  const eitherOpen = _m4WatchlistOpen || _m4InfoOpen;
  rp.classList.toggle('rp-hidden', !eitherOpen);
  rp.classList.toggle('rp-both', _m4WatchlistOpen && _m4InfoOpen);
  if (wl) wl.classList.toggle('rp-sec-hidden', !_m4WatchlistOpen);
  if (ip) ip.classList.toggle('rp-sec-hidden', !_m4InfoOpen);
}

function _updateToolbarBtns() {
  const wlBtn  = document.getElementById('m4WlBtn');
  const infoBtn = document.getElementById('m4InfoBtn');
  if (wlBtn)  wlBtn.classList.toggle('active', _m4WatchlistOpen);
  if (infoBtn) infoBtn.classList.toggle('active', _m4InfoOpen);
}

function _toggleFullscreen() {
  const el = document.getElementById('mod-m4');
  if (!document.fullscreenElement) el.requestFullscreen?.().catch(() => {});
  else document.exitFullscreen?.();
}

function _initSearch() {
  const inp = document.getElementById('m4SearchInp');
  const ac  = document.getElementById('m4Autocomplete');
  if (!inp || !ac) return;
  inp.addEventListener('input', () => {
    const q = inp.value.trim();
    if (!q) { ac.classList.add('hidden'); return; }
    const results = _getSearchResults(q);
    if (!results.length) { ac.classList.add('hidden'); return; }
    ac.innerHTML = results.map(r =>
      `<div class="m4-ac-item" onmousedown="event.preventDefault()" onclick="_selectSearchResult('${r.sym}')">
        <span class="m4-ac-sym">${r.sym}</span>
        <span class="m4-ac-name">${_escHtml(r.name)}</span>
        ${r.inWatchlist ? '<span class="m4-ac-badge">★</span>' : ''}
      </div>`).join('');
    ac.classList.remove('hidden');
  });
  inp.addEventListener('blur', () => setTimeout(() => ac.classList.add('hidden'), 150));
  inp.addEventListener('keydown', e => {
    if (e.key === 'Escape') { inp.value = ''; ac.classList.add('hidden'); }
    if (e.key === 'Enter') {
      const typed = inp.value.trim().toUpperCase();
      const typedNoSpace = typed.replace(/\s+/g, '');
      // Prefer exact ticker match over first autocomplete suggestion
      if (_stockNameMap[typed]) { _selectSearchResult(typed); return; }
      if (_stockNameMap[typedNoSpace]) { _selectSearchResult(typedNoSpace); return; }
      const first = ac.querySelector('.m4-ac-item');
      if (first) first.click();
      else if (typedNoSpace) _selectSearchResult(typedNoSpace);
    }
  });
}

function _getSearchResults(query) {
  const q = query.toUpperCase().trim();
  if (!q) return [];
  const results = [], seen = new Set();

  // Build watchlist symbol set (API symbols are objects {sym,name} or plain strings)
  const wlSyms = new Set();
  _watchlists.forEach(wl => {
    (wl.symbols || []).forEach(item => {
      const sym = typeof item === 'string' ? item : item.sym;
      wlSyms.add(sym);
    });
  });

  // Watchlist symbols that match query — shown first with star badge
  wlSyms.forEach(sym => {
    if (sym.startsWith(q) || sym.includes(q)) {
      if (!seen.has(sym)) {
        seen.add(sym);
        results.push({ sym, name: _stockNameMap[sym] || '', inWatchlist: true });
      }
    }
  });

  // Stock master prefix matches
  Object.entries(_stockNameMap).forEach(([sym, name]) => {
    if (!seen.has(sym) && sym.startsWith(q)) {
      seen.add(sym);
      results.push({ sym, name, inWatchlist: wlSyms.has(sym) });
    }
  });
  // Name contains matches
  if (results.length < 8) {
    Object.entries(_stockNameMap).forEach(([sym, name]) => {
      if (!seen.has(sym) && name.toUpperCase().includes(q)) {
        seen.add(sym);
        results.push({ sym, name, inWatchlist: wlSyms.has(sym) });
      }
    });
  }
  return results.slice(0, 8);
}

function _selectSearchResult(sym) {
  const inp = document.getElementById('m4SearchInp');
  const ac  = document.getElementById('m4Autocomplete');
  if (inp) inp.value = '';
  if (ac) ac.classList.add('hidden');
  openInCharts(sym);
}

async function _toggleNewsSection(base) {
  const sec = document.getElementById('m4NewsSection');
  const btn = document.getElementById('m4NewsBtn_' + base);
  if (!sec) return;
  if (!sec.classList.contains('hidden')) {
    sec.classList.add('hidden');
    if (btn) btn.textContent = '↓ News';
    return;
  }
  sec.classList.remove('hidden');
  if (btn) btn.textContent = '↑ Hide News';
  sec.innerHTML = '<div class="m4-news-loading">Fetching news…</div>';
  try {
    const data = await fetch(`/api/charts/news?symbol=${encodeURIComponent(base)}`).then(r => r.json());
    if (!data.items?.length) { sec.innerHTML = '<div class="m4-news-empty">No recent news found</div>'; return; }
    sec.innerHTML = data.items.map(item => `
      <a href="${item.url}" target="_blank" rel="noopener noreferrer" class="m4-news-item">
        <div class="m4-news-title">${_escHtml(item.title)}</div>
        <div class="m4-news-meta">
          ${item.source ? `<span class="m4-news-src">${_escHtml(item.source)}</span>` : ''}
          ${item.pub ? `<span class="m4-news-time">${_fmtNewsDate(item.pub)}</span>` : ''}
        </div>
      </a>`).join('');
  } catch(e) {
    sec.innerHTML = '<div class="m4-news-empty">Could not load news</div>';
  }
}

function _fmtNewsDate(pubStr) {
  try {
    const diff = Math.floor((Date.now() - new Date(pubStr)) / 60000);
    if (diff < 60) return diff + 'm ago';
    if (diff < 1440) return Math.floor(diff/60) + 'h ago';
    return Math.floor(diff/1440) + 'd ago';
  } catch(e) { return ''; }
}

function _escHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Sector stocks modal ────────────────────────────────────────────────────────
let _sectorModalEl = null;

function _getSectorModal() {
  if (!_sectorModalEl) {
    _sectorModalEl = document.createElement('div');
    _sectorModalEl.className = 'sec-modal-overlay';
    _sectorModalEl.style.display = 'none';
    _sectorModalEl.innerHTML = `
      <div class="sec-modal" id="secModalInner">
        <div class="sec-modal-header">
          <div>
            <div class="sec-modal-title" id="secModalTitle">–</div>
            <div class="sec-modal-meta" id="secModalMeta"></div>
          </div>
          <span class="sec-modal-close" id="secModalClose">✕</span>
        </div>
        <div class="sec-modal-body" id="secModalBody">
          <div class="sec-modal-loading">Loading…</div>
        </div>
      </div>`;
    document.body.appendChild(_sectorModalEl);
    document.getElementById('secModalClose').onclick = closeSectorModal;
    _sectorModalEl.addEventListener('click', e => { if (e.target === _sectorModalEl) closeSectorModal(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSectorModal(); });
  }
  return _sectorModalEl;
}

function closeSectorModal() {
  const el = _getSectorModal();
  el.style.display = 'none';
}

async function openSectorModal(sectorName, sectorMeta) {
  const overlay = _getSectorModal();
  overlay.style.display = 'flex';
  document.getElementById('secModalTitle').textContent = sectorName;
  const metaParts = [];
  if (sectorMeta.chg_pct != null) metaParts.push((sectorMeta.chg_pct >= 0 ? '+' : '') + sectorMeta.chg_pct.toFixed(2) + '% today');
  if (sectorMeta.pct_from_high != null) metaParts.push(sectorMeta.pct_from_high.toFixed(1) + '% from 52W high');
  if (sectorMeta.in_momentum) metaParts.push('● in momentum');
  document.getElementById('secModalMeta').textContent = metaParts.join('  ·  ');
  document.getElementById('secModalBody').innerHTML = '<div class="sec-modal-loading">Fetching stocks…</div>';

  try {
    const data = await api(`/api/market/sectors/${sectorName}/stocks`);
    if (!data || !data.stocks || data.stocks.length === 0) {
      document.getElementById('secModalBody').innerHTML = '<div class="sec-modal-loading" style="color:var(--muted)">Constituent list not available for this index.<br>Run <code>refresh_sectors.py</code> to populate.</div>';
      return;
    }
    const cards = data.stocks.map(s => {
      const chgColor = s.chg_pct >= 0 ? 'var(--green)' : 'var(--red)';
      return `<div class="sec-modal-stock" style="cursor:pointer" onclick="openInCharts('${s.symbol}')">
        <div class="sms-sym">${s.symbol} <span class="chart-link" style="pointer-events:none">↗</span></div>
        <div class="sms-price">₹${s.price?.toLocaleString('en-IN')}</div>
        <div class="sms-chg" style="color:${chgColor}">${s.chg_pct >= 0 ? '+' : ''}${s.chg_pct?.toFixed(2)}%</div>
      </div>`;
    }).join('');
    document.getElementById('secModalTitle').textContent = `${sectorName} · ${data.total} stocks`;
    document.getElementById('secModalBody').innerHTML = `<div class="sec-modal-stock-grid">${cards}</div>`;
  } catch(e) {
    let msg = e.message;
    try { msg = JSON.parse(msg).detail || msg; } catch(_) {}
    document.getElementById('secModalBody').innerHTML = `<div class="sec-modal-loading" style="color:var(--red)">${msg}</div>`;
  }
}
