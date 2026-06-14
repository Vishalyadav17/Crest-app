/**
 * fmt.js — Formatting utilities for Crest
 *
 * fmt(n)             — backward-compat rupee format (same as fmt.rupee)
 * fmt.rupee(n)       — ₹ with 0 decimal places
 * fmt.rupee2(n)      — ₹ with 2 decimal places
 * fmt.pct(n, dp=1)   — ±X.X% (replaces fmtPct)
 * fmt.units(n, dp=3) — number with N decimal places
 * fmt.marketCap(cr)  — "123 Cr" or "1.2K Cr"
 * fmt.cls(n)         — "green" or "red" (replaces cls)
 */
const fmt = function(n) {
  return n == null ? '–' : '₹' + Math.round(n).toLocaleString('en-IN');
};

fmt.rupee = function(n, dp = 0) {
  if (n == null) return '–';
  return '₹' + n.toLocaleString('en-IN', { maximumFractionDigits: dp, minimumFractionDigits: dp });
};

fmt.rupee2 = function(n) {
  return fmt.rupee(n, 2);
};

fmt.pct = function(n, dp = 1) {
  if (n == null) return '–';
  return (n >= 0 ? '+' : '') + n.toFixed(dp) + '%';
};

fmt.units = function(n, dp = 3) {
  if (n == null) return '–';
  return n.toLocaleString('en-IN', { maximumFractionDigits: dp });
};

fmt.marketCap = function(cr) {
  if (cr == null) return '–';
  return cr >= 10000 ? (cr / 1000).toFixed(1) + 'K Cr' : Math.round(cr) + ' Cr';
};

fmt.cls = function(n) {
  return n >= 0 ? 'green' : 'red';
};

window.fmt = fmt;

// Backward compat aliases
window.fmtPct = fmt.pct;
window.cls     = fmt.cls;
