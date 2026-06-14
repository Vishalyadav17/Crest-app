// ── Module 2: Market Monitor ─────────────────────────────────────────────────
let _m2Loaded = false;

function _sectorBg(chg) {
  if (chg >=  2) return 'rgba(0,208,156,0.18)';
  if (chg >= 0.5) return 'rgba(0,208,156,0.10)';
  if (chg >= -0.5) return 'rgba(37,42,58,0.6)';
  if (chg >= -2) return 'rgba(244,67,54,0.10)';
  return 'rgba(244,67,54,0.18)';
}

function _timeAgo(pub) {
  try {
    const d = new Date(pub);
    if (isNaN(d)) return '';
    const diffMs = Date.now() - d.getTime();
    if (diffMs < 0) return '';
    const mins = Math.floor(diffMs / 60000);
    if (mins < 60) return mins + 'm ago';
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return hrs + 'h ago';
    const days = Math.floor(hrs / 24);
    if (days > 365) return '';
    return days + 'd ago';
  } catch { return ''; }
}

async function loadMarketMonitor() {
  if (_m2Loaded) return;
  _m2Loaded = true;

  const [overview, adData, sectorsData, gainersData, breadthData, newsData, indicesCfg] = await Promise.all([
    api('/api/market/overview').catch(() => null),
    api('/api/market/ad-ratio').catch(() => null),
    api('/api/market/sectors').catch(() => null),
    api('/api/market/gainers-losers').catch(() => null),
    api('/api/market/breadth').catch(() => null),
    api('/api/market/news').catch(() => null),
    api('/api/market/available-indices').catch(() => null),
  ]);

  // Index tape
  if (overview) {
    _renderIndexTape(overview, indicesCfg);

    const ms = overview.market_signal;
    if (ms) {
      const sig = ms.signal.toLowerCase();
      const banner = document.getElementById('m2SignalBanner');
      banner.className = 'm2-signal-card ' + sig;
      document.getElementById('m2SignalDot').className = 'm2-signal-dot ' + sig;
      document.getElementById('m2SignalLabel').textContent = ms.signal;
      document.getElementById('m2SignalSub').textContent =
        (ms.breakout_likely ? 'Breakouts LIKELY' : 'Breakouts UNLIKELY') +
        ' · ' + ms.sectors_above_ema50 + '/' + ms.sectors_checked + ' sectors above 20 EMA';
    }
  }

  // A/D ratio — bicolor bar
  if (adData) {
    document.getElementById('m2AdAdv').textContent = adData.advances;
    document.getElementById('m2AdDec').textContent = adData.declines;
    const ratioEl = document.getElementById('m2AdRatio');
    ratioEl.textContent = adData.ratio?.toFixed(2) ?? '–';
    ratioEl.className = 'm2-ad-ratio-num ' + (adData.ratio >= 1 ? 'green' : 'red');
    const total = (adData.advances + adData.declines + (adData.unchanged || 0)) || 1;
    const advPct = adData.advances / total * 100;
    document.getElementById('m2BcAdv').style.width = advPct.toFixed(1) + '%';
  }

  // Sector heatmap — compact tiles
  if (sectorsData?.sectors) {
    const grid = document.getElementById('m2SectorGrid');
    grid.innerHTML = '';
    document.getElementById('m2MomentumCount').textContent =
      sectorsData.momentum_count + '/' + sectorsData.total + ' in momentum';
    sectorsData.sectors.forEach(s => {
      const chgColor = s.chg_pct >= 0 ? 'var(--green)' : 'var(--red)';
      const tile = document.createElement('div');
      tile.className = 'm2-sector-tile-sm';
      tile.style.background = _sectorBg(s.chg_pct);
      tile.innerHTML = `<div class="sec-name-sm">${s.name}</div>
        <div class="sec-chg-sm" style="color:${chgColor}">${s.chg_pct >= 0 ? '+' : ''}${s.chg_pct?.toFixed(2)}%</div>`;
      tile.addEventListener('click', () => openSectorModal(s.name, s));
      grid.appendChild(tile);
    });
  }

  // Gainers / Losers — compact table
  if (gainersData) _renderGainersLosers(gainersData);

  // Market breadth — per-index table
  if (breadthData) {
    const sigEl = document.getElementById('m2BreadthSignal');
    const sig = breadthData.breadth_signal || '';
    sigEl.textContent = sig;
    sigEl.className = 'm2-breadth-sig ' + sig;

    const tbody = document.getElementById('m2BreadthBody');
    if (breadthData.indices?.length) {
      tbody.innerHTML = breadthData.indices.map(idx => `<tr>
        <td>${idx.label}</td>
        <td class="${idx.css_20dma||''}">${idx.above_20dma}%</td>
        <td class="${idx.css_50dma||''}">${idx.above_50dma}%</td>
        <td class="${idx.css_200dma||''}">${idx.above_200dma}%</td>
      </tr>`).join('');
    }
  }

  // News — compact two-line format
  if (newsData?.length) {
    document.getElementById('m2NewsList').innerHTML = newsData.map(n => `
      <div class="m2-news-compact-item">
        <div class="m2-news-cat">${n.source}</div>
        <div class="m2-news-body">
          <a href="${n.link}" target="_blank" rel="noopener">${n.title}</a>
          ${n.pub ? `<div class="m2-news-time">${_timeAgo(n.pub)}</div>` : ''}
        </div>
      </div>`).join('');
  }
}

// ── Market Pulse partial refresh helpers ──────────────────────────────────────

function _setRefreshing(btnId, on) {
  const btn = document.getElementById(btnId);
  if (btn) btn.classList.toggle('spinning', on);
}

function _renderIndexTape(overview, indicesCfg) {
  const ORDER = indicesCfg?.order ?? ['N50','BNIFTY','MIDCAP100','SC100','USDINR'];
  const row = document.getElementById('m2IndexRow');
  // preserve the refresh button at the end
  const refreshBtn = document.getElementById('m2IndexRefreshBtn');
  row.innerHTML = '';
  ORDER.forEach(key => {
    const d = overview[key]; if (!d) return;
    const up = d.chg_pct >= 0;
    const emaClass = d.above_ema50 == null ? '' : (d.above_ema50 ? 'above-ema' : 'below-ema');
    const emaPill = d.ema50 != null
      ? `<div class="m2-index-ema">${d.above_ema50 ? '▲ above' : '▼ below'} 20 EMA &nbsp;·&nbsp; ${d.ema50?.toLocaleString('en-IN')}</div>`
      : '';
    row.innerHTML += `<div class="m2-index-card ${emaClass}">
      <div class="m2-index-label">${d.label || key}</div>
      <div class="m2-index-price">${d.price?.toLocaleString('en-IN') ?? '–'}</div>
      <div class="m2-index-change ${up ? 'green' : 'red'}">${up ? '+' : ''}${d.chg_pct?.toFixed(2)}%  (${up ? '+' : ''}${d.change?.toLocaleString('en-IN', {maximumFractionDigits:1})})</div>
      ${emaPill}
    </div>`;
  });
  if (refreshBtn) row.appendChild(refreshBtn);
}

function _renderGainersLosers(gainersData) {
  document.getElementById('m2AsOf').textContent = gainersData.as_of ? 'as of ' + gainersData.as_of : '';
  const mkRow = (s, cc) => `<tr>
    <td><span class="${cc}">${s.symbol}</span><span class="chart-link" onclick="openInCharts('${s.symbol}')">↗</span></td>
    <td>₹${s.price?.toLocaleString('en-IN')}</td>
    <td class="${cc}">${s.chg_pct >= 0 ? '+' : ''}${s.chg_pct?.toFixed(2)}%</td>
    <td style="color:var(--muted)">₹${s.turnover_cr}Cr</td>
  </tr>`;
  document.getElementById('m2GainersBody').innerHTML =
    (gainersData.gainers || []).map(s => mkRow(s,'green')).join('') ||
    '<tr><td colspan="4" style="text-align:center;color:var(--muted)">No data</td></tr>';
  document.getElementById('m2LosersBody').innerHTML =
    (gainersData.losers || []).map(s => mkRow(s,'red')).join('') ||
    '<tr><td colspan="4" style="text-align:center;color:var(--muted)">No data</td></tr>';
}

async function _refreshIndexTape() {
  _setRefreshing('m2IndexRefreshBtn', true);
  try {
    const d = await api('/api/market/overview').catch(() => null);
    if (d) _renderIndexTape(d);
  } finally {
    _setRefreshing('m2IndexRefreshBtn', false);
  }
}

async function _refreshGainersLosers() {
  _setRefreshing('m2GlRefreshBtn', true);
  try {
    const d = await api('/api/market/gainers-losers').catch(() => null);
    if (d) _renderGainersLosers(d);
  } finally {
    _setRefreshing('m2GlRefreshBtn', false);
  }
}

async function runSepa() {
  const ticker = document.getElementById('m2SepaInput').value.trim().toUpperCase();
  if (!ticker) return;
  const res = document.getElementById('m2SepaResult');
  res.innerHTML = `<span style="color:var(--muted)">Scoring ${ticker}… (10–20s)</span>`;
  try {
    const d = await api('/api/market/sepa/' + ticker);
    if (!d) return;
    const gc = d.score_color === 'green' ? 'var(--green)' : (d.score_color === 'gold' ? 'var(--gold)' : 'var(--red)');
    const CRIT_LABELS = {
      trend_template:    'Trend Template',
      high_proximity:    '52W High Proximity',
      low_distance:      '52W Low Distance',
      relative_strength: 'Relative Strength',
      vcp_proxy:         'VCP Contraction',
      liquidity:         'Liquidity',
      weinstein_stage2:  'Weinstein Stage 2',
    };
    const criteria = d.criteria || {};
    // Pullback signal badge
    const ps = d.pullback_signal || '';
    let pbClass = 'extended', pbLabel = ps || '–';
    if (ps.includes('BOUNCE')) { pbClass = 'bounce'; pbLabel = '▲ ' + ps; }
    else if (ps.includes('AT 20DMA')) { pbClass = 'at-dma'; pbLabel = '~ ' + ps; }

    res.innerHTML = `
      <div style="margin-bottom:10px;display:flex;align-items:center;gap:10px;flex-wrap:wrap">
        <span class="m2-sepa-score" style="color:${gc}">${d.total ?? '–'}</span>
        <span class="m2-sepa-grade-box" style="color:${gc}">${d.grade ?? ''}</span>
        <span style="font-size:12px;color:var(--muted)">/100 · ${ticker}</span>
      </div>
      <div style="margin-bottom:12px">
        <span class="m2-sepa-pullback ${pbClass}">${pbLabel || '–'}</span>
      </div>
      <div class="m2-sepa-criteria">
        ${Object.entries(CRIT_LABELS).map(([key, label]) => {
          const c = criteria[key] || {};
          const pass = c.score > 0;
          const scoreColor = c.score === c.max ? 'var(--green)' : (c.score > 0 ? 'var(--gold)' : 'var(--muted)');
          return `<div class="m2-sepa-crit">
            <span class="${pass ? 'cpass' : 'cfail'}" style="font-family:var(--font-mono)">${pass ? '+' : '–'}</span>
            <span><strong>${label}</strong> <span style="color:${scoreColor};font-family:var(--font-mono)">${c.score ?? 0}/${c.max ?? 0}</span><br><span style="font-size:11px;font-family:var(--font-mono)">${c.detail ?? ''}</span></span>
          </div>`;
        }).join('')}
      </div>`;
  } catch(e) {
    res.innerHTML = `<span style="color:var(--red)">Error: ${e.message}</span>`;
  }
}

