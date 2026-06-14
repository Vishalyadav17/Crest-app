/**
 * api.js — HTTP client utilities for Crest
 *
 * api(path)             — GET, returns JSON or null on 401
 * apiPost(path)         — POST (no body), returns JSON or null on 401
 * apiFetch(path, opts)  — Generic fetch with body support (PUT/DELETE/POST+body)
 */
const API = '';

async function api(path) {
  const r = await fetch(API + path);
  if (r.status === 401) { location.href = '/auth/google'; return null; }
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function apiPost(path) {
  const r = await fetch(API + path, { method: 'POST' });
  if (r.status === 401) { location.href = '/auth/google'; return null; }
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function apiFetch(path, opts = {}) {
  const r = await fetch(API + path, opts);
  if (r.status === 401) { location.href = '/auth/google'; return null; }
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function paginatedFetch(url, offset, pageSize = 20) {
  const sep = url.includes('?') ? '&' : '?';
  return api(`${url}${sep}limit=${pageSize}&offset=${offset}`);
}

window.api            = api;
window.apiPost        = apiPost;
window.apiFetch       = apiFetch;
window.paginatedFetch = paginatedFetch;
