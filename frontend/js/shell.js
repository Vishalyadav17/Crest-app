// ── Shell: module/sub switching, privacy, SW registration, account menu ──────

let _privacy = state.privacy;
if (_privacy) document.body.classList.add('privacy');

function switchModule(id) {
  document.querySelectorAll('.module-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.mod-tab').forEach(t => t.classList.remove('active'));
  document.getElementById('mod-' + id).classList.add('active');
  const tab = document.querySelector('.mod-tab[data-mod="' + id + '"]');
  if (tab) tab.classList.add('active');
  if (id === 'm2') loadMarketMonitor();
  if (id === 'm3') loadSwingDetector();
  if (id === 'm4' && !_m4Loaded) initCharts();
  if (id === 'm6') loadSettings();
}
function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const page = document.getElementById('page-content');
  const hidden = sidebar.classList.toggle('sidebar-hidden');
  page.classList.toggle('full-width', hidden);
}
function switchSub(name) {
  if (!document.getElementById('mod-m1').classList.contains('active')) switchModule('m1');
  document.querySelectorAll('.sub-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.sidebar-link').forEach(t => t.classList.remove('active'));
  document.getElementById('sub-' + name).classList.add('active');
  const link = document.querySelector('.sidebar-link[data-sub="' + name + '"]');
  if (link) link.classList.add('active');
  if (name === 'allocation' && !_allocLoaded) loadAllocation();
  if (name === 'mf'         && !_mfLoaded) loadMF();
  if (name === 'equity') loadIndianEquity();
  if (name === 'global'  && !_globalLoaded) loadGlobalHoldings();
  if (name === 'crypto'  && !_cryptoLoaded) loadCryptoHoldings();
}
function togglePrivacy() {
  _privacy = !_privacy;
  localStorage.setItem('privacy', _privacy ? '1' : '0');
  document.body.classList.toggle('privacy', _privacy);
  const btn = document.getElementById('privacyBtn');
  btn.innerHTML = _privacy
    ? '<span class="material-symbols-outlined" style="font-size:18px">visibility_off</span>'
    : '<span class="material-symbols-outlined" style="font-size:18px">visibility</span>';
  fetch('/api/user/preferences', {
    method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({key: 'privacy_mode', value: _privacy ? '1' : '0'})
  }).catch(() => {});
}
if (_privacy) {
  document.getElementById('privacyBtn').innerHTML = '<span class="material-symbols-outlined" style="font-size:18px">visibility_off</span>';
}

// ── Init ──────────────────────────────────────────────────────────────────────
(async () => {
  if ('serviceWorker' in navigator) {
    const ver = document.querySelector('meta[name="asset-version"]')?.content || '2';
    navigator.serviceWorker.register('/sw.js?v=' + ver).catch(() => {});
  }
  await Promise.all([loadQuote(), loadOverview()]);
  loadAlpha('N50');
})();

// ── Account menu + logout ─────────────────────────────────────────────────────
const _accountMenu = document.getElementById('accountMenu');
const _accountTrigger = document.getElementById('accountTrigger');
function setAccountOpen(open) {
  _accountMenu.classList.toggle('open', open);
  _accountTrigger.setAttribute('aria-expanded', open ? 'true' : 'false');
}
async function doLogout() {
  setAccountOpen(false);
  try { await fetch('/auth/logout', { method: 'POST' }); } catch(e) {}
  window.location.href = '/';
}
document.addEventListener('click', e => {
  const t = e.target;
  if (t.closest('[data-action="account-toggle"]')) { setAccountOpen(!_accountMenu.classList.contains('open')); return; }
  if (t.closest('[data-action="logout"]')) { doLogout(); return; }
  if (t.closest('[data-action="open-settings"]')) { setAccountOpen(false); switchModule('m6'); return; }
  if (t.closest('[data-action="notif-toggle"]')) { _toggleNotifDropdown(); return; }
  if (t.closest('[data-action="notif-mark-all"]')) { _markAllNotifRead(); return; }
  if (!t.closest('.account') && !t.closest('.notif-wrap')) {
    setAccountOpen(false);
    _closeNotifDropdown();
  }
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { setAccountOpen(false); _closeNotifDropdown(); }
});
(async () => {
  try {
    const p = await fetch('/api/settings/profile').then(r => r.ok ? r.json() : null);
    if (p && p.email) {
      document.getElementById('accountEmail').textContent = p.email;
      const initial = (p.name || p.email)[0].toUpperCase();
      document.getElementById('userAvatar').textContent = initial;
      document.querySelector('.account-id-avatar').textContent = initial;
      if (p.name) document.getElementById('accountName').textContent = p.name;
    }
  } catch(e) {}
})();

// ── Notification center ───────────────────────────────────────────────────────
let _notifOpen = false;
let _notifPollTimer = null;
const _notifDropdown = document.getElementById('notifDropdown');
const _notifBell     = document.getElementById('notifBell');
const _notifBadge    = document.getElementById('notifBadge');

function _toggleNotifDropdown() {
  _notifOpen = !_notifOpen;
  _notifDropdown?.classList.toggle('open', _notifOpen);
  if (_notifOpen) { _loadNotifications(true); }
}
function _closeNotifDropdown() {
  _notifOpen = false;
  _notifDropdown?.classList.remove('open');
}

async function _loadNotifications(markRead) {
  if (!_notifDropdown) return;
  const rows = await fetch('/api/notifications?limit=20').then(r => r.ok ? r.json() : []).catch(() => []);
  const unread = rows.filter(r => !r.is_read).length;
  if (_notifBadge) {
    _notifBadge.textContent = unread > 9 ? '9+' : unread;
    _notifBadge.style.display = unread > 0 ? '' : 'none';
  }
  const list = _notifDropdown.querySelector('.notif-list');
  if (list) {
    if (!rows.length) {
      list.innerHTML = '<div class="notif-empty">No notifications yet.</div>';
    } else {
      list.innerHTML = rows.map(n => {
        const ago = _notifTimeAgo(n.created_at);
        const typeIcon = n.type === 'price_alert' ? 'notifications_active' : n.type === 'swing_exit' ? 'trending_down' : 'info';
        return `<div class="notif-row${n.is_read ? '' : ' unread'}">
          <span class="material-symbols-outlined notif-icon">${typeIcon}</span>
          <div class="notif-body">
            <div class="notif-title">${n.title || ''}</div>
            ${n.body ? `<div class="notif-msg">${n.body}</div>` : ''}
            ${n.related_sym ? `<span class="notif-sym">${n.related_sym}</span>` : ''}
          </div>
          <div class="notif-time">${ago}</div>
        </div>`;
      }).join('');
    }
  }
  if (markRead && unread > 0) _markAllNotifRead();
}

async function _markAllNotifRead() {
  await fetch('/api/notifications/mark-all-read', { method: 'POST' }).catch(() => {});
  if (_notifBadge) _notifBadge.style.display = 'none';
  _notifDropdown?.querySelectorAll('.notif-row.unread').forEach(r => r.classList.remove('unread'));
}

function _notifTimeAgo(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    if (isNaN(d)) return '';
    const diffMs = Date.now() - d.getTime();
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return mins + 'm ago';
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return hrs + 'h ago';
    const days = Math.floor(hrs / 24);
    if (days > 365) return '';
    return days + 'd ago';
  } catch { return ''; }
}

function _pollNotifications() {
  if (document.hidden) return;
  fetch('/api/notifications?limit=20').then(r => r.ok ? r.json() : []).then(rows => {
    const unread = rows.filter(r => !r.is_read).length;
    if (_notifBadge) {
      _notifBadge.textContent = unread > 9 ? '9+' : unread;
      _notifBadge.style.display = unread > 0 ? '' : 'none';
    }
  }).catch(() => {});
}

// Poll every 60s while page is visible
_pollNotifications();
_notifPollTimer = setInterval(_pollNotifications, 60000);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) _pollNotifications();
});
