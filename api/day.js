const { query } = require('./_lib/db');
const { CACHE, allow, fail } = require('./_lib/http');
const { etBounds, todayKey, addDays, validDate, shapeRows, SELECT, TZ } = require('./_lib/shape');

// Every game on one calendar day (New York time), with its locked pick and result: /api/day?date=2026-11-15
module.exports = async (req, res) => {
  if (!allow(req, res)) return;
  const date = String((req.query && req.query.date) || '');
  if (!validDate(date)) return res.status(400).json({ error: 'date must look like 2026-11-15' });
  const today = todayKey();
  if (date > addDays(today, 14) || date < addDays(today, -400)) return res.status(400).json({ error: 'date out of range' });
  try {
    const [lo, hi] = etBounds(date);
    const games = shapeRows(await query(SELECT, [lo, hi]));
    // old days no longer change, so the CDN may keep them for an hour
    res.setHeader('Cache-Control', date < addDays(today, -2) ? 'public, s-maxage=3600, stale-while-revalidate=86400' : CACHE);
    res.status(200).json({ schema: 1, source: 'live', date, timezone: TZ, games });
  } catch (err) {
    fail(res, err);
  }
};
