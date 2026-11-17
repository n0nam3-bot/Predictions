const { snapshot } = require('./_lib/db');
const { allow } = require('./_lib/http');

// Which commit is deployed, and is the database reachable? The inbox workflow polls this to confirm a deploy.
module.exports = async (req, res) => {
  if (!allow(req, res)) return;
  res.setHeader('Cache-Control', 'no-store');
  const out = { ok: true, commit: process.env.VERCEL_GIT_COMMIT_SHA || null, db: 'ok', error: null, snapshot_age_s: null, health: null };
  try {
    const row = await snapshot('health');
    if (row) {
      out.health = JSON.parse(row.json);
      out.snapshot_age_s = Math.round((Date.now() - Date.parse(row.updated_utc)) / 1000);
    }
  } catch (err) {
    out.ok = false;
    out.db = 'error';
    out.error = String((err && err.message) || err).slice(0, 160);   // never contains a secret: only 'is not set', HTTP codes, SQL errors
  }
  res.status(200).send(JSON.stringify(out));
};
