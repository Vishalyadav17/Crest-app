// ── Module 3: Weekend Lab (Research Workbench) ───────────────────────────────
// Lazy-loaded when user clicks the "Weekend Lab" tab.

let _wlData = null;
let _wlLoading = false;
let _wlRunId = null;          // selected week folder (null = latest)
let _wlChatPick = null;
let _wlChatHistory = [];

// ── Entry point ───────────────────────────────────────────────────────────────
async function loadWeekendLab(runId) {
  if (_wlLoading) return;
  _wlLoading = true;
  if (runId !== undefined && runId !== null && runId !== '') _wlRunId = runId;
  const root = document.getElementById('wl-root');
  if (!root) { _wlLoading = false; return; }

  root.innerHTML = '<div class="wl-spinner">Loading…</div>';
  try {
    const url = '/api/research/workbench' + (_wlRunId ? '?run_id=' + encodeURIComponent(_wlRunId) : '');
    const d = await fetch(url).then(r => r.json());
    _wlData = d;
    _wlRender(d);
  } catch (e) {
    root.innerHTML = `<div class="m3-empty-state" style="margin-top:40px">
      <span class="material-symbols-outlined" style="font-size:40px;color:var(--err)">error</span>
      <p style="color:var(--err);margin-top:8px">Failed to load Weekend Lab</p></div>`;
  }
  _wlLoading = false;
}

// ── Helpers ─────────────────────────────────────────────────────────────────
let _wlSelected = null;
const _wlEsc = s => String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

// Minimal, XSS-safe markdown → HTML for LLM chat/analysis output. Escapes first, then applies
// inline (bold/italic/code/links) + block (headers/lists/tables/paragraphs) transforms.
function _wlMarkdown(src) {
  if (src == null) return '';
  const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const inline = s => esc(s)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*(?!\s)([^*]+?)\*(?!\*)/g, '$1<em>$2</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  const lines = String(src).replace(/\r/g, '').split('\n');
  const cells = r => r.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map(c => c.trim());
  let html = '', i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1])) {
      const head = cells(line); i += 2; let body = '';
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        body += '<tr>' + cells(lines[i]).map(c => `<td>${inline(c)}</td>`).join('') + '</tr>'; i++;
      }
      html += `<table class="wl-md-tbl"><thead><tr>${head.map(c => `<th>${inline(c)}</th>`).join('')}</tr></thead><tbody>${body}</tbody></table>`;
      continue;
    }
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) { const lvl = Math.min(h[1].length + 2, 6); html += `<h${lvl} class="wl-md-h">${inline(h[2])}</h${lvl}>`; i++; continue; }
    if (/^\s*[-*]\s+/.test(line)) {
      let items = '';
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) { items += `<li>${inline(lines[i].replace(/^\s*[-*]\s+/, ''))}</li>`; i++; }
      html += `<ul class="wl-md-ul">${items}</ul>`; continue;
    }
    if (/^\s*$/.test(line)) { i++; continue; }
    const para = [];
    while (i < lines.length && !/^\s*$/.test(lines[i]) && !/^#{1,6}\s/.test(lines[i]) && !/^\s*[-*]\s+/.test(lines[i]) && !/^\s*\|.*\|\s*$/.test(lines[i])) { para.push(lines[i]); i++; }
    html += `<p>${para.map(inline).join('<br>')}</p>`;
  }
  return html;
}
function _wlFolderLabel(f) {
  const r = (typeof _scanMonthLabel === 'function' && f.scanned_at)
    ? _scanMonthLabel(f.scanned_at)
    : (f.scanned_at ? String(f.scanned_at).slice(0, 10) : 'Run #' + f.id);
  return `${r} · ${f.picks_count || 0} picks`;
}
function _wlGrade(g) {
  const s = String(g || '').trim();
  if (!s) return '';
  let cls = 'g-b', label = s.toUpperCase();
  if (/high|strong|^a$/i.test(s)) { cls = 'g-a'; label = 'HIGH'; }
  else if (/qualif|^b$/i.test(s)) { cls = 'g-b'; label = 'QUAL'; }
  else if (/^c$/i.test(s)) { cls = 'g-c'; }
  else if (/^d$|avoid|weak/i.test(s)) { cls = 'g-d'; }
  else if (s.length > 5) { label = s.split(' ')[0].slice(0, 5).toUpperCase(); }
  return `<span class="wl-grade ${cls}">${_wlEsc(label)}</span>`;
}
const _wlVcOf = deep => {
  if (deep?.verdict_class) return deep.verdict_class;
  const c = deep?.conviction || 0;
  return c >= 7 ? 'strong' : c >= 5 ? 'ok' : c >= 3 ? 'weak' : 'avoid';
};

// ── Render ────────────────────────────────────────────────────────────────────
function _wlRender(d) {
  const root = document.getElementById('wl-root');
  if (!root) return;

  const hasLlm = d.user_has_llm;
  const run = d.run;
  const picks = d.picks || [];
  const review = d.weekend_review;
  const retro = d.retro;

  const analyzed = picks.filter(p => p.deep).length;
  const total = picks.length;

  // Last time "Analyze all" actually ran — newest deep-analysis timestamp across picks.
  const _lastDeep = picks.map(p => p.deep && p.deep.generated_at).filter(Boolean).sort().pop();
  const _lastAnalysed = _lastDeep ? new Date(_lastDeep).toLocaleString('en-IN',
    { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : null;

  if (!run || !picks.length) {
    root.innerHTML = `<div class="wl-page"><div class="wl-empty">
      <span class="material-symbols-outlined">manage_search</span>
      <h4 style="margin:0;color:var(--text);font-size:15px">No basket yet</h4>
      <p style="margin:0;font-size:12.5px">Run a scan in the Scanner tab — this week's picks will appear here for deep analysis.</p>
    </div></div>`;
    return;
  }

  // keep a valid selection (default first analyzed, else first)
  if (!_wlSelected || !picks.some(p => p.id === _wlSelected)) {
    _wlSelected = (picks.find(p => p.deep) || picks[0]).id;
  }

  const stance = (review?.themes?.market_stance || '').toLowerCase();
  const stanceCls = stance.includes('off') ? 'is-off' : stance.includes('neutral') ? 'is-neutral' : '';
  const stanceIcon = stanceCls === 'is-off' ? 'trending_down' : stanceCls === 'is-neutral' ? 'trending_flat' : 'trending_up';
  const stanceHtml = stance ? `
    <div class="wl-stance ${stanceCls}">
      <span class="wl-stance-k">Market stance</span>
      <span class="wl-stance-v"><span class="material-symbols-outlined">${stanceIcon}</span>${_wlEsc(stance)}</span>
      ${review?.summary ? `<span class="wl-hint">via ${_wlEsc(review.model_used || 'LLM')}</span>` : ''}
    </div>` : '';

  const now = new Date();
  const isWeekday = now.getDay() >= 1 && now.getDay() <= 5;

  const curRunId = (run && run.id) || _wlRunId;
  const foldersHtml = (d.folders && d.folders.length)
    ? `<select class="wl-folder-sel" title="Switch week folder" onchange="loadWeekendLab(this.value)">
        ${d.folders.map(f => `<option value="${f.id}" ${f.id == curRunId ? 'selected' : ''}>${_wlFolderLabel(f)}</option>`).join('')}
      </select>` : '';

  const header = `
    <div class="wl-head">
      <div class="wl-head-l">
        <h1 class="wl-title"><span class="material-symbols-outlined">science</span>Weekend Lab</h1>
        <p class="wl-meta"><b class="wl-num">${total}</b> picks · <b class="wl-num">${analyzed}</b> analyzed${isWeekday ? ' · best run on weekends' : ''}</p>
      </div>
      <div class="wl-head-r">
        ${foldersHtml}
        ${!hasLlm ? `<span class="wl-hint">Add a model key in <a href="#" onclick="switchModule('m6');return false" style="color:var(--blue)">Settings → Model</a> to analyze</span>` : `
        <button class="wl-btn wl-btn-primary ${analyzed >= total ? 'is-disabled' : ''}" id="wlBtnAnalyzeAll"
          onclick="${analyzed >= total ? 'return false' : '_wlAnalyzeAll()'}"
          ${analyzed >= total && _lastAnalysed ? `title="Last analysed: ${_lastAnalysed}"` : (analyzed >= total ? 'title="All picks analysed"' : '')}>
          <span class="material-symbols-outlined">bolt</span>Analyze all<span class="wl-num" id="wlAnalyzeProgress" style="display:none"></span>
        </button>
        <button class="wl-btn" onclick="_wlWeekendReview(${run.id})" ${analyzed < 3 ? 'disabled title="Analyze at least 3 picks first"' : ''}>
          <span class="material-symbols-outlined">summarize</span>Weekend review
        </button>`}
      </div>
    </div>`;

  const rail = `
    <aside class="wl-rail">
      <div class="wl-rail-h"><span>This week's basket</span><span class="wl-num">${total}</span></div>
      <div class="wl-rail-list">${picks.map(p => _wlRailRow(p, hasLlm)).join('')}</div>
    </aside>`;

  const body = `<section class="wl-body">${rail}<div id="wlDetailPane">${_wlDetailHtml(picks.find(p => p.id === _wlSelected))}</div></section>`;

  const reviewHtml = review ? _wlReviewHtml(review, retro) : '';

  // Weekend Review card sits directly below Market stance (per design), above the basket body.
  root.innerHTML = `<div class="wl-page" id="wlPage">${header}${stanceHtml}${reviewHtml}${body}</div>${_wlDrawerHtml()}`;
}

function _wlRailRow(p, hasLlm) {
  const deep = p.deep;
  const sel = p.id === _wlSelected ? ' is-sel' : '';
  let bot;
  if (deep) {
    const vc = _wlVcOf(deep);
    const conv = deep.conviction || 0;
    bot = `<div class="wl-pick-bot">
      <span class="wl-conv-pill v-${vc}">${_wlEsc(vc)} · ${conv}</span>
      <span class="wl-bar"><i class="bar-${vc}" style="width:${conv*10}%"></i></span>
    </div>`;
  } else if (hasLlm) {
    bot = `<button class="wl-ghost" onclick="event.stopPropagation();_wlAnalyzePick(${p.id})" data-pick="${p.id}"><span class="material-symbols-outlined">bolt</span>Analyze</button>`;
  } else {
    bot = `<div class="wl-pick-na">not analyzed</div>`;
  }
  return `<div class="wl-pick${sel}" onclick="_wlSelect(${p.id})">
    <div class="wl-pick-top"><span class="wl-tk">${_wlEsc(p.symbol)}</span>${_wlGrade(p.grade)}</div>
    <span class="wl-sector">${_wlEsc(p.sector || '')}</span>
    ${bot}
  </div>`;
}

function _wlDetailHtml(p) {
  if (!p) return '';
  const deep = p.deep;
  if (!deep) {
    return `<article class="wl-detail"><div class="wl-empty">
      <span class="material-symbols-outlined">neurology</span>
      <h4 style="margin:0;color:var(--text);font-size:15px">${_wlEsc(p.symbol)} not analyzed yet</h4>
      <p style="margin:0;font-size:12.5px">Run a deep dive to get an AI thesis, entry/exit plan and risk flags for this pick.</p>
      <button class="wl-btn wl-btn-primary" style="margin-top:8px" onclick="_wlAnalyzePick(${p.id})"><span class="material-symbols-outlined">bolt</span>Analyze ${_wlEsc(p.symbol)}</button>
    </div></article>`;
  }
  const vc = _wlVcOf(deep);
  const conv = deep.conviction || 0;
  const det = deep.detail || {};
  const flags = (deep.risk_flags || det.risk_flags || []).map(f => {
    const amber = /earn|iv|volat|crowd|extend/i.test(f);
    return `<span class="wl-flag ${amber ? 'flag-amber' : 'flag-red'}"><span class="material-symbols-outlined">${amber ? 'error' : 'priority_high'}</span>${_wlEsc(f)}</span>`;
  }).join('');
  const watch = (det.watch_items || []).map(w =>
    `<span class="wl-chip"><span class="material-symbols-outlined">check_circle</span>${_wlEsc(w)}</span>`).join('');
  return `<article class="wl-detail">
    <div class="wl-d-head">
      <div class="wl-d-id">
        <div class="wl-d-sym">${_wlEsc(p.symbol)}${_wlGrade(p.grade)}</div>
        <div class="wl-d-sub">${_wlEsc(p.sector || '')}${deep.verdict_short ? ` <span class="wl-dot"></span> ${_wlEsc(deep.verdict_short)}` : ''}</div>
      </div>
      <div class="wl-d-conv">
        <div class="wl-d-conv-top">
          <span class="wl-d-conv-lbl">Conviction</span>
          <span class="wl-d-score" style="color:var(--${vc==='strong'?'green':vc==='ok'?'blue':vc==='weak'?'amber':'red'})">${conv}<small>/10</small></span>
          <span class="wl-conv-pill v-${vc}">${_wlEsc(vc)}</span>
        </div>
        <div class="wl-d-bar"><i style="width:${conv*10}%;background:var(--${vc==='strong'?'green':vc==='ok'?'blue':vc==='weak'?'amber':'red'})"></i></div>
      </div>
    </div>
    ${deep.thesis ? `<div class="wl-sec"><div class="wl-sec-k"><span class="material-symbols-outlined">target</span>Thesis</div><p class="wl-thesis">${_wlEsc(deep.thesis)}</p></div>` : ''}
    ${(det.entry_plan || det.exit_plan) ? `<div class="wl-sec"><div class="wl-plan-grid">
      <div class="wl-plan is-entry"><div class="wl-plan-h"><span class="material-symbols-outlined">login</span>Entry plan</div><p>${_wlEsc(det.entry_plan || '—')}</p></div>
      <div class="wl-plan is-exit"><div class="wl-plan-h"><span class="material-symbols-outlined">logout</span>Exit plan</div><p>${_wlEsc(det.exit_plan || '—')}</p></div>
    </div></div>` : ''}
    ${watch ? `<div class="wl-sec"><div class="wl-sec-k"><span class="material-symbols-outlined">checklist</span>Watch items</div><div class="wl-chips">${watch}</div></div>` : ''}
    ${flags ? `<div class="wl-sec"><div class="wl-sec-k"><span class="material-symbols-outlined">warning</span>Risk flags</div><div class="wl-chips">${flags}</div></div>` : ''}
    ${(det.hold_horizon_days || det.sector_view) ? `<div class="wl-meta-grid">
      ${det.hold_horizon_days ? `<div class="wl-mcard"><div class="wl-sec-k"><span class="material-symbols-outlined">schedule</span>Hold horizon</div><div class="wl-mcard-v"><span class="wl-num">${det.hold_horizon_days}</span> days</div></div>` : ''}
      ${det.sector_view ? `<div class="wl-mcard"><div class="wl-sec-k"><span class="material-symbols-outlined">insights</span>Sector view</div><div class="wl-mcard-sub" style="margin-top:0">${_wlEsc(det.sector_view)}</div></div>` : ''}
    </div>` : ''}
    <div class="wl-d-foot"><span class="material-symbols-outlined">smart_toy</span>Generated via <b>${_wlEsc(deep.model_used || 'LLM')}${deep.provider ? ' · ' + _wlEsc(deep.provider) : ''}</b>
      <button class="wl-btn" style="margin-left:auto;height:28px" onclick="_wlOpenChat(${p.id},'${_wlEsc(p.symbol)}')"><span class="material-symbols-outlined">forum</span>Ask AI</button>
    </div>
  </article>`;
}

function _wlReviewHtml(review, retro) {
  const t = review.themes || {};
  const ranked = (t.ranked_syms || []).map(s => `<span class="wl-symtag sym-rank">${_wlEsc(s)}</span>`).join('');
  const skip = (t.skip_syms || []).map(s => `<span class="wl-symtag sym-skip">${_wlEsc(s)}</span>`).join('');
  const lessons = (t.lessons || []).map(l => `<li><span class="material-symbols-outlined">lightbulb</span>${_wlEsc(l)}</li>`).join('');
  const checklist = (t.next_week_checklist || []).map(c => `<li><span class="material-symbols-outlined">task_alt</span>${_wlEsc(c)}</li>`).join('');
  const retroCards = (retro?.picks || []).map(r => {
    const hit = /target/i.test(r.scan_result || '');
    const sl = /sl|stop/i.test(r.scan_result || '');
    const out = hit ? `<span class="wl-out out-hit"><span class="material-symbols-outlined">check</span>Target hit</span>`
      : sl ? `<span class="wl-out out-sl"><span class="material-symbols-outlined">close</span>Stop hit</span>`
      : `<span class="wl-conv-pill v-${r.verdict_class||'weak'}">${_wlEsc(r.verdict_short || r.verdict_class || '—')}</span>`;
    return `<div class="wl-retro-card"><div class="wl-retro-top"><span class="wl-tk">${_wlEsc(r.symbol)}</span>${out}</div>
      <div class="wl-retro-lesson">${_wlEsc(r.thesis || '')}</div></div>`;
  }).join('');
  return `<section class="wl-review">
    <div class="wl-review-h"><div class="wl-title2"><span class="material-symbols-outlined">summarize</span>Weekend Review</div>
      <span class="wl-stamp">via ${_wlEsc(review.model_used || 'LLM')}</span></div>
    <div class="wl-review-grid">
      <div><div class="wl-col-k">Summary</div><p class="wl-summary">${_wlEsc(review.summary || '')}</p>
        ${ranked ? `<div class="wl-rank"><span class="wl-rank-lbl">Ranked</span>${ranked}</div>` : ''}
        ${skip ? `<div class="wl-rank"><span class="wl-rank-lbl">Skip</span>${skip}</div>` : ''}
      </div>
      ${lessons ? `<div><div class="wl-col-k">Lessons</div><ul class="wl-list is-lessons">${lessons}</ul></div>` : '<div></div>'}
      ${checklist ? `<div><div class="wl-col-k">Next week checklist</div><ul class="wl-list is-check">${checklist}</ul></div>` : '<div></div>'}
    </div>
    ${retroCards ? `<div class="wl-retro"><div class="wl-retro-h"><span class="material-symbols-outlined">history</span>Last Week Retro
      <small>${retro?.scanned_at ? '· ' + retro.scanned_at.slice(0,10) : ''}</small></div>
      <div class="wl-retro-strip">${retroCards}</div></div>` : ''}
  </section>`;
}

function _wlDrawerHtml() {
  return `<aside class="wl-drawer" id="wlChatPanel">
    <div class="wl-dr-h">
      <div class="wl-dr-h-l"><b><span class="material-symbols-outlined">forum</span><span id="wlChatTitle">Ask AI</span></b><span id="wlChatSub"></span></div>
      <button class="wl-dr-x" onclick="_wlCloseChat()"><span class="material-symbols-outlined">close</span></button>
    </div>
    <div class="wl-dr-body" id="wlChatMessages"></div>
    <div class="wl-dr-foot"><div class="wl-input">
      <input id="wlChatInput" placeholder="Ask about this pick…" onkeydown="if(event.key==='Enter')_wlSendChat()">
      <button class="wl-send" onclick="_wlSendChat()"><span class="material-symbols-outlined">arrow_upward</span></button>
    </div></div>
  </aside>`;
}

function _wlSelect(pickId) {
  _wlSelected = pickId;
  const p = (_wlData?.picks || []).find(x => x.id === pickId);
  document.querySelectorAll('.wl-pick').forEach(el => el.classList.remove('is-sel'));
  event?.currentTarget?.classList?.add('is-sel');
  const pane = document.getElementById('wlDetailPane');
  if (pane && p) pane.innerHTML = _wlDetailHtml(p);
}

// ── Analyze single pick ───────────────────────────────────────────────────────
async function _wlAnalyzePick(pickId) {
  const btn = document.querySelector(`[data-pick="${pickId}"]`);
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="material-symbols-outlined rotating" style="font-size:13px">autorenew</span>'; }

  try {
    const r = await fetch(`/api/research/deep-dive/${pickId}`, {method:'POST'});
    if (!r.ok) {
      const err = await r.json().catch(()=>({}));
      _wlToast(err.detail || 'Analysis failed', true);
      return;
    }
    const result = await r.json();
    // Reload to reflect new analysis
    _wlLoading = false;
    await loadWeekendLab();
  } catch(e) {
    _wlToast('Network error', true);
  } finally {
    if (btn) { btn.disabled = false; }
  }
}

// ── Analyze all (sequential) ─────────────────────────────────────────────────
async function _wlAnalyzeAll() {
  const btn = document.getElementById('wlBtnAnalyzeAll');
  const prog = document.getElementById('wlAnalyzeProgress');
  if (btn) btn.disabled = true;
  if (prog) prog.style.display = '';

  const picks = (_wlData?.picks || []).filter(p => !p.deep);
  for (let i = 0; i < picks.length; i++) {
    if (prog) prog.textContent = `${i+1}/${picks.length}`;
    await _wlAnalyzePickSilent(picks[i].id);
    await new Promise(r => setTimeout(r, 1200)); // ~1.2s cadence
  }

  _wlLoading = false;
  await loadWeekendLab();
}

async function _wlAnalyzePickSilent(pickId) {
  try {
    await fetch(`/api/research/deep-dive/${pickId}`, {method:'POST'});
  } catch(e) { /* silent */ }
}

// ── Weekend review ────────────────────────────────────────────────────────────
async function _wlWeekendReview(runId) {
  if (!runId) return;
  _wlToast('Generating weekend review…');
  try {
    const r = await fetch(`/api/research/weekend-review/${runId}`, {method:'POST'});
    if (!r.ok) {
      const err = await r.json().catch(()=>({}));
      _wlToast(err.detail || 'Review failed', true);
      return;
    }
    _wlLoading = false;
    await loadWeekendLab();
  } catch(e) {
    _wlToast('Network error', true);
  }
}

// ── Chat ──────────────────────────────────────────────────────────────────────
function _wlOpenChat(pickId, sym) {
  _wlChatPick = pickId;
  _wlChatHistory = [];
  const panel = document.getElementById('wlChatPanel');
  const title = document.getElementById('wlChatTitle');
  const sub = document.getElementById('wlChatSub');
  const msgs = document.getElementById('wlChatMessages');
  if (!panel) return;
  const p = (_wlData?.picks || []).find(x => x.id === pickId);
  if (title) title.textContent = `Ask about ${sym}`;
  if (sub) sub.textContent = p?.deep ? `${p.sector || ''} · conviction ${p.deep.conviction || '—'}/10` : (p?.sector || '');
  if (msgs) msgs.innerHTML = `<div class="wl-msg is-ai"><div class="wl-bubble">Ask me about ${_wlEsc(sym)} — the thesis, entry/exit levels, or risk flags.</div></div>`;
  panel.classList.add('is-open');
  document.getElementById('wlPage')?.classList.add('wl-drawer-open');
  document.getElementById('wlChatInput')?.focus();
}

function _wlCloseChat() {
  document.getElementById('wlChatPanel')?.classList.remove('is-open');
  document.getElementById('wlPage')?.classList.remove('wl-drawer-open');
  _wlChatPick = null;
  _wlChatHistory = [];
}

async function _wlSendChat() {
  const inp = document.getElementById('wlChatInput');
  const msgs = document.getElementById('wlChatMessages');
  if (!inp || !msgs) return;
  const text = inp.value.trim();
  if (!text) return;
  inp.value = '';

  _wlChatHistory.push({role:'user', content:text});
  _wlAppendChatMsg('user', text, msgs);

  const wrap = document.createElement('div');
  wrap.className = 'wl-msg is-ai';
  wrap.innerHTML = '<div class="wl-bubble">…</div>';
  msgs.appendChild(wrap);
  msgs.scrollTop = msgs.scrollHeight;
  const bubble = wrap.querySelector('.wl-bubble');

  try {
    const r = await fetch('/api/research/chat', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({pick_id: _wlChatPick, messages: _wlChatHistory.slice(-6)}),
    });
    if (!r.ok) {
      const err = await r.json().catch(()=>({}));
      bubble.textContent = err.detail || 'Error';
      return;
    }
    const data = await r.json();
    _wlChatHistory.push({role:'assistant', content: data.text});
    bubble.innerHTML = _wlMarkdown(data.text);
    if (data.model_used) {
      const attr = document.createElement('div');
      attr.className = 'wl-attr';
      attr.innerHTML = `<span class="material-symbols-outlined">smart_toy</span>${_wlEsc(data.model_used)}`;
      wrap.appendChild(attr);
    }
    msgs.scrollTop = msgs.scrollHeight;
  } catch(e) {
    bubble.textContent = 'Network error';
  }
}

function _wlAppendChatMsg(role, text, container) {
  const div = document.createElement('div');
  div.className = `wl-msg ${role === 'user' ? 'is-user' : 'is-ai'}`;
  const b = document.createElement('div');
  b.className = 'wl-bubble';
  b.textContent = text;
  div.appendChild(b);
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

// ── Toast ─────────────────────────────────────────────────────────────────────
function _wlToast(msg, isErr = false) {
  const t = document.createElement('div');
  t.style.cssText = `position:fixed;bottom:24px;right:24px;padding:10px 18px;border-radius:8px;
    background:${isErr?'var(--err)':'var(--green)'};color:#fff;font-size:13px;z-index:9999;
    box-shadow:0 4px 12px rgba(0,0,0,.3);`;
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3000);
}
