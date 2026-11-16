const { snapshot } = require('./_lib/db');
const { CACHE, allow, fail } = require('./_lib/http');

// Serves the JSON the pipeline stored under snapshots.key = 'record'. Visitors never reach the database directly.
module.exports = async (req, res) => {
  if (!allow(req, res)) return;
  try {
    const row = await snapshot('record');
    res.setHeader('Cache-Control', CACHE);
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    if (!row) return res.status(200).send(JSON.stringify({ schema: 1, source: 'live', empty: true, games: [], records: null, generated_utc: null }));
    res.status(200).send(row.json);
  } catch (err) {
    fail(res, err);
  }
};
