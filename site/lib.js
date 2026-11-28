/* Small pure helpers for the page, kept apart so they can be tested in Node. */
(function (root) {
  'use strict';

  /* Profit on a winning bet of `units` at American odds. The same formula as market.profit_units in Python. */
  function toWin(odds, units) {
    const o = Number(odds), u = Number(units);
    if (odds == null || !isFinite(o) || o === 0 || !isFinite(u)) return null;
    return o > 0 ? (u * o) / 100 : (u * 100) / Math.abs(o);
  }

  /* How many of the 3 risk bars to fill for a suggested stake of `units`. */
  function meter(units) {
    const n = Math.round(Number(units));
    return isFinite(n) ? Math.max(0, Math.min(3, n)) : 0;
  }

  /* Units without trailing zeros: 2 -> "2", 1.5 -> "1.5", 11.25 -> "11.25". */
  function plain(u) { return String(Math.round(Number(u) * 100) / 100); }

  /* Signed units with two decimals: +1.33u, -2.00u (true minus sign). */
  function signed(u) {
    const x = Number(u) || 0;
    return (x > 0 ? '+' : x < 0 ? '\u2212' : '') + Math.abs(x).toFixed(2) + 'u';
  }

  const api = { toWin: toWin, meter: meter, plain: plain, signed: signed };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.PicksLib = api;
})(typeof window !== 'undefined' ? window : globalThis);
