// ── M1 Kite sync row ─────────────────────────────────────────────────────────
const _M1_KITE_TOOLS = [
  { name: 'get_holdings',    label: 'Holdings' },
  { name: 'get_positions',   label: 'Positions' },
  { name: 'get_margins',     label: 'Margins' },
  { name: 'get_mf_holdings', label: 'Mutual Funds' },
];

async function _m1LoadKiteRow() {
  const row = document.getElementById('m1KiteRow');
  if (!row) return;
  let status = { authenticated: false };
  try { status = await api('/api/kite/status'); } catch(e) { return; }
  if (!status.authenticated) return;

  const btns = _M1_KITE_TOOLS.map(t =>
    `<button class="m6-btn m6-btn-secondary m6-btn-sm" data-tool="${t.name}" onclick="_m1KiteFetch(this,'${t.name}','${t.label}')">${t.label}</button>`
  ).join('');
  row.innerHTML = `<span style="font-size:11px;color:var(--muted);font-family:var(--font-display)">Kite sync:</span>${btns}<span id="m1KiteSyncMsg" style="font-size:10px;color:var(--muted);font-family:var(--font-display)"></span>`;
  row.style.display = 'flex';
}

async function _m1KiteFetch(btn, tool, label) {
  const msg = document.getElementById('m1KiteSyncMsg');
  btn.disabled = true; btn.textContent = '…';
  if (msg) msg.textContent = '';
  try {
    const d = await apiFetch('/api/kite/tool/' + tool, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    const count = Array.isArray(d?.data) ? d.data.length : 0;
    if (msg) { msg.style.color = 'var(--green)'; msg.textContent = `${label} synced (${count})`; }
    // Reload overview to reflect updated data
    loadOverview();
  } catch(e) {
    if (msg) { msg.style.color = 'var(--red)'; msg.textContent = `${label} failed`; }
  } finally {
    btn.disabled = false; btn.textContent = label;
  }
}

// ── Quote ────────────────────────────────────────────────────────────────────
async function loadQuote() {
  const q = await api('/api/quote');
  if (!q) return;
  document.getElementById('quoteText').textContent = '"' + q.text + '"';
  document.getElementById('quoteAuthor').textContent = '— ' + q.author;
}
async function nextQuote() { await loadQuote(); }

function sidebarClose() {
  document.getElementById('sidebar').classList.add('sidebar-hidden');
  document.getElementById('page-content').classList.add('full-width');
}
let _vaultWeeks = [];
let _vaultCurrentKey = null;
let _vaultDetailCache = {};  // runId → full picks response; invalidated on any outcome write

function _toggleVaultSearch(btn) {
  const inp = document.getElementById('m3VaultSearch');
  if (!inp) return;
  const isOpen = inp.style.display !== 'none';
  inp.style.display = isOpen ? 'none' : '';
  btn.classList.toggle('active', !isOpen);
  if (!isOpen) inp.focus();
  else { inp.value = ''; filterVaultCards(''); }
}

function _generateVaultMonths() {
  const sel = document.getElementById('m3VaultMonthSel');
  if (!sel) return;
  const start = new Date(2026, 4, 1);
  const now = new Date();
  const end = new Date(now.getFullYear(), now.getMonth(), 1);
  const months = [];
  let d = new Date(start);
  while (d <= end) {
    const key = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;
    const label = d.toLocaleDateString('en-IN', {month:'long', year:'numeric'});
    months.push({key, label});
    d.setMonth(d.getMonth() + 1);
  }
  months.reverse();
  // "All" first + default — so every scan folder (across months) is visible by default;
  // month is an optional narrowing filter, not a hide-everything-else default.
  sel.innerHTML = '<option value="all">All scans</option>'
    + months.map(m => `<option value="${m.key}">${m.label}</option>`).join('');
}

function _onVaultMonthChange(monthKey) {
  if (monthKey === 'all') {
    _renderVaultFolders(_vaultWeeks);
    _vaultCurrentKey = null;
    if (typeof _resetVaultHeader === 'function') _resetVaultHeader();
    const det = document.getElementById('m3VaultDetail');
    if (det) det.innerHTML = `<div class="m3-vault-detail-empty"><span class="material-symbols-outlined" style="font-size:36px;color:var(--muted)">folder_open</span><div style="font-size:13px;color:var(--muted2);margin-top:10px">Select a scan folder to view its picks</div></div>`;
    return;
  }
  const [yr, mo] = monthKey.split('-').map(Number);
  const filtered = _vaultWeeks.filter(w => {
    if (!w.scanned_at) return true;
    const d = new Date(w.scanned_at);
    return d.getFullYear() === yr && d.getMonth() + 1 === mo;
  });
  _renderVaultFolders(filtered);
  _vaultCurrentKey = null;
  if (typeof _resetVaultHeader === 'function') _resetVaultHeader();
  const detail = document.getElementById('m3VaultDetail');
  if (detail) detail.innerHTML = `<div class="m3-vault-detail-empty"><span class="material-symbols-outlined" style="font-size:36px;color:var(--muted)">folder_open</span><div style="font-size:13px;color:var(--muted2);margin-top:10px">Select a scan folder to view its picks</div></div>`;
}

function filterVaultCards(q) {
  const lq = q.toLowerCase();
  const sel = document.getElementById('m3VaultMonthSel');
  const monthKey = sel?.value || '';
  const [yr, mo] = monthKey ? monthKey.split('-').map(Number) : [0, 0];
  const filtered = _vaultWeeks.filter(w => {
    if (yr && mo && w.scanned_at) {
      const d = new Date(w.scanned_at);
      if (d.getFullYear() !== yr || d.getMonth() + 1 !== mo) return false;
    }
    if (!lq) return true;
    const range = w.scanned_at ? _scanWeekRange(w.scanned_at) : (w.key || '');
    return range.toLowerCase().includes(lq);
  });
  _renderVaultFolders(filtered);
}

function _updateVaultHeaderFromFolder(picks, marketSummary) {
  // Sector allocation — live from the folder's picks
  const secCount = {};
  picks.forEach(p => { const s = p.sector || 'Other'; secCount[s] = (secCount[s] || 0) + 1; });
  const tot = picks.length || 1;
  const sectorDist = Object.entries(secCount)
    .map(([sector, count]) => ({ sector, pct: Math.round(count / tot * 100) }))
    .sort((a, b) => b.pct - a.pct).slice(0, 5);
  if (typeof _renderCompactSectorDist === 'function') _renderCompactSectorDist(sectorDist);

  // Avg R:R — live mean of pick R:R
  const rrs = picks.map(p => (p.levels || {}).rr).filter(x => x);
  const avgRR = rrs.length ? (rrs.reduce((a, b) => a + b, 0) / rrs.length).toFixed(1) : null;
  const rrEl = document.getElementById('m3VaultRR');
  if (rrEl) rrEl.textContent = avgRR ? '1:' + avgRR : '–';

  // Win rate — closed picks in this folder
  let wins = 0, losses = 0;
  picks.forEach(p => {
    const oc = (p.outcomes || []).find(o => o.exit_price);
    if (oc) { (oc.return_pct || 0) > 0 ? wins++ : losses++; }
    else if (p.scan_result === 'TARGET_HIT') wins++;
    else if (p.scan_result === 'SL_HIT') losses++;
  });
  const closedN = wins + losses;
  const wr = closedN ? Math.round(wins / closedN * 100) : null;
  const wrEl = document.getElementById('m3VaultWinRate');
  if (wrEl) { wrEl.textContent = wr != null ? wr + '%' : '–'; wrEl.className = 'm3-vsc-val ' + (wr == null ? '' : wr >= 60 ? 'green' : 'gold-c'); }

  // Sentiment — folder's market signal
  const sig = (marketSummary.signal || '').toString();
  const sigL = sig.toLowerCase();
  const sEl = document.getElementById('m3VaultSentiment');
  if (sEl) { sEl.textContent = sig ? sig.charAt(0) + sig.slice(1).toLowerCase() : '–';
    sEl.className = 'm3-vsc-val ' + (sigL === 'bullish' ? 'green' : sigL === 'caution' ? 'red' : sig ? 'gold-c' : ''); }
}

async function openVaultDetail(weekKey, dateLabel, cardEl) {
  document.querySelectorAll('.m3-vault-card').forEach(c => c.classList.remove('selected'));
  if (cardEl) cardEl.classList.add('selected');
  _vaultCurrentKey = weekKey;
  const detail = document.getElementById('m3VaultDetail');
  // Use cached response if available — avoids re-fetching same scan data
  let d = _vaultDetailCache[weekKey];
  if (!d) {
    detail.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:180px;color:var(--muted);font-size:13px">Loading…</div>`;
    d = await api('/api/swing/vault/' + weekKey).catch(
      () => api('/api/swing/history/' + weekKey).catch(() => null)
    );
    if (d) _vaultDetailCache[weekKey] = d;
  }
  if (!d) {
    detail.innerHTML = `<div style="text-align:center;color:var(--muted);padding:40px">Failed to load data.</div>`;
    return;
  }
  const picks = d.picks || [];
  const st = d.stats || {};
  const successCount = st.success_count ?? 0;
  const failureCount = st.failure_count ?? 0;
  const tradedCount  = st.traded_count  ?? 0;
  const avgRR        = st.avg_rr        ?? null;

  // ── Drive the top header (Sectors / Avg R:R / Win Rate / Sentiment) from THIS folder ──
  _updateVaultHeaderFromFolder(picks, d.market_summary || {});

  const rows = picks.map(p => {
    const lvl = p.levels || {};
    const mcap = p.mcap_cr ? (p.mcap_cr >= 10000 ? (p.mcap_cr/1000).toFixed(1)+'K' : Math.round(p.mcap_cr)) + 'Cr' : '–';
    const entryCell = (lvl.entry_lo && lvl.entry_hi) ? `₹${lvl.entry_lo} – ₹${lvl.entry_hi}` : (lvl.entry ? '₹'+lvl.entry : '–');
    const tradedOutcome = (p.outcomes||[]).find(o => o.was_traded);
    // any closed outcome (real fill OR synthetic month-end time-exit) carries exit_price + return_pct
    const closedOutcome = (p.outcomes||[]).find(o => o.exit_price != null);
    let resultBadge = '<span style="color:var(--muted);font-size:11px">–</span>';
    if (closedOutcome) {
      const win = (closedOutcome.return_pct || 0) >= 0;
      const retStr = closedOutcome.return_pct != null ? ` ${closedOutcome.return_pct >= 0 ? '+' : ''}${closedOutcome.return_pct.toFixed(1)}%` : '';
      const label = p.scan_result === 'TARGET_HIT' ? 'SUCCESS' : (win ? 'WIN' : 'FAIL');
      resultBadge = `<span class="m3-result-badge ${win ? 'win' : 'loss'}">${label}${retStr}</span>`;
    } else if (tradedOutcome?.was_traded) {
      resultBadge = `<span style="font-size:10px;font-weight:700;font-family:var(--font-display);color:var(--blue)">OPEN</span>`;
    } else if (p.scan_result === 'SL_HIT') {
      resultBadge = `<span class="m3-result-badge loss">FAIL</span>`;
    } else if (p.scan_result === 'TARGET_HIT') {
      resultBadge = `<span class="m3-result-badge win">SUCCESS</span>`;
    } else if (p.scan_result === 'TIME_EXIT') {
      resultBadge = `<span class="m3-result-badge loss">FAIL</span>`;
    }
    const ai = p.ai;
    let aiCell = '<span style="color:var(--muted);font-size:11px">–</span>';
    if (ai && ai.verdict) {
      const vc = ['pass','hold','exit_good'].includes(ai.class) ? 'good'
               : ['caution','weak'].includes(ai.class) ? 'warn' : 'bad';
      const click = ai.has_detail
        ? `onclick="openAiDrawer(${p.id}, ${JSON.stringify(p.symbol)})" style="cursor:pointer" title="View AI thesis"` : '';
      aiCell = `<span class="m3-ai-verdict ${vc}" ${click}><span class="material-symbols-outlined">psychology</span>${ai.verdict}</span>`;
    }
    return `<tr>
      <td>${p.symbol}</td>
      <td style="text-align:left;color:var(--muted);font-size:11px">${p.sector||'–'}</td>
      <td><span class="m3-comp-pill">${p.composite_score != null ? (Math.round(p.composite_score*10)/10) : (p.total ?? '–')}</span></td>
      <td style="text-align:left">${entryCell}</td>
      <td class="red">₹${lvl.sl||'–'}</td>
      <td class="green">₹${lvl.target||'–'}</td>
      <td>${lvl.rr ? '1:'+lvl.rr : '–'}</td>
      <td class="muted" title="Suggested holding horizon (from AI deep-dive)">${p.hold_horizon_days ? p.hold_horizon_days + 'd' : '–'}</td>
      <td class="muted">${mcap}</td>
      <td style="text-align:left">${resultBadge}</td>
      <td style="text-align:left" class="m3-ai-verdict-cell">${aiCell}</td>
    </tr>`;
  }).join('');

  const review = d.review;
  let reviewHtml = '';
  if (review && review.summary) {
    // themes_json is an array (batch_review) OR a structured object (weekend review) — normalize
    // so .map never throws (this was crashing the whole vault detail render → stuck on "Loading…").
    const _rt = review.themes;
    const themesArr = Array.isArray(_rt)
      ? _rt
      : (_rt && typeof _rt === 'object'
          ? Object.values(_rt).flat().filter(t => typeof t === 'string')
          : []);
    const themes = themesArr.map(t => `<span class="m3-rev-theme">${t}</span>`).join('');
    reviewHtml = `
      <div class="m3-scan-review">
        <div class="m3-scan-review-hdr">
          <span class="material-symbols-outlined">psychology</span>
          <span>AI Scan Review</span>
          ${review.model_used ? `<span class="m3-scan-review-model">${review.model_used}</span>` : ''}
        </div>
        <div class="m3-scan-review-body">${review.summary}</div>
        <div class="m3-scan-review-meta">
          ${review.strong_count != null ? `<span class="good">${review.strong_count} strong</span>` : ''}
          ${review.weak_count != null ? `<span class="bad">${review.weak_count} weak</span>` : ''}
          ${review.best_sym ? `<span>Best: <b>${review.best_sym}</b></span>` : ''}
          ${review.worst_sym ? `<span>Worst: <b>${review.worst_sym}</b></span>` : ''}
        </div>
        ${themes ? `<div class="m3-scan-review-themes">${themes}</div>` : ''}
      </div>`;
  }

  detail.innerHTML = `
    <div class="m3-vault-det-hdr">
      <div class="m3-vault-det-title">
        <span class="material-symbols-outlined" style="font-size:17px;color:var(--blue)">folder_open</span>
        ${dateLabel}
      </div>
      <button class="m3-popup-export" onclick="exportVaultCSV()">
        <span class="material-symbols-outlined" style="font-size:13px">download</span> CSV
      </button>
    </div>
    <div class="m3-vault-det-stats">
      <div class="m3-vault-det-stat"><div class="label">Total Picks</div><div class="value">${picks.length}</div></div>
      <div class="m3-vault-det-stat"><div class="label">Traded</div><div class="value">${tradedCount || '–'}</div></div>
      <div class="m3-vault-det-stat"><div class="label">Success</div><div class="value green">${successCount || '–'}</div></div>
      <div class="m3-vault-det-stat"><div class="label">Failure</div><div class="value red">${failureCount || '–'}</div></div>
      <div class="m3-vault-det-stat"><div class="label">Avg R:R</div><div class="value green">${avgRR ? '1:'+avgRR : '–'}</div></div>
    </div>
    ${reviewHtml}
    <table class="m3-popup-tbl">
      <thead><tr>
        <th style="text-align:left">Ticker</th><th style="text-align:left">Sector</th>
        <th>Score</th><th style="text-align:left">Entry Zone</th>
        <th>Stop Loss</th><th>Target</th><th>R:R</th><th>Hold</th><th>Mkt Cap</th>
        <th style="text-align:left">Result</th><th style="text-align:left">AI Verdict</th>
      </tr></thead>
      <tbody>${rows || '<tr><td colspan="11" style="text-align:center;color:var(--muted);padding:20px">No picks in this scan.</td></tr>'}</tbody>
    </table>
  `;
}

function exportVaultCSV() {
  if (!_vaultCurrentKey) return;
  api('/api/swing/vault/' + _vaultCurrentKey).then(d => {
    if (!d?.picks?.length) { alert('No data to export.'); return; }
    const hdr = 'Ticker,Sector,Composite,Entry Lo,Entry Hi,SL,Target,R:R,Mkt Cap Cr,Result';
    const rows = d.picks.map(p => {
      const lvl = p.levels || {};
      const closed = (p.outcomes||[]).find(o => o.exit_price != null);
      const tradedOpen = (p.outcomes||[]).find(o => o.was_traded && o.exit_price == null);
      const result = closed ? ((closed.return_pct||0) >= 0 ? (p.scan_result === 'TARGET_HIT' ? 'SUCCESS' : 'WIN') : 'FAIL')
                   : tradedOpen ? 'OPEN'
                   : p.scan_result === 'SL_HIT' ? 'FAIL'
                   : p.scan_result === 'TARGET_HIT' ? 'SUCCESS'
                   : p.scan_result === 'TIME_EXIT' ? 'FAIL' : '';
      return [p.symbol, p.sector||'', p.composite_score ?? p.total ?? '', lvl.entry_lo||'', lvl.entry_hi||'', lvl.sl||'', lvl.target||'', lvl.rr||'', p.mcap_cr||'', result].join(',');
    });
    const blob = new Blob([[hdr, ...rows].join('\n')], {type:'text/csv'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `scan_${_vaultCurrentKey}.csv`;
    a.click();
  }).catch(() => alert('Export failed.'));
}

// ── Overview ─────────────────────────────────────────────────────────────────
async function loadIndianEquity() {
  const d = await api('/api/portfolio/long-term').catch(() => null);
  if (!d) return;
  const s = d.summary || {};
  document.getElementById('ieInvKpi').textContent = fmt(s.invested);
  document.getElementById('ieValKpi').textContent = fmt(s.value);
  const pnlEl = document.getElementById('iePnlKpi');
  pnlEl.textContent = fmt(s.pnl); pnlEl.className = 'kpi-value amt ' + cls(s.pnl);
  document.getElementById('ieCntKpi').textContent = s.count ?? 0;
  const body = document.getElementById('ieBody');
  body.innerHTML = (d.holdings || []).length
    ? d.holdings.map(h => `<tr>
        <td style="text-align:left"><span style="color:var(--blue);font-weight:700">${h.sym}</span><span class="chart-link" onclick="openInCharts('${h.sym}')">↗</span></td>
        <td style="text-align:left;color:var(--muted)">${h.sector || '–'}</td>
        <td>${h.qty}</td>
        <td>₹${h.avg.toLocaleString('en-IN',{maximumFractionDigits:2})}</td>
        <td>₹${h.ltp.toLocaleString('en-IN',{maximumFractionDigits:2})}</td>
        <td>${fmt(h.invested)}</td>
        <td>${fmt(h.value)}</td>
        <td class="${cls(h.pnl)}">${(h.pnl>=0?'+':'')+fmt(Math.abs(h.pnl))}</td>
        <td class="${cls(h.pnl_pct)}">${fmtPct(h.pnl_pct)}</td>
        <td>${h.weight}%</td>
      </tr>`).join('')
    : '<tr><td colspan="10" class="m3-trades-empty">No long-term holdings yet. Refresh from Kite in My Trades and tag holdings as Long-term.</td></tr>';
}

async function loadOverview() {
  const d = await api('/api/portfolio/overview');
  if (!d) return;

  document.getElementById('asOf').textContent = d.as_of
    ? 'Updated ' + new Date(d.as_of).toLocaleDateString('en-IN', {day:'numeric',month:'short',year:'numeric'})
    : '';

  const since = d.first_trade_date;

  document.getElementById('totalWealth').textContent   = fmt(d.total_wealth);

  const retEl = document.getElementById('totalRet');
  retEl.textContent = fmtPct(d.total_pnl_pct);
  retEl.className   = 'v1-wealth-delta amt ' + cls(d.total_pnl_pct);

  document.getElementById('totalInvested').textContent = fmt(d.total_invested);
  const pnlEl = document.getElementById('totalPnl');
  pnlEl.textContent = (d.total_pnl >= 0 ? '+' : '') + (fmt(Math.abs(d.total_pnl)) === '–' ? '–' : fmt(Math.abs(d.total_pnl)));
  pnlEl.className   = 'sub amt ' + cls(d.total_pnl);

  // CAGR — computed by backend
  if (d.cagr != null) {
    const cagrEl = document.getElementById('totalCagr');
    cagrEl.textContent = fmtPct(d.cagr);
    cagrEl.className   = 'value amt ' + cls(d.cagr);
  }

  const b = d.buckets || {};
  const eqVal = (b.stocks?.value || 0) + (b.gold?.value || 0) + (b.etf?.value || 0);

  document.getElementById('stocksVal').textContent = fmt(eqVal);
  document.getElementById('mfVal').textContent     = fmt(b.mf?.value || 0);
  document.getElementById('cashVal').textContent   = fmt(d.cash);

  // Asset split bar — equity (stocks+gold+etf) / MF / cash
  const tw   = d.total_wealth || 0;
  const sPct = tw ? Math.round(eqVal / tw * 100) : 0;
  const mPct = tw ? Math.round((b.mf?.value || 0) / tw * 100) : 0;
  const cPct = Math.max(0, 100 - sPct - mPct);
  document.getElementById('v1SegStocks').style.width = sPct + '%';
  document.getElementById('v1SegMf').style.width     = mPct + '%';
  document.getElementById('v1SegCash').style.width   = cPct + '%';
  document.getElementById('v1LegStocks').textContent = `Equity ${sPct}%`;
  document.getElementById('v1LegMf').textContent     = `MF ${mPct}%`;
  document.getElementById('v1LegCash').textContent   = `Cash ${cPct}%`;

  // Asset-class boxes — value with invested + P&L% sub-line
  const setBox = (key, bk, subNoun) => {
    const valEl = document.getElementById('box' + key + 'Val');
    const subEl = document.getElementById('box' + key + 'Sub');
    if (!valEl || !bk) return;
    valEl.textContent = fmt(bk.value);
    const noun = bk.count != null ? `${bk.count} ${subNoun}` : '';
    subEl.textContent = `${noun} · inv ${fmt(bk.invested)} · ${fmtPct(bk.pnl_pct)}`;
    subEl.className = 'sub amt ' + cls(bk.pnl);
  };
  setBox('Stocks', b.stocks, 'holdings');
  setBox('Mf', b.mf, 'funds');
  setBox('Gold', b.gold, 'holdings');
  setBox('Etf', b.etf, 'holdings');
  document.getElementById('kpiCash').textContent = fmt(d.cash);

  // T+1
  if (d.t_plus_0 && d.t_plus_0.length > 0) {
    document.getElementById('t0Card').style.display = '';
    document.getElementById('t0Title').textContent = `T+1 Buys (settle tomorrow) · Realized P&L: ${fmt(d.realized_pnl_today || 0)}`;
    const g = document.getElementById('t0Grid');
    d.t_plus_0.forEach(t => {
      g.innerHTML += `<div class="t0-item">
        <div class="t0-sym">${t.sym}</div>
        <div class="t0-detail">${t.qty} qty · Avg ${fmt(t.avg)}</div>
        <div class="t0-detail">${t.note || ''}</div>
        <div class="t0-tag">T+1 · Unsettled</div>
      </div>`;
    });
  }

  _m1LoadKiteRow();

  // Score card — top-row mini format + full bars in right column
  if (d.score && d.score.overall) {
    const sc = d.score;
    document.getElementById('scoreCard').style.display = 'flex';
    document.getElementById('scoreVal').textContent    = Math.round(sc.overall * 10);
    document.getElementById('scoreTarget').textContent = '→ ' + Math.round(sc.target * 10) + '/100 target';

    const miniEl = document.getElementById('scoreDims');
    miniEl.innerHTML = (sc.dimensions || []).map(dim => `
      <div class="v1-score-mini-row">
        <div class="v1-score-mini-label">${dim.name}</div>
        <div class="v1-score-mini-track"><div class="v1-score-mini-fill" style="width:${dim.val*10}%"></div></div>
        <div class="v1-score-mini-val">${Math.round(dim.val*10)}</div>
      </div>`).join('');
  }
}

// ── Alpha ─────────────────────────────────────────────────────────────────────
let _alphaIndex = 'N50';
let _alphaChart = null;

async function loadAlpha(idx) {
  _alphaIndex = idx;
  document.getElementById('btnN50').classList.toggle('active', idx === 'N50');
  document.getElementById('btnN500').classList.toggle('active', idx === 'N500');
  const d = await api('/api/portfolio/alpha?index=' + idx);
  if (!d) return;

  const periods = ['1M','3M','6M','1Y','3Y'];
  const portVals = [], idxVals = [];
  periods.forEach(p => {
    const info = d.periods[p] || {};
    portVals.push(info.portfolio ?? null);
    idxVals.push(info.index ?? null);
  });

  const ctx = document.getElementById('alphaChart').getContext('2d');
  if (_alphaChart) { _alphaChart.destroy(); _alphaChart = null; }
  _alphaChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: periods,
      datasets: [
        { label: 'Portfolio', data: portVals, backgroundColor: 'rgba(177,197,255,0.5)', borderColor: '#b1c5ff', borderWidth: 1.5, borderRadius: 4 },
        { label: idx,         data: idxVals,  backgroundColor: 'rgba(141,144,159,0.25)', borderColor: '#8d909f', borderWidth: 1.5, borderRadius: 4 },
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: true, position: 'top', labels: { color: '#8d909f', font: { size: 10 }, boxWidth: 10 } },
        tooltip: { callbacks: { label: ctx => ctx.dataset.label + ': ' + (ctx.raw != null ? (ctx.raw >= 0 ? '+' : '') + ctx.raw.toFixed(1) + '%' : '–') } }
      },
      scales: {
        x: { ticks: { color: '#8d909f', font: { size: 10 } }, grid: { color: 'rgba(51,65,85,0.4)' } },
        y: { ticks: { color: '#8d909f', font: { size: 10 }, callback: v => v + '%' }, grid: { color: 'rgba(51,65,85,0.4)' } }
      }
    }
  });
  document.getElementById('alphaNote').textContent = d.note || '';
}

// ── Allocation ────────────────────────────────────────────────────────────────
let _allocLoaded = false;
async function loadAllocation() {
  _allocLoaded = true;
  const d = await api('/api/portfolio/allocation');
  if (!d) return;

  // Sector table
  const sb = document.getElementById('sectorBody');
  d.sectors.sectors.forEach(s => {
    const rowId = 'sec-' + s.sector.replace(/\W/g,'');
    sb.innerHTML += `<tr class="alloc-row" id="${rowId}" onclick="toggleExpand(this,'${rowId}-exp')">
      <td><span class="expand-icon">▶</span><strong>${s.sector}</strong></td>
      <td>${s.pct_of_equity}%</td>
      <td class="amt">${fmt(s.capital)}</td>
      <td>${s.count}</td>
      <td>${s.top_stock}</td>
    </tr>
    <tr class="alloc-expand" id="${rowId}-exp" style="display:none">
      <td colspan="5"><div class="alloc-inner">
        <table><thead><tr><th style="text-align:left">Stock</th><th>In Sector</th><th>In Portfolio</th><th>Capital</th></tr></thead><tbody>
          ${s.stocks.map(st => `<tr><td>${st.sym}<span class="chart-link" onclick="openInCharts('${st.sym}')">↗</span></td><td>${st.weight_in_sector_pct}%</td><td>${st.weight_in_portfolio_pct}%</td><td class="amt">${fmt(st.capital)}</td></tr>`).join('')}
        </tbody></table>
      </div></td>
    </tr>`;
  });

  // Market cap table
  const mb = document.getElementById('mcapBody');
  d.mcap.buckets.forEach(b => {
    const rowId = 'cap-' + b.bucket;
    mb.innerHTML += `<tr class="alloc-row" id="${rowId}" onclick="toggleExpand(this,'${rowId}-exp')">
      <td><span class="expand-icon">▶</span><strong>${b.bucket} Cap</strong></td>
      <td>${b.pct_of_equity}%</td>
      <td class="amt">${fmt(b.capital)}</td>
      <td>${b.count}</td>
    </tr>
    <tr class="alloc-expand" id="${rowId}-exp" style="display:none">
      <td colspan="4"><div class="alloc-inner">
        <table><thead><tr><th style="text-align:left">Stock</th><th style="text-align:left">Sector</th><th>Weight</th><th>Capital</th></tr></thead><tbody>
          ${b.stocks.map(s => `<tr><td>${s.sym}</td><td style="color:var(--muted)">${s.sector}</td><td>${s.weight_pct}%</td><td class="amt">${fmt(s.capital)}</td></tr>`).join('')}
        </tbody></table>
      </div></td>
    </tr>`;
  });

  // Concentration chart
  const items = d.concentration.items;
  const colors = items.map(i => i.trim_flag ? 'rgba(245,158,11,0.7)' : 'rgba(177,197,255,0.5)');
  const borders = items.map(i => i.trim_flag ? '#F59E0B' : '#b1c5ff');
  const labels  = items.map(i => i.trim_flag ? i.sym + ' ⚠' : i.sym);
  if (window._concChart) window._concChart.destroy();
  window._concChart = new Chart(document.getElementById('concChart'), {
    type: 'bar',
    data: { labels, datasets: [{
      label: 'Weight %', data: items.map(i => i.weight_pct),
      backgroundColor: colors, borderColor: borders, borderWidth: 1, borderRadius: 4
    }]},
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { backgroundColor:'#171f33', titleColor:'#dae2fd', bodyColor:'#8d909f', borderColor:'#334155', borderWidth:1,
          callbacks: { label: ctx => ` ${ctx.raw}% — ${fmt(items[ctx.dataIndex].capital)}` }
        },
        annotation: {}
      },
      scales: {
        x: { grid:{color:'#1a2540'}, ticks:{color:'#8d909f',callback:v=>v+'%'} },
        y: { grid:{display:false}, ticks:{color:'#dae2fd',font:{size:11}} }
      }
    }
  });
}

function toggleExpand(row, expandId) {
  const exp = document.getElementById(expandId);
  const showing = exp.style.display !== 'none';
  exp.style.display = showing ? 'none' : '';
  row.classList.toggle('open', !showing);
}

// ── US Equity (Global Holdings) ───────────────────────────────────────────────
let _globalLoaded = false;
async function loadGlobalHoldings() {
  _globalLoaded = true;
  const d = await api('/api/portfolio/global');
  if (!d) return;

  const s = d.summary || {};
  document.getElementById('usInvKpi').textContent = fmt(s.invested_inr);
  document.getElementById('usValKpi').textContent = fmt(s.value_inr);
  const pnlEl = document.getElementById('usPnlKpi');
  pnlEl.textContent = fmt(s.pnl_inr);
  pnlEl.className = 'kpi-value amt ' + cls(s.pnl_inr);
  document.getElementById('usFxKpi').textContent = s.fx_rate ? '₹' + s.fx_rate.toFixed(2) + '/USD' : '–';

  // Update overview card
  const boxUs = document.getElementById('boxUsVal');
  if (boxUs) boxUs.textContent = fmt(s.value_inr);

  const tbody = document.getElementById('usBody');
  if (!d.holdings || d.holdings.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" class="pf-empty-cell"><div class="pf-empty">
      <div class="pf-empty-icon"><span class="material-symbols-outlined">public</span></div>
      <h4>No US holdings yet</h4>
      <p>Track your US stocks (e.g. AAPL, MSFT) — prices and ₹ value update automatically at the FX rate above.</p>
      <button class="pf-add-btn" onclick="_openAddGlobalModal()"><span class="material-symbols-outlined">add</span>Add your first holding</button>
    </div></td></tr>`;
    return;
  }
  tbody.innerHTML = d.holdings.map(h => {
    const pos = h.pnl_inr >= 0;
    return `<tr>
      <td><span class="sym">${h.sym}</span>${h.name ? `<div style="font-size:10px;color:var(--muted)">${h.name}</div>` : ''}</td>
      <td class="mono">${h.qty}</td>
      <td class="mono amt">$${h.avg_price_usd.toFixed(2)}</td>
      <td class="mono amt">$${h.ltp_usd.toFixed(2)}</td>
      <td class="amt">${fmt(h.invested_inr)}</td>
      <td class="amt">${fmt(h.value_inr)}</td>
      <td class="${pos?'green':'red'} amt">${fmt(h.pnl_inr)}</td>
      <td><span class="pnl-pill ${pos?'pos':'neg'} amt">${fmtPct(h.pnl_pct)}</span></td>
      <td><button class="btn-sm red" onclick="_closeGlobalHolding(${h.id})">Close</button></td>
    </tr>`;
  }).join('');
}

async function _closeGlobalHolding(id) {
  if (!confirm('Remove this US holding?')) return;
  const r = await fetch('/api/portfolio/global/' + id + '/close', {method:'POST'});
  if (r.ok) { _globalLoaded = false; loadGlobalHoldings(); }
}

function _openAddGlobalModal() {
  ['addUsSymInput','addUsQtyInput','addUsAvgInput','addUsExchInput','addUsBrokerInput'].forEach(i => {
    const el = document.getElementById(i);
    if (el) el.value = '';
  });
  document.getElementById('addUsError').style.display = 'none';
  document.getElementById('addGlobalModal').style.display = 'flex';
}

async function _submitAddGlobal() {
  const sym  = document.getElementById('addUsSymInput').value.trim().toUpperCase();
  const qty  = parseFloat(document.getElementById('addUsQtyInput').value);
  const avg  = parseFloat(document.getElementById('addUsAvgInput').value);
  const exch = document.getElementById('addUsExchInput').value.trim();
  const brok = document.getElementById('addUsBrokerInput').value.trim();
  const errEl = document.getElementById('addUsError');
  if (!sym || !qty || !avg) { errEl.textContent = 'Sym, qty and avg price required.'; errEl.style.display = ''; return; }
  errEl.style.display = 'none';
  const r = await fetch('/api/portfolio/global', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({sym, qty, avg_price_usd: avg, exchange: exch || 'NYSE/NASDAQ', broker: brok}),
  });
  const data = await r.json();
  if (!r.ok) { errEl.textContent = data.error || 'Failed'; errEl.style.display = ''; return; }
  document.getElementById('addGlobalModal').style.display = 'none';
  _globalLoaded = false;
  loadGlobalHoldings();
}


// ── Crypto Holdings ───────────────────────────────────────────────────────────
let _cryptoLoaded = false;
async function loadCryptoHoldings() {
  _cryptoLoaded = true;
  const d = await api('/api/portfolio/crypto');
  if (!d) return;

  const s = d.summary || {};
  document.getElementById('cryptoInvKpi').textContent = fmt(s.invested_inr);
  document.getElementById('cryptoValKpi').textContent = fmt(s.value_inr);
  const pnlEl = document.getElementById('cryptoPnlKpi');
  pnlEl.textContent = fmt(s.pnl_inr);
  pnlEl.className = 'kpi-value amt ' + cls(s.pnl_inr);
  document.getElementById('cryptoCntKpi').textContent = s.count || 0;

  // Update overview card
  const boxC = document.getElementById('boxCryptoVal');
  if (boxC) boxC.textContent = fmt(s.value_inr);

  const tbody = document.getElementById('cryptoBody');
  if (!d.holdings || d.holdings.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" class="pf-empty-cell"><div class="pf-empty">
      <div class="pf-empty-icon"><span class="material-symbols-outlined">currency_bitcoin</span></div>
      <h4>No crypto holdings yet</h4>
      <p>Track coins like BTC or ETH — live prices via CoinGecko, converted to ₹ at the current FX rate.</p>
      <button class="pf-add-btn" onclick="_openAddCryptoModal()"><span class="material-symbols-outlined">add</span>Add your first holding</button>
    </div></td></tr>`;
    return;
  }
  tbody.innerHTML = d.holdings.map(h => {
    const pos = h.pnl_inr >= 0;
    return `<tr>
      <td><span class="sym">${h.sym}</span>${h.name ? `<div style="font-size:10px;color:var(--muted)">${h.name}</div>` : ''}</td>
      <td class="mono">${h.qty}</td>
      <td class="mono amt">$${h.avg_price_usd.toFixed(2)}</td>
      <td class="mono amt">$${h.ltp_usd.toFixed(2)}</td>
      <td class="amt">${fmt(h.invested_inr)}</td>
      <td class="amt">${fmt(h.value_inr)}</td>
      <td class="${pos?'green':'red'} amt">${fmt(h.pnl_inr)}</td>
      <td><span class="pnl-pill ${pos?'pos':'neg'} amt">${fmtPct(h.pnl_pct)}</span></td>
      <td><button class="btn-sm red" onclick="_closeCryptoHolding(${h.id})">Close</button></td>
    </tr>`;
  }).join('');
}

async function _closeCryptoHolding(id) {
  if (!confirm('Remove this crypto holding?')) return;
  const r = await fetch('/api/portfolio/crypto/' + id + '/close', {method:'POST'});
  if (r.ok) { _cryptoLoaded = false; loadCryptoHoldings(); }
}

function _openAddCryptoModal() {
  ['addCSymInput','addCCgInput','addCQtyInput','addCAvgInput','addCWalletInput'].forEach(i => {
    const el = document.getElementById(i);
    if (el) el.value = '';
  });
  document.getElementById('addCError').style.display = 'none';
  document.getElementById('addCryptoModal').style.display = 'flex';
}

async function _submitAddCrypto() {
  const sym    = document.getElementById('addCSymInput').value.trim().toUpperCase();
  const cgId   = document.getElementById('addCCgInput').value.trim().toLowerCase() || sym.toLowerCase();
  const qty    = parseFloat(document.getElementById('addCQtyInput').value);
  const avg    = parseFloat(document.getElementById('addCAvgInput').value);
  const wallet = document.getElementById('addCWalletInput').value.trim();
  const errEl  = document.getElementById('addCError');
  if (!sym || !qty || !avg) { errEl.textContent = 'Sym, qty and avg price required.'; errEl.style.display = ''; return; }
  errEl.style.display = 'none';
  const r = await fetch('/api/portfolio/crypto', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({sym, coingecko_id: cgId, qty, avg_price_usd: avg, wallet_or_exchange: wallet}),
  });
  const data = await r.json();
  if (!r.ok) { errEl.textContent = data.error || 'Failed'; errEl.style.display = ''; return; }
  document.getElementById('addCryptoModal').style.display = 'none';
  _cryptoLoaded = false;
  loadCryptoHoldings();
}


// ── Mutual Funds ──────────────────────────────────────────────────────────────
let _mfLoaded = false;
async function loadMF() {
  _mfLoaded = true;
  const d = await api('/api/portfolio/mf');
  if (!d) return;

  const s = d.summary;
  document.getElementById('mfInvKpi').textContent = fmt(s.total_invested);
  document.getElementById('mfValKpi').textContent = fmt(s.total_value);
  document.getElementById('mfPnlKpi').textContent = fmt(s.total_pnl);
  document.getElementById('mfPnlKpi').className   = 'kpi-value amt ' + cls(s.total_pnl);
  document.getElementById('mfRetKpi').textContent = fmtPct(s.total_pnl_pct);
  document.getElementById('mfRetKpi').className   = 'kpi-value amt ' + cls(s.total_pnl_pct);

  const typeColors = { ELSS:'#f5a623', Index:'#4e8ef7', Active:'#a259f7' };
  const tbody = document.getElementById('mfBody');
  (d.holdings || []).forEach(f => {
    const pos = f.pnl >= 0;
    const tc  = typeColors[f.type] || '#7a8199';
    const scLink = f.scheme_code
      ? `<span class="sector-tag" style="font-family:var(--font-mono);font-size:10px;cursor:pointer" onclick="_openMFNavModal(${f.id},'${f.name||''}')" title="View NAV history">${f.scheme_code}</span>`
      : `<span class="sector-tag" style="font-size:10px;color:var(--muted);cursor:pointer" onclick="_openMFSchemeSearch(${f.id},'${(f.name||'').replace(/'/g,'')}')" title="Link scheme code">Link</span>`;
    tbody.innerHTML += `<tr>
      <td>
        <span class="sym" title="${(f.full_name||f.name||'').replace(/"/g,'')}">${f.name}</span>
        <div style="margin-top:2px">${scLink}</div>
      </td>
      <td><span class="sector-tag" style="background:rgba(0,0,0,0.2);color:${tc}">${f.type||'–'}</span></td>
      <td>${f.units != null ? f.units.toFixed(3) : '–'}</td>
      <td class="amt">${fmt(f.avg)}</td>
      <td class="amt">${fmt(f.nav)}</td>
      <td class="amt">${fmt(f.invested)}</td>
      <td class="amt">${fmt(f.current)}</td>
      <td class="${pos?'green':'red'} amt">${fmt(f.pnl)}</td>
      <td><span class="pnl-pill ${pos?'pos':'neg'} amt">${fmtPct(f.pnl_pct)}</span></td>
      <td class="amt">${f.weight_pct != null ? f.weight_pct + '%' : '–'}</td>
    </tr>`;
  });

  // Overlap + watchpoints — only reveal the grid when at least one has content.
  const ov = d.overlap;
  const wp = d.watchpoints;
  const hasOv = ov && Object.keys(ov).length;
  const hasWp = wp && (Array.isArray(wp) ? wp.length : Object.keys(wp).length);
  if (hasOv) {
    document.getElementById('overlapCard').innerHTML = '<h4>MF Overlap Analysis</h4>' +
      Object.values(ov).map(v => `<div class="overlap-item">${v}</div>`).join('');
  }
  if (hasWp) {
    const items = Array.isArray(wp) ? wp : Object.values(wp);
    document.getElementById('watchpointsCard').innerHTML = '<h4>Watchpoints</h4><ul>' +
      items.map(w => `<li>${w}</li>`).join('') + '</ul>';
  }
  const grid = document.getElementById('mfExtraGrid');
  if (grid) grid.style.display = (hasOv || hasWp) ? 'grid' : 'none';

  // Picks tab
  loadMFPicks();
}


// ── MF Scheme Code Linking ────────────────────────────────────────────────────

async function _openMFSchemeSearch(holdingId, fundName) {
  const modal = document.getElementById('mfSchemeModal');
  if (!modal) return;
  document.getElementById('mfSchemeHoldingId').value = holdingId;
  document.getElementById('mfSchemeSearchInput').value = '';
  document.getElementById('mfSchemeResults').innerHTML = '';
  document.getElementById('mfSchemeError').style.display = 'none';
  modal.style.display = 'flex';
  document.getElementById('mfSchemeSearchInput').focus();
  // Pre-fill search with fund name words
  const q = fundName.split(' ').slice(0,3).join(' ');
  if (q) { document.getElementById('mfSchemeSearchInput').value = q; await _mfSchemeSearch(); }
}

async function _mfSchemeSearch() {
  const q = document.getElementById('mfSchemeSearchInput').value.trim();
  if (!q) return;
  const d = await api('/api/settings/mf/scheme-search?q=' + encodeURIComponent(q));
  if (!d) return;
  const el = document.getElementById('mfSchemeResults');
  if (!d.results || !d.results.length) { el.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:8px">No matches</div>'; return; }
  el.innerHTML = d.results.map(r => `
    <div class="mf-scheme-row" onclick="_linkSchemeCode(${document.getElementById('mfSchemeHoldingId').value},'${r.scheme_code}')">
      <div style="font-size:12px;font-weight:600">${r.name}</div>
      <div style="font-size:11px;color:var(--muted);font-family:var(--font-mono)">Code: ${r.scheme_code} · NAV: ₹${r.nav}</div>
    </div>`).join('');
}

async function _linkSchemeCode(holdingId, schemeCode) {
  const r = await fetch(`/api/portfolio/mf/${holdingId}/scheme-code`, {
    method: 'PUT', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({scheme_code: schemeCode}),
  });
  if (r.ok) {
    document.getElementById('mfSchemeModal').style.display = 'none';
    _mfLoaded = false; loadMF();
  } else {
    document.getElementById('mfSchemeError').textContent = 'Failed to link scheme code';
    document.getElementById('mfSchemeError').style.display = '';
  }
}


// ── MF NAV History Modal ──────────────────────────────────────────────────────
let _mfNavChart = null;

async function _openMFNavModal(holdingId, fundName) {
  const modal = document.getElementById('mfNavModal');
  if (!modal) return;
  document.getElementById('mfNavModalTitle').textContent = fundName || 'NAV History';
  document.getElementById('mfNavChartStatus').textContent = 'Loading…';
  modal.style.display = 'flex';
  const d = await api(`/api/portfolio/mf/${holdingId}/nav-history?days=365`);
  if (!d || !d.history || !d.history.length) {
    document.getElementById('mfNavChartStatus').textContent = 'No history. Link scheme code and wait for next NAV sync.';
    return;
  }
  document.getElementById('mfNavChartStatus').textContent = '';
  const labels = d.history.map(h => h.date);
  const navs   = d.history.map(h => h.nav);
  const ctx = document.getElementById('mfNavChart').getContext('2d');
  if (_mfNavChart) { _mfNavChart.destroy(); _mfNavChart = null; }
  _mfNavChart = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: [{ label: 'NAV', data: navs, borderColor: '#4e8ef7', borderWidth: 1.5, pointRadius: 0, tension: 0.3, fill: false }] },
    options: { responsive: true, plugins: { legend: { display: false } }, scales: {
      x: { ticks: { maxTicksLimit: 6, color: 'var(--muted)', font: { size: 10 } }, grid: { display: false } },
      y: { ticks: { color: 'var(--muted)', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.05)' } },
    }},
  });
}


// ── MF Picks ──────────────────────────────────────────────────────────────────
let _mfPicksLoaded = false;
async function loadMFPicks() {
  if (_mfPicksLoaded) return;
  _mfPicksLoaded = true;
  const el = document.getElementById('mfPicksSection');
  if (!el) return;
  const d = await api('/api/portfolio/mf/picks');
  if (!d || !d.categories || !d.categories.length) { el.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:12px">No picks configured.</div>'; return; }

  // Tab buttons + panels
  const tabsHtml = d.categories.map((c, i) =>
    `<button class="v1-chart-tab${i===0?' active':''}" onclick="_mfPickTab(${i})">${c.category}</button>`
  ).join('');
  const panelsHtml = d.categories.map((c, i) => `
    <div class="mf-picks-panel" id="mfPickPanel${i}" style="display:${i===0?'block':'none'}">
      <table style="width:100%">
        <thead><tr><th style="text-align:left">Fund</th><th>Latest NAV</th><th>1Y Return</th><th>Why</th></tr></thead>
        <tbody>${c.funds.map(f => `<tr>
          <td style="max-width:260px;font-size:12px">${f.name}</td>
          <td class="mono amt">${f.latest_nav != null ? '₹'+f.latest_nav.toFixed(2) : '–'}</td>
          <td><span class="pnl-pill ${(f.return_1y||0)>=0?'pos':'neg'} amt">${f.return_1y != null ? (f.return_1y>0?'+':'') + f.return_1y.toFixed(1)+'%' : '–'}</span></td>
          <td style="font-size:11px;color:var(--muted)">${f.why||''}</td>
        </tr>`).join('')}</tbody>
      </table>
    </div>`).join('');

  el.innerHTML = `
    <div style="margin-top:24px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <h3 style="margin:0">Curated Picks</h3>
        <div class="v1-chart-tabs">${tabsHtml}</div>
      </div>
      ${panelsHtml}
    </div>`;
}

function _mfPickTab(idx) {
  document.querySelectorAll('.mf-picks-panel').forEach((p, i) => p.style.display = i === idx ? 'block' : 'none');
  document.querySelectorAll('#mfPicksSection .v1-chart-tab').forEach((b, i) => b.classList.toggle('active', i === idx));
}

