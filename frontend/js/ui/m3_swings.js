// ── Module 3: Alpha Scanner tabs ─────────────────────────────────────────────
let _m3ActiveTab = 'scanner';

function switchM3Tab(tab) {
  _m3ActiveTab = tab;
  const panels = {scanner:'m3PanelScanner', trades:'m3PanelTrades', analytics:'m3PanelAnalytics', lab:'m3PanelLab'};
  const btns   = {scanner:'m3TabBtnScanner', trades:'m3TabBtnTrades', analytics:'m3TabBtnAnalytics', lab:'m3TabBtnLab'};
  Object.keys(panels).forEach(t => {
    const p = document.getElementById(panels[t]);
    const b = document.getElementById(btns[t]);
    if (p) p.style.display = t === tab ? '' : 'none';
    if (b) b.classList.toggle('active', t === tab);
  });
  if (tab === 'trades') loadMyTrades();
  if (tab === 'analytics') _loadMarketNote();
  if (tab === 'lab' && typeof loadWeekendLab === 'function') loadWeekendLab();
}

// ── AI: daily market note strip ──────────────────────────────────────────────
let _marketNoteLoaded = false;
async function _loadMarketNote() {
  if (_marketNoteLoaded) return;
  const strip = document.getElementById('m3MarketNote');
  if (!strip) return;
  const d = await api('/api/swing/market-note').catch(() => null);
  if (!d || !d.note) { strip.style.display = 'none'; return; }
  _marketNoteLoaded = true;
  strip.style.display = '';
  const staleBadge = d.stale
    ? `<span class="m3-mn-stale" title="No fresh market data since this date — server may have been offline. This is NOT today's read.">STALE · ${d.days_old != null ? d.days_old + 'd old' : 'old'}</span>`
    : '';
  strip.innerHTML = `
    <span class="material-symbols-outlined m3-mn-icon">psychology</span>
    <div class="m3-mn-body"><span class="m3-mn-date">As of ${d.date || '—'}</span>${staleBadge}${d.note}</div>
    ${d.model_used ? `<span class="m3-mn-model">${d.model_used}</span>` : ''}`;
}

async function _refreshScanner() {
  try { await _refreshLastPicks(); } catch(e) {}
}

// ── Module 3: Swing Detector ──────────────────────────────────────────────────
let _m3Loaded = false;

// IST weekend window: Fri 4 PM → Mon 9 AM
function _isWeekendWindow() {
  const now = new Date();
  const istMs = now.getTime() + (5.5 * 60 + now.getTimezoneOffset()) * 60000;
  const ist = new Date(istMs);
  const day = ist.getDay();
  const t   = ist.getHours() * 60 + ist.getMinutes();
  if (day === 0 || day === 6) return true;
  if (day === 5 && t >= 960)  return true;
  if (day === 1 && t < 540)   return true;
  return false;
}

function _isMarketHours() {
  const now = new Date();
  const istMs = now.getTime() + (5.5 * 60 + now.getTimezoneOffset()) * 60000;
  const ist = new Date(istMs);
  const day = ist.getDay();
  if (day === 0 || day === 6) return false;
  const t = ist.getHours() * 60 + ist.getMinutes();
  return t >= 555 && t <= 930; // 9:15–15:30 IST
}

function _applyWeekendGate() {
  const allowed = _isWeekendWindow();
  ['m3RunBtnIdle','m3RunBtnIdleInit','m3RerunBtn'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = !allowed;
  });
  const msg = document.getElementById('m3WeekdayMsg');
  if (msg) msg.style.display = allowed ? 'none' : '';
}

function _showExplain(el, html) {
  const tip = document.getElementById('m3ExplainTip');
  tip.innerHTML = html;
  tip.style.display = 'block';
  const rect = el.getBoundingClientRect();
  const tipW = 280, tipH = tip.offsetHeight || 140;
  let left = Math.max(8, Math.min(rect.left, window.innerWidth - tipW - 8));
  let top  = rect.top - tipH - 10;
  if (top < 8) top = rect.bottom + 8;
  tip.style.left = left + 'px';
  tip.style.top  = top  + 'px';
}
function _hideExplain() { document.getElementById('m3ExplainTip').style.display = 'none'; }

function _entryExplanation(ps) {
  if (!ps) return '<p>No signal data available.</p>';
  if (ps.includes('BOUNCE')) {
    return `<p><b>20DMA Bounce</b></p><p>The stock pulled back to its 20-day moving average and buyers stepped in, pushing price back up. This is the <b>ideal swing entry</b> — the trend is intact, the correction is complete, and momentum is resuming. Offers the tightest stop loss (just below the 20DMA) for maximum R:R.</p>`;
  }
  if (ps.includes('AT 20DMA')) {
    const m = ps.match(/([+-]?[\d.]+)%/);
    const pct = m ? m[1] + '%' : '';
    return `<p><b>At the 20DMA (${pct})</b></p><p>Price is right at the 20-day moving average — the <b>sweet spot</b> for swing entries. In a healthy uptrend this level acts as dynamic support. Entering here keeps the stop tight (below DMA) while giving room to run to the prior high as target.</p>`;
  }
  if (ps.includes('above 20DMA')) {
    const m = ps.match(/\+([\d.]+)%/);
    const pct = m ? m[1] + '%' : '';
    return `<p><b>Extended above 20DMA (+${pct})</b></p><p>The stock is ${pct} above its 20-day moving average — <b>trending but stretched</b>. Ideal entry has already passed. Risk of entering at a short-term peak. Best to <b>wait for a pullback</b> toward the 20DMA. If entering now, use a tighter stop and smaller size.</p>`;
  }
  if (ps.includes('below 20DMA')) {
    return `<p><b>Below 20DMA</b></p><p>Stock is below its 20-day moving average — a <b>caution zone</b>. The short-term trend is weakening. Wait for the stock to reclaim and close above the 20DMA with volume before considering entry.</p>`;
  }
  return `<p>${ps}</p>`;
}

function _showExplainIdx(el) {
  const idx = parseInt(el.dataset.tipIdx ?? el.dataset['tip-idx'] ?? el.getAttribute('data-tip-idx'));
  const ps = (window._m3TipSignals || [])[idx] || '';
  _showExplain(el, _entryExplanation(ps));
}

const _posSaveTimers = {};
function _updatePos(pickId, sym, inputEl) {
  const row = inputEl.closest('tr');
  const inputs = row.querySelectorAll('.m3-pos-inp');
  const qty = parseFloat(inputs[0].value) || 0;
  const prc = parseFloat(inputs[1].value) || 0;
  const totalEl = document.getElementById('postotal_' + sym);
  if (totalEl) {
    totalEl.textContent = (qty && prc) ? '= ₹' + (qty * prc).toLocaleString('en-IN', {maximumFractionDigits:0}) : '';
  }
  clearTimeout(_posSaveTimers[pickId]);
  _posSaveTimers[pickId] = setTimeout(() => {
    fetch(API + '/api/swing/vault/' + pickId + '/outcome', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        was_traded: !!(qty && prc),
        qty: qty || null,
        entry_price: prc || null,
      }),
    }).catch(() => {});
  }, 800);
}

async function loadSwingDetector() {
  if (_m3Loaded) return;
  _m3Loaded = true;
  _applyWeekendGate();
  await _refreshLastPicks();
  _refreshPicksCMP();
}

// WS handlers for scanner pick CMP cells: sym → handler fn
const _scannerWsHandlers = new Map();

async function _refreshLastPicks() {
  const [d, hist] = await Promise.all([
    api('/api/swing/last-picks').catch(() => null),
    api('/api/swing/vault').catch(() => null),
  ]);

  const ms = (d || {}).market_summary || {};
  const sig = ms.signal || 'NEUTRAL';
  const sigLower = sig.toLowerCase();
  const badge = document.getElementById('m3CbSignalBadge');
  if (badge) {
    badge.className = 'm3-cb-signal-badge ' + (sigLower === 'bullish' ? '' : sigLower);
    const dot = badge.querySelector('.m3-cb-signal-dot');
    if (dot) {
      dot.style.background = sigLower === 'bullish' ? 'var(--green)' : sigLower === 'caution' ? 'var(--red)' : 'var(--gold)';
      dot.style.boxShadow = sigLower === 'bullish' ? '0 0 6px rgba(16,185,129,0.5)' : 'none';
      dot.style.animation = sigLower === 'bullish' ? '' : 'none';
    }
    document.getElementById('m3CbSignalText').textContent = sig;
  }
  const trend = document.getElementById('m3CbTrend');
  if (trend) trend.textContent = 'Market Trend: ' + (ms.nifty_above_ema50 !== undefined ? (ms.nifty_above_ema50 ? 'Upward Momentum' : 'Below 50 EMA') : '–');

  if (Array.isArray(ms.all_sectors) && ms.all_sectors.length) {
    const pillsHtml = ms.all_sectors.filter(s => s.qualified).map(s =>
      `<span class="m3-cb-sector-pill passing">SECTOR: ${s.name}${s.change != null ? ' (' + (s.change >= 0 ? '+' : '') + s.change.toFixed(1) + '%)' : ''}</span>`
    ).join('') || ms.all_sectors.slice(0, 4).map(s => `<span class="m3-cb-sector-pill">${s.name}</span>`).join('');
    const cbSectors = document.getElementById('m3CbSectors');
    if (cbSectors) cbSectors.innerHTML = pillsHtml;
  }

  const hasPicks = d?.picks?.length > 0;

  document.getElementById('m3StateIdle').style.display = hasPicks ? 'none' : '';
  document.getElementById('m3StatePopulated').style.display = hasPicks ? '' : 'none';

  if (!hasPicks) return;

  const ipoPicks = (d.picks || []).filter(p => p.is_ipo_pick);
  const ipoSyms = new Set(ipoPicks.map(p => p.symbol));
  const picks = (d.picks || []).filter(p => !p.is_ipo_pick && !ipoSyms.has(p.symbol));
  document.getElementById('m3ActivePicksCount').textContent = picks.length;

  _renderIpoStrip(ipoPicks);
  _renderSectorRanking();
  _renderValidation();

  const lastRunEl = document.getElementById('m3LastRunChip');
  if (lastRunEl && d.scanned_at) {
    const dt = new Date(d.scanned_at);
    lastRunEl.textContent = 'Last run: ' + dt.toLocaleString('en-IN', {day:'numeric',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'});
  }

  const weekBadge = document.getElementById('m3PicksWeekBadge');
  if (weekBadge && d.scanned_at) {
    const dt = new Date(d.scanned_at);
    weekBadge.textContent = dt.toLocaleDateString('en-IN', {month:'long', year:'numeric'}) + ' basket';
  }

  const sCount = ms.sectors_passing ?? '–';
  const sTotal = ms.sectors_total ?? '–';
  document.getElementById('m3SectorMomCount').textContent = sCount + '/' + sTotal + ' sectors in momentum';

  window._m3TipSignals = picks.map(p => p.pullback_signal || '');
  window._m3Orders = {};

  const _grp = { enterable: [], weak_missed: [], closed: [], churned: [] };
  picks.forEach(p => {
    // scan_result is authoritative — a closed/churned pick is never enterable, regardless
    // of a stale tracking strength_status.
    const sr = p.scan_result;
    if (sr === 'CHURNED') { _grp.churned.push(p); return; }
    if (sr === 'SL_HIT' || sr === 'TARGET_HIT' || sr === 'TIME_EXIT' || (sr && sr.startsWith('pruned_'))) { _grp.closed.push(p); return; }
    const s = p.strength_status || 'enterable';
    if (s === 'closed') _grp.closed.push(p);
    else if (s === 'weak' || s === 'missed') _grp.weak_missed.push(p);
    else _grp.enterable.push(p);
  });
  const _subhdr = (label, cls, n) =>
    `<tr class="m3-grp-row ${cls}"><td colspan="11"><span class="m3-grp-label">${label}</span><span class="m3-grp-cnt">${n}</span></td></tr>`;

  const renderRow = (p, i) => {
    const lvl = p.levels || {};
    const tags = (p.is_holding ? '<span class="m3-tag holding">HOLD</span>' : '')
               + (p.is_portfolio_fit ? '<span class="m3-tag portfit">FIT</span>' : '')
               + (p.grade === 'HIGH CONVICTION' ? '<span class="m3-tag hconv">HC</span>' : '')
               + (p.is_ipo ? '<span class="m3-tag ipo" title="Recent IPO">IPO</span>' : '')
               + (p.is_microcap ? '<span class="m3-tag microcap">MCAP</span>' : '')
               + (p.hold_horizon_days ? `<span class="m3-tag holddur" title="Suggested holding horizon (AI deep-dive)">⏱ ${p.hold_horizon_days}d hold</span>` : '');
    const mcap = p.mcap_cr ? (p.mcap_cr >= 10000 ? (p.mcap_cr/1000).toFixed(1)+'K' : Math.round(p.mcap_cr))+'Cr' : '–';
    const rrPill = lvl.rr ? `<span style="background:var(--blue-action);color:#fff;border-radius:4px;padding:2px 7px;font-size:11px;font-weight:700;font-family:var(--font-display)">1:${lvl.rr}</span>` : '–';

    const _cs = p.composite_score;
    const compVal = _cs != null ? (Math.round(_cs * 10) / 10) : (p.total ?? '–');
    const compTier = (_cs ?? 0) >= 85 ? 't1' : (_cs ?? 0) >= 70 ? 't2' : 't3';
    const subSeg = (cls, v) => `<div class="seg ${cls}" title="${v ?? '–'}"><i style="transform:scaleX(${Math.max(0, Math.min(1, (v || 0) / 100)).toFixed(2)})"></i></div>`;
    const flagPill = p.tradeability_status === 'FLAGGED'
      ? `<span class="m3-flag-pill">⚠ FLAG<span class="ftip">${(p.tradeability_flags || []).join(', ') || 'Surveillance flag'}</span></span>` : '';
    const flags = p.tradeability_flags || [];
    const earningsSetupPill = flags.includes('earnings_setup_strong')
      ? `<span class="m3-flag-pill buy" title="Strong QTD order flow vs guidance">EARNINGS SETUP</span>`
      : flags.includes('earnings_setup_building')
        ? `<span class="m3-flag-pill warn" title="Building QTD order flow">SETUP ↑</span>`
        : '';
    const ordObj = (p.position_size_json || {}).order;
    if (ordObj) window._m3Orders[p.symbol] = ordObj;
    const ordBtn = ordObj ? `<button class="m3-ord-btn" onclick="_showOrderPop('${p.symbol}')" title="Recommended order (copy to Kite)">📋</button>` : '';
    const sStatus = p.strength_status || 'enterable';
    let strengthBadge = '';
    if (sStatus === 'enterable') {
      const bs = p.band_state;
      const lbl = bs === 'in_band' ? '✓ IN ZONE' : (bs === 'approaching' ? '↓ APPROACHING' : 'ENTERABLE');
      strengthBadge = `<span class="m3-strength-badge enter">${lbl}</span>`;
    } else if (sStatus === 'missed') {
      strengthBadge = `<span class="m3-strength-badge miss">EXTENDED</span>`;
    } else if (sStatus === 'weak') {
      strengthBadge = `<span class="m3-strength-badge weak">WEAK</span>`;
    }

    const ps = p.pullback_signal || '';
    let pbClass = 'extended', pbText = 'EXTENDED';
    if (ps.includes('BOUNCE')) {
      pbClass = 'bounce'; pbText = '▲ 20DMA BOUNCE';
    } else if (ps.match(/AT\s20[DE]MA/) || ps.includes('AT 20DMA') || ps.includes('AT 20EMA')) {
      pbClass = 'at-dma'; pbText = '~ AT 20DMA';
    } else if (ps.toLowerCase().includes('vcp')) {
      pbClass = 'bounce'; pbText = 'VCP BREAKOUT';
    } else if (ps.includes('above 20DMA') || ps.includes('above 20EMA')) {
      const m = ps.match(/\+([\d.]+)%/);
      const pct = m ? parseFloat(m[1]) : 0;
      if (pct <= 3) { pbClass = 'bounce'; pbText = `NEAR 20EMA`; }
      else if (pct <= 7) { pbClass = 'at-dma'; pbText = `+${pct}% 20EMA`; }
      else { pbClass = 'extended'; pbText = `+${pct}% EXTENDED`; }
    } else if (ps.includes('below')) {
      pbClass = 'extended'; pbText = 'BELOW 20DMA';
    } else if (ps) {
      pbText = ps.length > 18 ? ps.slice(0,18)+'…' : ps;
    }
    const rowClass = pbClass === 'bounce' ? 'row-bounce' : (pbClass === 'at-dma' ? 'row-at-dma' : '');

    const entryCell = (lvl.entry_lo && lvl.entry_hi)
      ? `<span class="m3-entry-range"><span class="er-lo">₹${lvl.entry_lo}</span><span class="er-sep"> – </span><span class="er-hi">₹${lvl.entry_hi}</span></span>`
      : `₹${lvl.entry ?? '–'}`;

    const dbOutcome = (p.outcomes || []).find(o => o.was_traded);
    const _timeExit = p.scan_result === 'TIME_EXIT';
    const _teOutcome = _timeExit ? (p.outcomes || []).find(o => o.exit_price != null) : null;

    const cmp = lvl.price;
    const _pruned = p.scan_result && p.scan_result.startsWith('pruned_');
    const _churned = p.scan_result === 'CHURNED';
    const alreadyHit = p.scan_result === 'SL_HIT' || p.scan_result === 'TARGET_HIT' || _timeExit || _pruned || _churned;
    let cmpHtml = '–';
    if (cmp) {
      let badgeHtml = '';
      if (dbOutcome?.exit_price) {
        const retPct = dbOutcome.return_pct;
        const retStr = retPct != null ? ` ${retPct > 0 ? '+' : ''}${retPct.toFixed(1)}%` : '';
        const retRs  = dbOutcome.absolute_pl ?? null;
        const rsStr  = retRs != null ? ` · ${retRs >= 0 ? '+' : ''}₹${Math.abs(retRs).toLocaleString('en-IN')}` : '';
        const cls    = (retPct || 0) >= 0 ? 'target-hit' : 'sl-hit';
        badgeHtml = `<div class="m3-cmp-badge ${cls}">CLOSED${retStr}${rsStr}</div>`;
      } else if (_pruned) {
        const reasonLabel = { pruned_macro: 'MACRO', pruned_earnings: 'EARNINGS', pruned_news: 'NEWS', sl_hit: 'SL', pruned_sl: 'SL' }[p.scan_result] || 'PRUNED';
        badgeHtml = `<div class="m3-cmp-badge pruned">[PRUNED · ${reasonLabel}]</div>`;
      } else if (_churned) {
        badgeHtml = `<div class="m3-cmp-badge churned">CHURNED</div>`;
      } else if (p.scan_result === 'SL_HIT') {
        badgeHtml = `<div class="m3-cmp-badge sl-hit">SL HIT</div>`;
      } else if (p.scan_result === 'TARGET_HIT') {
        badgeHtml = `<div class="m3-cmp-badge target-hit">TARGET HIT</div>`;
      } else if (_timeExit) {
        const r = _teOutcome?.return_pct;
        const rs = r != null ? ` ${r >= 0 ? '+' : ''}${r.toFixed(1)}%` : '';
        badgeHtml = `<div class="m3-cmp-badge ${(r || 0) >= 0 ? 'target-hit' : 'sl-hit'}">TIME EXIT${rs}</div>`;
      } else if (p.initial_badge) {
        badgeHtml = `<div class="m3-cmp-badge ${p.initial_badge_class}">${p.initial_badge}</div>`;
      }
      const closedFlag = (dbOutcome?.exit_price || alreadyHit) ? '1' : '';
      cmpHtml = `<div class="m3-cmp-wrap" id="cmpwrap_${p.symbol}" data-pick-id="${p.id}" data-entry-lo="${lvl.entry_lo||''}" data-entry-hi="${lvl.entry_hi||''}" data-sl="${lvl.sl||''}" data-target="${lvl.target||''}" data-closed="${closedFlag}"><div class="m3-cmp-price">₹${cmp.toLocaleString('en-IN',{maximumFractionDigits:2})}</div>${badgeHtml}</div>`;
    }
    const posKey = 'm3pos_' + p.symbol;
    const lsPos = (() => { try { return JSON.parse(localStorage.getItem(posKey)||'null'); } catch(e){return null;} })();
    const savedQty = dbOutcome?.qty ?? lsPos?.qty ?? '';
    const savedPrc = dbOutcome?.entry_price ?? lsPos?.prc ?? '';
    const totalVal = (savedQty && savedPrc) ? '₹' + (parseFloat(savedQty)*parseFloat(savedPrc)).toLocaleString('en-IN',{maximumFractionDigits:0}) : '';
    if (!dbOutcome && lsPos?.qty && lsPos?.prc) {
      setTimeout(() => fetch(API + '/api/swing/vault/' + p.id + '/outcome', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({was_traded:true, qty:parseFloat(lsPos.qty), entry_price:parseFloat(lsPos.prc)}),
      }).then(() => localStorage.removeItem(posKey)).catch(()=>{}), 0);
    }

    const isOpen = !alreadyHit && !dbOutcome?.exit_price;
    const promoted = p.promoted_to_trade_id ? '<span style="font-size:9px;color:var(--muted);font-family:var(--font-display);margin-left:4px">[→ My Trades]</span>' : '';
    return `<tr class="${rowClass} m3-row-${sStatus}" draggable="${isOpen ? 'true' : 'false'}"
      ondragstart="event.dataTransfer.setData('text/pick-id','${p.id}');event.currentTarget.style.opacity='0.5'"
      ondragend="event.currentTarget.style.opacity=''">
      <td class="muted" style="font-weight:700">${String(i+1).padStart(2,'0')}</td>
      <td><span class="sym" style="color:var(--blue)">${p.symbol}</span>${flagPill}${earningsSetupPill}${strengthBadge}${promoted}${tags}<span class="chart-link" onclick="openInCharts('${p.symbol}')">↗</span></td>
      <td class="m3-comp-cell">
        <div class="m3-comp-top ${compTier}"><span class="m3-comp-num">${compVal}</span><span class="m3-comp-max">/100</span></div>
        <div class="m3-subbar">${subSeg('s-sec',p.sector_momentum_score)}${subSeg('s-rs',p.leadership_score)}${subSeg('s-sepa',p.total)}${subSeg('s-bo',p.breakout_score)}</div>
        <div class="m3-sublbl"><span>Sec</span><span>RS</span><span>SEPA</span><span>Brk</span></div>
      </td>
      <td style="text-align:left">
        <span class="m3-pullback-badge ${pbClass}">${pbText}</span>
        <span class="m3-explain-icon" data-tip-idx="${i}"
          onmouseenter="_showExplainIdx(this)" onmouseleave="_hideExplain()">📋</span>
      </td>
      <td>${entryCell}</td>
      <td>${cmpHtml}</td>
      <td class="red">₹${lvl.sl ?? '–'}</td>
      <td class="green">₹${lvl.target ?? '–'}</td>
      <td>${rrPill}</td>
      <td class="muted">${mcap}</td>
      <td style="text-align:left">
        ${(() => {
          const isClosed = !!(dbOutcome?.exit_price || p.scan_result === 'SL_HIT' || p.scan_result === 'TARGET_HIT' || p.scan_result === 'CHURNED' || (p.scan_result && p.scan_result.startsWith('pruned_')));
          const dis = isClosed ? 'disabled' : '';
          const sepCls = isClosed ? 'locked' : '';
          return `<div class="m3-pos-cell">
          ${ordBtn}
          <div class="m3-pos-inputs">
            <input class="m3-pos-inp m3-qty-inp" id="qtyinp_${p.symbol}" type="number" placeholder="qty" value="${savedQty}"
              oninput="_updatePos(${p.id}, '${p.symbol}', this)" min="0" ${dis}>
            <span class="m3-pos-sep ${sepCls}">×</span>
            <input class="m3-pos-inp m3-prc-inp" id="posinp_${p.symbol}" type="text" inputmode="decimal" placeholder="price" value="${savedPrc}"
              oninput="_updatePos(${p.id}, '${p.symbol}', this)" ${dis}>
          </div>
          <div class="m3-pos-total" id="postotal_${p.symbol}">${totalVal}</div>
          </div>`;
        })()}
      </td>
    </tr>`;
  };

  window._m3TipSignals = [..._grp.enterable, ..._grp.weak_missed, ..._grp.closed, ..._grp.churned].map(p => p.pullback_signal || '');
  let _gi = 0;
  let _bodyHtml = '';
  if (_grp.enterable.length) {
    _bodyHtml += _subhdr('✅ Active · Enterable', 'enter', _grp.enterable.length)
              + _grp.enterable.map(p => renderRow(p, _gi++)).join('');
  }
  if (_grp.weak_missed.length) {
    _bodyHtml += _subhdr('⚠ Weak / Missed · zone blown, still tracked', 'weak', _grp.weak_missed.length)
              + _grp.weak_missed.map(p => renderRow(p, _gi++)).join('');
  }
  if (_grp.closed.length) {
    _bodyHtml += _subhdr('🔒 Closed · scanner scorecard (not enterable)', 'closed', _grp.closed.length)
              + _grp.closed.map(p => renderRow(p, _gi++)).join('');
  }
  if (_grp.churned.length) {
    _bodyHtml += _subhdr('♻ Churned · replaced by higher-scored picks', 'closed', _grp.churned.length)
              + _grp.churned.map(p => renderRow(p, _gi++)).join('');
  }
  document.getElementById('m3PicksBody').innerHTML = _bodyHtml ||
    '<tr><td colspan="11" style="text-align:center;color:var(--muted);padding:28px">No picks loaded.</td></tr>';

  // Subscribe WS for live CMP on pick symbols
  if (_isMarketHours()) {
    const allPicks = [..._grp.enterable, ..._grp.weak_missed];
    const pickSyms = allPicks.map(p => p.symbol);
    if (pickSyms.length) {
      PriceWsClient.subscribe(pickSyms);
      pickSyms.forEach(sym => {
        const old = _scannerWsHandlers.get(sym);
        if (old) PriceWsClient.offPrice(sym, old);
        const handler = payload => {
          const ltp = payload?.ltp;
          if (!ltp) return;
          const wrap = document.getElementById('cmpwrap_' + sym);
          if (!wrap || wrap.dataset.closed === '1') return;
          const priceDiv = wrap.querySelector('.m3-cmp-price');
          if (priceDiv) priceDiv.textContent = '₹' + ltp.toLocaleString('en-IN', {maximumFractionDigits:2});
        };
        _scannerWsHandlers.set(sym, handler);
        PriceWsClient.onPrice(sym, handler);
      });
    }
  }

  _vaultWeeks = (hist?.weeks || []);
  _generateVaultMonths();
  const sel = document.getElementById('m3VaultMonthSel');
  if (sel?.options?.length) _onVaultMonthChange(sel.options[0].value);
  else _renderVaultFolders(_vaultWeeks);

  // Scan-vault header (Sectors / Avg R:R / Win Rate / Sentiment) is folder-driven:
  // stays '–' until the user selects a scan folder (see openVaultDetail).
  _resetVaultHeader();
}


// ───────── Scanner v2 — P6 surface renderers ─────────

function _renderIpoStrip(ipoPicks) {
  const el = document.getElementById('m3IpoStrip');
  if (!el) return;
  if (!ipoPicks || !ipoPicks.length) { el.style.display = 'none'; el.innerHTML = ''; return; }
  el.style.display = '';
  el.innerHTML = '<span class="m3-ipo-strip-label">🚀 IPO Breakouts</span>' + ipoPicks.map(p => {
    const lvl = p.levels || {};
    const comp = p.composite_score != null ? (Math.round(p.composite_score * 10) / 10) : (p.total ?? '–');
    const zone = (lvl.entry_lo && lvl.entry_hi) ? `₹${lvl.entry_lo}–${lvl.entry_hi}` : (lvl.entry ? `₹${lvl.entry}` : '–');
    return `<div class="m3-ipo-card">
      <div class="ic-sym">${p.symbol}<small>${p.sector || 'IPO'}</small></div>
      <div class="ic-field"><span class="ic-k">Composite</span><span class="ic-v pur">${comp}</span></div>
      <div class="ic-field"><span class="ic-k">Entry Zone</span><span class="ic-v">${zone}</span></div>
      <div class="ic-field"><span class="ic-k">R:R</span><span class="ic-v">${lvl.rr ? '1:' + lvl.rr : '–'}</span></div>
      <button class="m3-ord-btn" onclick="openInCharts('${p.symbol}')" title="Open chart">↗</button>
    </div>`;
  }).join('');
}

async function _renderSectorRanking() {
  const el = document.getElementById('m3SectorPillsPop');
  const cnt = document.getElementById('m3SectorMomCount');
  if (!el) return;
  const data = await api('/api/swing/sector-ranking?limit=12').catch(() => null);
  const sectors = (data && data.sectors) || [];
  if (!sectors.length) { el.innerHTML = '<span style="font-size:10px;color:var(--muted)">No sector data</span>'; return; }
  const qClass = q => ({ Leading: 'lead', Improving: 'impr', Weakening: 'weak', Lagging: 'lag' }[q] || 'lag');
  if (cnt) {
    const lead = sectors.filter(s => s.rrg_quadrant === 'Leading' || s.rrg_quadrant === 'Improving').length;
    cnt.textContent = `${lead}/${sectors.length} sectors in momentum`;
  }
  el.innerHTML = sectors.map(s =>
    `<span class="m3-sector-pill ${qClass(s.rrg_quadrant)}" title="${s.rrg_quadrant || ''} · 1M ${s.perf_1m ?? '–'}% · ${s.num_stocks || 0} stocks">
      <span class="sp-score">${s.score != null ? Math.round(s.score * 10) / 10 : '–'}</span> ${s.name}</span>`
  ).join('');
}

function _showOrderPop(sym) {
  const o = (window._m3Orders || {})[sym];
  if (!o) return;
  const line = `${o.side} ${o.symbol} qty=${o.qty} @${o.order_type} ${o.entry} SL ${o.stop_loss} Tgt ${o.target} ${o.product}`;
  document.getElementById('m3OrderTitle').textContent = `${o.symbol} · qty ${o.qty}`;
  document.getElementById('m3OrderLine').innerHTML =
    `<span class="b">${o.side}</span> ${o.symbol} <span class="key">qty</span>=${o.qty} <span class="key">@${o.order_type}</span> ${o.entry}<br>` +
    `<span class="key">SL</span> ${o.stop_loss} &nbsp; <span class="key">Tgt</span> ${o.target} &nbsp; <span class="key">${o.product}</span>`;
  const copyBtn = document.getElementById('m3OrderCopy');
  copyBtn.onclick = () => {
    if (navigator.clipboard) navigator.clipboard.writeText(line);
    copyBtn.textContent = 'Copied ✓';
    setTimeout(() => copyBtn.textContent = 'Copy order line', 1400);
  };
  document.getElementById('m3OrderPop').classList.add('open');
}

function _toggleForwardTrack() {
  const el = document.getElementById('m3ValWrap');
  const wrap = document.getElementById('m3FwdWrap');
  const sub = document.getElementById('m3FwdBarSub');
  if (!el) return;
  const open = el.style.display !== 'none';
  el.style.display = open ? 'none' : '';
  if (wrap) wrap.classList.toggle('open', !open);
  if (sub) sub.textContent = 'predictive scorecard · click to ' + (open ? 'expand' : 'collapse');
}

function _showFwdGuide(elm) {
  _showExplain(elm, `<p><b>Forward-track — predictive scorecard</b></p>
    <p>How past scanner picks actually performed, measured from each pick's entry baseline.</p>
    <p><b>+1w / +2w / +4w / +12w</b> — hit-rate (% of picks up) and avg return that many weeks after the pick. <i>pending</i> = horizon not elapsed yet.</p>
    <p><b>By composite bucket</b> — 1-week hit-rate grouped by composite score; higher bucket = stronger setup.</p>
    <p><b>INDICATIVE ONLY</b> — the walk-forward backtest is a rough estimate (reduced composite, survivorship bias). Directional, not exact.</p>`);
}

function _resetVaultHeader() {
  _renderCompactSectorDist([]);
  const rr = document.getElementById('m3VaultRR');     if (rr) rr.textContent = '–';
  const win = document.getElementById('m3VaultWinRate'); if (win) { win.textContent = '–'; win.className = 'm3-vsc-val'; }
  const sent = document.getElementById('m3VaultSentiment'); if (sent) { sent.textContent = '–'; sent.className = 'm3-vsc-val'; }
}

async function _renderValidation() {
  const el = document.getElementById('m3ValWrap');
  const wrap = document.getElementById('m3FwdWrap');
  if (!el) return;
  const v = await api('/api/swing/validation').catch(() => null);
  const ft = v && v.forward_track;
  if (!ft || !ft.overall) { if (wrap) wrap.style.display = 'none'; return; }
  if (wrap) wrap.style.display = '';
  const hz = ['1w', '2w', '4w', '12w'];
  const cards = hz.map(h => {
    const d = ft.overall[h] || {};
    const has = d.hit_rate != null;
    return `<div class="m3-val-card ${has ? '' : 'pending'}">
      <div class="vh">+${h.replace('w', ' Week')}${h === '1w' ? '' : 's'}</div>
      <div class="vhit">${has ? d.hit_rate + '%' : 'pending'}</div>
      <div class="vavg">${has ? (d.avg_return >= 0 ? '+' : '') + d.avg_return + '% avg' : '—'}</div>
      <div class="vn">${has ? 'n=' + d.n + ' · elapsed' : 'horizon not elapsed'}</div>
    </div>`;
  }).join('');
  const buckets = ft.by_score_bucket || {};
  const bChips = Object.keys(buckets).map(b => {
    const d = (buckets[b] || {})['1w'] || {};
    if (d.hit_rate == null) return '';
    return `<div class="m3-val-bchip">${b} <span class="bn">${d.hit_rate}%</span> · ${d.avg_return >= 0 ? '+' : ''}${d.avg_return}%</div>`;
  }).join('');
  const bt = v.backtest || {};
  const btRow = bt.overall ? `<div class="m3-val-btrow">
      <span class="x">${Array.isArray(bt.rebalances) ? bt.rebalances.length : (bt.rebalances ?? '–')} rebalances</span>
      <span class="x">overall hit <b>${bt.overall.hit_rate ?? '–'}%</b></span>
      <span class="x">avg <b>${bt.overall.avg_return >= 0 ? '+' : ''}${bt.overall.avg_return ?? '–'}%</b></span>
    </div>` : '';
  // Attribution table (per-component hit-rate if available)
  const attr = ft.attribution || null;
  let attrHtml = '';
  if (attr) {
    const comps = ['sepa_total','rs_pct','leadership','breakout','sector_momentum'];
    const labels = ['SEPA','RS%','Leadership','Breakout','Sec Mom'];
    const rows = comps.map((c, i) => {
      const buckets = attr[c] || {};
      const topBucket = Object.keys(buckets)[0];
      if (!topBucket) return '';
      const d4 = (buckets[topBucket] || {})['4w'] || {};
      const d2 = (buckets[topBucket] || {})['2w'] || {};
      const fmt = d => d.hit_rate != null ? `${d.hit_rate}% n=${d.n}` : '—';
      return `<tr><td>${labels[i]}</td><td class="mono">${topBucket}</td><td class="mono">${fmt(d2)}</td><td class="mono">${fmt(d4)}</td></tr>`;
    }).join('');
    attrHtml = rows ? `<div style="font-size:11px;color:var(--muted);margin-top:14px;margin-bottom:4px">Component attribution (top bucket · hit-rate @ 2w / 4w)</div>
      <table class="ui-table" style="font-size:11px"><thead><tr><th>Component</th><th>Bucket</th><th>2w</th><th>4w</th></tr></thead><tbody>${rows}</tbody></table>` : '';
  }

  el.innerHTML = `
    <div class="m3-val-title">Forward-track — live picks, return from entry baseline (${ft.picks_tracked || 0} picks tracked)</div>
    <div class="m3-val-grid">${cards}</div>
    ${bChips ? '<div style="font-size:11px;color:var(--muted);margin-top:12px">By composite bucket (1w hit-rate)</div><div class="m3-val-buckets">' + bChips + '</div>' : ''}
    ${attrHtml}
    <div class="m3-val-caveat"><b>INDICATIVE ONLY</b> — walk-forward backtest, reduced composite (no point-in-time sector momentum), survivorship + current-KB bias.${btRow}</div>`;
}

// Shared in-memory CMP price cache
let _cmpPrices = null;
const _CMP_CACHE_TTL = 120000;

function _getCachedCmp() {
  if (_cmpPrices && Date.now() - _cmpPrices.ts < _CMP_CACHE_TTL) return _cmpPrices;
  return null;
}

function _applyCmpToScannerDOM(states) {
  let newlyFrozen = false;
  const fmt = v => v.toLocaleString('en-IN', {maximumFractionDigits:2});

  Object.entries(states || {}).forEach(([sym, state]) => {
    const wrap = document.getElementById('cmpwrap_' + sym);
    if (!wrap) return;

    const cmp = state.cmp;
    if (!cmp) return;

    const priceClass = ['sl-hit','sl-touched'].includes(state.label_class)       ? 'sl-price'
                     : ['target-hit','target-touched'].includes(state.label_class) ? 'target-price'
                     : '';
    const badgeHtml  = state.label
      ? `<div class="m3-cmp-badge ${state.label_class}">${state.label}</div>`
      : '';

    wrap.innerHTML = `<div class="m3-cmp-price ${priceClass}">₹${fmt(cmp)}</div>${badgeHtml}`;

    if (state.frozen) wrap.dataset.closed = '1';
    if (state.newly_frozen) newlyFrozen = true;
  });

  if (newlyFrozen) {
    _vaultDetailCache = {};
    _m3TradesLoaded = false;
    if (_m3ActiveTab === 'trades') loadMyTrades();
  }
}

async function _refreshPicksCMP() {
  try {
    const data = await api('/api/swing/picks/cmp').catch(() => null);
    if (!data?.prices) return;
    _cmpPrices = { prices: data.prices, ohlc: data.ohlc || {}, states: data.states || {}, ts: Date.now() };
    _applyCmpToScannerDOM(data.states || {});
    _m3TradesLoaded = false;
  } catch(e) {}
}

function _scanMonthLabel(scannedAt) {
  // Baskets are monthly — folders are labelled by the scan's calendar month.
  return new Date(scannedAt).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' });
}

function _scanWeekRange(scannedAt) {
  const dt  = new Date(scannedAt);
  const day = dt.getDay();
  const toMon = day === 6 ? 2 : day === 0 ? 1 : day === 5 ? 3 : (8 - day) % 7 || 7;
  const mon = new Date(dt); mon.setDate(dt.getDate() + toMon);
  const fri = new Date(mon); fri.setDate(mon.getDate() + 4);
  const f = d => d.toLocaleDateString('en-IN', {day:'numeric', month:'short'});
  return `${f(mon)} – ${f(fri)}`;
}
