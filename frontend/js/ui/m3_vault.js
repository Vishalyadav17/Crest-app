// ── Module 3: Scan Vault + AI drawer ──────────────────────────────────────────

async function openAiDrawer(pickId, sym) {
  const drawer = document.getElementById('m3VaultAiDrawer');
  const backdrop = document.getElementById('m3VaultAiBackdrop');
  if (!drawer) return;
  const body = drawer.querySelector('.m3-ai-drawer-body');
  drawer.querySelector('.m3-ai-drawer-sym').textContent = sym || '';
  body.innerHTML = `<div style="color:var(--muted);font-size:13px;padding:24px 0;text-align:center">Loading…</div>`;
  backdrop.classList.add('open');
  drawer.classList.add('open');
  const rows = await api('/api/swing/vault/' + pickId + '/analysis').catch(() => null);
  if (!rows || !rows.length) {
    body.innerHTML = `<div style="color:var(--muted);font-size:13px;padding:24px 0;text-align:center">No AI analysis for this pick yet.</div>`;
    return;
  }
  body.innerHTML = rows.map(r => {
    const vc = ['pass','hold','exit_good'].includes(r.verdict_class) ? 'good'
             : ['caution','weak'].includes(r.verdict_class) ? 'warn' : 'bad';
    const rf = Array.isArray(r.risk_flags) ? r.risk_flags : (r.risk_flags ? Object.values(r.risk_flags) : []);
    const flags = rf.map(f => `<li>${f}</li>`).join('');
    return `
      <div class="m3-ai-drawer-block">
        <div class="m3-ai-drawer-kind">${r.kind === 'failure' ? 'Failure Analysis' : 'Setup Validation'}</div>
        ${r.verdict_short ? `<div class="m3-ai-verdict ${vc} lg"><span class="material-symbols-outlined">psychology</span>${r.verdict_short}</div>` : ''}
        ${r.thesis ? `<div class="m3-ai-drawer-thesis">${typeof _wlMarkdown==='function' ? _wlMarkdown(r.thesis) : r.thesis}</div>` : ''}
        ${r.failure_reason ? `<div class="m3-ai-drawer-fail"><b>Why it failed:</b> ${typeof _wlMarkdown==='function' ? _wlMarkdown(r.failure_reason) : r.failure_reason}</div>` : ''}
        ${flags ? `<div class="m3-ai-drawer-flags-h">Risk flags</div><ul class="m3-ai-drawer-flags">${flags}</ul>` : ''}
        <div class="m3-ai-drawer-meta">${r.provider || ''}${r.model_used ? ' · ' + r.model_used : ''}</div>
      </div>`;
  }).join('');
}

function closeAiDrawer() {
  document.getElementById('m3VaultAiDrawer')?.classList.remove('open');
  document.getElementById('m3VaultAiBackdrop')?.classList.remove('open');
}

function _renderVaultFolders(weeks) {
  const grid = document.getElementById('m3VaultGrid');
  if (!weeks.length) {
    grid.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:12px">No scans for this period.</div>';
    return;
  }
  const show = weeks.slice(0, 5);
  grid.innerHTML = show.map((w) => {
    const isLatest = _vaultWeeks.length && w === _vaultWeeks[0];
    const range    = w.scanned_at ? _scanMonthLabel(w.scanned_at) : (w.key || `Run #${w.id}`);
    const runRef   = w.id || w.key;
    const sigColor = (w.signal || '').toLowerCase() === 'bullish' ? 'var(--green)' : (w.signal || '').toLowerCase() === 'caution' ? 'var(--red)' : 'var(--gold)';
    const isSelected = _vaultCurrentKey == runRef;
    const outcomeHtml = (w.wins || w.losses)
      ? `<div class="m3-vault-outcome-row">${w.wins ? `<span class="m3-vault-win-pill">${w.wins}W</span>` : ''}${w.losses ? `<span class="m3-vault-loss-pill">${w.losses}L</span>` : ''}</div>` : '';
    return `<div class="m3-vault-card${isLatest ? ' active-week' : ''}${isSelected ? ' selected' : ''}" data-label="${range}" data-key="${runRef}" onclick="openVaultDetail(${JSON.stringify(runRef)}, '${range}', this)">
      <div class="m3-vault-card-top">
        <span class="material-symbols-outlined" style="font-size:18px;color:var(--muted)">folder_open</span>
        ${isLatest ? '<div class="m3-vault-active-dot"></div>' : `<span style="font-size:9px;font-weight:700;color:${sigColor};font-family:var(--font-display)">${w.signal || 'NEUTRAL'}</span>`}
      </div>
      <div class="m3-vault-date">${range}</div>
      <div class="m3-vault-qualifiers">${w.picks_count || 0} picks</div>
      ${outcomeHtml}
    </div>`;
  }).join('');
}

function _renderCompactSectorDist(sectorDist) {
  const colors = ['#10B981','#F59E0B','#b1c5ff','#9050e8','#22d3ee'];
  const el = document.getElementById('m3VaultSectorPills');
  if (!el) return;
  if (!sectorDist?.length) { el.innerHTML = '<span style="color:var(--muted);font-size:11px">–</span>'; return; }
  el.innerHTML = sectorDist.map((e,i) =>
    `<span class="m3-vsc-pill" style="color:${colors[i%colors.length]};border-color:${colors[i%colors.length]}30">${e.sector} ${e.pct}%</span>`
  ).join('');
}
