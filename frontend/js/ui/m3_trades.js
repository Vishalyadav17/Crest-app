// ── Module 3: My Trades + My Swings ───────────────────────────────────────────
let _m3TradesLoaded = false;
let _m3TradesData   = null;
let _m3SwingsData   = null;

const _M3_CLOSED_PAGE_SIZE = 15;
let _m3ClosedPage = 0;

function toggleTradesTable(which) {
  const wrap  = document.getElementById(which === 'open' ? 'm3OpenTableWrap' : 'm3ClosedTableWrap');
  const caret = document.getElementById(which === 'open' ? 'm3OpenCaret' : 'm3ClosedCaret');
  if (!wrap) return;
  const collapsed = wrap.style.display === 'none';
  wrap.style.display = collapsed ? '' : 'none';
  if (caret) caret.textContent = collapsed ? '▾' : '▸';
}

// WS handlers for trade rows: tradeId → handler fn
const _tradeWsHandlers = new Map();

async function reconcileTrades() {
  const btn = document.getElementById('m3ReconcileBtn');
  const msg = document.getElementById('m3ReconcileMsg');
  if (btn) { btn.disabled = true; btn.dataset.html = btn.innerHTML; btn.textContent = 'Refreshing…'; }
  if (msg) msg.textContent = 'Pulling holdings + positions from Kite…';
  try {
    const d = await apiFetch('/api/swing/reconcile', { method: 'POST' });
    const c = d.changes || {};
    const bits = [];
    if (c.created?.length) bits.push(`${c.created.length} added`);
    if (c.closed?.length)  bits.push(`${c.closed.length} closed`);
    if (c.updated?.length) bits.push(`${c.updated.length} updated`);
    if (c.merged?.length)  bits.push(`${c.merged.length} merged`);
    if (msg) msg.textContent = bits.length ? `Synced — ${bits.join(', ')}.` : 'Synced — no changes.';
    _m3TradesLoaded = false;
    _m3SwingsData = null;
    await loadMyTrades();
    const unc = c.unclassified || [];
    if (unc.length) _showClassifyPopup(unc);
  } catch (e) {
    if (msg) msg.textContent = 'Refresh failed — ' + (e.message || 'connect Kite in Settings').slice(0, 120);
  } finally {
    if (btn) { btn.disabled = false; if (btn.dataset.html) btn.innerHTML = btn.dataset.html; }
  }
}

function _showClassifyPopup(items) {
  const rows = items.map(it => `
    <div class="m3-cls-row" data-sym="${it.sym}">
      <div class="m3-cls-sym">${it.sym}<span class="m3-cls-meta">${it.qty} @ ₹${(it.avg||0).toLocaleString('en-IN',{maximumFractionDigits:2})}</span></div>
      <select class="m3-type-sel m3-cls-sel">
        <option value="long_term" ${it.suggested==='long_term'?'selected':''}>Long-term</option>
        <option value="swing" ${it.suggested==='swing'?'selected':''}>Swing</option>
        <option value="manual" ${it.suggested==='manual'?'selected':''}>Manual</option>
      </select>
    </div>`).join('');
  const ov = document.createElement('div');
  ov.className = 'm3-cls-overlay';
  ov.innerHTML = `<div class="m3-cls-modal">
    <div class="m3-cls-hdr">New holdings from Kite — where do these go?</div>
    <div class="m3-cls-subhdr">${items.length} untracked stock${items.length===1?'':'s'}. <b>Long-term</b> → Indian Equity · <b>Swing/Manual</b> → My Trades.</div>
    <div class="m3-cls-list">${rows}</div>
    <div class="m3-cls-actions">
      <button class="m3-rerun-btn" id="m3ClsCancel">Later</button>
      <button class="m3-rerun-btn m3-cls-confirm" id="m3ClsConfirm">Save placement</button>
    </div>
  </div>`;
  document.body.appendChild(ov);
  ov.addEventListener('click', e => { if (e.target === ov) ov.remove(); });
  ov.querySelector('#m3ClsCancel').onclick = () => ov.remove();
  ov.querySelector('#m3ClsConfirm').onclick = async () => {
    const cls = {};
    ov.querySelectorAll('.m3-cls-row').forEach(r => { cls[r.dataset.sym] = r.querySelector('select').value; });
    const btn = ov.querySelector('#m3ClsConfirm');
    btn.disabled = true; btn.textContent = 'Saving…';
    try {
      await apiFetch('/api/portfolio/classify', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ classifications: cls }),
      });
      ov.remove();
      await loadMyTrades();
    } catch (e) { btn.disabled = false; btn.textContent = 'Save placement'; }
  };
}

async function loadMyTrades() {
  _m3TradesLoaded = true;
  const d = await api('/api/portfolio/swings').catch(() => null);
  if (!d) return;
  _m3SwingsData = d;
  _renderTradesTable(d);
  _updateCombinedKpiDeployed();
  if (d.active?.length) {
    api('/api/portfolio/swings/unrealised').then(ur => {
      if (ur?.positions) _applySwingsUnrealisedDOM(ur.positions);
    }).catch(() => {});
    _subscribeSwingPrices(d.active);
  }
}

async function _updateCombinedKpiDeployed() {
  const fmt = v => v != null ? v.toLocaleString('en-IN', {maximumFractionDigits:0}) : '–';
  const d = await api('/api/swing/combined-summary').catch(() => null);
  if (!d) return;

  document.getElementById('m3KpiDeployed').textContent   = d.total_invested ? '₹' + fmt(d.total_invested) : '–';
  document.getElementById('m3KpiClosedPl').textContent   = d.closed_pl != null ? (d.closed_pl >= 0 ? '+' : '') + '₹' + fmt(Math.abs(d.closed_pl)) : '–';
  document.getElementById('m3KpiClosedPl').className     = 'm3-trades-kpi-val ' + (d.closed_pl > 0 ? 'green' : d.closed_pl < 0 ? 'red' : '');
  document.getElementById('m3KpiWinRate').textContent    = d.win_rate != null ? d.win_rate + '%' : '–';
  document.getElementById('m3KpiWinRate').className      = 'm3-trades-kpi-val ' + (d.win_rate_class || '');

  const b = d.budget;
  const meter = document.getElementById('m3BudgetMeter');
  if (b && meter) {
    meter.style.display = '';
    meter.classList.toggle('over', !!b.over);
    document.getElementById('m3BudgetDeployed').textContent = '₹' + fmt(b.deployed);
    document.getElementById('m3BudgetFree').textContent     = '₹' + fmt(b.free);
    document.getElementById('m3BudgetTotal').textContent    = '₹' + fmt(b.total);
    const fill = document.getElementById('m3BudgetFill');
    if (fill) fill.style.width = Math.min(100, Math.max(0, b.pct_deployed || 0)) + '%';
  }

  const uEl    = document.getElementById('m3KpiUnrealised');
  const uSubEl = document.getElementById('m3KpiUnrealisedPct');
  if (d.unrealised_pnl != null) {
    if (uEl) { uEl.textContent = (d.unrealised_pnl >= 0 ? '+' : '') + '₹' + fmt(Math.abs(d.unrealised_pnl)); uEl.className = 'm3-trades-kpi-val ' + (d.unrealised_pnl > 0 ? 'green' : d.unrealised_pnl < 0 ? 'red' : ''); }
    if (uSubEl && d.unrealised_pct_on_deployed != null) { uSubEl.textContent = (d.unrealised_pct_on_deployed >= 0 ? '+' : '') + d.unrealised_pct_on_deployed + '% on deployed'; }
  } else {
    if (uEl) uEl.textContent = '–';
    if (uSubEl) uSubEl.textContent = '–';
  }
}

function _typeDropdown(s) {
  const manual = s.trade_type === 'manual';
  return `<select class="m3-type-sel" onchange="setTradeType(${s.id}, this.value)" title="Manual trades are excluded from scanner win-rate">
    <option value="scanner" ${manual ? '' : 'selected'}>Scanner</option>
    <option value="manual" ${manual ? 'selected' : ''}>Manual</option>
  </select>`;
}

async function setTradeType(id, type) {
  try {
    await apiFetch('/api/swing/trades/' + id + '/type', {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trade_type: type }),
    });
    if (_m3SwingsData) {
      ['active', 'closed'].forEach(k => (_m3SwingsData[k] || []).forEach(t => { if (t.id === id) t.trade_type = type; }));
    }
    _updateCombinedKpiDeployed();
  } catch (e) { /* dropdown reverts on next load */ }
}

function _renderTradesTable(d) {
  const active = d.active || [];
  const closed = d.closed || [];

  document.getElementById('m3TradesOpenCount').textContent = active.length;
  document.getElementById('m3TradesClosedCount').textContent = closed.length;

  const badge = document.getElementById('m3TradesBadge');
  if (badge) {
    badge.style.display = active.length > 0 ? '' : 'none';
    badge.textContent = active.length;
  }

  const tbl = document.getElementById('m3TradesOpenBody')?.closest('table');
  if (tbl) {
    tbl.ondragover = e => { e.preventDefault(); tbl.classList.add('drag-over'); };
    tbl.ondragleave = () => tbl.classList.remove('drag-over');
    tbl.ondrop = async e => {
      e.preventDefault();
      tbl.classList.remove('drag-over');
      const pickId = parseInt(e.dataTransfer.getData('text/pick-id') || '0');
      if (!pickId) return;
      const r = await apiFetch('/api/swing/promote-to-trade', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pick_id: pickId }),
      });
      if (r?.ok) { await loadMyTrades(); await _refreshScanner(); }
    };
  }

  document.getElementById('m3TradesOpenBody').innerHTML = active.length
    ? active.map(s => {
        const inv     = s.invested != null ? '₹' + s.invested.toLocaleString('en-IN', {maximumFractionDigits:0}) : '–';
        const ltBadge = s.hold_long_term ? '<span class="m3-lt-badge">[LT]</span>' : '';
        return `<tr id="swrow_${s.id}">
          <td><span style="color:var(--blue);font-weight:700">${s.sym}</span>${ltBadge}<span class="chart-link" onclick="openInCharts('${s.sym}')">↗</span></td>
          <td>${_typeDropdown(s)}</td>
          <td>₹${s.avg?.toLocaleString('en-IN',{maximumFractionDigits:2}) ?? '–'}</td>
          <td>${s.qty ?? '–'}</td>
          <td>${inv}</td>
          <td><div class="m3-trades-cmp-cell" id="swcmp_${s.id}"><span style="color:var(--muted);font-size:11px">–</span></div></td>
          <td id="swpl_${s.id}" style="color:var(--muted)">–</td>
          <td id="swplpct_${s.id}" style="color:var(--muted)">–</td>
          <td class="red">${s.sl ? '₹'+s.sl.toLocaleString('en-IN',{maximumFractionDigits:2}) : '–'}</td>
          <td class="green">${s.target ? '₹'+s.target.toLocaleString('en-IN',{maximumFractionDigits:2}) : '–'}</td>
          <td>
            <button class="m3-edit-btn" onclick="_showSwingEditForm(${s.id},'${s.sym}',${s.avg||0},${s.qty||0},${s.sl||0},${s.target||0})">Edit</button>
            <button class="m3-close-btn" onclick="_showSwingExitForm(${s.id},'${s.sym}',${s.avg||0},${s.qty||0})">Close</button>
            <button class="m3-lt-btn" title="${s.hold_long_term ? 'Clear LT' : 'Mark Long-term'}" onclick="_toggleLongTerm(${s.id},${!s.hold_long_term})">${s.hold_long_term ? '⊠' : '⊞'} LT</button>
          </td>
        </tr>`;
      }).join('')
    : '<tr><td colspan="11" class="m3-trades-empty">No open trades. Click "Refresh from Kite" or "+ Add Manual Trade". You can also drag a scanner pick here.</td></tr>';

  const pageCount = Math.max(1, Math.ceil(closed.length / _M3_CLOSED_PAGE_SIZE));
  if (_m3ClosedPage >= pageCount) _m3ClosedPage = pageCount - 1;
  if (_m3ClosedPage < 0) _m3ClosedPage = 0;
  const start    = _m3ClosedPage * _M3_CLOSED_PAGE_SIZE;
  const pageRows = closed.slice(start, start + _M3_CLOSED_PAGE_SIZE);

  document.getElementById('m3TradesClosedBody').innerHTML = pageRows.length
    ? pageRows.map(s => {
        const pl     = s.realized_pnl;
        const retPct = s.return_pct;
        const win    = (s.realized_pnl || 0) > 0;
        const typeLabel = s.trade_type === 'manual' ? 'Manual' : 'Scanner';
        return `<tr>
          <td><span style="color:var(--blue);font-weight:700">${s.sym}</span></td>
          <td><span style="color:var(--muted);font-size:10px">${typeLabel}</span></td>
          <td>₹${s.avg?.toLocaleString('en-IN',{maximumFractionDigits:2}) ?? '–'}</td>
          <td>₹${s.exit?.toLocaleString('en-IN',{maximumFractionDigits:2}) ?? '–'}</td>
          <td>${s.qty ?? '–'}</td>
          <td class="${pl > 0 ? 'green' : pl < 0 ? 'red' : ''}">${pl != null ? (pl >= 0 ? '+' : '') + '₹' + Math.abs(pl).toLocaleString('en-IN',{maximumFractionDigits:0}) : '–'}</td>
          <td class="${retPct > 0 ? 'green' : retPct < 0 ? 'red' : ''}">${retPct != null ? (retPct >= 0 ? '+' : '') + retPct.toFixed(2) + '%' : '–'}</td>
          <td><span class="m3-result-badge ${win ? 'win' : 'loss'}">${win ? 'WIN' : 'LOSS'}</span></td>
        </tr>`;
      }).join('')
    : '<tr><td colspan="8" class="m3-trades-empty">No closed trades yet.</td></tr>';

  _renderClosedPager(closed.length, pageCount, start, pageRows.length);
}

function _renderClosedPager(total, pageCount, start, shown) {
  const pager = document.getElementById('m3ClosedPager');
  if (!pager) return;
  if (total <= _M3_CLOSED_PAGE_SIZE) { pager.style.display = 'none'; pager.innerHTML = ''; return; }
  pager.style.display = '';
  const from = total ? start + 1 : 0;
  const to   = start + shown;
  pager.innerHTML = `
    <button class="m3-pager-btn" ${_m3ClosedPage <= 0 ? 'disabled' : ''} onclick="_m3ClosedGoto(${_m3ClosedPage - 1})">‹ Prev</button>
    <span class="m3-pager-info">${from}–${to} of ${total}</span>
    <button class="m3-pager-btn" ${_m3ClosedPage >= pageCount - 1 ? 'disabled' : ''} onclick="_m3ClosedGoto(${_m3ClosedPage + 1})">Next ›</button>`;
}

function _m3ClosedGoto(page) {
  _m3ClosedPage = page;
  if (_m3SwingsData) _renderTradesTable(_m3SwingsData);
}

function _applySwingsUnrealisedDOM(positions) {
  if (!positions?.length) return;
  const posMap = Object.fromEntries(positions.map(p => [p.id, p]));
  (_m3SwingsData?.active || []).forEach(s => {
    const pos   = posMap[s.id];
    const cell  = document.getElementById('swcmp_' + s.id);
    if (!pos?.cmp || !cell) return;
    const pl    = pos.unrealised_pl;
    const plPct = pos.unrealised_pct;
    const plColor = pl > 0 ? 'var(--green)' : pl < 0 ? 'var(--red)' : 'var(--muted)';
    cell.innerHTML = `<span style="font-family:var(--font-display);font-weight:700">₹${pos.cmp.toLocaleString('en-IN',{maximumFractionDigits:2})}</span>`;
    const plEl    = document.getElementById('swpl_'    + s.id);
    const plPctEl = document.getElementById('swplpct_' + s.id);
    if (plEl)    { plEl.textContent = pl != null ? (pl >= 0 ? '+' : '') + '₹' + Math.abs(pl).toLocaleString('en-IN',{maximumFractionDigits:0}) : '–'; plEl.style.color = plColor; }
    if (plPctEl) { plPctEl.textContent = plPct != null ? (plPct >= 0 ? '+' : '') + plPct.toFixed(1) + '%' : '–'; plPctEl.style.color = plColor; }
  });
}

// WS live price updates for swing trade rows
function _subscribeSwingPrices(active) {
  if (!active?.length || !_isMarketHours()) return;
  const syms = [...new Set(active.map(s => s.sym))];
  PriceWsClient.subscribe(syms);
  active.forEach(s => {
    const old = _tradeWsHandlers.get(s.id);
    if (old) PriceWsClient.offPrice(s.sym, old);
    const handler = payload => {
      const ltp = payload?.ltp;
      if (!ltp) return;
      const cell = document.getElementById('swcmp_' + s.id);
      if (cell) cell.innerHTML = `<span style="font-family:var(--font-display);font-weight:700">₹${ltp.toLocaleString('en-IN',{maximumFractionDigits:2})}</span>`;
      if (s.avg && s.qty) {
        const pl    = (ltp - s.avg) * s.qty;
        const plPct = (ltp - s.avg) / s.avg * 100;
        const plColor = pl > 0 ? 'var(--green)' : pl < 0 ? 'var(--red)' : 'var(--muted)';
        const plEl    = document.getElementById('swpl_'    + s.id);
        const plPctEl = document.getElementById('swplpct_' + s.id);
        if (plEl)    { plEl.textContent = (pl >= 0 ? '+' : '') + '₹' + Math.abs(pl).toLocaleString('en-IN',{maximumFractionDigits:0}); plEl.style.color = plColor; }
        if (plPctEl) { plPctEl.textContent = (plPct >= 0 ? '+' : '') + plPct.toFixed(1) + '%'; plPctEl.style.color = plColor; }
      }
    };
    _tradeWsHandlers.set(s.id, handler);
    PriceWsClient.onPrice(s.sym, handler);
  });
}

function _showSwingAddForm() {
  const wrap = document.getElementById('m3SwingAddFormWrap');
  if (!wrap) return;
  if (wrap.innerHTML) { wrap.innerHTML = ''; return; }
  wrap.innerHTML = `
    <div class="m3-swing-form">
      <div class="m3-swing-form-group">
        <span class="m3-swing-form-label">Symbol</span>
        <input class="m3-swing-form-inp wide" id="swFormSym" type="text" placeholder="e.g. RELIANCE" autocomplete="off" style="text-transform:uppercase">
      </div>
      <div class="m3-swing-form-group">
        <span class="m3-swing-form-label">Qty</span>
        <input class="m3-swing-form-inp" id="swFormQty" type="text" inputmode="decimal" placeholder="Qty">
      </div>
      <div class="m3-swing-form-group">
        <span class="m3-swing-form-label">Entry ₹</span>
        <input class="m3-swing-form-inp" id="swFormEntry" type="text" inputmode="decimal" placeholder="Avg price">
      </div>
      <div class="m3-swing-form-group">
        <span class="m3-swing-form-label">SL ₹ (opt)</span>
        <input class="m3-swing-form-inp" id="swFormSL" type="text" inputmode="decimal" placeholder="Stop loss">
      </div>
      <div class="m3-swing-form-group">
        <span class="m3-swing-form-label">Target ₹ (opt)</span>
        <input class="m3-swing-form-inp" id="swFormTarget" type="text" inputmode="decimal" placeholder="Target">
      </div>
      <button class="m3-swing-save-btn" onclick="_saveNewSwing()">Add</button>
      <button class="m3-swing-cancel-btn" onclick="document.getElementById('m3SwingAddFormWrap').innerHTML=''">✕</button>
    </div>`;
  const symEl   = document.getElementById('swFormSym');
  const entryEl = document.getElementById('swFormEntry');
  symEl?.focus();
  symEl?.addEventListener('input', e => { e.target.value = e.target.value.toUpperCase(); });
  symEl?.addEventListener('blur', async e => {
    const sym = e.target.value.trim().toUpperCase();
    if (!sym || entryEl?.value) return;
    try {
      const r = await api('/api/portfolio/cmp?syms=' + sym);
      const ltp = r?.[sym]?.ltp;
      if (ltp && entryEl) { entryEl.value = ltp.toFixed(2); entryEl.style.borderColor = 'var(--blue)'; }
    } catch(e2) {}
  });
}

async function _saveNewSwing() {
  const sym    = document.getElementById('swFormSym')?.value.trim().toUpperCase();
  const qty    = parseFloat(document.getElementById('swFormQty')?.value) || null;
  const avg    = parseFloat(document.getElementById('swFormEntry')?.value);
  const sl     = parseFloat(document.getElementById('swFormSL')?.value) || null;
  const target = parseFloat(document.getElementById('swFormTarget')?.value) || null;
  if (!sym) { alert('Enter a symbol.'); return; }
  if (!avg || avg <= 0) { alert('Enter a valid entry price.'); return; }
  await fetch(API + '/api/portfolio/swings', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({sym, qty, avg_price: avg, sl, target}),
  });
  document.getElementById('m3SwingAddFormWrap').innerHTML = '';
  await loadMySwings();
}

function loadMySwings() { return loadMyTrades(); }

function _showSwingEditForm(swingId, sym, avg, qty, sl, target) {
  const row = document.getElementById('swrow_' + swingId);
  if (!row) return;
  const existingForm = document.getElementById('sweditrow_' + swingId);
  if (existingForm) { existingForm.remove(); return; }
  const formRow = document.createElement('tr');
  formRow.id = 'sweditrow_' + swingId;
  formRow.className = 'm3-exit-row';
  formRow.innerHTML = `<td colspan="11">
    <div class="m3-exit-form">
      <span style="font-size:11px;color:var(--muted2);font-family:var(--font-display)">Edit ${sym}:</span>
      <div class="m3-swing-form-group">
        <span class="m3-swing-form-label">Entry ₹</span>
        <input class="m3-exit-inp" id="sweditp_${swingId}" type="text" inputmode="decimal" value="${avg||''}" placeholder="Entry price">
      </div>
      <div class="m3-swing-form-group">
        <span class="m3-swing-form-label">Qty</span>
        <input class="m3-exit-inp" id="sweditq_${swingId}" type="text" inputmode="decimal" value="${qty||''}" placeholder="Qty">
      </div>
      <div class="m3-swing-form-group">
        <span class="m3-swing-form-label">SL ₹</span>
        <input class="m3-exit-inp" id="sweditsl_${swingId}" type="text" inputmode="decimal" value="${sl||''}" placeholder="SL">
      </div>
      <div class="m3-swing-form-group">
        <span class="m3-swing-form-label">Target ₹</span>
        <input class="m3-exit-inp" id="swedittgt_${swingId}" type="text" inputmode="decimal" value="${target||''}" placeholder="Target">
      </div>
      <button class="m3-exit-confirm" onclick="_saveSwingEdit(${swingId})">Save</button>
      <button class="m3-exit-cancel" onclick="document.getElementById('sweditrow_${swingId}')?.remove()">✕</button>
    </div>
  </td>`;
  row.after(formRow);
  document.getElementById('sweditp_' + swingId)?.focus();
}

async function _saveSwingEdit(swingId) {
  const avg    = parseFloat(document.getElementById('sweditp_'   + swingId)?.value);
  const qty    = parseFloat(document.getElementById('sweditq_'   + swingId)?.value) || null;
  const sl     = parseFloat(document.getElementById('sweditsl_'  + swingId)?.value) || null;
  const target = parseFloat(document.getElementById('swedittgt_' + swingId)?.value) || null;
  if (!avg || avg <= 0) { alert('Enter a valid entry price.'); return; }
  await fetch(API + '/api/portfolio/swings/' + swingId, {
    method: 'PATCH', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({avg_price: avg, qty, sl, target}),
  });
  document.getElementById('sweditrow_' + swingId)?.remove();
  await loadMySwings();
}

function _showSwingExitForm(swingId, sym, avg, qty) {
  const row = document.getElementById('swrow_' + swingId);
  if (!row) return;
  const existingForm = document.getElementById('swexitrow_' + swingId);
  if (existingForm) { existingForm.remove(); return; }
  const today = new Date().toISOString().slice(0,10);
  const formRow = document.createElement('tr');
  formRow.id = 'swexitrow_' + swingId;
  formRow.className = 'm3-exit-row';
  formRow.innerHTML = `<td colspan="11">
    <div class="m3-exit-form">
      <span style="font-size:11px;color:var(--muted2);font-family:var(--font-display)">Exit ${sym}:</span>
      <input class="m3-exit-inp" id="swexitp_${swingId}" type="text" inputmode="decimal" placeholder="Exit price">
      <input class="m3-exit-inp" id="swexitd_${swingId}" type="date" value="${today}" style="width:120px">
      <button class="m3-mktprice-btn" onclick="_fillMarketPrice('${sym}','swexitp_${swingId}')">Use Market Price</button>
      <button class="m3-exit-confirm" onclick="_confirmSwingExit(${swingId},'${sym}',${avg||0},${qty||0})">Confirm Close</button>
      <button class="m3-exit-cancel" onclick="document.getElementById('swexitrow_${swingId}')?.remove()">✕</button>
    </div>
  </td>`;
  row.after(formRow);
  document.getElementById('swexitp_' + swingId)?.focus();
}

async function _confirmSwingExit(swingId, sym, avg, qty) {
  const exitPrice = parseFloat(document.getElementById('swexitp_' + swingId)?.value);
  const exitDate  = document.getElementById('swexitd_' + swingId)?.value;
  if (!exitPrice || exitPrice <= 0) { alert('Enter a valid exit price.'); return; }
  await fetch(API + '/api/portfolio/swings/' + swingId + '/close', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({exit_price: exitPrice, exit_date: exitDate}),
  });
  document.getElementById('swexitrow_' + swingId)?.remove();
  await loadMySwings();
}

async function _toggleLongTerm(swingId, value) {
  await apiFetch('/api/swing/trades/' + swingId + '/hold-long-term', {
    method: 'PUT', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({value}),
  });
  await loadMySwings();
}

function _showExitForm(pickId, sym, entryPrice, qty) {
  const row = document.getElementById('orow_' + pickId);
  if (!row) return;
  const existingForm = document.getElementById('exitrow_' + pickId);
  if (existingForm) { existingForm.remove(); return; }
  const today = new Date().toISOString().slice(0,10);
  const formRow = document.createElement('tr');
  formRow.id = 'exitrow_' + pickId;
  formRow.className = 'm3-exit-row';
  formRow.innerHTML = `<td colspan="11">
    <div class="m3-exit-form">
      <span style="font-size:11px;color:var(--muted2);font-family:var(--font-display)">Exit ${sym}:</span>
      <input class="m3-exit-inp" id="exitprice_${pickId}" type="text" inputmode="decimal" placeholder="Exit price">
      <input class="m3-exit-inp" id="exitdate_${pickId}" type="date" value="${today}" style="width:120px">
      <button class="m3-mktprice-btn" onclick="_fillMarketPrice('${sym}','exitprice_${pickId}')">Use Market Price</button>
      <button class="m3-exit-confirm" onclick="_confirmExit(${pickId},'${sym}',${entryPrice||0},${qty||0})">Confirm Close</button>
      <button class="m3-exit-cancel" onclick="document.getElementById('exitrow_${pickId}')?.remove()">✕</button>
    </div>
  </td>`;
  row.after(formRow);
  document.getElementById('exitprice_' + pickId)?.focus();
}

async function _confirmExit(pickId, sym, entryPrice, qty) {
  const exitPrice = parseFloat(document.getElementById('exitprice_' + pickId)?.value);
  const exitDate  = document.getElementById('exitdate_' + pickId)?.value;
  if (!exitPrice || exitPrice <= 0) { alert('Enter a valid exit price.'); return; }
  await fetch(API + '/api/swing/vault/' + pickId + '/outcome', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({was_traded:true, qty, entry_price:entryPrice, exit_price:exitPrice, exit_date:exitDate}),
  });
  document.getElementById('exitrow_' + pickId)?.remove();
  _vaultDetailCache = {};
  _m3TradesLoaded = false;
  await loadMyTrades();
}

function _showPickEditForm(pickId, sym, entryPrice, qty) {
  const row = document.getElementById('orow_' + pickId);
  if (!row) return;
  const existingForm = document.getElementById('editrow_' + pickId);
  if (existingForm) { existingForm.remove(); return; }
  const formRow = document.createElement('tr');
  formRow.id = 'editrow_' + pickId;
  formRow.className = 'm3-exit-row';
  formRow.innerHTML = `<td colspan="11">
    <div class="m3-exit-form">
      <span style="font-size:11px;color:var(--muted2);font-family:var(--font-display)">Edit ${sym}:</span>
      <div class="m3-swing-form-group">
        <span class="m3-swing-form-label">Entry ₹</span>
        <input class="m3-exit-inp" id="editentry_${pickId}" type="text" inputmode="decimal" value="${entryPrice || ''}" placeholder="Entry price">
      </div>
      <div class="m3-swing-form-group">
        <span class="m3-swing-form-label">Qty</span>
        <input class="m3-exit-inp" id="editqty_${pickId}" type="text" inputmode="decimal" value="${qty || ''}" placeholder="Qty">
      </div>
      <button class="m3-exit-confirm" onclick="_savePickEdit(${pickId})">Save</button>
      <button class="m3-exit-cancel" onclick="document.getElementById('editrow_${pickId}')?.remove()">✕</button>
    </div>
  </td>`;
  row.after(formRow);
  document.getElementById('editentry_' + pickId)?.focus();
}

async function _savePickEdit(pickId) {
  const entryPrice = parseFloat(document.getElementById('editentry_' + pickId)?.value);
  const qty = parseFloat(document.getElementById('editqty_' + pickId)?.value);
  if (!entryPrice || entryPrice <= 0) { alert('Enter a valid entry price.'); return; }
  await fetch(API + '/api/swing/vault/' + pickId + '/outcome', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({was_traded:true, qty: qty||null, entry_price:entryPrice}),
  });
  document.getElementById('editrow_' + pickId)?.remove();
  _m3TradesLoaded = false;
  await loadMyTrades();
}

async function _fillMarketPrice(sym, inputId) {
  const inp = document.getElementById(inputId);
  if (!inp) return;
  inp.placeholder = 'fetching…';
  const cached = _getCachedCmp();
  if (cached?.prices?.[sym]) {
    inp.value = cached.prices[sym];
    return;
  }
  try {
    const d = await api('/api/portfolio/cmp?symbols=' + encodeURIComponent(sym)).catch(() => null);
    if (d?.prices?.[sym]) {
      inp.value = d.prices[sym];
      if (_cmpPrices) _cmpPrices.prices[sym] = d.prices[sym];
    } else {
      inp.placeholder = 'not found';
    }
  } catch { inp.placeholder = 'error'; }
}
