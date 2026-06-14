/**
 * PriceWsClient — WebSocket client for /ws/prices
 *
 * Protocol:
 *   subscribe(symbols)    → subscribe to a list of symbol strings (no .NS suffix)
 *   unsubscribe(symbols)  → remove symbols from subscription
 *   onPrice(sym, handler) → register a callback fired on each price update for sym
 *   offPrice(sym, handler)→ remove callback
 *
 * Automatically reconnects on disconnect.
 * Pauses/resumes with document visibility.
 */
const PriceWsClient = (() => {
  let _ws = null;
  let _subs = new Set();           // currently subscribed symbols
  let _handlers = new Map();       // sym → Set<fn>
  let _paused = false;
  let _reconnectTimer = null;

  function _wsUrl() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    return `${proto}://${location.host}/ws/prices`;
  }

  function _connect() {
    if (_ws && (_ws.readyState === WebSocket.OPEN || _ws.readyState === WebSocket.CONNECTING)) return;
    if (_paused) return;
    _ws = new WebSocket(_wsUrl());

    _ws.onopen = () => {
      if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
      if (_subs.size > 0) {
        _ws.send(JSON.stringify({ action: 'subscribe', symbols: [..._subs] }));
      }
    };

    _ws.onmessage = evt => {
      try {
        const msg = JSON.parse(evt.data);
        if (msg.type === 'prices' || msg.type === 'snapshot') {
          const data = msg.data || {};
          for (const [sym, payload] of Object.entries(data)) {
            const fns = _handlers.get(sym);
            if (fns) fns.forEach(fn => fn(payload));
          }
        }
      } catch (_) {}
    };

    _ws.onclose = () => {
      if (!_paused && _subs.size > 0) {
        _reconnectTimer = setTimeout(_connect, 3000);
      }
    };

    _ws.onerror = () => _ws.close();
  }

  function _send(msg) {
    if (_ws?.readyState === WebSocket.OPEN) {
      _ws.send(JSON.stringify(msg));
    }
  }

  function subscribe(symbols) {
    const newSyms = symbols.filter(s => !_subs.has(s));
    newSyms.forEach(s => _subs.add(s));
    if (newSyms.length === 0) return;
    _connect();
    _send({ action: 'subscribe', symbols: newSyms });
  }

  function unsubscribe(symbols) {
    symbols.forEach(s => _subs.delete(s));
    _send({ action: 'unsubscribe', symbols });
    if (_subs.size === 0 && _ws) {
      _ws.close();
      _ws = null;
    }
  }

  function onPrice(sym, fn) {
    if (!_handlers.has(sym)) _handlers.set(sym, new Set());
    _handlers.get(sym).add(fn);
  }

  function offPrice(sym, fn) {
    _handlers.get(sym)?.delete(fn);
  }

  function pause() {
    _paused = true;
    if (_ws) { _ws.close(); _ws = null; }
    if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
  }

  function resume() {
    _paused = false;
    if (_subs.size > 0) _connect();
  }

  function close() {
    _subs.clear();
    _handlers.clear();
    pause();
  }

  // Visibility-aware pausing
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) pause();
    else resume();
  });

  return { subscribe, unsubscribe, onPrice, offPrice, pause, resume, close };
})();

window.PriceWsClient = PriceWsClient;
