const { snapshot } = require('./_lib/db');
const { allow } = require('./_lib/http');

// Which commit is deployed, and is the database reachable? The inbox workflow polls this to confirm a deploy.
module.exports = async (req, res) => {
  if (!allow(req, res)) return;
  res.setHeader('Cache-Control', 'no-store');
  const out = { ok: true, commit: process.env.VERCEL_GIT_COMMIT_SHA || null, db: 'ok', snapshot_age_s: null, health: null };
  try {
    const row = await snapshot('health');
    if (row) {
      out.health = JSON.parse(row.json);
      out.snapshot_age_s = Math.round((Date.now() - Date.parse(row.updated_utc)) / 1000);
    }
  } catch (err) {
    out.ok = false;
    out.db = 'error';
  }
  res.status(200).send(JSON.stringify(out));
};
