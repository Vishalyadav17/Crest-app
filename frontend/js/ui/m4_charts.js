// ── Module 4: Live Charts ─────────────────────────────────────────────────────
const CHART_DEFAULTS = [
  {symbol:'RELIANCE.NS', tf:'1d', src:'yfinance'},
  {symbol:'HDFCBANK.NS', tf:'1d', src:'yfinance'},
  {symbol:'BTC',         tf:'1h', src:'hyperliquid'},
  {symbol:'ETH',         tf:'1h', src:'hyperliquid'},
  {symbol:'^NSEI',       tf:'1d', src:'yfinance'},
  {symbol:'SOL',         tf:'1h', src:'hyperliquid'},
  {symbol:'TATAMOTORS.NS',tf:'1d',src:'yfinance'},
  {symbol:'AVAX',        tf:'1h', src:'hyperliquid'},
];
const CHART_SYMBOLS = {
  yfinance:    ['RELIANCE.NS','HDFCBANK.NS','INFY.NS','TCS.NS','ICICIBANK.NS',
                'KOTAKBANK.NS','TATAMOTORS.NS','SBIN.NS','BAJFINANCE.NS','HCLTECH.NS',
                'ADANIENT.NS','WIPRO.NS','AXISBANK.NS','ITC.NS','^NSEI','^BSESN'],
  hyperliquid: ['BTC','ETH','SOL','AVAX','ARB','OP','LINK','DOGE','PEPE','WIF','SUI','TIA','SEI'],
};
let _HL_CRYPTO = new Set(['BTC','ETH','SOL','AVAX','ARB','OP','LINK','DOGE','PEPE','WIF','SUI','TIA','SEI','XRP','MATIC','NEAR','AAVE','UNI']);
let _indicatorCfg = { ppv_lookback: 10, dry_frac: 5, vol_ma_period: 50,
  volume_colors: { ppv:'#2196F3', down_heavy:'#EF5350', up_strong:'#26A69A', dry:'#FF9800', noise:'#555555' } };

let _chartCount      = 4;
let _chartPanes      = new Map();   // id -> { lwChart, cfg }
let _chartPollers    = new Map();   // id -> intervalId  (fallback only)
let _chartWsHandlers = new Map();   // id -> { sym, handler }
let _chartRefreshTmr = null;
let _chartLastPrices = new Map();   // id -> last price
let _m4Loaded        = false;
let _chartPendingSymbol = null;
let _lcClockTimer    = null;
let _lcIndOutsideListenerSet = false;
let _lcIndMenuOpen   = false;

// HL WebSocket state
let _hlWS     = null;
let _hlSubs   = new Map();    // coin -> Map<paneId, callback>
let _hlPaneMap= new Map();    // paneId -> coin

function _loadChartsState() {
  try { const r = localStorage.getItem('gp_charts_state'); return r ? JSON.parse(r) : null; }
  catch(e) { return null; }
}
function _saveChartsState() {
  const panes = {};
  _chartPanes.forEach((p, id) => { panes[id] = p.cfg; });
  const val = JSON.stringify({ count: _chartCount, panes });
  localStorage.setItem('gp_charts_state', val);
  // Sync to server in background (fire-and-forget)
  fetch('/api/user/preferences', {
    method:'PUT', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({key:'charts_state', value: val})
  }).catch(()=>{});
}
function _saveIndicators() {
  localStorage.setItem('gp_indicators', JSON.stringify(_m4Indicators));
  fetch('/api/user/preferences', {
    method:'PUT', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({key:'indicators', value: JSON.stringify(_m4Indicators)})
  }).catch(()=>{});
}

async function initCharts() {
  _m4Loaded = true;

  // Load indicator config + crypto symbol list from backend
  Promise.all([
    fetch('/api/charts/indicator-config').then(r => r.json()).catch(() => null),
    fetch('/api/market/crypto-symbols').then(r => r.json()).catch(() => null),
  ]).then(([indCfg, cryptoCfg]) => {
    if (indCfg) Object.assign(_indicatorCfg, indCfg);
    if (cryptoCfg?.symbols) _HL_CRYPTO = new Set(cryptoCfg.symbols);
  });

  // Load name map from CSV (fast, no yfinance)
  fetch('/api/charts/namemap').then(r => r.json()).then(d => {
    Object.assign(_stockNameMap, d.names || {});
    _chartPanes.forEach((pane, id) => {
      const sym = pane.cfg.symbol;
      const nameEl = document.getElementById('lcName' + id);
      if (nameEl) nameEl.textContent = _stockNameMap[sym.replace('.NS','')] || '';
    });
  }).catch(() => {});

  // Load preferences from server (primary), fall back to localStorage
  let serverPrefs = {};
  try {
    const r = await fetch('/api/user/preferences');
    if (r.ok) serverPrefs = await r.json();
  } catch(_) {}
  const chartsStatePref = serverPrefs['charts_state'] || null;
  const indicatorsPref  = serverPrefs['indicators']   || null;

  const state = chartsStatePref ? JSON.parse(chartsStatePref) : _loadChartsState();
  if (indicatorsPref) {
    try { Object.assign(_m4Indicators, JSON.parse(indicatorsPref)); } catch(_) {}
  }

  _chartCount = state?.count || 4;
  _renderChartsToolbar();
  _fetchWatchlists();
  _updateRightPanel();
  if (_m4InfoOpen) {
    const panel = document.getElementById('m4InfoPanel');
    if (panel) panel.innerHTML = `<div class="m4-rp-hdr"><span>Stock Info</span><button class="m4-rp-hdr-btn" onclick="_toggleInfoPanel()">✕</button></div><div class="m4-info-empty">Select a stock to view details</div>`;
  }
  // Indices panel persisted open → populate it (else it renders blank on load)
  if (typeof _m4IndicesOpen !== 'undefined' && _m4IndicesOpen && typeof _fetchIndices === 'function') {
    (_indicesLoaded && typeof _renderIndicesPanel === 'function') ? _renderIndicesPanel() : _fetchIndices();
  }
  setChartsCount(_chartCount);
  if (_chartRefreshTmr) clearInterval(_chartRefreshTmr);
  _chartRefreshTmr = setInterval(_refreshAllChartPanes, 60000);
  if (_chartPendingSymbol) {
    const pending = _chartPendingSymbol;
    _chartPendingSymbol = null;
    setTimeout(() => overrideChartPane(0, pending), 150);
  }
}

function _renderChartsToolbar() {
  const tb = document.getElementById('chartsToolbar');
  const counts = [1, 2, 4, 6, 8];
  const indItems = [
    ..._EMA_CONFIGS.map(e => `<label class="lc-ind-row"><input type="checkbox" ${_m4Indicators[e.key]?'checked':''} onchange="_toggleIndicator('${e.key}',this.checked)"><span class="lc-ind-dot" style="background:${e.color}"></span><span>${e.label}</span></label>`),
    `<div class="lc-ind-section">Simple Volume (Finally Nitin)</div>`,
    `<label class="lc-ind-row"><input type="checkbox" ${_m4Indicators.volume?'checked':''} onchange="_toggleIndicator('volume',this.checked)"><span>Show volume</span></label>`,
    `<label class="lc-ind-row"><input type="checkbox" ${_m4Indicators.pocketPivots?'checked':''} onchange="_toggleIndicator('pocketPivots',this.checked)"><span>Pocket Pivots</span></label>`,
    `<div style="padding:4px 2px 2px;font-size:10px;color:var(--muted);line-height:1.8">
      <span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#2196F3;margin-right:5px;vertical-align:middle"></span>PPV — up day &gt; any down vol, last 10 days<br>
      <span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#26A69A;margin-right:5px;vertical-align:middle"></span>Up day &gt; 50-bar avg vol<br>
      <span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#EF5350;margin-right:5px;vertical-align:middle"></span>Down day &gt; 50-bar avg vol<br>
      <span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#FF9800;margin-right:5px;vertical-align:middle"></span>Dry vol &lt; avg/5<br>
      <span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#363A45;margin-right:5px;vertical-align:middle"></span>Noise (below avg)
    </div>`,
  ].join('');
  const _ic = {
    search:  `<svg class="wt-ico" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/></svg>`,
    lists:   `<svg class="wt-ico" viewBox="0 0 24 24"><line x1="4" y1="6" x2="20" y2="6"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="18" x2="20" y2="18"/></svg>`,
    info:    `<svg class="wt-ico" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16"/><circle cx="12" cy="7.6" r=".4" fill="currentColor" stroke="none"/></svg>`,
    indices: `<svg class="wt-ico" viewBox="0 0 24 24"><polyline points="3 14 8 9 12 13 16 7 21 12"/></svg>`,
    wave:    `<svg class="wt-ico" viewBox="0 0 24 24"><path d="M3 12c2 0 2.5-6 4.5-6S10 18 12 18s2.5-12 4.5-12S19 12 21 12"/></svg>`,
    caret:   `<svg class="wt-ico wt-caret" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg>`,
    full:    `<svg class="wt-ico" viewBox="0 0 24 24"><polyline points="4 9 4 4 9 4"/><polyline points="20 9 20 4 15 4"/><polyline points="4 15 4 20 9 20"/><polyline points="20 15 20 20 15 20"/></svg>`,
  };
  tb.innerHTML = `<div class="wt-toolbar" role="toolbar" aria-label="Wavesight chart toolbar">
    <div class="wt-search" id="m4SearchWrap">
      <button class="wt-search-toggle" id="m4SearchToggle" aria-label="Search stocks">${_ic.search}</button>
      <div class="wt-search-field">${_ic.search}<input class="wt-search-input" id="m4SearchInp" placeholder="Search stocks…" autocomplete="off"></div>
      <div class="m4-autocomplete hidden" id="m4Autocomplete"></div>
    </div>
    <div class="wt-spacer"></div>
    <span id="lcClock" class="wt-clock"></span>
    <div class="wt-spacer"></div>
    <div class="wt-group">
      <button class="wt-btn wt-toggle ${_m4WatchlistOpen?'active':''}" id="m4WlBtn" onclick="_toggleWatchlistPanel()">${_ic.lists}Lists</button>
      <button class="wt-btn wt-toggle ${_m4InfoOpen?'active':''}" id="m4InfoBtn" onclick="_toggleInfoPanel()">${_ic.info}Info</button>
      <button class="wt-btn wt-toggle ${typeof _m4IndicesOpen!=='undefined'&&_m4IndicesOpen?'active':''}" id="m4IndBtn" onclick="_toggleIndicesPanel()">${_ic.indices}Indices</button>
    </div>
    <div class="wt-sep"></div>
    <div class="wt-group">
      <div class="wt-dropdown">
        <button class="wt-btn" id="lcIndBtn" onclick="_toggleIndicatorsMenu()">${_ic.wave}Indicators${_ic.caret}</button>
        <div id="lcIndMenu" class="wt-menu hidden">
          <div class="lc-ind-section">EMAs</div>
          ${indItems}
        </div>
      </div>
      <div class="wt-segmented" role="group" aria-label="Layout">
        <span class="wt-seg-label">Layout</span>
        ${counts.map(n => `<button class="wt-seg ${n===_chartCount?'active':''}" onclick="setChartsCount(${n})">${n}</button>`).join('')}
      </div>
      <button class="wt-btn wt-icon" onclick="_toggleFullscreen()" title="Fullscreen">${_ic.full}</button>
    </div>
  </div>`;
  _initSearch();
  _initToolbarSearch();
  if (!_lcClockTimer) {
    _lcClockTimer = setInterval(() => {
      if (!document.hidden) {
        const el = document.getElementById('lcClock');
        if (el) el.textContent = new Date().toLocaleTimeString('en-IN', {hour12:false});
      }
    }, 1000);
  }
  if (!_lcIndOutsideListenerSet) {
    _lcIndOutsideListenerSet = true;
    document.addEventListener('click', e => {
      if (!e.target.closest('#lcIndMenu') && !e.target.closest('#lcIndBtn')) {
        document.getElementById('lcIndMenu')?.classList.add('hidden');
        _lcIndMenuOpen = false;
      }
    });
  }
}

function _initToolbarSearch() {
  const wrap   = document.getElementById('m4SearchWrap');
  const toggle = document.getElementById('m4SearchToggle');
  const inp    = document.getElementById('m4SearchInp');
  if (!wrap || !toggle || !inp) return;
  toggle.addEventListener('click', () => {
    wrap.classList.add('open');
    setTimeout(() => inp.focus(), 120);
  });
  inp.addEventListener('blur', () => {
    if (!inp.value.trim()) setTimeout(() => wrap.classList.remove('open'), 160);
  });
}

function setChartsCount(n) {
  _chartCount = n;
  document.querySelectorAll('.wt-seg').forEach(b => {
    b.classList.toggle('active', +b.textContent === n);
  });
  // Destroy all existing panes
  _chartPanes.forEach((pane, id) => {
    _unsubscribeHLPane(id);
    _stopChartPoller(id);
    _stopChartWs(id);
    if (pane.lwChart) { pane.lwChart._ro?.disconnect(); pane.lwChart.remove(); }
  });
  _chartPanes.clear();
  _chartLastPrices.clear();

  const grid = document.getElementById('chartsGrid');
  grid.className = 'lc-grid-' + n;
  grid.innerHTML = '';

  const state = _loadChartsState();
  for (let i = 0; i < n; i++) {
    const cfg = state?.panes?.[i] || CHART_DEFAULTS[i % CHART_DEFAULTS.length];
    _createChartPane(i, {...cfg});
  }
  _saveChartsState();
}

function _buildPaneHTML(id, cfg) {
  const tfOpts = ['1m','5m','15m','30m','1h','4h','1d','1w']
    .map(t => `<option value="${t}" ${t===cfg.tf?'selected':''}>${t}</option>`).join('');
  // Symbol is changed via top search / watchlist / index clicks — no per-pane symbol box.
  return `<div class="lc-pane-header">
    <div class="lc-controls">
      <select class="lc-tf-sel">${tfOpts}</select>
    </div>
    <div class="lc-ticker" id="lcTicker${id}">
      <span class="lc-t-sym">${cfg.symbol.replace('.NS','')}</span>
      <span class="lc-t-name" id="lcName${id}"></span>
      <span class="lc-t-price">–</span>
      <span class="lc-t-ohlc" id="lcOhlc${id}"></span>
    </div>
    <div class="lc-controls">
      <select class="lc-src-sel">
        <option value="yfinance"    ${cfg.src==='yfinance'   ?'selected':''}>NSE</option>
        <option value="hyperliquid" ${cfg.src==='hyperliquid'?'selected':''}>Crypto</option>
      </select>
    </div>
  </div>
  <div class="lc-chart-body"></div>`;
}

function _createChartPane(id, cfg) {
  const el = document.createElement('div');
  el.className = 'lc-pane';
  el.dataset.paneId = id;
  el.innerHTML = _buildPaneHTML(id, cfg);
  document.getElementById('chartsGrid').appendChild(el);

  const body = el.querySelector('.lc-chart-body');
  const lwChart = LightweightCharts.createChart(body, {
    layout: { background: {color:'#0b1326'}, textColor: '#8d909f' },
    grid:   { vertLines:{color:'#1a2540'}, horzLines:{color:'#1a2540'} },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: { borderColor: '#334155' },
    timeScale: { borderColor:'#334155', timeVisible:true, secondsVisible:false },
    width:  body.clientWidth  || 400,
    height: body.clientHeight || 300,
  });

  const series = lwChart.addCandlestickSeries({
    upColor:'#10B981', downColor:'#EF4444',
    borderUpColor:'#10B981', borderDownColor:'#EF4444',
    wickUpColor:'#10B981', wickDownColor:'#EF4444',
  });
  lwChart._series = series;

  const ro = new ResizeObserver(() => {
    lwChart.applyOptions({ width: body.clientWidth, height: body.clientHeight });
  });
  ro.observe(body);
  lwChart._ro = ro;

  lwChart.subscribeCrosshairMove(param => _onCrosshair(id, param));

  _chartPanes.set(String(id), { lwChart, cfg: {...cfg}, emaSeries: {}, volSeries: null, _lastCandles: null });
  _wireChartControls(id, el, lwChart);
  _loadChartPane(id, cfg, lwChart);
}

function _wireChartControls(id, el, lwChart) {
  const tfSel  = el.querySelector('.lc-tf-sel');
  const srcSel = el.querySelector('.lc-src-sel');

  function reload() {
    const cur = _chartPanes.get(String(id)).cfg;
    const cfg = { symbol: cur.symbol, tf: tfSel.value, src: srcSel.value };
    _chartPanes.get(String(id)).cfg = cfg;
    _saveChartsState();
    _loadChartPane(id, cfg, lwChart);
  }

  if (tfSel)  tfSel.addEventListener('change', reload);
  if (srcSel) srcSel.addEventListener('change', reload);
}

function _loadChartPane(id, cfg, lwChart) {
  _unsubscribeHLPane(id);
  _stopChartPoller(id);
  _stopChartWs(id);
  lwChart._series.setData([]);

  // Leaving a custom-index view: drop any leftover overlay + de-highlight the panel
  const _pane = _chartPanes.get(String(id));
  if (_pane) {
    if (_pane._indexLineSeries) { try { lwChart.removeSeries(_pane._indexLineSeries); } catch(e) {} _pane._indexLineSeries = null; }
    _pane._indexMode = false;
  }
  // Opening a stock that belongs to the active index keeps the index selected +
  // its member list expanded; opening anything else de-selects the index.
  const _base = (cfg.symbol || '').replace('.NS', '').replace('^', '').toUpperCase();
  const _isMember = typeof _activeIndexMembers !== 'undefined' && _activeIndexMembers.has(_base);
  if (String(id) === '0' && typeof _activeIndexId !== 'undefined' && _activeIndexId !== null && !_isMember) {
    _activeIndexId = null;
    if (typeof _activeIndexMembers !== 'undefined') _activeIndexMembers = new Set();
    if (typeof _m4IndicesOpen !== 'undefined' && _m4IndicesOpen && typeof _renderIndicesPanel === 'function') _renderIndicesPanel();
  }

  const ticker = document.getElementById('lcTicker' + id);
  if (ticker) {
    ticker.querySelector('.lc-t-sym').textContent = _base;
    const nameEl = ticker.querySelector('.lc-t-name');
    const nm = _stockNameMap[_base];
    if (nameEl) nameEl.textContent = (nm && nm.toUpperCase() !== _base) ? nm : '';   // no duplicate
    ticker.querySelector('.lc-t-price').textContent = '…';
    ticker.querySelector('.lc-t-price').style.color = 'var(--muted)';
  }

  // Update info panel for pane 0 — always track symbol so opening panel later shows current stock
  if (String(id) === '0') {
    _m4InfoSymbol = cfg.symbol;
    if (_m4InfoOpen) _loadAndShowInfo(cfg.symbol);
  }

  fetch(`/api/charts/history?symbol=${encodeURIComponent(cfg.symbol)}&timeframe=${cfg.tf}&source=${cfg.src}`)
    .then(r => r.json())
    .then(data => {
      if (data.candles?.length) {
        const pane = _chartPanes.get(String(id));
        if (pane) pane._lastCandles = data.candles;
        lwChart._series.setData(data.candles);
        lwChart.timeScale().fitContent();
        _applyIndicators(id, data.candles);
        _onCrosshair(id, null);   // seed OHLC legend with last bar
        // Seed ticker price from last close so it never stays stuck on '…' (live WS overrides)
        const tk = document.getElementById('lcTicker' + id);
        const pe = tk && tk.querySelector('.lc-t-price');
        if (pe && pe.textContent === '…') {
          const lastClose = data.candles[data.candles.length - 1].close;
          pe.textContent = lastClose != null ? lastClose.toLocaleString('en-IN', {minimumFractionDigits:2, maximumFractionDigits:2}) : '–';
        }
      }
    })
    .catch(err => console.warn('[Charts] history pane', id, err));

  if (cfg.src === 'hyperliquid') {
    _subscribeHLPane(id, cfg.symbol, price => _updateChartTicker(id, cfg.symbol, price));
  } else {
    _startChartWs(id, cfg.symbol);
  }
}

function _refreshAllChartPanes() {
  _chartPanes.forEach((pane, id) => {
    const {cfg, lwChart} = pane;
    fetch(`/api/charts/history?symbol=${encodeURIComponent(cfg.symbol)}&timeframe=${cfg.tf}&source=${cfg.src}`)
      .then(r => r.json())
      .then(data => { if (data.candles?.length) lwChart._series.setData(data.candles); })
      .catch(() => {});
  });
}

// ── OHLC legend (TradingView-style, updates on hover; falls back to last bar) ──
function _setOhlcLegend(id, c) {
  const el = document.getElementById('lcOhlc' + id);
  if (!el) return;
  if (!c || c.open == null) { el.innerHTML = ''; return; }
  const up = c.close >= c.open;
  const f = v => v != null ? Number(v).toLocaleString('en-IN', {maximumFractionDigits:2}) : '–';
  el.className = 'lc-t-ohlc ' + (up ? 'up' : 'dn');
  el.innerHTML = `<span>O ${f(c.open)}</span><span>H ${f(c.high)}</span><span>L ${f(c.low)}</span><span>C ${f(c.close)}</span>`;
}

function _onCrosshair(id, param) {
  const pane = _chartPanes.get(String(id));
  if (!pane) return;
  let c = null;
  if (param && param.seriesData && pane.lwChart._series) {
    const d = param.seriesData.get(pane.lwChart._series);
    if (d && d.open != null) c = d;
  }
  if (!c && pane._lastCandles && pane._lastCandles.length) c = pane._lastCandles[pane._lastCandles.length - 1];
  _setOhlcLegend(id, c);
}

// ── Ticker bar ────────────────────────────────────────────────────────────────
function _updateChartTicker(id, symbol, price) {
  const ticker = document.getElementById('lcTicker' + id);
  if (!ticker) return;
  const last = _chartLastPrices.get(String(id));
  _chartLastPrices.set(String(id), price);
  ticker.querySelector('.lc-t-sym').textContent = symbol.replace('.NS','');
  const priceEl = ticker.querySelector('.lc-t-price');
  priceEl.textContent = price != null
    ? price.toLocaleString('en-IN', {minimumFractionDigits:2, maximumFractionDigits:2})
    : '–';
  if (last !== undefined && price != null) {
    const dir = price > last ? 'up' : price < last ? 'dn' : null;
    if (dir) {
      priceEl.style.color = dir === 'up' ? 'var(--green)' : 'var(--red)';
      ticker.classList.remove('lc-flash-up', 'lc-flash-dn');
      void ticker.offsetWidth;
      ticker.classList.add(dir === 'up' ? 'lc-flash-up' : 'lc-flash-dn');
      setTimeout(() => ticker.classList.remove('lc-flash-up', 'lc-flash-dn'), 700);
    }
  }
}

// ── NSE price via WebSocket (replaces yfinance poller) ───────────────────────
function _startChartWs(id, symbol) {
  const sym = symbol.replace('.NS','').replace('^','').toUpperCase();
  const handler = payload => {
    if (payload.ltp != null) _updateChartTicker(id, symbol, payload.ltp);
  };
  _chartWsHandlers.set(String(id), { sym, handler });
  PriceWsClient.onPrice(sym, handler);
  PriceWsClient.subscribe([sym]);
}
function _stopChartWs(id) {
  const entry = _chartWsHandlers.get(String(id));
  if (!entry) return;
  PriceWsClient.offPrice(entry.sym, entry.handler);
  PriceWsClient.unsubscribe([entry.sym]);
  _chartWsHandlers.delete(String(id));
}
function _startChartPoller(id, symbol, source, cb) {
  _stopChartPoller(id);
  const tick = () => {
    fetch(`/api/charts/quote?symbol=${encodeURIComponent(symbol)}&source=${source}`)
      .then(r => r.json())
      .then(data => { if (data.price != null) cb(data); })
      .catch(() => {});
  };
  tick();
  _chartPollers.set(String(id), setInterval(tick, 60000));
}
function _stopChartPoller(id) {
  const t = _chartPollers.get(String(id));
  if (t) { clearInterval(t); _chartPollers.delete(String(id)); }
}

// ── Hyperliquid WebSocket (one shared connection) ─────────────────────────────
function _hlConnect() {
  if (_hlWS && (_hlWS.readyState === WebSocket.OPEN || _hlWS.readyState === WebSocket.CONNECTING)) return;
  _hlWS = new WebSocket('wss://api.hyperliquid.xyz/ws');
  _hlWS.onopen = () => {
    const coins = new Set();
    _hlPaneMap.forEach(coin => coins.add(coin));
    coins.forEach(coin => _hlSendMsg({method:'subscribe', subscription:{type:'trades', coin}}));
  };
  _hlWS.onmessage = evt => {
    try {
      const msg = JSON.parse(evt.data);
      if (msg.channel === 'trades') {
        const trades = Array.isArray(msg.data) ? msg.data : [msg.data];
        trades.forEach(trade => {
          const price = parseFloat(trade.px);
          if (!isNaN(price) && _hlSubs.has(trade.coin)) {
            _hlSubs.get(trade.coin).forEach(cb => cb(price));
          }
        });
      }
    } catch(e) {}
  };
  _hlWS.onclose = () => {
    if (_hlSubs.size > 0) setTimeout(_hlConnect, 3000);
  };
}
function _hlSendMsg(msg) {
  if (_hlWS?.readyState === WebSocket.OPEN) _hlWS.send(JSON.stringify(msg));
}
function _subscribeHLPane(id, coin, cb) {
  _unsubscribeHLPane(id);
  _hlPaneMap.set(String(id), coin);
  if (!_hlSubs.has(coin)) _hlSubs.set(coin, new Map());
  _hlSubs.get(coin).set(String(id), cb);
  _hlConnect();
  _hlSendMsg({method:'subscribe', subscription:{type:'trades', coin}});
}
function _unsubscribeHLPane(id) {
  const coin = _hlPaneMap.get(String(id));
  if (!coin) return;
  _hlPaneMap.delete(String(id));
  const coinSubs = _hlSubs.get(coin);
  if (coinSubs) {
    coinSubs.delete(String(id));
    if (coinSubs.size === 0) {
      _hlSubs.delete(coin);
      _hlSendMsg({method:'unsubscribe', subscription:{type:'trades', coin}});
      if (_hlSubs.size === 0 && _hlWS) { _hlWS.close(); _hlWS = null; }
    }
  }
}

// ── Override pane 0 (called from openInCharts) ────────────────────────────────
function overrideChartPane(id, cfg) {
  const pane = _chartPanes.get(String(id));
  if (!pane) return;
  pane.cfg = {...cfg};
  _saveChartsState();

  const el = document.querySelector(`.lc-pane[data-pane-id="${id}"]`);
  if (el) {
    const srcSel = el.querySelector('.lc-src-sel');
    const symSel = el.querySelector('.lc-sym-sel');
    const tfSel  = el.querySelector('.lc-tf-sel');
    const symInp = el.querySelector('.lc-sym-inp');
    if (srcSel) srcSel.value = cfg.src;
    if (symSel) {
      const syms = CHART_SYMBOLS[cfg.src] || [];
      // If the symbol isn't in the preset list, add it at the top so it shows as selected
      const allSyms = syms.includes(cfg.symbol) ? syms : [cfg.symbol, ...syms];
      symSel.innerHTML = allSyms.map(s => `<option value="${s}" ${s===cfg.symbol?'selected':''}>${s}</option>`).join('');
    }
    if (tfSel) tfSel.value = cfg.tf;
    if (symInp) symInp.value = '';
  }
  _loadChartPane(id, cfg, pane.lwChart);
}

// ── Cross-module entry point ──────────────────────────────────────────────────
// Clicking a chart link (↗) opens Wavesight in a NEW TAB, deep-linked to the symbol.
function openInCharts(symbol, source) {
  const url = location.origin + '/?chart=' + encodeURIComponent(symbol) +
              (source ? '&src=' + encodeURIComponent(source) : '');
  window.open(url, '_blank', 'noopener');
}

// Same-tab open (used by the ?chart= deep-link handler in the freshly opened tab).
function _openChartSameTab(symbol, source) {
  if (!source) {
    const upper = symbol.toUpperCase().replace('.NS','');
    source = _HL_CRYPTO.has(upper) ? 'hyperliquid' : 'yfinance';
    if (source === 'yfinance' && !symbol.includes('.') && !symbol.startsWith('^')) {
      symbol = symbol + '.NS';
    }
    if (source === 'hyperliquid') symbol = upper;
  }
  const cfg = { symbol, tf: '1d', src: source };

  // Programmatically click the Charts tab so switchModule fires with a real event
  const chartTab = document.querySelectorAll('.mod-tab')[3];
  if (!_m4Loaded) {
    _chartPendingSymbol = cfg;
    chartTab.click();
  } else {
    chartTab.click();
    setTimeout(() => overrideChartPane(0, cfg), 80);
  }
}

// On load: if opened via ?chart=SYMBOL, jump straight to that chart in this tab.
(function _handleChartDeepLink() {
  try {
    const p = new URLSearchParams(location.search);
    const sym = p.get('chart');
    if (!sym) return;
    const go = () => _openChartSameTab(sym, p.get('src') || undefined);
    if (document.readyState === 'complete') setTimeout(go, 400);
    else window.addEventListener('load', () => setTimeout(go, 400));
  } catch (e) {}
})();

// ── Indicators ────────────────────────────────────────────────────────────────
const _EMA_CONFIGS = [
  { key:'ema10',  period:10,  color:'#06B6D4', label:'10 EMA'  },
  { key:'ema20',  period:20,  color:'#4ADE80', label:'20 EMA'  },
  { key:'ema50',  period:50,  color:'#F97316', label:'50 EMA'  },
  { key:'ema100', period:100, color:'#60A5FA', label:'100 EMA' },
  { key:'ema200', period:200, color:'#EC4899', label:'200 EMA' },
];
let _m4Indicators = (() => {
  try { const s = localStorage.getItem('gp_indicators'); return s ? JSON.parse(s) : null; } catch(e) { return null; }
})() || { ema10:false, ema20:true, ema50:true, ema100:false, ema200:true, volume:true, pocketPivots:true };

// _saveIndicators defined above near _saveChartsState

function _calcEMA(closes, period) {
  const result = new Array(closes.length).fill(null);
  if (closes.length < period) return result;
  let sum = 0;
  for (let i = 0; i < period; i++) sum += closes[i];
  const k = 2 / (period + 1);
  let ema = sum / period;
  result[period - 1] = ema;
  for (let i = period; i < closes.length; i++) {
    ema = closes[i] * k + ema * (1 - k);
    result[i] = ema;
  }
  return result;
}

// 50-period SMA of volume (returns null until enough bars)
function _calcVolSMA(volumes, period) {
  const result = new Array(volumes.length).fill(null);
  for (let i = period - 1; i < volumes.length; i++) {
    let s = 0;
    for (let j = i - period + 1; j <= i; j++) s += volumes[j];
    result[i] = s / period;
  }
  return result;
}

function _applyIndicators(id, candles) {
  const pane = _chartPanes.get(String(id));
  if (!pane) return;
  const { lwChart } = pane;

  // Remove existing indicator series
  Object.values(pane.emaSeries || {}).forEach(s => { try { lwChart.removeSeries(s); } catch(e) {} });
  if (pane.volSeries) { try { lwChart.removeSeries(pane.volSeries); } catch(e) {} }
  pane.emaSeries = {};
  pane.volSeries = null;

  if (!candles || candles.length < 2) return;
  const closes = candles.map(c => c.close);
  const times  = candles.map(c => c.time);

  // ── Simple Volume with Pocket Pivots (Finally Nitin) ──────────────────────
  const hasVol = _m4Indicators.volume;
  if (hasVol) {
    const volumes = candles.map(c => c.volume);
    const volMA   = _calcVolSMA(volumes, 50);   // 50-period SMA of volume
    const DRY_FRAC = _indicatorCfg.dry_frac;

    // is this candle an up day? (close > previous close)
    const isUp   = i => i === 0 ? candles[0].close >= candles[0].open
                                : candles[i].close >  candles[i-1].close;
    const isDown = i => i === 0 ? candles[0].close <  candles[0].open
                                : candles[i].close <= candles[i-1].close;

    // PPV: up day whose volume > highest down-day volume in last 10 TRADING days
    const ppvSet = new Set();
    if (_m4Indicators.pocketPivots) {
      for (let i = 1; i < candles.length; i++) {
        if (!isUp(i)) continue;
        let maxDownVol = 0, hasDown = false;
        const lookback = Math.max(0, i - (_indicatorCfg.ppv_lookback ?? 10));
        for (let j = lookback; j < i; j++) {
          if (isDown(j)) { hasDown = true; if (candles[j].volume > maxDownVol) maxDownVol = candles[j].volume; }
        }
        if (hasDown && candles[i].volume > maxDownVol) ppvSet.add(i);
      }
    }

    const vc = _indicatorCfg.volume_colors;
    const volData = candles.map((c, i) => {
      const vol = c.volume;
      const ma  = volMA[i];   // null for first 49 bars
      let color;
      if (ppvSet.has(i)) {
        color = vc.ppv;
      } else if (isDown(i) && ma !== null && vol > ma) {
        color = vc.down_heavy;
      } else if (isUp(i) && ma !== null && vol > ma) {
        color = vc.up_strong;
      } else if (ma !== null && vol < ma / DRY_FRAC) {
        color = vc.dry;
      } else {
        color = vc.noise ?? '#363A45';
      }
      return { time: c.time, value: vol, color };
    });

    const volSeries = lwChart.addHistogramSeries({ priceFormat:{type:'volume'}, priceScaleId:'' });
    volSeries.priceScale().applyOptions({ scaleMargins:{ top:0.8, bottom:0 } });
    volSeries.setData(volData);
    pane.volSeries = volSeries;
    lwChart.applyOptions({ rightPriceScale:{ scaleMargins:{ top:0.05, bottom:0.18 } } });
  } else {
    lwChart.applyOptions({ rightPriceScale:{ scaleMargins:{ top:0.05, bottom:0.02 } } });
  }

  // EMA lines
  _EMA_CONFIGS.forEach(cfg => {
    if (!_m4Indicators[cfg.key]) return;
    const emas = _calcEMA(closes, cfg.period);
    const data = times.map((t, i) => emas[i] != null ? { time:t, value:emas[i] } : null).filter(Boolean);
    if (!data.length) return;
    const series = lwChart.addLineSeries({
      color: cfg.color, lineWidth:1,
      priceLineVisible:false, lastValueVisible:false, crosshairMarkerVisible:false,
    });
    series.setData(data);
    pane.emaSeries[cfg.key] = series;
  });
}

function _toggleIndicator(key, val) {
  _m4Indicators[key] = val;
  _saveIndicators();
  _chartPanes.forEach((pane, id) => {
    if (pane._lastCandles) _applyIndicators(id, pane._lastCandles);
  });
}

function _toggleIndicatorsMenu() {
  _lcIndMenuOpen = !_lcIndMenuOpen;
  document.getElementById('lcIndMenu')?.classList.toggle('hidden', !_lcIndMenuOpen);
}

