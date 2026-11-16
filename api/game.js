const { query } = require('./_lib/db');
const { CACHE, allow, fail } = require('./_lib/http');

// One locked pick with its full analysis: /api/game?id=espn:nba:401234
module.exports = async (req, res) => {
  if (!allow(req, res)) return;
  const id = String((req.query && req.query.id) || '');
  if (!/^[A-Za-z0-9:_.\-]{1,80}$/.test(id)) return res.status(400).json({ error: 'bad id' });
  try {
    const rows = await query('SELECT id, sport, start_utc, published_utc, tag, verdict, market, selection, odds, fair_odds, ' +
      'model_prob, market_prob, edge, units, confidence, top_pick, coverage, payload_json, hash FROM picks WHERE id = ?', [id]);
    if (!rows.length) return res.status(404).json({ error: 'not found' });
    const { payload_json: payload, ...pick } = rows[0];
    res.setHeader('Cache-Control', CACHE);
    res.status(200).json({ ...pick, analysis: JSON.parse(payload) });
  } catch (err) {
    fail(res, err);
  }
};
