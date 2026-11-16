const CACHE = 'public, s-maxage=20, stale-while-revalidate=300';

function allow(req, res) {
  if (req.method === 'GET' || req.method === 'HEAD') return true;
  res.setHeader('Allow', 'GET, HEAD');
  res.status(405).json({ error: 'method not allowed' });
  return false;
}

function fail(res, err) {
  res.setHeader('Cache-Control', 'no-store');
  res.status(503).json({ error: 'database unavailable', detail: String(err && err.message || err).slice(0, 120) });
}

module.exports = { CACHE, allow, fail };
